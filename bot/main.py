import os
import asyncio
import logging
from datetime import datetime, timezone
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

# If no successful update poll for this many seconds, assume the bot is stuck
MAX_IDLE_SECONDS = 120


class LastUpdateTracker:
    """Tracks the timestamp of the last successful update poll."""

    def __init__(self):
        self._last_update_time: datetime = datetime.now(timezone.utc)

    def mark_update(self):
        self._last_update_time = datetime.now(timezone.utc)

    def seconds_since_last_update(self) -> float:
        return (datetime.now(timezone.utc) - self._last_update_time).total_seconds()


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler. Logs the error and keeps the bot running."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)


async def run_bot_async() -> int:
    """
    Start the bot with polling using manual lifecycle management.
    Returns 0 on clean stop, 2 on crash/network error.
    """
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

    update_tracker = LastUpdateTracker()

    # Patch the updater to track successful polls
    original_process_updates = application.updater._process_updates

    async def patched_process_updates(updates):
        if updates:
            update_tracker.mark_update()
        return await original_process_updates(updates)

    application.updater._process_updates = patched_process_updates

    logger.info("Starting bot polling manually...")
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            bootstrap_retries=0,
            drop_pending_updates=False,
        )

        logger.info("Bot is running. Monitoring for stuck connections...")

        while True:
            await asyncio.sleep(10.0)

            # Check if updater stopped
            if not application.updater.running:
                logger.error("Updater stopped unexpectedly!")
                break

            # Check if we haven't received updates for too long
            idle_seconds = update_tracker.seconds_since_last_update()
            if idle_seconds > MAX_IDLE_SECONDS:
                logger.error(
                    f"No updates received for {idle_seconds:.0f} seconds "
                    f"(limit: {MAX_IDLE_SECONDS}s). Assuming connection is stuck. Restarting..."
                )
                break

        return 2  # Signal restart needed

    except asyncio.CancelledError:
        logger.info("Bot was cancelled.")
        return 0
    except Exception as e:
        logger.error(f"Bot polling exited with error: {e}", exc_info=True)
        return 2
    finally:
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception as cleanup_err:
            logger.warning(f"Cleanup error (non-fatal): {cleanup_err}")


async def main_async():
    """Main async entry point with automatic restart on failure."""
    attempt = 0

    while True:
        logger.info(f"Starting bot (attempt {attempt + 1})...")
        exit_code = await run_bot_async()

        if exit_code in (0, 1):
            # 0 = clean exit, 1 = configuration error — do not restart
            logger.info("Bot stopped. Exiting.")
            break

        # exit_code 2 = crash / network error — restart with backoff
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        logger.info(f"Bot will restart in {delay} seconds...")
        await asyncio.sleep(delay)
        attempt += 1


def main():
    """Entry point that creates a new event loop for each run."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt. Exiting.")
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()


if __name__ == "__main__":
    main()