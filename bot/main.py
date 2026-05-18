import os
import logging
from dotenv import load_dotenv

from telegram.ext import ApplicationBuilder

from bot.config import load_config
from bot.utils import PlateCache
from bot.handlers import register_handlers


# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Loading configuration...")
    config = load_config()

    if not config.bot_token:
        logger.error("BOT_TOKEN is not set. Exiting.")
        return

    if config.target_group_id == 0:
        logger.error("TARGET_GROUP_ID is not set or invalid. Exiting.")
        return

    logger.info("Initializing plate cache from Google Sheets...")
    plate_cache = PlateCache(config, cache_ttl=300)
    plate_count = plate_cache.get_plate_count()
    logger.info(f"Loaded {plate_count} plate numbers into cache.")

    logger.info("Building Telegram application...")
    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .build()
    )

    logger.info("Registering handlers...")
    register_handlers(application, plate_cache, config.target_group_id)

    logger.info("Starting bot polling...")
    application.run_polling()


if __name__ == "__main__":
    main()