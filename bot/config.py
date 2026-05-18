import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str
    target_group_id: int
    google_sheet_id: str
    sheet_name: str
    column_index: int


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "")
    target_group_id = int(os.getenv("TARGET_GROUP_ID", "0"))
    google_sheet_id = os.getenv(
        "GOOGLE_SHEET_ID",
        "1NPuVFYQi0_T2qH5vxRYXH2SKhW498YslS3FxOxg9lT4",
    )
    sheet_name = os.getenv("SHEET_NAME", "Sheet1")
    column_index = int(os.getenv("COLUMN_INDEX", "1"))

    return Config(
        bot_token=bot_token,
        target_group_id=target_group_id,
        google_sheet_id=google_sheet_id,
        sheet_name=sheet_name,
        column_index=column_index,
    )