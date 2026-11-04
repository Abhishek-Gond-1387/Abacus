"""Database-leased background worker for queued evaluations."""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from abacus.api import PROBLEM_FILES, _load_problem, _utc_now
from abacus.api_store import RunStore
from abacus.database import PROJECT_ROOT, default_database_url
from abacus.cli import run_problem


LOGGER = logging.getLogger("abacus.worker")
MAX_ATTEMPTS = 3


class EvaluationWorker:
    def __init__(
        self,
        store: RunStore,
        *,
        runs_dir: Path,
        worker_id: str,
        poll_seconds: float = 1.0,
        lease_seconds: int = 90,
    ) -> None:
        if poll_seconds <= 0 or lease_seconds < 3:
            raise ValueError("poll_seconds must be positive and lease_seconds must be at least 3.")
        self.store = store
        self.runs_dir = runs_dir
        self.worker_id = worker_id[:128]
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds

    def run_one(self) -> bool:
        self.store.recover_expired_leases(now=_utc_now(), max_attempts=MAX_ATTEMPTS)
        claimed = self.store.claim_next_run(
            worker_id=self.worker_id,
            now=_utc_now(),
            lease_seconds=self.lease_seconds,
        )
        if claimed is None:
            return False
        row, lease_token = claimed
        run_id = row["run_id"]
        problem_id = row["problem_id"]
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()

        def heartbeat() -> None:
            interval = max(1.0, self.lease_seconds / 3)
            while not stop_heartbeat.wait(interval):
                try:
                    renewed = self.store.renew_lease(
                        run_id,
                        lease_token=lease_token,
                        now=_utc_now(),
                        lease_seconds=self.lease_seconds,
                    )
                except SQLAlchemyError:
                    LOGGER.exception(json.dumps({
                        "event": "worker_lease_renewal_failed",
                        "run_id": run_id,
                        "worker_id": self.worker_id,
                    }))
                    lease_lost.set()
                    return
                if not renewed:
                    lease_lost.set()
                    return

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f"abacus-lease-{run_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            filename = PROBLEM_FILES.get(problem_id)
            if filename is None:
                raise ValueError("The queued run refers to an unavailable problem.")
            spec = _load_problem(problem_id)
            record = run_problem(spec, runs_dir=self.runs_dir, run_id=run_id)
            record.pop("log_path", None)
            if lease_lost.is_set():
                LOGGER.warning(json.dumps({
                    "event": "worker_discarded_lost_lease_result",
                    "run_id": run_id,
                    "worker_id": self.worker_id,
                }))
                return True
            self.store.finish_run(
                run_id,
                record,
                now=_utc_now(),
                lease_token=lease_token,
            )
            LOGGER.info(json.dumps({
                "event": "worker_run_finished",
                "run_id": run_id,
                "worker_id": self.worker_id,
            }))
        except Exception as error:
            try:
                self.store.fail_run(
                    run_id,
                    error_category="evaluation_failed",
                    now=_utc_now(),
                    lease_token=lease_token,
                )
            except RuntimeError:
                LOGGER.warning(json.dumps({
                    "event": "worker_could_not_fail_lost_lease",
                    "run_id": run_id,
                    "worker_id": self.worker_id,
                }))
            LOGGER.error(json.dumps({
                "event": "worker_run_failed",
                "run_id": run_id,
                "problem_id": problem_id,
                "worker_id": self.worker_id,
                "error_type": type(error).__name__,
            }))
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=2)
        return True

    def serve(self, *, once: bool = False) -> None:
        while True:
            try:
                worked = self.run_one()
            except SQLAlchemyError:
                LOGGER.exception(json.dumps({
                    "event": "worker_storage_error",
                    "worker_id": self.worker_id,
                }))
                worked = False
            if once:
                return
            if not worked:
                time.sleep(self.poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued Abacus evaluations.")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{uuid4().hex[:12]}")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("ABACUS_WORKER_POLL_SECONDS", "1")))
    parser.add_argument("--lease-seconds", type=int, default=int(os.getenv("ABACUS_WORKER_LEASE_SECONDS", "90")))
    parser.add_argument("--once", action="store_true", help="Process at most one queued run and exit.")
    args = parser.parse_args()

    data_dir = Path(os.getenv("ABACUS_DATA_DIR", ".abacus-data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    runs_dir = Path(os.getenv("ABACUS_RUNS_DIR", str(data_dir / "runs")))
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)

    store = RunStore(default_database_url())
    try:
        store.initialize()
        store.sync_problems(list(PROBLEM_FILES), now=_utc_now())
        worker = EvaluationWorker(
            store,
            runs_dir=runs_dir.resolve(),
            worker_id=args.worker_id,
            poll_seconds=args.poll_seconds,
            lease_seconds=args.lease_seconds,
        )
        worker.serve(once=args.once)
    except KeyboardInterrupt:
        LOGGER.info(json.dumps({"event": "worker_shutdown", "worker_id": args.worker_id}))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("ABACUS_LOG_LEVEL", "INFO"))
    raise SystemExit(main())
