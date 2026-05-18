import time
import logging

from bot.sheets import load_plate_numbers, normalize_plate
from bot.config import Config

logger = logging.getLogger(__name__)


class PlateCache:
    """
    Caches the set of known plate numbers from Google Sheets.
    Refreshes periodically to avoid excessive HTTP requests.
    """

    def __init__(self, config: Config, cache_ttl: int = 300):
        self.config = config
        self.cache_ttl = cache_ttl  # seconds (default: 5 minutes)
        self._plates: set[str] = set()
        self._last_update: float = 0

    def _refresh(self):
        """Fetch plate numbers from Google Sheets via public CSV export."""
        logger.info("Refreshing plate number cache from Google Sheets...")
        self._plates = load_plate_numbers(self.config)
        self._last_update = time.time()
        logger.info(f"Cache refreshed: {len(self._plates)} plates loaded.")

    def is_known(self, plate: str) -> bool:
        """Check if a plate number is in the database (with normalized comparison)."""
        if time.time() - self._last_update > self.cache_ttl:
            self._refresh()

        normalized = normalize_plate(plate)
        if not normalized:
            return False

        return normalized in self._plates

    def get_plate_count(self) -> int:
        """Return the number of cached plates."""
        if time.time() - self._last_update > self.cache_ttl:
            self._refresh()
        return len(self._plates)