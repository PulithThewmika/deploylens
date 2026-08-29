from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    repo: str | None = None
    argocd_app: str | None = None
    namespace: str
    created_at: datetime


class LatestDeployInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commit_sha: str | None = None
    author: str | None = None
    status: str
    finished_at: datetime | None = None


class HealthSummary(BaseModel):
    score: int | None = None
    verdict: str | None = None


class ServiceWithStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    namespace: str
    repo: str | None = None
    argocd_app: str | None = None
    latest_deploy: LatestDeployInfo | None = None
    health: HealthSummary | None = None
    active_alert_count: int = 0


class DeploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    commit_sha: str | None = None
    branch: str | None = None
    author: str | None = None
    status: str
    image_tag: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class HealthAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deployment_id: int
    score: int
    verdict: str
    error_rate_base: float | None = None
    error_rate_post: float | None = None
    latency_p99_base_ms: float | None = None
    latency_p99_post_ms: float | None = None
    restarts_base: float | None = None
    restarts_post: float | None = None
    details: dict | None = None
    assessed_at: datetime


class DeploymentDetailResponse(DeploymentResponse):
    commit_at: datetime | None = None
    build_status: str | None = None
    build_duration_s: float | None = None
    sync_status: str | None = None
    workflow_run_id: int | None = None
    argocd_revision: str | None = None
    created_at: datetime
    health_assessment: HealthAssessmentResponse | None = None
    service: ServiceResponse | None = None


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deployment_id: int
    service_id: int
    severity: str
    title: str
    description: str | None = None
    fired_at: datetime
    resolved_at: datetime | None = None
    alertmanager_id: str | None = None


class TimelineStage(BaseModel):
    stage: str
    at: datetime | None = None
    status: str
    duration_s: float | None = None


class HealthEvidenceItem(BaseModel):
    metric: str
    baseline: float | None = None
    post: float | None = None
    change_pct: float | None = None


class DeploymentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    service_name: str
    commit_sha: str | None = None
    branch: str | None = None
    author: str | None = None
    status: str
    image_tag: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    health: HealthSummary | None = None
    timeline: list[TimelineStage] = []


class DeploymentDetailWithTimelineResponse(DeploymentDetailResponse):
    timeline: list[TimelineStage] = []
    health_evidence: list[HealthEvidenceItem] = []


class HealthDetailResponse(BaseModel):
    deployment_id: int
    status: str
    score: int | None = None
    verdict: str | None = None
    assessed_at: datetime | None = None
    evidence: list[HealthEvidenceItem] = []


class CompareMetric(BaseModel):
    metric: str
    deploy_a: float | None = None
    deploy_b: float | None = None
    change_pct: float | None = None


class CompareResponse(BaseModel):
    deploy_a_id: int
    deploy_b_id: int
    service: str
    metrics: list[CompareMetric] = []


class DORAMetricsResponse(BaseModel):
    """Unified DORA metrics response matching MCP get_dora_metrics output."""
    deploy_frequency_per_day: float | None = None
    lead_time_avg_s: float | None = None
    change_failure_rate: float | None = None
    mttr_s: float | None = None
    period: str = "30d"
    service: str | None = None
