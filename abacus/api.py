"""Authenticated HTTP API for the local Abacus evaluation pipeline."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from abacus.api_store import RunQuotaExceeded, RunStore
from abacus.cli import run_problem
from abacus.database import default_database_url, sqlite_url
from abacus.schemas import ProblemSpec, ProblemValidationError, load_problem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_FILES = {
    "p01_true_sort": "p01_true_sort.json",
    "p02_false_sort": "p02_false_sort.json",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
CLIENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
LOGGER = logging.getLogger("abacus.api")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    problem_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _configured_client_keys(
    api_key_reader: Callable[[], str] | None,
) -> dict[str, dict[str, Any]]:
    """Read client secrets and nonsecret policies; secrets never enter the database."""
    if api_key_reader is not None:
        return {"default": {
            "api_key": api_key_reader(), "role": "admin",
            "daily_run_limit": 100, "max_active_runs": 3,
        }}
    encoded = os.getenv("ABACUS_CLIENT_API_KEYS", "").strip()
    if encoded:
        def reject_duplicate_ids(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("ABACUS_CLIENT_API_KEYS contains a duplicate client ID.")
                result[key] = value
            return result

        try:
            mapping = json.loads(encoded, object_pairs_hook=reject_duplicate_ids)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("ABACUS_CLIENT_API_KEYS must be a JSON object.") from error
        if type(mapping) is not dict or not mapping:
            raise ValueError("ABACUS_CLIENT_API_KEYS must be a non-empty JSON object.")
        policies: dict[str, dict[str, Any]] = {}
        for client_id, configured in mapping.items():
            if type(client_id) is not str or not CLIENT_ID_PATTERN.fullmatch(client_id):
                raise ValueError("Client IDs in ABACUS_CLIENT_API_KEYS are invalid.")
            if type(configured) is str:
                policy = {
                    "api_key": configured,
                    "role": "admin",
                    "daily_run_limit": 100,
                    "max_active_runs": 3,
                }
            elif type(configured) is dict and set(configured).issubset({
                "api_key", "role", "daily_run_limit", "max_active_runs",
            }):
                policy = {
                    "api_key": configured.get("api_key"),
                    "role": configured.get("role", "member"),
                    "daily_run_limit": configured.get("daily_run_limit", 100),
                    "max_active_runs": configured.get("max_active_runs", 3),
                }
            else:
                raise ValueError("Each client must be an API key string or a valid policy object.")
            if (
                type(policy["api_key"]) is not str
                or type(policy["role"]) is not str
                or policy["role"] not in {"admin", "member"}
                or type(policy["daily_run_limit"]) is not int
                or not 1 <= policy["daily_run_limit"] <= 1_000_000
                or type(policy["max_active_runs"]) is not int
                or not 1 <= policy["max_active_runs"] <= 10_000
            ):
                raise ValueError("Client role and quotas in ABACUS_CLIENT_API_KEYS are invalid.")
            policies[client_id] = policy
        usable = [policy["api_key"] for policy in policies.values() if len(policy["api_key"]) >= 32]
        if len(usable) != len(policies) or len(set(usable)) != len(usable):
            raise ValueError("Each configured client API key must be unique and at least 32 characters.")
        return policies
    return {"default": {
        "api_key": os.getenv("ABACUS_API_KEY", ""),
        "role": "admin",
        "daily_run_limit": 100,
        "max_active_runs": 3,
    }}


def _request_log(
    *, request_id: str, method: str, path: str, status_code: int, duration_ms: float
) -> None:
    LOGGER.info(json.dumps({
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
    }, separators=(",", ":")))


def _load_problem(problem_id: str) -> ProblemSpec:
    filename = PROBLEM_FILES.get(problem_id)
    if filename is None:
        raise HTTPException(status_code=404, detail="Unknown problem_id.")
    path = PROJECT_ROOT / "problems" / filename
    try:
        return load_problem(path)
    except (ProblemValidationError, OSError) as error:
        LOGGER.error(json.dumps({
            "event": "problem_configuration_error",
            "problem_id": problem_id,
            "error_type": type(error).__name__,
        }, separators=(",", ":")))
        raise HTTPException(status_code=503, detail="The configured problem is unavailable.") from error


def _public_run(row: dict[str, Any], *, include_record: bool) -> dict[str, Any]:
    result = {
        "run_id": row["run_id"],
        "problem_id": row["problem_id"],
        "state": row["state"],
        "outcome": row["outcome"],
        "run_status": row["run_status"],
        "error_category": row["error_category"],
        "created_at_utc": row["created_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
        "finished_at_utc": row["finished_at_utc"],
    }
    if include_record:
        result["record"] = row["record"]
    return result


def create_app(
    *,
    data_dir: str | Path | None = None,
    database_url: str | None = None,
    api_key_reader: Callable[[], str] | None = None,
) -> FastAPI:
    """Create the service with optional isolated paths/readers for deployment and integration checks."""
    use_environment_paths = data_dir is None
    if use_environment_paths:
        configured_data_dir = Path(os.getenv("ABACUS_DATA_DIR", ".abacus-data"))
    else:
        configured_data_dir = Path(data_dir)
    if not configured_data_dir.is_absolute():
        configured_data_dir = PROJECT_ROOT / configured_data_dir
    configured_data_dir = configured_data_dir.resolve()

    if database_url is None:
        if use_environment_paths and os.getenv("ABACUS_DATABASE_URL"):
            configured_database_url = default_database_url()
        else:
            database_path = Path(
                os.getenv("ABACUS_DATABASE_PATH", str(configured_data_dir / "abacus.sqlite3"))
                if use_environment_paths else configured_data_dir / "abacus.sqlite3"
            )
            if not database_path.is_absolute():
                database_path = PROJECT_ROOT / database_path
            configured_database_url = sqlite_url(database_path.resolve())
    else:
        configured_database_url = database_url
    runs_dir = Path(
        os.getenv("ABACUS_RUNS_DIR", str(configured_data_dir / "runs"))
        if use_environment_paths else configured_data_dir / "runs"
    )
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir
    runs_dir = runs_dir.resolve()
    store = RunStore(configured_database_url)
    client_api_keys = _configured_client_keys(api_key_reader)
    api_key_clients = {
        policy["api_key"]: client_id for client_id, policy in client_api_keys.items()
    }
    local_ui_auto_auth = os.getenv("ABACUS_LOCAL_UI_AUTO_AUTH", "0").strip().lower() in {
        "1", "true", "yes",
    }
    run_mode = os.getenv("ABACUS_RUN_MODE", "inline").strip().lower()
    if run_mode not in {"inline", "queue"}:
        raise ValueError("ABACUS_RUN_MODE must be 'inline' or 'queue'.")
    run_semaphore = threading.BoundedSemaphore(value=1)
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store.initialize()
        store.sync_clients({
            client_id: {
                "role": policy["role"],
                "daily_run_limit": policy["daily_run_limit"],
                "max_active_runs": policy["max_active_runs"],
            }
            for client_id, policy in client_api_keys.items()
        }, now=_utc_now())
        store.sync_problems(list(PROBLEM_FILES), now=_utc_now())
        now = _utc_now()
        if run_mode == "queue":
            retried, exhausted = store.recover_expired_leases(now=now)
            if retried or exhausted:
                LOGGER.warning(json.dumps({
                    "event": "expired_worker_leases_recovered",
                    "requeued": retried,
                    "interrupted": exhausted,
                }))
        else:
            recovered = store.recover_orphaned_runs(now=_utc_text(now))
            if recovered:
                LOGGER.warning(json.dumps({"event": "orphaned_runs_recovered", "count": recovered}))
        try:
            yield
        finally:
            store.close()

    app = FastAPI(
        title="Abacus API",
        version="1.0.0",
        description="Authenticated API for the offline Abacus evaluation pipeline.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.runs_dir = runs_dir

    def authenticated_client(api_key: str | None = Security(API_KEY_HEADER)) -> dict[str, Any]:
        if not any(len(policy["api_key"]) >= 32 for policy in client_api_keys.values()):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured.",
            )
        for configured_key, client_id in api_key_clients.items():
            try:
                if api_key is not None and secrets.compare_digest(api_key, configured_key):
                    client = store.get_client(client_id)
                    if client is not None and client["is_active"]:
                        return client
                    break
            except TypeError:
                continue
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    def admin_client(client: dict[str, Any] = Depends(authenticated_client)) -> dict[str, Any]:
        if client["role"] != "admin":
            raise HTTPException(status_code=403, detail="Admin role required.")
        return client

    def is_local_ui_request(request: Request) -> bool:
        """Limit the optional keyless browser flow to same-origin loopback requests."""
        if not local_ui_auto_auth or request.client is None:
            return False
        try:
            if not ipaddress.ip_address(request.client.host).is_loopback:
                return False
            host_header = request.headers.get("host", "")
            host = urlsplit(f"//{host_header}")
            if host.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return False
            origin_value = request.headers.get("origin")
            if origin_value:
                origin = urlsplit(origin_value)
                if (
                    origin.scheme not in {"http", "https"}
                    or origin.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or origin.netloc.casefold() != host.netloc.casefold()
                ):
                    return False
        except ValueError:
            return False
        return True

    @app.middleware("http")
    async def structured_request_logging(request: Request, call_next):
        local_policy = client_api_keys.get("default")
        local_key = local_policy.get("api_key", "") if local_policy else ""
        if (
            request.url.path.startswith("/v1/") or request.url.path == "/metrics"
        ) and b"x-api-key" not in {
            name.lower() for name, _value in request.scope.get("headers", [])
        } and len(local_key) >= 32 and is_local_ui_request(request):
            request.scope["headers"] = [
                *request.scope.get("headers", []),
                (b"x-api-key", local_key.encode("latin-1")),
            ]
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        started = time.perf_counter()
        response_status = 500
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_seconds = time.perf_counter() - started
            try:
                store.record_http_request(
                    status_code=response_status,
                    duration_seconds=duration_seconds,
                    now=_utc_now(),
                )
            except SQLAlchemyError as error:
                LOGGER.error(json.dumps({
                    "event": "http_metric_write_failed",
                    "error_type": type(error).__name__,
                }, separators=(",", ":")))
            _request_log(
                request_id=request_id,
                method=request.method,
                path=getattr(request.scope.get("route"), "path", request.url.path),
                status_code=response_status,
                duration_ms=duration_seconds * 1_000,
            )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, error: SQLAlchemyError):
        LOGGER.error(json.dumps({
            "event": "database_error",
            "request_id": getattr(request.state, "request_id", None),
            "error_type": type(error).__name__,
        }, separators=(",", ":")))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Run storage is temporarily unavailable."},
        )

    @app.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"], response_model=None)
    def readiness() -> JSONResponse | dict[str, str]:
        if not any(len(policy["api_key"]) >= 32 for policy in client_api_keys.values()):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"},
            )
        try:
            if not store.ping():
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"status": "not_ready"},
                )
        except SQLAlchemyError:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    @app.get("/ui/session", include_in_schema=False)
    def local_ui_session(request: Request) -> dict[str, Any]:
        """Report local-only auto-auth readiness without returning any API secret."""
        policy = client_api_keys.get("default")
        if not is_local_ui_request(request) or policy is None or len(policy["api_key"]) < 32:
            raise HTTPException(status_code=404, detail="Local UI auto-connect is unavailable.")
        client = store.get_client("default")
        if client is None or not client["is_active"]:
            raise HTTPException(status_code=503, detail="Local UI client is not ready.")
        return {
            "authenticated": True,
            "client_id": client["client_id"],
            "role": client["role"],
        }

    @app.get("/metrics", include_in_schema=False, dependencies=[Depends(authenticated_client)])
    def prometheus_metrics() -> Response:
        snapshot = store.get_http_metrics()
        body = "\n".join((
            "# HELP abacus_http_requests_total Total HTTP requests recorded in durable storage.",
            "# TYPE abacus_http_requests_total counter",
            f"abacus_http_requests_total {snapshot['requests_total']}",
            "# HELP abacus_http_requests_4xx_total HTTP client-error responses.",
            "# TYPE abacus_http_requests_4xx_total counter",
            f"abacus_http_requests_4xx_total {snapshot['requests_4xx_total']}",
            "# HELP abacus_http_requests_5xx_total HTTP server-error responses.",
            "# TYPE abacus_http_requests_5xx_total counter",
            f"abacus_http_requests_5xx_total {snapshot['requests_5xx_total']}",
            "# HELP abacus_http_request_duration_seconds_sum Cumulative HTTP request duration.",
            "# TYPE abacus_http_request_duration_seconds_sum counter",
            f"abacus_http_request_duration_seconds_sum {snapshot['request_duration_seconds_sum']:.6f}",
            "",
        ))
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/v1/problems", dependencies=[Depends(authenticated_client)], tags=["problems"])
    def list_problems() -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        for problem_id in PROBLEM_FILES:
            spec = _load_problem(problem_id)
            problems.append({
                "problem_id": spec.problem_id,
                "claim": spec.claim,
                "target_id": spec.target_id,
                "contract_id": spec.contract_id,
                "oracle_id": spec.oracle_id,
            })
        return problems

    @app.get("/v1/admin/clients", tags=["admin"])
    def list_api_clients(
        _admin: dict[str, Any] = Depends(admin_client),
    ) -> list[dict[str, Any]]:
        """List client roles, limits, and current usage without exposing API keys."""
        return store.list_clients(now=_utc_now())

    @app.post(
        "/v1/runs",
        status_code=status.HTTP_201_CREATED,
        tags=["runs"],
        response_model=None,
    )
    def submit_run(
        payload: RunRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        client: dict[str, Any] = Depends(authenticated_client),
    ) -> JSONResponse | dict[str, Any]:
        if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key must be 16-128 safe ASCII characters.",
            )
        spec = _load_problem(payload.problem_id)
        idempotency_hash = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()

        client_id = client["client_id"]
        try:
            existing, created = store.reserve_run(
                run_id=str(uuid4()),
                client_id=client_id,
                problem_id=spec.problem_id,
                idempotency_hash=idempotency_hash,
                now=_utc_text(),
            )
        except RunQuotaExceeded as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": error.reason},
                headers={"Retry-After": str(error.retry_after)},
            ) from error
        if not created:
            if existing["problem_id"] != spec.problem_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key was already used for a different problem.",
                )
            response_status = (
                status.HTTP_200_OK
                if existing["state"] in {"finished", "failed", "interrupted"}
                else status.HTTP_202_ACCEPTED
            )
            return JSONResponse(
                status_code=response_status,
                content=_public_run(existing, include_record=existing["state"] == "finished"),
            )

        run_id = existing["run_id"]
        if run_mode == "queue":
            queued = store.get_run(run_id, client_id=client_id)
            assert queued is not None
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=_public_run(queued, include_record=False),
                headers={"Retry-After": "1"},
            )
        if not run_semaphore.acquire(blocking=False):
            store.fail_run(run_id, error_category="service_busy", now=_utc_text())
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Another evaluation is running; retry with a new Idempotency-Key.",
                headers={"Retry-After": "2"},
            )

        try:
            lease_token = store.mark_running(run_id, now=_utc_text())
            record = run_problem(spec, runs_dir=app.state.runs_dir, run_id=run_id)
            record.pop("log_path", None)
            store.finish_run(run_id, record, now=_utc_text(), lease_token=lease_token)
            finished = store.get_run(run_id, client_id=client_id)
            assert finished is not None
            return _public_run(finished, include_record=False)
        except HTTPException:
            raise
        except Exception as error:
            token = locals().get("lease_token")
            store.fail_run(
                run_id,
                error_category="evaluation_failed",
                now=_utc_text(),
                lease_token=token,
            )
            LOGGER.error(json.dumps({
                "event": "run_failed",
                "run_id": run_id,
                "problem_id": spec.problem_id,
                "error_type": type(error).__name__,
            }, separators=(",", ":")))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "evaluation_failed", "run_id": run_id},
            ) from error
        finally:
            run_semaphore.release()

    @app.get("/v1/runs/{run_id}", tags=["runs"])
    def get_run(
        run_id: UUID,
        client: dict[str, Any] = Depends(authenticated_client),
    ) -> dict[str, Any]:
        client_id = client["client_id"]
        row = store.get_run(str(run_id), client_id=client_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
        return _public_run(row, include_record=row["state"] == "finished")

    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.is_dir():
        # Keep the UI on the API origin so operators never need wildcard CORS.
        # Mounted after API routes so the existing endpoints retain precedence.
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


app = create_app()
