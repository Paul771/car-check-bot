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
        """Create a new PlateCache.
        Initializes an empty prefix set for fast short‑match lookups.
        """
        self.config = config
        self.cache_ttl = cache_ttl  # seconds (default: 5 minutes)
        self._plates: set[str] = set()
        self._prefixes: set[str] = set()
        self._last_update: float = 0

    def _refresh(self):
        """Refresh the plate cache.
        If the Google Sheet cannot be fetched, keep the existing cache and log a warning.
        """
        logger.info("Refreshing plate number cache from Google Sheets...")
        try:
            self._plates = load_plate_numbers(self.config)
            # Build prefix set for fast short‑match lookups
            self._prefixes = {p[:6] for p in self._plates}
        except Exception as e:
            logger.warning(f"Failed to refresh plate cache: {e}. Keeping previous cache.")
            # Keep existing plates/prefixes unchanged
        self._last_update = time.time()
        logger.info(f"Cache refreshed: {len(self._plates)} plates loaded.")

    def is_known(self, plate: str) -> bool:
        """Check if a plate number is known.
        - Full match for plates with length >= 8.
        - Prefix match for plates with length >= 6.
        """
        if time.time() - self._last_update > self.cache_ttl:
            self._refresh()

        normalized = normalize_plate(plate)
        if not normalized:
            return False

        if len(normalized) >= 8:
            # Full match (8+ chars): exact match of the full plate
            return normalized in self._plates
        elif len(normalized) >= 6:
            # Prefix match (6 or more chars): compare against pre‑computed prefixes
            return normalized[:6] in self._prefixes
        return False

    def get_plate_count(self) -> int:
        """Return the number of cached plates."""
        if time.time() - self._last_update > self.cache_ttl:
            self._refresh()
        return len(self._plates)