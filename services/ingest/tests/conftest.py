import hashlib
import hmac
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("ARGOCD_WEBHOOK_TOKEN", "test-token")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_TOKEN", "test-am-token")

from app.main import app  # noqa: E402
from app.db import get_session  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_safety_score_network_calls():
    """compute_safety_score's cluster-utilization factor makes a real
    Prometheus HTTP call. Webhook-level tests exercise the correlation/
    idempotency logic, not the safety score formula itself (see
    test_safety_score.py) — stub it out so tests stay fast and
    deterministic regardless of what's listening on PROM_URL locally."""
    with patch(
        "app.routers.webhooks_github.compute_safety_score",
        AsyncMock(return_value=(0, {})),
    ):
        yield


def _sign_payload(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class _FakeNestedTransaction:
    """Minimal stand-in for SQLAlchemy's AsyncSessionTransaction: an async
    context manager, never suppresses exceptions (matching real savepoint
    semantics — session.begin_nested() itself is a plain sync call that
    returns this, not a coroutine)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.begin_nested = MagicMock(return_value=_FakeNestedTransaction())
    return session


@pytest.fixture
def client(mock_session):
    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def github_secret():
    return os.environ["GITHUB_WEBHOOK_SECRET"]


@pytest.fixture
def argocd_token():
    return os.environ["ARGOCD_WEBHOOK_TOKEN"]


@pytest.fixture
def alertmanager_token():
    return os.environ["ALERTMANAGER_WEBHOOK_TOKEN"]


@pytest.fixture
def sign_github_payload(github_secret):
    def _sign(payload: bytes) -> str:
        return _sign_payload(payload, github_secret)
    return _sign
