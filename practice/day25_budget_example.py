"""Write a partial UNRESOLVED log when a tiny token budget blocks a call."""

from pathlib import Path

if __package__:
    from .budgets import BudgetConfig, BudgetTracker
else:
    from budgets import BudgetConfig, BudgetTracker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "practice" / "day25_tiny_budget_log.json"


def main() -> None:
    tracker = BudgetTracker(
        BudgetConfig(
            max_rounds=1,
            max_wall_time_seconds=10,
            max_model_calls=2,
            max_tokens=4,
            max_cost_usd=0.02,
        )
    )
    if not tracker.start_round():
        raise RuntimeError("The example round could not start.")

    # Preflight denies this request, so no model call is made.
    reservation = tracker.reserve_call(
        estimated_tokens=8,
        estimated_cost_usd=0.005,
        estimated_duration_seconds=1,
    )
    if reservation is not None:
        raise AssertionError("The deliberately tiny token limit should block the call.")

    tracker.finish_round()
    destination = tracker.save_log(LOG_PATH, evidence_complete=False)
    log = tracker.to_dict(evidence_complete=False)
    print(f"Run outcome: {log['run_outcome']['outcome']}")
    print(f"Stop reason: {log['stop_reason']}")
    print(f"Saved partial log: {destination}")


if __name__ == "__main__":
    main()
