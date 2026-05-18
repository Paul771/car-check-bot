from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from bot.utils import PlateCache
from bot.sheets import normalize_plate


# Constants / Messages
MSG_START = (
    "Привет! Я бот для проверки номеров автомобилей.\n\n"
    "Отправьте мне номер машины, и я проверю его по базе данных."
)
MSG_FOUND = "Номер {plate} найден в базе данных ✅"
MSG_NOT_FOUND = (
    "Номер {plate} не числится в базе данных ❌\n\n"
    "Если хотите сообщить об этом, отправьте фото автомобиля "
    "(можно с текстовой подписью)."
)
MSG_PHOTO_FORWARDED = "Сообщение передано в группу разбора."
MSG_PLATE_COUNT = "В базе данных {count} номеров."


def register_handlers(
    application,
    plate_cache: PlateCache,
    target_group_id: int,
):
    """Register all message handlers with the application."""

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(MSG_START)

    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        count = plate_cache.get_plate_count()
        await update.message.reply_text(MSG_PLATE_COUNT.format(count=count))

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text.strip()

        # Ignore commands
        if user_text.startswith("/"):
            return

        normalized = normalize_plate(user_text)
        if not normalized:
            await update.message.reply_text(
                "Пожалуйста, отправьте корректный номер автомобиля."
            )
            return

        if plate_cache.is_known(normalized):
            await update.message.reply_text(
                MSG_FOUND.format(plate=user_text)
            )
        else:
            await update.message.reply_text(
                MSG_NOT_FOUND.format(plate=user_text)
            )

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Forward the photo + caption (if any) to the target group.
        Then reply to the user.
        """
        # Build the message to forward
        message = update.message

        # Copy the message to the target group
        # (copy_message preserves photo and caption)
        await message.copy(chat_id=target_group_id)

        await update.message.reply_text(MSG_PHOTO_FORWARDED)

    # --- Register handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))

    # Text handler (but not commands, not photos)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    # Photo handler (with or without caption)
    application.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )