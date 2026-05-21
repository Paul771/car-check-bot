import os
import time
import asyncio
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes

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

# Retry delays between restart attempts (seconds)
RETRY_DELAYS = [5, 15, 30, 60, 120]


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler. Logs the error and keeps the bot running."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)


def run_bot():
    """Start the bot with polling. Returns the exit code."""
    logger.info("Loading configuration...")
    config = load_config()

    if not config.bot_token:
        logger.error("BOT_TOKEN is not set. Exiting.")
        return 1

    if config.target_group_id == 0:
        logger.error("TARGET_GROUP_ID is not set or invalid. Exiting.")
        return 1

    logger.info("Initializing plate cache from Google Sheets...")
    plate_cache = PlateCache(config, cache_ttl=300)
    plate_count = plate_cache.get_plate_count()
    logger.info(f"Loaded {plate_count} plate numbers into cache.")

    logger.info("Building Telegram application...")
    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .http_version("1.1")
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(30.0)
        .get_updates_pool_timeout(30.0)
        .build()
    )

    # Register global error handler so the bot doesn't crash on network errors
    application.add_error_handler(error_handler)

    logger.info("Registering handlers...")
    register_handlers(application, plate_cache, config.target_group_id)

    logger.info("Starting bot polling...")
    try:
        application.run_polling(
            close_loop=False,  # Keep the event loop alive for retry
        )
    except Exception as e:
        logger.error(f"Bot polling exited with error: {e}", exc_info=True)
        return 2

    return 0


def main():
    """Entry point with automatic restart on failure."""
    attempt = 0

    while True:
        logger.info(f"Starting bot (attempt {attempt + 1})...")
        exit_code = run_bot()

        if exit_code in (0, 1):
            # 0 = clean exit, 1 = configuration error — do not restart
            logger.info("Bot stopped. Exiting.")
            break

        # exit_code 2 = crash / network error — restart with backoff
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        logger.info(f"Bot will restart in {delay} seconds...")
        time.sleep(delay)
        attempt += 1


if __name__ == "__main__":
    main()
