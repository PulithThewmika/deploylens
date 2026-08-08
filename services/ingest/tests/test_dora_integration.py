"""DORA view integration tests — validate SQL against a real PostgreSQL instance.

These tests seed known data into a real database, query the DORA views,
and assert the aggregations match hand-calculated expectations. This
catches the class of bugs (wrong status filters, AVG vs median, missing
joins) that mock-based tests cannot detect.

Connection modes (tried in order):
1. DORA_TEST_DATABASE_URL env var — direct connection to any PostgreSQL
2. testcontainers-python — spins up a temporary PostgreSQL container
3. Skip — if neither is available
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    from testcontainers.postgres import PostgresContainer
    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False

DORA_TEST_DATABASE_URL = os.environ.get("DORA_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not HAS_PSYCOPG2,
    reason="psycopg2 not installed",
)

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


@pytest.fixture(scope="module")
def pg():
    """Connect to PostgreSQL and apply the schema + DORA views.

    Uses DORA_TEST_DATABASE_URL if set, otherwise tries testcontainers.
    """
    container = None

    if DORA_TEST_DATABASE_URL:
        conn = psycopg2.connect(DORA_TEST_DATABASE_URL)
    elif HAS_TESTCONTAINERS:
        try:
            container = PostgresContainer("postgres:16-alpine")
            container.start()
            conn = psycopg2.connect(container.get_connection_url())
        except Exception:
            pytest.skip("Docker not available — skipping integration tests")
    else:
        pytest.skip("No database available (set DORA_TEST_DATABASE_URL or install testcontainers)")

    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            description TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE services (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            repo TEXT,
            argocd_app TEXT,
            namespace TEXT NOT NULL DEFAULT 'default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    cur.execute("""
        CREATE TABLE deployments (
            id SERIAL PRIMARY KEY,
            service_id INTEGER NOT NULL REFERENCES services(id),
            commit_sha TEXT,
            branch TEXT,
            author TEXT,
            commit_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'pending',
            build_status TEXT,
            build_duration_s REAL,
            sync_status TEXT,
            workflow_run_id BIGINT,
            argocd_revision TEXT,
            image_tag TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    cur.execute("""
        CREATE TABLE health_assessments (
            id SERIAL PRIMARY KEY,
            deployment_id INTEGER NOT NULL UNIQUE REFERENCES deployments(id),
            score INTEGER NOT NULL,
            verdict TEXT NOT NULL,
            error_rate_base REAL,
            error_rate_post REAL,
            latency_p99_base_ms REAL,
            latency_p99_post_ms REAL,
            restarts_base REAL,
            restarts_post REAL,
            details JSONB,
            assessed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    cur.execute("""
        CREATE TABLE alerts (
            id SERIAL PRIMARY KEY,
            deployment_id INTEGER NOT NULL REFERENCES deployments(id),
            service_id INTEGER NOT NULL REFERENCES services(id),
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            fired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            alertmanager_id TEXT
        );
    """)

    cur.execute("""
        CREATE VIEW dora_deploy_frequency AS
        SELECT
            d.finished_at::date AS deploy_date,
            s.name AS service_name,
            COUNT(*) AS deploy_count
        FROM deployments d
        JOIN services s ON s.id = d.service_id
        WHERE d.status IN ('deployed', 'assessed')
          AND d.finished_at IS NOT NULL
        GROUP BY d.finished_at::date, s.name
        ORDER BY deploy_date DESC, service_name;
    """)

    cur.execute("""
        CREATE VIEW dora_lead_time AS
        SELECT
            s.name AS service_name,
            d.finished_at,
            EXTRACT(EPOCH FROM (d.finished_at - d.commit_at)) AS lead_time_seconds
        FROM deployments d
        JOIN services s ON s.id = d.service_id
        WHERE d.status IN ('deployed', 'assessed')
          AND d.commit_at IS NOT NULL
          AND d.finished_at IS NOT NULL;
    """)

    cur.execute("""
        CREATE VIEW dora_change_failure_rate AS
        SELECT
            s.name AS service_name,
            d.started_at,
            CASE
                WHEN d.status IN ('build_failed', 'sync_failed')
                  OR ha.verdict IN ('failed', 'degraded')
                THEN true
                ELSE false
            END AS is_failure
        FROM deployments d
        JOIN services s ON s.id = d.service_id
        LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
        WHERE d.status IN ('deployed', 'assessed', 'build_failed', 'sync_failed');
    """)

    cur.execute("""
        CREATE VIEW dora_mttr AS
        SELECT
            s.name AS service_name,
            a.fired_at,
            EXTRACT(EPOCH FROM (a.resolved_at - a.fired_at)) AS mttr_seconds
        FROM alerts a
        JOIN services s ON s.id = a.service_id
        WHERE a.resolved_at IS NOT NULL;
    """)

    yield conn

    cur.close()
    conn.close()
    if container:
        container.stop()


@pytest.fixture(autouse=True)
def _clean_tables(pg):
    """Truncate all data between tests."""
    cur = pg.cursor()
    cur.execute("TRUNCATE alerts, health_assessments, deployments, services RESTART IDENTITY CASCADE")
    pg.commit()
    yield
    cur.close()


def _insert_service(cur, name="orders"):
    cur.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        (name,),
    )
    return cur.fetchone()[0]


def _insert_deployment(cur, service_id, *, status="deployed", commit_at=None,
                       finished_at=None, started_at=None):
    cur.execute(
        """INSERT INTO deployments
           (service_id, status, commit_at, finished_at, started_at)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (service_id, status, commit_at, finished_at, started_at or NOW),
    )
    return cur.fetchone()[0]


def _insert_health(cur, deployment_id, verdict="healthy", score=90):
    cur.execute(
        """INSERT INTO health_assessments (deployment_id, score, verdict)
           VALUES (%s, %s, %s)""",
        (deployment_id, score, verdict),
    )


def _insert_alert(cur, deployment_id, service_id, *,
                  fired_at=None, resolved_at=None):
    cur.execute(
        """INSERT INTO alerts
           (deployment_id, service_id, severity, title, fired_at, resolved_at)
           VALUES (%s, %s, 'warning', 'test alert', %s, %s) RETURNING id""",
        (deployment_id, service_id, fired_at or NOW, resolved_at),
    )
    return cur.fetchone()[0]


# ── Deploy Frequency ────────────────────────────────────────────────────

class TestDeployFrequency:
    def test_counts_deployed_and_assessed(self, pg):
        """Both 'deployed' and 'assessed' statuses are counted."""
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(cur, sid, status="deployed", finished_at=NOW)
        _insert_deployment(cur, sid, status="assessed", finished_at=NOW)
        _insert_deployment(cur, sid, status="building", finished_at=NOW)
        pg.commit()

        cur.execute("SELECT SUM(deploy_count) FROM dora_deploy_frequency")
        assert cur.fetchone()[0] == 2

    def test_excludes_null_finished_at(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(cur, sid, status="deployed", finished_at=None)
        pg.commit()

        cur.execute("SELECT SUM(deploy_count) FROM dora_deploy_frequency")
        assert cur.fetchone()[0] is None

    def test_groups_by_date_and_service(self, pg):
        cur = pg.cursor()
        s1 = _insert_service(cur, "orders")
        s2 = _insert_service(cur, "payments")
        _insert_deployment(cur, s1, status="deployed", finished_at=NOW)
        _insert_deployment(cur, s1, status="deployed", finished_at=NOW)
        _insert_deployment(cur, s2, status="deployed", finished_at=NOW - DAY)
        pg.commit()

        cur.execute(
            "SELECT service_name, deploy_count FROM dora_deploy_frequency ORDER BY service_name"
        )
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("orders", 2)
        assert rows[1] == ("payments", 1)


# ── Lead Time ───────────────────────────────────────────────────────────

class TestLeadTime:
    def test_calculates_seconds_between_commit_and_deploy(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(
            cur, sid, status="deployed",
            commit_at=NOW - timedelta(seconds=600),
            finished_at=NOW,
        )
        _insert_deployment(
            cur, sid, status="assessed",
            commit_at=NOW - timedelta(seconds=1200),
            finished_at=NOW,
        )
        pg.commit()

        cur.execute("SELECT AVG(lead_time_seconds) FROM dora_lead_time")
        avg = cur.fetchone()[0]
        assert abs(avg - 900.0) < 0.01

    def test_excludes_deployments_without_commit_at(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(cur, sid, status="deployed", commit_at=None, finished_at=NOW)
        pg.commit()

        cur.execute("SELECT COUNT(*) FROM dora_lead_time")
        assert cur.fetchone()[0] == 0

    def test_period_filtering_works(self, pg):
        """Consumers can filter by finished_at for period-based queries."""
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(
            cur, sid, status="deployed",
            commit_at=NOW - timedelta(days=60) - HOUR,
            finished_at=NOW - timedelta(days=60),
        )
        _insert_deployment(
            cur, sid, status="deployed",
            commit_at=NOW - HOUR,
            finished_at=NOW,
        )
        pg.commit()

        cur.execute(
            "SELECT AVG(lead_time_seconds) FROM dora_lead_time "
            "WHERE finished_at >= %s",
            (NOW - timedelta(days=30),),
        )
        avg = cur.fetchone()[0]
        assert abs(avg - 3600.0) < 0.01


# ── Change Failure Rate ─────────────────────────────────────────────────

class TestChangeFailureRate:
    def test_counts_build_and_sync_failures(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        _insert_deployment(cur, sid, status="deployed", finished_at=NOW)
        _insert_deployment(cur, sid, status="build_failed")
        _insert_deployment(cur, sid, status="sync_failed")
        pg.commit()

        cur.execute("""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric / COUNT(*), 4
            ) FROM dora_change_failure_rate
        """)
        rate = float(cur.fetchone()[0])
        assert abs(rate - 0.6667) < 0.001

    def test_counts_degraded_and_failed_verdicts(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        d1 = _insert_deployment(cur, sid, status="assessed", finished_at=NOW)
        d2 = _insert_deployment(cur, sid, status="assessed", finished_at=NOW)
        d3 = _insert_deployment(cur, sid, status="deployed", finished_at=NOW)
        _insert_health(cur, d1, verdict="failed", score=30)
        _insert_health(cur, d2, verdict="degraded", score=60)
        _insert_health(cur, d3, verdict="healthy", score=95)
        pg.commit()

        cur.execute("""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric / COUNT(*), 4
            ) FROM dora_change_failure_rate
        """)
        rate = float(cur.fetchone()[0])
        assert abs(rate - 0.6667) < 0.001

    def test_zero_failures(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        d1 = _insert_deployment(cur, sid, status="deployed", finished_at=NOW)
        d2 = _insert_deployment(cur, sid, status="assessed", finished_at=NOW)
        _insert_health(cur, d2, verdict="healthy", score=95)
        pg.commit()

        cur.execute("""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric / COUNT(*), 4
            ) FROM dora_change_failure_rate
        """)
        rate = float(cur.fetchone()[0])
        assert rate == 0.0


# ── MTTR ────────────────────────────────────────────────────────────────

class TestMTTR:
    def test_average_of_resolved_alerts(self, pg):
        """AVG of [1800s, 3600s] = 2700s, excludes unresolved."""
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        d1 = _insert_deployment(cur, sid, status="deployed", finished_at=NOW)

        _insert_alert(cur, d1, sid,
                      fired_at=NOW - timedelta(seconds=1800),
                      resolved_at=NOW)
        _insert_alert(cur, d1, sid,
                      fired_at=NOW - timedelta(seconds=3600),
                      resolved_at=NOW)
        _insert_alert(cur, d1, sid,
                      fired_at=NOW, resolved_at=None)
        pg.commit()

        cur.execute("SELECT AVG(mttr_seconds) FROM dora_mttr")
        avg = cur.fetchone()[0]
        assert abs(avg - 2700.0) < 0.01

    def test_no_resolved_alerts_returns_null(self, pg):
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        d1 = _insert_deployment(cur, sid, status="deployed", finished_at=NOW)
        _insert_alert(cur, d1, sid, fired_at=NOW, resolved_at=None)
        pg.commit()

        cur.execute("SELECT AVG(mttr_seconds) FROM dora_mttr")
        assert cur.fetchone()[0] is None

    def test_period_filtering_works(self, pg):
        """Consumers can filter by fired_at for period-based queries."""
        cur = pg.cursor()
        sid = _insert_service(cur, "orders")
        d1 = _insert_deployment(cur, sid, status="deployed", finished_at=NOW)

        _insert_alert(cur, d1, sid,
                      fired_at=NOW - timedelta(days=60),
                      resolved_at=NOW - timedelta(days=60) + HOUR)
        _insert_alert(cur, d1, sid,
                      fired_at=NOW - HOUR,
                      resolved_at=NOW)
        pg.commit()

        cur.execute(
            "SELECT AVG(mttr_seconds) FROM dora_mttr WHERE fired_at >= %s",
            (NOW - timedelta(days=30),),
        )
        avg = cur.fetchone()[0]
        assert abs(avg - 3600.0) < 0.01


# ── Full Scenario (matches #37 acceptance criteria) ─────────────────────

class TestFullScenario:
    def test_all_four_metrics_with_seeded_data(self, pg):
        """Seed the exact scenario from issue #37 and verify all four DORA
        metrics against hand-calculated expectations.

        Data:
        - 10 deployments across 5 days in 30 days (freq = 10/30 ≈ 0.333)
        - Lead times: 300, 600, 900, 1200, 1500s → AVG = 900s
        - 4 failures (1 build_failed, 1 sync_failed, 1 failed verdict,
          1 degraded verdict) out of 10 → CFR = 0.4
        - 2 resolved alerts: 1800s + 3600s → MTTR = 2700s
        """
        cur = pg.cursor()
        sid = _insert_service(cur, "sample-app")

        base = NOW - timedelta(days=5)
        lead_times = [300, 600, 900, 1200, 1500]

        deploy_ids = []
        for i in range(5):
            d = _insert_deployment(
                cur, sid, status="assessed",
                commit_at=base + i * DAY - timedelta(seconds=lead_times[i]),
                finished_at=base + i * DAY,
                started_at=base + i * DAY - timedelta(seconds=lead_times[i]),
            )
            deploy_ids.append(d)

        for i in range(3):
            _insert_deployment(
                cur, sid, status="deployed",
                finished_at=base + (i + 5) * timedelta(hours=12),
                started_at=base + (i + 5) * timedelta(hours=12) - HOUR,
            )

        d_bf = _insert_deployment(cur, sid, status="build_failed",
                                  started_at=base + timedelta(days=3))
        d_sf = _insert_deployment(cur, sid, status="sync_failed",
                                  started_at=base + timedelta(days=4))

        _insert_health(cur, deploy_ids[0], verdict="failed", score=30)
        _insert_health(cur, deploy_ids[1], verdict="degraded", score=60)
        for i in range(2, 5):
            _insert_health(cur, deploy_ids[i], verdict="healthy", score=90)

        _insert_alert(cur, deploy_ids[0], sid,
                      fired_at=NOW - timedelta(seconds=1800),
                      resolved_at=NOW)
        _insert_alert(cur, deploy_ids[1], sid,
                      fired_at=NOW - timedelta(seconds=3600),
                      resolved_at=NOW)
        _insert_alert(cur, deploy_ids[2], sid,
                      fired_at=NOW, resolved_at=None)
        pg.commit()

        cur.execute("SELECT SUM(deploy_count) FROM dora_deploy_frequency")
        total_deploys = cur.fetchone()[0]
        assert total_deploys == 8

        cur.execute(
            "SELECT AVG(lead_time_seconds) FROM dora_lead_time "
            "WHERE service_name = 'sample-app'"
        )
        avg_lt = cur.fetchone()[0]
        assert abs(avg_lt - 900.0) < 0.01

        cur.execute("""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric / COUNT(*), 4
            ) FROM dora_change_failure_rate
            WHERE service_name = 'sample-app'
        """)
        cfr = float(cur.fetchone()[0])
        assert abs(cfr - 0.4) < 0.001

        cur.execute(
            "SELECT AVG(mttr_seconds) FROM dora_mttr "
            "WHERE service_name = 'sample-app'"
        )
        avg_mttr = cur.fetchone()[0]
        assert abs(avg_mttr - 2700.0) < 0.01
