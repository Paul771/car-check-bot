from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from bot.utils import PlateCache
from bot.sheets import normalize_plate
from bot.plate_recognizer import detect_plate


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

# Conversation states
CONFIRMING_PLATE, ENTERING_PLATE, CONFIRMING_SEND = range(3)

# Confidence thresholds
HIGH_CONFIDENCE = 0.8
LOW_CONFIDENCE = 0.3


# Latin letters used in Russian plates mapped to their Cyrillic display forms.
_LATIN_TO_CYRILLIC = str.maketrans({
    "A": "А",
    "B": "В",
    "E": "Е",
    "K": "К",
    "M": "М",
    "H": "Н",
    "O": "О",
    "P": "Р",
    "C": "С",
    "T": "Т",
    "Y": "У",
    "X": "Х",
})


def _display_plate(plate: str) -> str:
    """Convert plate to uppercase Cyrillic display form."""
    return plate.strip().upper().translate(_LATIN_TO_CYRILLIC)


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


def _confirm_plate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_plate"),
         InlineKeyboardButton("❌ Исправить", callback_data="wrong_plate")]
    ])


def _send_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Отправить", callback_data="confirm_send"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_send")]
    ])


def _no_detection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Ввести номер", callback_data="enter_plate"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_no_plate")]
    ])


