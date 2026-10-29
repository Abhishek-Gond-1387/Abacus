"""Practice UTF-8 files, JSON, and paths anchored to the project."""

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRACTICE_DIR = PROJECT_ROOT / "practice"
SAMPLE_JSON = PRACTICE_DIR / "sample.json"
SAMPLE_TEXT = PRACTICE_DIR / "sample.txt"
REQUIRED_FIELDS = {"name": str, "numbers": list, "enabled": bool}


def validate_record(record: Any) -> dict[str, Any]:
    """Require the sample record's fields and their expected basic types."""
    if not isinstance(record, dict):
        raise ValueError("JSON data must be an object")

    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ValueError("Missing required JSON field(s): " + ", ".join(missing))

    for field, expected_type in REQUIRED_FIELDS.items():
        if not isinstance(record[field], expected_type):
            raise ValueError(
                f"JSON field {field!r} must have type {expected_type.__name__}"
            )
    return record


def main() -> None:
    """Write and read example files, then check the JSON round-trip."""
    PRACTICE_DIR.mkdir(parents=True, exist_ok=True)

    original = {
        "name": "Abacus – सत्यापन",
        "numbers": [1, -2, 3, 0],
        "enabled": True,
    }
    with SAMPLE_JSON.open("w", encoding="utf-8") as file:
        json.dump(original, file, indent=2, ensure_ascii=False)
        file.write("\n")

    with SAMPLE_JSON.open("r", encoding="utf-8") as file:
        loaded = validate_record(json.load(file))

    if loaded != original:
        raise AssertionError("JSON round-trip changed the sample record")

    with SAMPLE_TEXT.open("w", encoding="utf-8") as file:
        file.write("UTF-8 check: नमस्ते, Abacus!\n")
    with SAMPLE_TEXT.open("r", encoding="utf-8") as file:
        text = file.read()

    print("Loaded name:", loaded["name"])
    print("JSON round-trip matches:", loaded == original)
    print("Text file:", text.rstrip())


if __name__ == "__main__":
    main()
