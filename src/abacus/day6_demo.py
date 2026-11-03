"""Run the offline stub; pass --live to make one real API request."""

from __future__ import annotations

import argparse
import sys

from . import LLMError, ask, stub_ask


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also send one request to the configured API (uses quota and may incur charges)",
    )
    args = parser.parse_args(argv)

    stub_result = stub_ask("Give one short suggestion for a sorting function.")
    print(f"Stub ({stub_result.provider}): {stub_result.text}")
    print("Stub usage: unavailable; no API request was made.")

    if not args.live:
        print("Live API call skipped. Pass --live to make one request.")
        return 0

    try:
        live_result = ask(
            "Reply with exactly: Abacus Day 6 API check passed.",
            system="Follow the user's requested response format exactly.",
            max_tokens=32,
        )
    except LLMError as error:
        print(f"Live API call failed ({error.category}): {error}", file=sys.stderr)
        return 1

    print(f"Live response ({live_result.provider}/{live_result.model}): {live_result.text}")
    print(f"Usage: {live_result.usage if live_result.usage is not None else 'not reported'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