def register_handlers(
    application,
    plate_cache: PlateCache,
    target_group_id: int,
    config,
):
    """Register all message handlers with the application."""

    def is_private_chat(update: Update) -> bool:
        """Check if the message is from a private chat (not a group)."""
        return update.effective_chat and update.effective_chat.type == "private"

    async def _process_plate(
        update: Update, context: ContextTypes.DEFAULT_TYPE, plate: str
    ) -> int:
        """Search plate in DB, reply 'found' or ask 'send to admin?'."""
        normalized = normalize_plate(plate)
        if not normalized:
            await update.effective_message.reply_text("Некорректный номер.")
            return ConversationHandler.END

        if plate_cache.is_known(normalized):
            await update.effective_message.reply_text(
                f"✅ Номер {_display_plate(plate)} найден в базе данных!"
            )
            return ConversationHandler.END

        context.user_data["send_plate"] = plate
        await update.effective_message.reply_text(
            f"❌ Номер {_display_plate(plate)} не найден в базе.\n\n"
            f"Отправить фото в группу разбора?",
            reply_markup=_send_to_admin_keyboard(),
        )
        return CONFIRMING_SEND

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
                MSG_FOUND.format(plate=_display_plate(user_input))
            )
        else:
            await update.message.reply_text(
                MSG_NOT_FOUND.format(plate=_display_plate(user_input))
            )

    def _forward_to_admin_text(user_identifier: str, user_text: str) -> str:
        return f"📩 Текстовое сообщение\nОт: {user_identifier}\n\n{user_text}"

    async def cmd_send_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /send_admin <text> command — forward text message to target group."""
        if not is_private_chat(update):
            return

        args = context.args
        if not args:
            context.user_data["awaiting_admin_text"] = True
            await update.message.reply_text(MSG_SEND_ADMIN_PROMPT)
            return

        user_identifier = _resolve_user_identifier(update)
        await context.bot.send_message(
            chat_id=target_group_id,
            text=_forward_to_admin_text(user_identifier, " ".join(args).strip()),
        )
        await update.message.reply_text(MSG_SENT_ADMIN)

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_chat(update):
            return
        user_text = update.message.text.strip()

        # Ignore commands
        if user_text.startswith("/"):
            return

        # Check if user is responding to /send_admin prompt
        if context.user_data.pop("awaiting_admin_text", False):
            user_identifier = _resolve_user_identifier(update)
            await context.bot.send_message(
                chat_id=target_group_id,
                text=_forward_to_admin_text(user_identifier, user_text),
            )
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
                MSG_FOUND.format(plate=_display_plate(user_text))
            )
            return

        # If user recently sent a photo for OCR, redirect to send-to-admin flow
        if context.user_data.get("photo_file_id"):
            context.user_data["send_plate"] = user_text
            await update.message.reply_text(
                f"❌ Номер {_display_plate(user_text)} не найден в базе.\n\n"
                f"Отправить фото в группу разбора?",
                reply_markup=_send_to_admin_keyboard(),
            )
            return

        await update.message.reply_text(
            MSG_NOT_FOUND.format(plate=_display_plate(user_text))
        )

    async def handle_photo_detection(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entry point for photo messages. Detect plate, branch by confidence."""
        if not is_private_chat(update):
            return ConversationHandler.END

        message = update.message
        photo_file = message.photo[-1]

        # Download photo bytes
        file = await context.bot.get_file(photo_file.file_id)
        image_bytes = await file.download_as_bytearray()

        # Store metadata for later forwarding
        context.user_data["photo_file_id"] = photo_file.file_id
        context.user_data["original_chat_id"] = update.effective_chat.id
        context.user_data["original_message_id"] = message.message_id

        results = await detect_plate(
            bytes(image_bytes), config.plate_recognizer_token
        )

        if results is None:
            await message.reply_text(
                "Сервис распознавания временно недоступен. "
                "Попробуйте позже или используйте /send_admin."
            )
            return ConversationHandler.END

        if not results:
            await message.reply_text(
                "Не удалось распознать номер на фото.",
                reply_markup=_no_detection_keyboard(),
            )
            return ENTERING_PLATE

        result = results[0]
        plate = result.get("plate", "")
        confidence = result.get("confidence", 0.0)

        if confidence >= HIGH_CONFIDENCE:
            return await _process_plate(update, context, plate)

        context.user_data["detected_plate"] = plate
        await message.reply_text(
            f"Похоже на номер: {_display_plate(plate)} (уверенность: {confidence:.0%})\n"
            f"Подтвердите или введите правильный номер:",
            reply_markup=_confirm_plate_keyboard(),
        )
        return CONFIRMING_PLATE

    async def handle_plate_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User confirms the detected plate is correct."""
        query = update.callback_query
        await query.answer()
        plate = context.user_data.get("detected_plate", "")
        await query.edit_message_text(f"Поиск номера {_display_plate(plate)}...")
        return await _process_plate(update, context, plate)

    async def handle_plate_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User says detected plate is wrong — prompt manual entry."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Введите номер вручную:")
        return ENTERING_PLATE

    async def handle_manual_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User typed a plate number manually."""
        plate = update.message.text.strip()
        return await _process_plate(update, context, plate)

    async def handle_enter_plate_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User pressed 'Enter plate' button — prompt for text."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Введите номер автомобиля:")
        return ENTERING_PLATE

    async def handle_cancel_no_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User cancels after no-detection."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Ок.")
        return ConversationHandler.END

    async def handle_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User confirmed — forward photo + plate to admin group."""
        query = update.callback_query
        await query.answer()
        plate = context.user_data.get("send_plate", "")
        photo_file_id = context.user_data.get("photo_file_id", "")
        user_identifier = _resolve_user_identifier(update)

        caption = f"📩 От: {user_identifier}\n\nОбнаруженный номер: {_display_plate(plate)}"
        if photo_file_id:
            await context.bot.send_photo(
                chat_id=target_group_id,
                photo=photo_file_id,
                caption=caption,
            )
        else:
            await context.bot.send_message(
                chat_id=target_group_id,
                text=caption,
            )

        await query.edit_message_text("Фото отправлено в группу разбора.")
        return ConversationHandler.END

    async def handle_admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User declined to forward to admin group."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Ок.")
        return ConversationHandler.END

    async def handle_admin_confirm_by_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User sent a photo in CONFIRMING_SEND — forward original photo + plate to admin."""
        if not is_private_chat(update):
            return ConversationHandler.END
        plate = context.user_data.get("send_plate", "")
        photo_file_id = context.user_data.get("photo_file_id", "")
        user_identifier = _resolve_user_identifier(update)

        caption = f"📩 От: {user_identifier}\n\nОбнаруженный номер: {_display_plate(plate)}"
        if photo_file_id:
            await context.bot.send_photo(
                chat_id=target_group_id,
                photo=photo_file_id,
                caption=caption,
            )
        else:
            await context.bot.send_message(
                chat_id=target_group_id,
                text=caption,
            )

        await update.message.reply_text("Фото отправлено в группу разбора.")
        return ConversationHandler.END

    async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User cancelled the conversation with /cancel."""
        await update.message.reply_text("Диалог отменён.")
        return ConversationHandler.END

    # --- Register handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("find", cmd_find))
    application.add_handler(CommandHandler("send_admin", cmd_send_admin))

    # Text handler (but not commands, not photos)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    # Photo + OCR ConversationHandler (replaces old handle_photo)
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo_detection)],
        states={
            CONFIRMING_PLATE: [
                CallbackQueryHandler(handle_plate_confirmed, pattern="^confirm_plate$"),
                CallbackQueryHandler(handle_plate_wrong, pattern="^wrong_plate$"),
                MessageHandler(filters.PHOTO, handle_photo_detection),
            ],
            ENTERING_PLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_plate),
                CallbackQueryHandler(handle_enter_plate_prompt, pattern="^enter_plate$"),
                CallbackQueryHandler(handle_cancel_no_plate, pattern="^cancel_no_plate$"),
            ],
            CONFIRMING_SEND: [
                CallbackQueryHandler(handle_admin_confirm, pattern="^confirm_send$"),
                CallbackQueryHandler(handle_admin_cancel, pattern="^cancel_send$"),
                MessageHandler(filters.PHOTO, handle_admin_confirm_by_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(conv_handler)