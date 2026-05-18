import csv
import io
import logging
import urllib.request
import urllib.error

from bot.config import Config

logger = logging.getLogger(__name__)

# Google Sheet can be exported as CSV without auth via this URL:
# https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}
# gid=0 means first sheet (Sheet1).


def _get_sheet_gid(sheet_name: str) -> int:
    """
    Map common sheet names to gid (0-based index).
    For most cases gid=0 is 'Sheet1'.
    For custom sheet names, Google uses incremental gid values.
    """
    # By default, the first sheet is gid=0
    return 0


def fetch_sheet_csv(config: Config) -> str:
    """
    Fetch the entire Google Sheet as CSV via public export URL.
    Returns raw CSV text. Uses direct connection (bypasses system proxy)
    to avoid corporate proxy issues.
    """
    gid = _get_sheet_gid(config.sheet_name)
    url = (
        f"https://docs.google.com/spreadsheets/d/{config.google_sheet_id}"
        f"/export?format=csv&gid={gid}"
    )

    logger.info(f"Fetching sheet data from: {url}")
    try:
        # Create an opener with empty ProxyHandler to bypass system proxy
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(url, timeout=30) as response:
            csv_text = response.read().decode("utf-8")
            return csv_text
    except urllib.error.URLError as e:
        logger.error(f"Failed to fetch sheet: {e}")
        raise


def load_plate_numbers(config: Config) -> set[str]:
    """
    Load all plate numbers from the public Google Sheet.
    Uses CSV export (no auth required for public sheets).
    Returns a set of normalized (uppercase, stripped) strings.
    """
    csv_text = fetch_sheet_csv(config)
    reader = csv.reader(io.StringIO(csv_text))

    plates = set()
    col_idx = config.column_index - 1  # 1-based to 0-based

    for row_num, row in enumerate(reader, start=1):
        if col_idx < len(row):
            val = row[col_idx].strip().upper()
            if val:
                plates.add(val)

    logger.info(f"Loaded {len(plates)} plate numbers from sheet (excl. header).")
    return plates


def normalize_plate(text: str) -> str:
    """Normalize a plate number for comparison."""
    return text.strip().upper()