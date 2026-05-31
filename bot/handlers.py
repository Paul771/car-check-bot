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
BOT_DESCRIPTION = (
    "🔍 Бот для проверки номеров автомобилей по базе данных Google Sheets.\n\n"
    "📌 Возможности:\n"
    "• Проверка номера по базе (поиск по полному номеру или первым 6 символам)\n"
    "• Отправка фото нарушителя в группу разбора\n"
    "• Отправка текстового сообщения с описанием в группу разбора\n\n"
    "📋 Команды:\n"
    "/start — приветствие и список команд\n"
    "/find <номер> — проверить номер в базе (пример: /find А123ВВ777)\n"
    "/send_admin <текст> — отправить текстовое сообщение в группу разбора\n"
    "/stats — количество номеров в базе\n\n"
    "📸 Также можно просто отправить фото автомобиля "
    "(с подписью или без) — оно будет переслано в группу разбора "
    "с указанием отправителя."
)

MSG_START = (
    "Привет! Я бот для проверки номеров автомобилей.\n\n"
    "Отправьте мне номер машины, и я проверю его по базе данных.\n\n"
    "📋 Команды:\n"
    "/find <номер> — проверить номер в базе\n"
    "/send_admin <текст> — отправить сообщение в группу разбора\n"
    "/stats — статистика базы\n\n"
    "📸 Также можно отправить фото для передачи в группу разбора."
)
MSG_FOUND = "Номер {plate} найден в базе данных ✅"
MSG_NOT_FOUND = (
    "Номер {plate} не числится в базе данных ❌\n\n"
    "Если хотите сообщить об этом, отправьте фото автомобиля "
    "(можно с текстовой подписью) или используйте команду /send_admin."
)
MSG_PHOTO_FORWARDED = "Сообщение передано в группу разбора."
MSG_SENT_ADMIN = "Текстовое сообщение передано в группу разбора."
MSG_SEND_ADMIN_PROMPT = "Напишите текст сообщения для отправки в группу разбора:"
MSG_PLATE_COUNT = "В базе данных {count} номеров."


def _resolve_user_identifier(update: Update) -> str:
    """Get user identifier: username if available, else first/last name, else ID."""
    user = update.effective_user
    if user.username:
        return f"@{user.username}"
    elif user.first_name or user.last_name:
        parts = [user.first_name, user.last_name]
        return " ".join(p for p in parts if p)
    else:
        return f"User {user.id}"


def register_handlers(
    application,
    plate_cache: PlateCache,
    target_group_id: int,
):
    """Register all message handlers with the application."""

    def is_private_chat(update: Update) -> bool:
        """Check if the message is from a private chat (not a group)."""
        return update.effective_chat and update.effective_chat.type == "private"

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_chat(update):
            return
        await update.message.reply_text(MSG_START)

    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_chat(update):
            return
        count = plate_cache.get_plate_count()
        await update.message.reply_text(MSG_PLATE_COUNT.format(count=count))

    async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /find <plate_number> command."""
        if not is_private_chat(update):
            return

        # Join all args after command
        args = context.args
        if not args:
            await update.message.reply_text(
                "Использование: /find <номер>\n"
                "Пример: /find А123ВВ777"
            )
            return

        user_input = " ".join(args).strip()
        normalized = normalize_plate(user_input)
        if not normalized:
            await update.message.reply_text(
                "Пожалуйста, отправьте корректный номер автомобиля."
            )
            return

        if plate_cache.is_known(normalized):
            await update.message.reply_text(
                MSG_FOUND.format(plate=user_input)
            )
        else:
            await update.message.reply_text(
                MSG_NOT_FOUND.format(plate=user_input)
            )

    async def cmd_send_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /send_admin <text> command — forward text message to target group."""
        if not is_private_chat(update):
            return

        args = context.args
        if not args:
            context.user_data["awaiting_admin_text"] = True
            await update.message.reply_text(MSG_SEND_ADMIN_PROMPT)
            return

        await _forward_to_admin(update, " ".join(args).strip(), target_group_id)
        await update.message.reply_text(MSG_SENT_ADMIN)

    async def _forward_to_admin(update: Update, user_text: str, target_group_id: int):
        """Forward text message to the target group."""
        user_identifier = _resolve_user_identifier(update)
        message_to_group = f"📩 Текстовое сообщение\nОт: {user_identifier}\n\n{user_text}"
        await update.message.bot.send_message(
            chat_id=target_group_id,
            text=message_to_group,
        )

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_chat(update):
            return
        user_text = update.message.text.strip()

        # Ignore commands
        if user_text.startswith("/"):
            return

        # Check if user is responding to /send_admin prompt
        if context.user_data.pop("awaiting_admin_text", False):
            await _forward_to_admin(update, user_text, target_group_id)
            await update.message.reply_text(MSG_SENT_ADMIN)
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
        Forward the photo + caption (if any) to the target group,
        prepending the sender's username/ID to avoid spam.
        Then reply to the user.
        Only works in private chats.
        """
        if not is_private_chat(update):
            return
        message = update.message
        user_identifier = _resolve_user_identifier(update)

        # Prepare the caption with user info
        original_caption = message.caption or ""
        if original_caption:
            new_caption = f"📩 От: {user_identifier}\n\n{original_caption}"
        else:
            new_caption = f"📩 От: {user_identifier}"

        # Copy the message to the target group with modified caption
        await message.copy(chat_id=target_group_id, caption=new_caption)

        await update.message.reply_text(MSG_PHOTO_FORWARDED)

    # --- Register handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("find", cmd_find))
    application.add_handler(CommandHandler("send_admin", cmd_send_admin))

    # Text handler (but not commands, not photos)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    # Photo handler (with or without caption)
    application.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )