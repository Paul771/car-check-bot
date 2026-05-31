import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str
    target_group_id: int
    google_sheet_id: str
    sheet_name: str
    column_index: int
    plate_recognizer_token: str = ""
    plate_recognizer_confidence: float = 0.97


def _parse_column_index(raw: str | None) -> int:
    """Parse COLUMN_INDEX env var, returning 2 (column B) by default.
    Handles empty string (e.g. when docker-compose passes an unset variable).
    """
    if not raw or not raw.strip():
        return 2
    return int(raw.strip())


def load_config() -> Config:
    """Load configuration from environment variables.
    Provides clearer error messages for required values.
    """
    bot_token = os.getenv("BOT_TOKEN", "")
    target_group_id = int(os.getenv("TARGET_GROUP_ID", "0"))
    google_sheet_id = os.getenv(
        "GOOGLE_SHEET_ID",
        "1NPuVFYQi0_T2qH5vxRYXH2SKhW498YslS3FxOxg9lT4",
    )
    sheet_name = os.getenv("SHEET_NAME", "Sheet1")
    column_index = _parse_column_index(os.getenv("COLUMN_INDEX"))

    plate_recognizer_token = os.getenv("PLATE_RECOGNIZER_API_KEY", "")

    raw_confidence = os.getenv("PLATE_RECOGNIZER_CONFIDENCE", "0.97")
    try:
        plate_recognizer_confidence = float(raw_confidence)
    except ValueError:
        plate_recognizer_confidence = 0.97
    if not (0.0 <= plate_recognizer_confidence <= 1.0):
        plate_recognizer_confidence = 0.97

    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is required but not set.")
    if target_group_id == 0:
        raise ValueError("TARGET_GROUP_ID environment variable must be a non‑zero integer.")
    return Config(
        bot_token=bot_token,
        target_group_id=target_group_id,
        google_sheet_id=google_sheet_id,
        sheet_name=sheet_name,
        column_index=column_index,
        plate_recognizer_token=plate_recognizer_token,
        plate_recognizer_confidence=plate_recognizer_confidence,
    )