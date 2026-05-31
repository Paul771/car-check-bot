import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from bot.utils import PlateCache
from bot.sheets import normalize_plate
from bot.plate_recognizer import detect_plate


logger = logging.getLogger(__name__)


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
MSG_FIND_PROMPT = "Введите номер автомобиля для поиска:"
MSG_PLATE_COUNT = "В базе данных {count} номеров."

# Confidence thresholds
HIGH_CONFIDENCE = 0.8


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


async def _safe_edit(query, text: str):
    try:
        await query.edit_message_text(text)
    except Exception:
        pass


def _cleanup_plate_context(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("photo_file_id", None)
    context.user_data.pop("send_plate", None)
    context.user_data.pop("detected_plate", None)


def register_handlers(
    application,
    plate_cache: PlateCache,
    target_group_id: int,
    config,
):
    """Register all message handlers with the application."""

    def is_private_chat(update: Update) -> bool:
        return update.effective_chat and update.effective_chat.type == "private"

    async def _search_and_maybe_offer_send(
        update: Update, context: ContextTypes.DEFAULT_TYPE, plate: str
    ):
        """Search plate in DB, reply 'found' or ask 'send to admin?'."""
        normalized = normalize_plate(plate)
        if not normalized:
            await update.effective_message.reply_text("Некорректный номер.")
            return

        if plate_cache.is_known(normalized):
            await update.effective_message.reply_text(
                f"✅ Номер {_display_plate(plate)} найден в базе данных!"
            )
            _cleanup_plate_context(context)
            return

        context.user_data["send_plate"] = plate
        await update.effective_message.reply_text(
            f"❌ Номер {_display_plate(plate)} не найден в базе.\n\n"
            f"Отправить фото в группу разбора?",
            reply_markup=_send_to_admin_keyboard(),
        )

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

        args = context.args
        if not args:
            context.user_data["awaiting_find_input"] = True
            await update.message.reply_text(MSG_FIND_PROMPT)
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

        if user_text.startswith("/"):
            return

        # /send_admin response
        if context.user_data.pop("awaiting_admin_text", False):
            user_identifier = _resolve_user_identifier(update)
            await context.bot.send_message(
                chat_id=target_group_id,
                text=_forward_to_admin_text(user_identifier, user_text),
            )
            await update.message.reply_text(MSG_SENT_ADMIN)
            return

        # /find response
        if context.user_data.pop("awaiting_find_input", False):
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
            else:
                await update.message.reply_text(
                    MSG_NOT_FOUND.format(plate=_display_plate(user_text))
                )
            return

        # If user has a recent photo context, search and offer send-to-admin
        if context.user_data.get("photo_file_id"):
            await _search_and_maybe_offer_send(update, context, user_text)
            return

        # Default: search plate
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
        else:
            await update.message.reply_text(
                MSG_NOT_FOUND.format(plate=_display_plate(user_text))
            )

    async def handle_photo_detection(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entry point for photo messages. Detect plate, branch by confidence."""
        if not is_private_chat(update):
            return
        _cleanup_plate_context(context)
        try:
            message = update.message
            photo_file = message.photo[-1]

            file = await context.bot.get_file(photo_file.file_id)
            image_bytes = await file.download_as_bytearray()

            context.user_data["photo_file_id"] = photo_file.file_id

            results = await detect_plate(
                bytes(image_bytes), config.plate_recognizer_token
            )

            if results is None:
                await message.reply_text(
                    "Сервис распознавания временно недоступен. "
                    "Попробуйте позже или используйте /send_admin."
                )
                return

            if not results:
                await message.reply_text(
                    "Не удалось распознать номер на фото.",
                    reply_markup=_no_detection_keyboard(),
                )
                return

            result = results[0]
            plate = result.get("plate", "")
            try:
                raw = result.get("score") or result.get("confidence") or result.get("oscore") or 0.0
                confidence = float(raw)
            except (ValueError, TypeError):
                confidence = 0.0
            if confidence >= 1.0:
                confidence /= 100.0

            logger.info("PR result[0]: plate=%s score=%s", plate, confidence)

            if confidence >= HIGH_CONFIDENCE:
                await _search_and_maybe_offer_send(update, context, plate)
                return

            context.user_data["detected_plate"] = plate
            await message.reply_text(
                f"Похоже на номер: {_display_plate(plate)} (уверенность: {confidence:.1%})\n"
                f"Подтвердите или введите правильный номер:",
                reply_markup=_confirm_plate_keyboard(),
            )
        except Exception:
            logger.exception("handle_photo_detection crashed")
            await update.effective_message.reply_text(
                "Произошла ошибка при обработке фото. Попробуйте ещё раз."
            )

    async def handle_plate_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User confirms the detected plate is correct."""
        query = update.callback_query
        await query.answer()
        plate = context.user_data.get("detected_plate", "")
        await _safe_edit(query, f"Поиск номера {_display_plate(plate)}...")
        await _search_and_maybe_offer_send(update, context, plate)

    async def handle_plate_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User says detected plate is wrong — prompt manual entry."""
        query = update.callback_query
        await query.answer()
        context.user_data.pop("detected_plate", None)
        await _safe_edit(query, "Введите номер вручную:")

    async def handle_enter_plate_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User pressed 'Enter plate' button — prompt for text."""
        query = update.callback_query
        await query.answer()
        await _safe_edit(query, "Введите номер автомобиля:")

    async def handle_cancel_no_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User cancels after no-detection."""
        query = update.callback_query
        await query.answer()
        await _safe_edit(query, "Ок.")
        _cleanup_plate_context(context)

    async def handle_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User confirmed — forward photo + plate to admin group."""
        query = update.callback_query
        await query.answer()
        plate = context.user_data.get("send_plate", "")
        photo_file_id = context.user_data.get("photo_file_id", "")
        user_identifier = _resolve_user_identifier(update)

        caption = f"📩 От: {user_identifier}\n\nОбнаруженный номер: {_display_plate(plate)}"
        try:
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
            await _safe_edit(query, "Фото отправлено в группу разбора.")
        except Exception as e:
            logger.error("Send to admin failed: %s", e)
            await _safe_edit(query, "Ошибка отправки в группу разбора.")
        _cleanup_plate_context(context)

    async def handle_admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User declined to forward to admin group."""
        query = update.callback_query
        await query.answer()
        await _safe_edit(query, "Ок.")
        _cleanup_plate_context(context)

    # --- Register handlers ---

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("find", cmd_find))
    application.add_handler(CommandHandler("send_admin", cmd_send_admin))

    # Photo detection (always restarts fresh, no conversation state)
    application.add_handler(
        MessageHandler(filters.PHOTO, handle_photo_detection)
    )

    # Inline button callbacks
    application.add_handler(CallbackQueryHandler(handle_plate_confirmed, pattern="^confirm_plate$"))
    application.add_handler(CallbackQueryHandler(handle_plate_wrong, pattern="^wrong_plate$"))
    application.add_handler(CallbackQueryHandler(handle_enter_plate_prompt, pattern="^enter_plate$"))
    application.add_handler(CallbackQueryHandler(handle_cancel_no_plate, pattern="^cancel_no_plate$"))
    application.add_handler(CallbackQueryHandler(handle_admin_confirm, pattern="^confirm_send$"))
    application.add_handler(CallbackQueryHandler(handle_admin_cancel, pattern="^cancel_send$"))

    # Text handler (but not commands, not photos)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
