"""Authenticated HTTP API for the local Abacus evaluation pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from abacus.api_store import RunStore
from abacus.cli import run_problem
from abacus.schemas import ProblemSpec, ProblemValidationError, load_problem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_FILES = {
    "p01_true_sort": "p01_true_sort.json",
    "p02_false_sort": "p02_false_sort.json",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
LOGGER = logging.getLogger("abacus.api")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    problem_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


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

    database_path = Path(
        os.getenv("ABACUS_DATABASE_PATH", str(configured_data_dir / "abacus.sqlite3"))
        if use_environment_paths else configured_data_dir / "abacus.sqlite3"
    )
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    database_path = database_path.resolve()
    runs_dir = Path(
        os.getenv("ABACUS_RUNS_DIR", str(configured_data_dir / "runs"))
        if use_environment_paths else configured_data_dir / "runs"
    )
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir
    runs_dir = runs_dir.resolve()
    store = RunStore(database_path)
    read_api_key = api_key_reader or (lambda: os.getenv("ABACUS_API_KEY", ""))
    run_semaphore = threading.BoundedSemaphore(value=1)
    metrics_lock = threading.Lock()
    metrics = {
        "requests_total": 0,
        "requests_4xx_total": 0,
        "requests_5xx_total": 0,
        "request_duration_seconds_sum": 0.0,
    }

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store.initialize()
        now = _utc_now()
        recovered = store.recover_orphaned_runs(now=_utc_text(now))
        if recovered:
            LOGGER.warning(json.dumps({"event": "orphaned_runs_recovered", "count": recovered}))
        yield

    app = FastAPI(
        title="Abacus API",
        version="1.0.0",
        description="Authenticated API for the offline Abacus evaluation pipeline.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.runs_dir = runs_dir

    def require_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> None:
        expected = read_api_key()
        if not expected or len(expected) < 32:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured.",
            )
        try:
            authenticated = api_key is not None and secrets.compare_digest(api_key, expected)
        except TypeError:
            authenticated = False
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

    @app.middleware("http")
    async def structured_request_logging(request: Request, call_next):
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
            with metrics_lock:
                metrics["requests_total"] += 1
                if 400 <= response_status < 500:
                    metrics["requests_4xx_total"] += 1
                elif response_status >= 500:
                    metrics["requests_5xx_total"] += 1
                metrics["request_duration_seconds_sum"] += duration_seconds
            _request_log(
                request_id=request_id,
                method=request.method,
                path=getattr(request.scope.get("route"), "path", request.url.path),
                status_code=response_status,
                duration_ms=duration_seconds * 1_000,
            )

    @app.exception_handler(sqlite3.Error)
    async def database_error_handler(request: Request, error: sqlite3.Error):
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
        key = read_api_key()
        if not key or len(key) < 32:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"},
            )
        try:
            if not store.ping():
                raise sqlite3.OperationalError("SQLite ping returned no result.")
        except sqlite3.Error:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_api_key)])
    def prometheus_metrics() -> Response:
        with metrics_lock:
            snapshot = dict(metrics)
        body = "\n".join((
            "# HELP abacus_http_requests_total Total HTTP requests served by this process.",
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

    @app.get("/v1/problems", dependencies=[Depends(require_api_key)], tags=["problems"])
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

    @app.post(
        "/v1/runs",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_api_key)],
        tags=["runs"],
        response_model=None,
    )
    def submit_run(
        payload: RunRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> JSONResponse | dict[str, Any]:
        if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key must be 16-128 safe ASCII characters.",
            )
        spec = _load_problem(payload.problem_id)
        idempotency_hash = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()

        existing, created = store.reserve_run(
            run_id=str(uuid4()),
            problem_id=spec.problem_id,
            idempotency_hash=idempotency_hash,
            now=_utc_text(),
        )
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
        if not run_semaphore.acquire(blocking=False):
            store.fail_run(run_id, error_category="service_busy", now=_utc_text())
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Another evaluation is running; retry with a new Idempotency-Key.",
                headers={"Retry-After": "2"},
            )

        try:
            store.mark_running(run_id, now=_utc_text())
            record = run_problem(spec, runs_dir=app.state.runs_dir, run_id=run_id)
            record.pop("log_path", None)
            store.finish_run(run_id, record, now=_utc_text())
            finished = store.get_run(run_id)
            assert finished is not None
            return _public_run(finished, include_record=False)
        except HTTPException:
            raise
        except Exception as error:
            store.fail_run(run_id, error_category="evaluation_failed", now=_utc_text())
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

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(require_api_key)], tags=["runs"])
    def get_run(run_id: UUID) -> dict[str, Any]:
        row = store.get_run(str(run_id))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
        return _public_run(row, include_record=row["state"] == "finished")

    return app


app = create_app()
