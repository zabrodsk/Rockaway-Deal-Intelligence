"""Agent-facing API facade for OpenClaw and similar tool clients."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from agent.person_intel.models import BulkFounderJobRequest, PersonProfileJobRequest


class AgentJobState(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    done = "done"
    error = "error"
    stopped = "stopped"


class AgentError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class AgentErrorEnvelope(BaseModel):
    error: AgentError


class AgentFileMetadata(BaseModel):
    name: str
    size: int
    mime_type: str = ""
    sha256: str | None = None


class AgentUploadResponse(BaseModel):
    upload_id: str
    mode: str
    files: list[AgentFileMetadata]
    created_at: str


class AgentAnalysisCreateRequest(BaseModel):
    upload_id: str
    use_web_search: bool = False
    instructions: str | None = None
    input_mode: str = "pitchdeck"
    run_name: str | None = None
    vc_investment_strategy: str | None = None
    phase_models: dict[str, dict[str, str]] | None = None
    quality_tier: str | None = None
    premium_phase_models: dict[str, str] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None

    @field_validator(
        "upload_id",
        "instructions",
        "input_mode",
        "run_name",
        "vc_investment_strategy",
        "quality_tier",
        "llm_provider",
        "llm_model",
        mode="before",
    )
    @classmethod
    def _coerce_str(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        text = str(value).strip()
        return text or None


class AgentAnalysisStatusResponse(BaseModel):
    analysis_id: str
    status: AgentJobState
    progress: str
    progress_log: list[str] = Field(default_factory=list)
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    llm: str | None = None
    created_at: str | None = None


class AgentAnalysisResultResponse(BaseModel):
    analysis_id: str
    status: AgentJobState
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    llm: str | None = None
    results: dict[str, Any]


class AgentActionRequest(BaseModel):
    action: str

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        action = (value or "").strip().lower()
        if action not in {"pause", "resume", "stop"}:
            raise ValueError("action must be one of: pause, resume, stop")
        return action


class AgentAnalysisSummary(BaseModel):
    analysis_id: str
    status: AgentJobState
    progress: str
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    created_at: str | None = None
    input_mode: str | None = None
    use_web_search: bool | None = None
    run_name: str | None = None
    llm: str | None = None


class AgentAnalysisEventsResponse(BaseModel):
    analysis_id: str
    status: AgentJobState
    progress: str
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    events: list[str] = Field(default_factory=list)


class AgentJobsResponse(BaseModel):
    jobs: list[AgentAnalysisSummary]


class AgentCompanyRunsResponse(BaseModel):
    companies: list[dict[str, Any]]


class AgentCompanyAnalysesResponse(BaseModel):
    company_name: str
    analyses: list[dict[str, Any]]


class AgentPersonProfileCreateResponse(BaseModel):
    job_id: str
    status: AgentJobState
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    created_at: str


class AgentPersonProfileStatusResponse(BaseModel):
    job_id: str
    status: AgentJobState
    progress: str
    terminal: bool
    result_available: bool
    recommended_poll_after_seconds: int
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentBulkFounderJob(BaseModel):
    person_key: str
    full_name: str = ""
    job_id: str
    status: AgentJobState


class AgentBulkFounderSkipped(BaseModel):
    person_key: str
    full_name: str
    status: str
    reason: str


class AgentBulkFounderCreateResponse(BaseModel):
    company_slug: str
    jobs: list[AgentBulkFounderJob]
    skipped: list[AgentBulkFounderSkipped]
    terminal: bool = False
    result_available: bool = False
    recommended_poll_after_seconds: int = 2


class AgentConfigResponse(BaseModel):
    llm: str
    default_llm: dict[str, Any]
    available_models: list[dict[str, Any]]
    pricing_catalog: Any
    phase_model_defaults: dict[str, Any]
    quality_tiers: list[dict[str, Any]]
    premium_phase_options: dict[str, Any]


class AgentCapabilitiesResponse(BaseModel):
    api_version: str
    auth_scheme: str
    openapi_url: str
    idempotency_supported: bool
    async_resources: list[str]
    recommended_poll_after_seconds: dict[str, int]
    endpoints: list[str]


class _IdempotencyRecord(BaseModel):
    fingerprint: str
    status_code: int
    body: dict[str, Any]


_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_RECORDS: dict[str, _IdempotencyRecord] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_state(value: str | None) -> AgentJobState:
    normalized = str(value or "").strip().lower()
    if normalized in {"queued", "claimed", "finalizing"}:
        normalized = "running"
    if normalized == "interrupted":
        normalized = "stopped"
    if normalized not in {member.value for member in AgentJobState}:
        normalized = "pending"
    return AgentJobState(normalized)


def _is_terminal(state: AgentJobState) -> bool:
    return state in {AgentJobState.done, AgentJobState.error, AgentJobState.stopped}


def _recommended_poll_seconds(state: AgentJobState) -> int:
    if state in {AgentJobState.pending, AgentJobState.running}:
        return 2
    if state == AgentJobState.paused:
        return 5
    return 0


def _agent_error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = AgentErrorEnvelope(
        error=AgentError(
            code=code,
            message=message,
            retryable=retryable,
            details=details,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _http_exception_to_error(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"
    retryable = exc.status_code in {408, 409, 429, 500, 502, 503, 504}
    code = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        501: "not_implemented",
        503: "service_unavailable",
    }.get(exc.status_code, "request_failed")
    details = detail if isinstance(detail, dict) else None
    return _agent_error_response(
        exc.status_code,
        code,
        message,
        retryable=retryable,
        details=details,
    )


def _auth_enabled() -> tuple[bool, str | None]:
    enabled_raw = os.getenv("AGENT_API_ENABLED", "true").strip().lower()
    if enabled_raw in {"0", "false", "no", "off"}:
        return False, "Agent API is disabled."
    api_key = os.getenv("AGENT_API_KEY", "").strip()
    if not api_key:
        return False, "AGENT_API_KEY is not configured."
    return True, None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _require_agent_auth(authorization: str | None = Header(default=None)) -> None:
    enabled, reason = _auth_enabled()
    if not enabled:
        raise HTTPException(status_code=503, detail=reason or "Agent API unavailable.")
    expected = os.getenv("AGENT_API_KEY", "").strip()
    token = _extract_bearer_token(authorization)
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")


def _build_fingerprint(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _idempotency_lookup(scope: str, key: str, fingerprint: str) -> _IdempotencyRecord | JSONResponse | None:
    cache_key = f"{scope}:{key}"
    with _IDEMPOTENCY_LOCK:
        record = _IDEMPOTENCY_RECORDS.get(cache_key)
    if not record:
        return None
    if record.fingerprint != fingerprint:
        return _agent_error_response(
            status.HTTP_409_CONFLICT,
            "idempotency_key_reused",
            "Idempotency-Key was already used with a different request payload.",
            retryable=False,
        )
    return record


def _idempotency_store(scope: str, key: str, fingerprint: str, status_code: int, body: BaseModel) -> None:
    cache_key = f"{scope}:{key}"
    record = _IdempotencyRecord(
        fingerprint=fingerprint,
        status_code=status_code,
        body=body.model_dump(mode="json"),
    )
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_RECORDS[cache_key] = record


def _replay_or_conflict(
    *,
    scope: str,
    idempotency_key: str | None,
    fingerprint: str,
    response: Response,
) -> _IdempotencyRecord | JSONResponse | None:
    normalized_key = (idempotency_key or "").strip()
    if not normalized_key:
        return None
    result = _idempotency_lookup(scope, normalized_key, fingerprint)
    if isinstance(result, _IdempotencyRecord):
        response.status_code = result.status_code
        response.headers["Idempotent-Replayed"] = "true"
    return result


def _filter_agent_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    filtered = copy.deepcopy(schema)
    filtered["paths"] = {
        path: value
        for path, value in (schema.get("paths") or {}).items()
        if path.startswith("/api/agent/")
    }
    return filtered


def _analysis_status_from_payload(payload: dict[str, Any]) -> AgentAnalysisStatusResponse:
    state = _normalize_state(payload.get("status"))
    return AgentAnalysisStatusResponse(
        analysis_id=str(payload.get("job_id") or ""),
        status=state,
        progress=str(payload.get("progress") or ""),
        progress_log=list(payload.get("progress_log") or []),
        terminal=_is_terminal(state),
        result_available=bool(payload.get("results")),
        recommended_poll_after_seconds=_recommended_poll_seconds(state),
        llm=payload.get("llm"),
        created_at=payload.get("created_at"),
    )


def _analysis_events_from_payload(payload: dict[str, Any]) -> AgentAnalysisEventsResponse:
    state = _normalize_state(payload.get("status"))
    return AgentAnalysisEventsResponse(
        analysis_id=str(payload.get("job_id") or ""),
        status=state,
        progress=str(payload.get("progress") or ""),
        terminal=_is_terminal(state),
        result_available=False,
        recommended_poll_after_seconds=_recommended_poll_seconds(state),
        events=list(payload.get("progress_log") or []),
    )


def _analysis_result_from_payload(payload: dict[str, Any], *, llm: str | None = None) -> AgentAnalysisResultResponse:
    results = payload.get("results") or {}
    state = _normalize_state((results or {}).get("job_status") or "done")
    return AgentAnalysisResultResponse(
        analysis_id=str(payload.get("job_id") or ""),
        status=state,
        terminal=True,
        result_available=True,
        recommended_poll_after_seconds=0,
        llm=llm or (results or {}).get("llm"),
        results=results,
    )


def _analysis_summary_from_payload(payload: dict[str, Any]) -> AgentAnalysisSummary:
    state = _normalize_state(payload.get("status"))
    return AgentAnalysisSummary(
        analysis_id=str(payload.get("job_id") or ""),
        status=state,
        progress=str(payload.get("progress") or ""),
        terminal=_is_terminal(state),
        result_available=bool(payload.get("has_results")),
        recommended_poll_after_seconds=_recommended_poll_seconds(state),
        created_at=payload.get("created_at"),
        input_mode=payload.get("input_mode"),
        use_web_search=payload.get("use_web_search"),
        run_name=payload.get("run_name"),
        llm=payload.get("llm"),
    )


def _person_status_from_payload(payload: dict[str, Any]) -> AgentPersonProfileStatusResponse:
    state = _normalize_state(payload.get("status"))
    result = payload.get("result")
    return AgentPersonProfileStatusResponse(
        job_id=str(payload.get("job_id") or ""),
        status=state,
        progress=str(payload.get("progress") or ""),
        terminal=_is_terminal(state),
        result_available=result is not None,
        recommended_poll_after_seconds=_recommended_poll_seconds(state),
        result=result,
        error=payload.get("error"),
    )


def create_agent_router(
    *,
    app: Any,
    upload_files_handler: Callable[[list[UploadFile]], Awaitable[dict[str, Any]]],
    start_analysis_handler: Callable[[str, Any], Awaitable[dict[str, Any]]],
    get_status_handler: Callable[[str, Response], Awaitable[dict[str, Any]]],
    get_job_log_handler: Callable[[str, Response], Awaitable[dict[str, Any]]],
    get_analysis_handler: Callable[[str, Response], Awaitable[dict[str, Any]]],
    control_analysis_handler: Callable[[str, Any], Awaitable[dict[str, Any]]],
    get_config_handler: Callable[[], dict[str, Any]],
    list_jobs_handler: Callable[[], dict[str, Any]],
    list_company_runs_handler: Callable[[], dict[str, Any]],
    get_company_analyses_handler: Callable[[str], dict[str, Any]],
    create_person_profile_handler: Callable[[PersonProfileJobRequest], Awaitable[dict[str, Any]]],
    get_person_profile_status_handler: Callable[[str], Awaitable[dict[str, Any]]],
    create_bulk_founder_jobs_handler: Callable[[BulkFounderJobRequest], Awaitable[dict[str, Any]]],
) -> APIRouter:
    if not getattr(app.state, "agent_api_exception_handlers_registered", False):
        async def _agent_http_exception_handler(request: Request, exc: HTTPException) -> Response:
            if request.url.path.startswith("/api/agent/"):
                return _http_exception_to_error(exc)
            return await http_exception_handler(request, exc)

        async def _agent_validation_exception_handler(
            request: Request,
            exc: RequestValidationError,
        ) -> Response:
            if request.url.path.startswith("/api/agent/"):
                return _agent_error_response(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "validation_error",
                    "Request validation failed.",
                    retryable=False,
                    details={"errors": exc.errors()},
                )
            return await request_validation_exception_handler(request, exc)

        app.add_exception_handler(HTTPException, _agent_http_exception_handler)
        app.add_exception_handler(RequestValidationError, _agent_validation_exception_handler)
        app.state.agent_api_exception_handlers_registered = True

    error_responses = {
        400: {"model": AgentErrorEnvelope},
        401: {"model": AgentErrorEnvelope},
        404: {"model": AgentErrorEnvelope},
        409: {"model": AgentErrorEnvelope},
        422: {"model": AgentErrorEnvelope},
        429: {"model": AgentErrorEnvelope},
        500: {"model": AgentErrorEnvelope},
        501: {"model": AgentErrorEnvelope},
        503: {"model": AgentErrorEnvelope},
    }
    router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[Depends(_require_agent_auth)])

    @router.get(
        "/capabilities",
        response_model=AgentCapabilitiesResponse,
        responses=error_responses,
    )
    async def get_capabilities() -> AgentCapabilitiesResponse:
        return AgentCapabilitiesResponse(
            api_version="v1",
            auth_scheme="bearer",
            openapi_url="/api/agent/openapi.json",
            idempotency_supported=True,
            async_resources=["analyses", "person_profiles"],
            recommended_poll_after_seconds={
                "pending": 2,
                "running": 2,
                "paused": 5,
                "done": 0,
                "error": 0,
                "stopped": 0,
            },
            endpoints=[
                "/api/agent/capabilities",
                "/api/agent/config",
                "/api/agent/uploads",
                "/api/agent/analyses",
                "/api/agent/analyses/{analysis_id}",
                "/api/agent/analyses/{analysis_id}/events",
                "/api/agent/analyses/{analysis_id}/result",
                "/api/agent/analyses/{analysis_id}/actions",
                "/api/agent/jobs",
                "/api/agent/company-runs",
                "/api/agent/companies/{company_name}/analyses",
                "/api/agent/person-profiles",
                "/api/agent/person-profiles/{job_id}",
                "/api/agent/person-profiles/bulk-founders",
                "/api/agent/openapi.json",
            ],
        )

    @router.get(
        "/openapi.json",
        response_model=dict[str, Any],
        responses=error_responses,
    )
    async def get_agent_openapi() -> dict[str, Any]:
        return _filter_agent_openapi(app.openapi())

    @router.get(
        "/config",
        response_model=AgentConfigResponse,
        responses=error_responses,
    )
    async def get_config() -> AgentConfigResponse | JSONResponse:
        try:
            return AgentConfigResponse.model_validate(get_config_handler())
        except HTTPException as exc:
            return _http_exception_to_error(exc)

    @router.post(
        "/uploads",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentUploadResponse,
        responses=error_responses,
    )
    async def create_upload(
        response: Response,
        files: list[UploadFile] = File(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentUploadResponse | JSONResponse:
        fingerprint = _build_fingerprint(
            [{"filename": item.filename, "content_type": item.content_type} for item in files]
        )
        replay = _replay_or_conflict(
            scope="uploads",
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            response=response,
        )
        if isinstance(replay, JSONResponse):
            return replay
        if isinstance(replay, _IdempotencyRecord):
            return AgentUploadResponse.model_validate(replay.body)

        try:
            payload = await upload_files_handler(files)
        except HTTPException as exc:
            return _http_exception_to_error(exc)

        model = AgentUploadResponse(
            upload_id=payload["job_id"],
            mode=str(payload.get("mode") or "documents"),
            files=[
                AgentFileMetadata(
                    name=item["name"],
                    size=int(item["size"]),
                    mime_type=str(item.get("mime_type") or ""),
                    sha256=item.get("sha256"),
                )
                for item in payload.get("files") or []
            ],
            created_at=_utc_now(),
        )
        if idempotency_key and idempotency_key.strip():
            _idempotency_store("uploads", idempotency_key.strip(), fingerprint, status.HTTP_202_ACCEPTED, model)
        return model

    @router.post(
        "/analyses",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentAnalysisStatusResponse,
        responses=error_responses,
    )
    async def create_analysis(
        req: AgentAnalysisCreateRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentAnalysisStatusResponse | JSONResponse:
        fingerprint = _build_fingerprint(req.model_dump(mode="json"))
        replay = _replay_or_conflict(
            scope="analyses:create",
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            response=response,
        )
        if isinstance(replay, JSONResponse):
            return replay
        if isinstance(replay, _IdempotencyRecord):
            return AgentAnalysisStatusResponse.model_validate(replay.body)

        try:
            payload = await start_analysis_handler(req.upload_id, req)
        except HTTPException as exc:
            return _http_exception_to_error(exc)

        model = AgentAnalysisStatusResponse(
            analysis_id=req.upload_id,
            status=_normalize_state(payload.get("status")),
            progress="Starting analysis...",
            progress_log=[],
            terminal=False,
            result_available=False,
            recommended_poll_after_seconds=2,
            llm=payload.get("llm"),
            created_at=_utc_now(),
        )
        if idempotency_key and idempotency_key.strip():
            _idempotency_store("analyses:create", idempotency_key.strip(), fingerprint, status.HTTP_202_ACCEPTED, model)
        return model

    @router.get(
        "/analyses/{analysis_id}",
        response_model=AgentAnalysisStatusResponse,
        responses=error_responses,
    )
    async def get_analysis_status(analysis_id: str, response: Response) -> AgentAnalysisStatusResponse | JSONResponse:
        try:
            payload = await get_status_handler(analysis_id, response)
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return _analysis_status_from_payload(payload)

    @router.get(
        "/analyses/{analysis_id}/events",
        response_model=AgentAnalysisEventsResponse,
        responses=error_responses,
    )
    async def get_analysis_events(analysis_id: str, response: Response) -> AgentAnalysisEventsResponse | JSONResponse:
        try:
            payload = await get_job_log_handler(analysis_id, response)
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return _analysis_events_from_payload(payload)

    @router.get(
        "/analyses/{analysis_id}/result",
        response_model=AgentAnalysisResultResponse,
        responses=error_responses,
    )
    async def get_analysis_result(analysis_id: str, response: Response) -> AgentAnalysisResultResponse | JSONResponse:
        try:
            payload = await get_analysis_handler(analysis_id, response)
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return _analysis_result_from_payload(payload)

    @router.post(
        "/analyses/{analysis_id}/actions",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentAnalysisStatusResponse,
        responses=error_responses,
    )
    async def control_analysis(
        analysis_id: str,
        req: AgentActionRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentAnalysisStatusResponse | JSONResponse:
        fingerprint = _build_fingerprint({"analysis_id": analysis_id, **req.model_dump(mode="json")})
        replay = _replay_or_conflict(
            scope="analyses:actions",
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            response=response,
        )
        if isinstance(replay, JSONResponse):
            return replay
        if isinstance(replay, _IdempotencyRecord):
            return AgentAnalysisStatusResponse.model_validate(replay.body)

        try:
            payload = await control_analysis_handler(analysis_id, req)
        except HTTPException as exc:
            return _http_exception_to_error(exc)

        state = _normalize_state(payload.get("status"))
        model = AgentAnalysisStatusResponse(
            analysis_id=analysis_id,
            status=state,
            progress=str(payload.get("progress") or ""),
            progress_log=[],
            terminal=_is_terminal(state),
            result_available=state in {AgentJobState.done, AgentJobState.stopped},
            recommended_poll_after_seconds=_recommended_poll_seconds(state),
            llm=None,
            created_at=None,
        )
        if idempotency_key and idempotency_key.strip():
            _idempotency_store("analyses:actions", idempotency_key.strip(), fingerprint, status.HTTP_202_ACCEPTED, model)
        return model

    @router.get(
        "/jobs",
        response_model=AgentJobsResponse,
        responses=error_responses,
    )
    async def list_jobs() -> AgentJobsResponse | JSONResponse:
        try:
            payload = list_jobs_handler()
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return AgentJobsResponse(
            jobs=[_analysis_summary_from_payload(item) for item in payload.get("jobs") or []]
        )

    @router.get(
        "/company-runs",
        response_model=AgentCompanyRunsResponse,
        responses=error_responses,
    )
    async def list_company_runs() -> AgentCompanyRunsResponse | JSONResponse:
        try:
            payload = list_company_runs_handler()
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return AgentCompanyRunsResponse.model_validate(payload)

    @router.get(
        "/companies/{company_name}/analyses",
        response_model=AgentCompanyAnalysesResponse,
        responses=error_responses,
    )
    async def get_company_analyses(company_name: str) -> AgentCompanyAnalysesResponse | JSONResponse:
        try:
            payload = get_company_analyses_handler(company_name)
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return AgentCompanyAnalysesResponse.model_validate(payload)

    @router.post(
        "/person-profiles",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentPersonProfileCreateResponse,
        responses=error_responses,
    )
    async def create_person_profile(
        req: PersonProfileJobRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentPersonProfileCreateResponse | JSONResponse:
        fingerprint = _build_fingerprint(req.model_dump(mode="json"))
        replay = _replay_or_conflict(
            scope="person-profiles:create",
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            response=response,
        )
        if isinstance(replay, JSONResponse):
            return replay
        if isinstance(replay, _IdempotencyRecord):
            return AgentPersonProfileCreateResponse.model_validate(replay.body)

        try:
            payload = await create_person_profile_handler(req)
        except HTTPException as exc:
            return _http_exception_to_error(exc)

        model = AgentPersonProfileCreateResponse(
            job_id=str(payload.get("job_id") or ""),
            status=_normalize_state(payload.get("status")),
            terminal=False,
            result_available=False,
            recommended_poll_after_seconds=2,
            created_at=_utc_now(),
        )
        if idempotency_key and idempotency_key.strip():
            _idempotency_store(
                "person-profiles:create",
                idempotency_key.strip(),
                fingerprint,
                status.HTTP_202_ACCEPTED,
                model,
            )
        return model

    @router.get(
        "/person-profiles/{job_id}",
        response_model=AgentPersonProfileStatusResponse,
        responses=error_responses,
    )
    async def get_person_profile_status(job_id: str) -> AgentPersonProfileStatusResponse | JSONResponse:
        try:
            payload = await get_person_profile_status_handler(job_id)
        except HTTPException as exc:
            return _http_exception_to_error(exc)
        return _person_status_from_payload(payload)

    @router.post(
        "/person-profiles/bulk-founders",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AgentBulkFounderCreateResponse,
        responses=error_responses,
    )
    async def create_bulk_founder_jobs(
        req: BulkFounderJobRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentBulkFounderCreateResponse | JSONResponse:
        fingerprint = _build_fingerprint(req.model_dump(mode="json"))
        replay = _replay_or_conflict(
            scope="person-profiles:bulk-founders",
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            response=response,
        )
        if isinstance(replay, JSONResponse):
            return replay
        if isinstance(replay, _IdempotencyRecord):
            return AgentBulkFounderCreateResponse.model_validate(replay.body)

        try:
            payload = await create_bulk_founder_jobs_handler(req)
        except HTTPException as exc:
            return _http_exception_to_error(exc)

        model = AgentBulkFounderCreateResponse(
            company_slug=str(payload.get("company_slug") or ""),
            jobs=[
                AgentBulkFounderJob(
                    person_key=str(item.get("person_key") or ""),
                    full_name=str(item.get("full_name") or ""),
                    job_id=str(item.get("job_id") or ""),
                    status=_normalize_state(item.get("status")),
                )
                for item in payload.get("jobs") or []
            ],
            skipped=[
                AgentBulkFounderSkipped(
                    person_key=str(item.get("person_key") or ""),
                    full_name=str(item.get("full_name") or ""),
                    status=str(item.get("status") or ""),
                    reason=str(item.get("reason") or ""),
                )
                for item in payload.get("skipped") or []
            ],
        )
        if idempotency_key and idempotency_key.strip():
            _idempotency_store(
                "person-profiles:bulk-founders",
                idempotency_key.strip(),
                fingerprint,
                status.HTTP_202_ACCEPTED,
                model,
            )
        return model

    return router
