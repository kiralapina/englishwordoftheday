import asyncio
import concurrent.futures
import logging
import os
import random
import re
import sys
from datetime import datetime, time, timedelta, timezone
from functools import partial
from typing import Set
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

import database
import usage_metrics
import word_api
from grammar import config as grammar_config
from grammar.content_loader import get_all_exercises, get_all_topics
from grammar.dto import GrammarEventDTO, GrammarResponseDTO
from grammar.entrypoint import handle_grammar_event
from grammar.enums import ExerciseType, GrammarAction
from grammar.services.exercise_service import get_current_exercise
from grammar import repositories as grammar_repositories

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования - запись в файл и консоль
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)  # Создаем папку logs, если её нет

# Формат логов
log_format = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Настройка корневого логгера
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Очищаем существующие обработчики, чтобы избежать дублирования
root_logger.handlers.clear()

# Обработчик для записи в файл (логи с датой в имени файла)
log_file = os.path.join(log_dir, f'bot_{datetime.now().strftime("%Y-%m-%d")}.log')
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_format)
root_logger.addHandler(file_handler)

# Обработчик для записи в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)
root_logger.addHandler(console_handler)

# Настройка логирования для библиотеки telegram (только предупреждения и ошибки)
telegram_logger = logging.getLogger('telegram')
telegram_logger.setLevel(logging.WARNING)

# Получаем логгер для нашего модуля
logger = logging.getLogger(__name__)

# Логирование запуска
logger.info("=" * 50)
logger.info("Бот запускается...")
logger.info(f"Логи записываются в файл: {log_file}")
logger.info("=" * 50)

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Thread pool for offloading synchronous DB / grammar calls
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="bot_io")


async def _run_sync(func, *args, **kwargs):
    """Run a synchronous function in the thread pool without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, partial(func, *args, **kwargs))


# Большие базы слов и идиом (подгружаются из data/)
from data.words_base import WORDS_OF_THE_DAY
from data.idioms_base import IDIOMS_BY_LEVEL


def get_idiom_of_day(level: str) -> dict:
    """Идиома дня по уровню пользователя."""
    level = level.upper() if level in ("A1", "A2", "B1", "B2", "C1", "C2") else "B1"
    idioms = IDIOMS_BY_LEVEL.get(level, IDIOMS_BY_LEVEL["B1"])
    day_of_year = datetime.now().timetuple().tm_yday
    return idioms[(day_of_year - 1) % len(idioms)]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню — кнопки под полем ввода."""
    keyboard_rows = [
        [KeyboardButton("📚 Слово дня"), KeyboardButton("💬 Идиома дня")],
        [KeyboardButton("📖 Мои слова"), KeyboardButton("➕ Добавить слово")],
    ]
    if grammar_config.grammar_module_enabled():
        keyboard_rows.append([KeyboardButton("📘 Грамматика"), KeyboardButton("⚙️ Настройки")])
    else:
        keyboard_rows.append([KeyboardButton("⚙️ Настройки")])
    return ReplyKeyboardMarkup(
        keyboard_rows,
        resize_keyboard=True,
    )


def level_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора уровня (A1–C2)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("A1", callback_data="level_A1"), InlineKeyboardButton("A2", callback_data="level_A2")],
        [InlineKeyboardButton("B1", callback_data="level_B1"), InlineKeyboardButton("B2", callback_data="level_B2")],
        [InlineKeyboardButton("C1", callback_data="level_C1"), InlineKeyboardButton("C2", callback_data="level_C2")],
    ])


# Множество для хранения ID пользователей, подписанных на слова дня
subscribed_users: Set[int] = set()
GRAMMAR_RUNTIME_READY = False
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

def get_word_of_day() -> dict:
    """Получает слово дня на основе текущей даты"""
    day_of_year = datetime.now().timetuple().tm_yday
    word_index = (day_of_year - 1) % len(WORDS_OF_THE_DAY)
    word_data = WORDS_OF_THE_DAY[word_index]
    logger.info(f"Получено слово дня: {word_data['word']} (день года: {day_of_year}, индекс: {word_index})")
    return word_data


def _grammar_reply_markup(response: GrammarResponseDTO) -> InlineKeyboardMarkup | None:
    if not response.buttons:
        return None
    rows = []
    for row in response.buttons:
        rows.append([
            InlineKeyboardButton(button.text, callback_data=button.callback_data or "grammar:home")
            for button in row
        ])
    return InlineKeyboardMarkup(rows)


def _apply_grammar_state(context: ContextTypes.DEFAULT_TYPE, response: GrammarResponseDTO) -> None:
    state_update = response.state_update or {}
    if not state_update:
        return
    context.user_data["grammar_module"] = state_update.get("module", "grammar")
    context.user_data["grammar_state"] = state_update.get("state")
    context.user_data["grammar_topic_id"] = state_update.get("topic_id")
    context.user_data["grammar_session_id"] = state_update.get("session_id")
    context.user_data["grammar_exercise_id"] = state_update.get("exercise_id")
    context.user_data["grammar_exercise_index"] = state_update.get("exercise_index")
    context.user_data["grammar_expects_text_reply"] = response.expects_text_reply


def _clear_grammar_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "grammar_module",
        "grammar_state",
        "grammar_topic_id",
        "grammar_session_id",
        "grammar_exercise_id",
        "grammar_exercise_index",
        "grammar_expects_text_reply",
    ):
        context.user_data.pop(key, None)


def _grammar_level(user_id: int) -> str:
    level = database.get_user_level(user_id).upper()
    if level == "C2":
        return "C1"
    return level if level in {"A1", "A2", "B1", "B2", "C1"} else "B1"


def _grammar_response_unavailable() -> GrammarResponseDTO:
    return GrammarResponseDTO(message_text="Раздел грамматики сейчас недоступен.")


def _expects_text_grammar_answer(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("grammar_expects_text_reply"):
        return True
    session_id = context.user_data.get("grammar_session_id")
    if not session_id:
        return False
    exercise = get_current_exercise(session_id)
    return bool(exercise and exercise.type != ExerciseType.MULTIPLE_CHOICE)


async def _send_grammar_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    response: GrammarResponseDTO,
    *,
    edit_message: bool = False,
) -> None:
    _apply_grammar_state(context, response)
    markup = _grammar_reply_markup(response)
    if edit_message and update.callback_query:
        await update.callback_query.edit_message_text(
            response.message_text,
            parse_mode=response.parse_mode,
            reply_markup=markup,
        )
        return
    if update.message:
        await update.message.reply_text(
            response.message_text,
            parse_mode=response.parse_mode,
            reply_markup=markup,
        )
        return
    if update.callback_query:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=response.message_text,
            parse_mode=response.parse_mode,
            reply_markup=markup,
        )


def _build_grammar_event(
    user_id: int,
    chat_id: int,
    action: GrammarAction,
    *,
    topic_id: str | None = None,
    session_id: str | None = None,
    payload: dict | None = None,
) -> GrammarEventDTO:
    return GrammarEventDTO(
        user_id=str(user_id),
        chat_id=str(chat_id),
        level=_grammar_level(user_id),
        ui_language="ru",
        action=action,
        topic_id=topic_id,
        session_id=session_id,
        payload=payload or {},
    )


def _build_and_handle_grammar(user_id, chat_id, action, *, topic_id=None, session_id=None, payload=None):
    """Build event + call grammar entrypoint in one sync step (for executor offloading)."""
    event = _build_grammar_event(user_id, chat_id, action, topic_id=topic_id, session_id=session_id, payload=payload)
    return handle_grammar_event(event)


async def grammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть grammar-модуль."""
    if not grammar_config.grammar_module_enabled() or not GRAMMAR_RUNTIME_READY:
        await update.message.reply_text(_grammar_response_unavailable().message_text)
        return
    response = await _run_sync(
        _build_and_handle_grammar, update.effective_user.id, update.effective_chat.id, GrammarAction.OPEN_HOME,
    )
    await _send_grammar_response(update, context, response)
    asyncio.get_running_loop().run_in_executor(_executor, track_activity, update.effective_user.id, "open_grammar")


async def callback_grammar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка inline-кнопок grammar-модуля."""
    query = update.callback_query
    await query.answer()
    if not grammar_config.grammar_module_enabled() or not GRAMMAR_RUNTIME_READY:
        await query.edit_message_text(_grammar_response_unavailable().message_text)
        return

    data = query.data or ""
    parts = data.split(":")
    action = None
    topic_id = None
    session_id = None
    payload: dict = {}

    if len(parts) >= 2 and parts[1] == "home":
        action = GrammarAction.OPEN_HOME
    elif len(parts) >= 2 and parts[1] == "list_topics":
        action = GrammarAction.LIST_TOPICS
    elif len(parts) >= 2 and parts[1] == "choose_level":
        level = await _run_sync(database.get_user_level, update.effective_user.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"⚙️ Твой уровень: <b>{level}</b>.\n\n"
                "Выбери уровень для грамматики и идиом:"
            ),
            reply_markup=level_keyboard(),
            parse_mode="HTML",
        )
        return
    elif len(parts) >= 2 and parts[1] == "toggle_push":
        action = GrammarAction.TOGGLE_NOTIFICATIONS
    elif len(parts) >= 3 and parts[1] == "topic":
        action = GrammarAction.OPEN_TOPIC
        topic_id = parts[2]
    elif len(parts) >= 3 and parts[1] == "practice":
        action = GrammarAction.START_TOPIC_PRACTICE
        topic_id = parts[2]
    elif len(parts) >= 2 and parts[1] == "weak":
        action = GrammarAction.START_WEAK_TOPICS_REVIEW
    elif len(parts) >= 2 and parts[1] == "mistakes":
        action = GrammarAction.START_MISTAKES_REVIEW
    elif len(parts) >= 2 and parts[1] == "exit":
        action = GrammarAction.EXIT_GRAMMAR
    elif len(parts) >= 4 and parts[1] == "skip":
        action = GrammarAction.SUBMIT_ANSWER
        session_id = parts[2]
        payload["exercise_index"] = int(parts[3])
        payload["skip"] = True
    elif len(parts) >= 5 and parts[1] == "answer":
        action = GrammarAction.SUBMIT_ANSWER
        session_id = parts[2]
        payload["exercise_index"] = int(parts[3])
        payload["option_index"] = int(parts[4])

    if action is None:
        return

    response = await _run_sync(
        _build_and_handle_grammar,
        update.effective_user.id, update.effective_chat.id, action,
        topic_id=topic_id, session_id=session_id, payload=payload,
    )
    await _send_grammar_response(update, context, response, edit_message=True)
    asyncio.get_running_loop().run_in_executor(_executor, track_activity, update.effective_user.id, f"grammar_{action.value}")


def track_activity(user_id: int, event_type: str) -> None:
    """Log bot-wide user activity without breaking the main flow."""
    try:
        usage_metrics.track_user_activity(
            user_id=str(user_id),
            event_type=event_type,
            event_at=datetime.utcnow(),
        )
    except Exception as e:
        logger.warning("Failed to track user activity for %s (%s): %s", user_id, event_type, e)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Добавляем пользователя в список подписанных и в БД
    subscribed_users.add(user_id)
    database.get_or_create_user(user_id, user.username)
    
    word_data = get_word_of_day()
    
    message = (
        f"Привет, {user.first_name}! 👋\n\n"
        f"Я бот для изучения английского языка.\n\n"
        f"📚 <b>Слово дня сегодня:</b>\n"
        f"<b>{word_data['word']}</b>\n"
        f"🔊 <i>{word_data['transcription']}</i>\n"
        f"{word_data['translation']}\n"
        f"<i>Пример: {word_data['example']}</i>\n\n"
        "🔥 <b>Что умеет бот:</b>\n"
        "• Слово дня и идиома дня — каждый день, под твой уровень\n"
        "• 📘 Грамматика — теория, упражнения и повтор слабых тем\n"
        "• Личный словарь с интервальным повторением (SRS)\n"
        "• ИИ проверяет письменные задания и объясняет ошибки\n\n"
        "⚡ <b>Что нового:</b>\n"
        "• Раздел грамматики: 14 тем (A1–C1), теория + практика\n"
        "• Для B2/C1 — больше заданий на перефразирование\n"
        "• Умная проверка ответов через ИИ (с пояснениями на русском)\n"
        "• Весь контент подстраивается под выбранный уровень\n\n"
        "🚀 <b>Как начать:</b>\n"
        "1. Открой «⚙️ Настройки» и выбери свой уровень.\n"
        "2. Для грамматики открой «📘 Грамматика».\n"
        "3. В заданиях с кнопками нажимай ответ, без кнопок — пиши сообщением.\n\n"
        "Используй меню внизу или /help."
    )
    
    await update.message.reply_text(message, parse_mode='HTML', reply_markup=main_menu_keyboard())
    track_activity(user_id, "command_start")
    logger.info(f"User {user_id} ({user.first_name}) started the bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    user = update.effective_user
    grammar_section = "📘 <b>Грамматика</b> — теория, упражнения и повтор слабых тем\n" if grammar_config.grammar_module_enabled() else ""
    grammar_command_hint = " | /grammar — раздел грамматики" if grammar_config.grammar_module_enabled() else ""
    message = (
        "📋 <b>Меню и команды:</b>\n\n"
        "📚 <b>Слово дня</b> — ежедневное слово с транскрипцией\n"
        "💬 <b>Идиома дня</b> — идиома по твоему уровню (A1–C2)\n"
        "📖 <b>Мои слова</b> — твоя лексика и повторения (SRS)\n"
        "➕ <b>Добавить слово</b> — формат: <code>слово — перевод</code>\n"
        f"{grammar_section}"
        "⚙️ <b>Настройки</b> — смена уровня\n\n"
        "<b>Как пользоваться грамматикой:</b>\n"
        "1. Выбери уровень в настройках.\n"
        "2. Открой тему и прочитай короткую теорию.\n"
        "3. Если в упражнении есть кнопки, нажми нужный вариант.\n"
        "4. Если кнопок нет, напиши ответ сообщением в чат.\n\n"
        "/start — главное меню | /word — слово дня | /help — эта справка | /test — проверка бота | /stats — статистика"
        f"{grammar_command_hint}"
    )
    await update.message.reply_text(message, parse_mode='HTML', reply_markup=main_menu_keyboard())
    track_activity(user.id, "command_help")
    logger.info(f"User {user.id} ({user.first_name}) requested help")

async def word_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /word - выдает слово дня"""
    word_data = get_word_of_day()
    
    message = (
        f"📚 <b>Слово дня:</b>\n"
        f"<b>{word_data['word']}</b>\n"
        f"🔊 <i>{word_data['transcription']}</i>\n"
        f"{word_data['translation']}\n"
        f"<i>Пример: {word_data['example']}</i>"
    )
    
    await update.message.reply_text(message, parse_mode='HTML')
    track_activity(update.effective_user.id, "command_word")
    logger.info(f"User {update.effective_user.id} requested word of the day")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /test - проверка работы бота"""
    user = update.effective_user
    is_subscribed = user.id in subscribed_users
    level = database.get_user_level(user.id)
    
    message = (
        f"✅ <b>Проверка работы бота:</b>\n\n"
        f"Статус: Работает нормально ✅\n"
        f"Ваш ID: {user.id}\n"
        f"Уровень: {level}\n"
        f"Подписка на слова дня: {'Активна ✅' if is_subscribed else 'Не активна ❌'}\n"
        f"Текущая дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"Все команды работают корректно! 🎉"
    )
    
    await update.message.reply_text(message, parse_mode='HTML')
    track_activity(user.id, "command_test")
    logger.info(f"User {user.id} tested the bot")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать внутреннюю статистику использования бота."""
    user = update.effective_user
    try:
        metrics = usage_metrics.get_usage_metrics()
        total_users = len(database.get_all_user_ids())
        message = (
            "📊 <b>Статистика бота</b>\n\n"
            f"MAU ({metrics['window_days']} days): <b>{metrics['mau']}</b>\n"
            f"Всего пользователей: <b>{total_users}</b>\n"
            f"Рассчитано: <code>{metrics['calculated_at']}</code>"
        )
        await update.message.reply_text(message, parse_mode='HTML')
        track_activity(user.id, "command_stats")
    except Exception as e:
        logger.error("Failed to build stats: %s", e)
        await update.message.reply_text("Не удалось получить статистику. Проверь подключение к БД.")


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Разовая рассылка сообщения всем пользователям. Только для админа."""
    if update.effective_user.id != ADMIN_ID:
        return
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "Использование: <code>/announce Текст сообщения</code>\n"
            "Поддерживается HTML-разметка.",
            parse_mode="HTML",
        )
        return
    user_ids = database.get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"Рассылка завершена: {sent} доставлено, {failed} ошибок.")
    logger.info("Admin announce: sent=%d, failed=%d", sent, failed)


async def idiom_of_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Идиома дня по уровню пользователя."""
    user = update.effective_user
    level = database.get_user_level(user.id)
    idiom = get_idiom_of_day(level)
    msg = (
        f"💬 <b>Идиома дня</b> (уровень {level})\n\n"
        f"<b>{idiom['idiom']}</b>\n"
        f"Значение: {idiom['meaning']}\n"
        f"<i>Пример: {idiom['example']}</i>\n\n"
        f"✏️ Напиши в ответ своё предложение с этой фразой — потренируешься!"
    )
    await update.message.reply_text(msg, parse_mode='HTML')
    track_activity(user.id, "open_idiom_of_day")
    logger.info(f"User {user.id} requested idiom of the day")


async def my_words_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Мои слова: показать количество на повторение и предложить повторить."""
    user = update.effective_user
    track_activity(user.id, "open_my_words")
    due = database.get_words_for_review(user.id, limit=20)
    all_words = database.get_all_user_words(user.id, limit=100)
    
    if not all_words:
        await update.message.reply_text(
            "📖 Пока слов нет. Добавь первое через кнопку «➕ Добавить слово» или напиши: <code>слово — перевод</code>.",
            parse_mode='HTML'
        )
        return
    
    text = f"📖 <b>Твоя лексика:</b> {len(all_words)} слов\n"
    text += f"🔄 На повторение сегодня: {len(due)} слов\n\n"
    if due:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Повторить", callback_data="review_start")]])
        await update.message.reply_text(text + "Нажми кнопку ниже, чтобы начать повторение.", reply_markup=keyboard, parse_mode='HTML')
    else:
        await update.message.reply_text(text + "Всё повторено на сегодня! 🎉", parse_mode='HTML')
    logger.info(f"User {user.id} opened my words")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройки: выбор уровня."""
    user_id = update.effective_user.id
    level = database.get_user_level(user_id)
    await update.message.reply_text(
        (
            f"⚙️ Твой уровень: <b>{level}</b>.\n\n"
            "Этот уровень сейчас влияет на весь учебный контент бота.\n"
            "Для грамматики доступны уровни A1-C1. Если у тебя выбран C2, в грамматике пока будет использоваться C1.\n\n"
            "Выбери новый уровень:"
        ),
        reply_markup=level_keyboard(),
        parse_mode='HTML'
    )
    track_activity(user_id, "open_settings")


async def callback_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатия уровня (A1–C2)."""
    query = update.callback_query
    await query.answer()
    if not query.data or not query.data.startswith("level_"):
        return
    level = query.data.replace("level_", "")
    database.set_user_level(update.effective_user.id, level)
    await query.edit_message_text(
        f"✅ Уровень изменён на <b>{level}</b>. Теперь под него подстраивается учебный контент бота.",
        parse_mode='HTML',
    )
    track_activity(update.effective_user.id, "set_level")
    logger.info(f"User {update.effective_user.id} set level to {level}")


async def callback_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ответа в повторении (правильно/неправильно)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data or ""
    
    if data == "review_start":
        due = database.get_words_for_review(user_id, limit=20)
        if not due:
            await query.edit_message_text("🔄 На сегодня повторений нет. Загляни завтра!")
            track_activity(user_id, "review_start_empty")
            return
        context.user_data["review_list"] = due
        context.user_data["review_index"] = 0
        await query.edit_message_text("🔄 Выбери перевод ниже:")
        await _send_review_word(query, context, user_id, due[0])
        track_activity(user_id, "review_start")
        return
    
    if data.startswith("review_ok_"):
        vocab_id = int(data.replace("review_ok_", ""))
        database.advance_srs(vocab_id, user_id)
        review_list = context.user_data.get("review_list") or []
        idx = context.user_data.get("review_index", 0) + 1
        context.user_data["review_index"] = idx
        if idx < len(review_list):
            await query.edit_message_text("✅ Верно! Следующее слово:")
            await _send_review_word(query, context, user_id, review_list[idx])
        else:
            await query.edit_message_text("✅ Верно! Повторение на сегодня завершено. 🎉")
            context.user_data.pop("review_list", None)
            context.user_data.pop("review_index", None)
        track_activity(user_id, "review_ok")
        return
    
    if data.startswith("review_fail_"):
        await query.edit_message_text("❌ Неверно. Попробуй ещё раз позже в «Мои слова».")
        context.user_data.pop("review_list", None)
        context.user_data.pop("review_index", None)
        track_activity(user_id, "review_fail")


def _make_review_keyboard(vocab_id: int, translation: str, user_id: int) -> InlineKeyboardMarkup:
    """Кнопки выбора перевода: один правильный + до трёх неверных вариантов."""
    if not translation:
        translation = "?"
    all_words = database.get_all_user_words(user_id, limit=50)
    others = [w["translation"] for w in all_words if w.get("translation") and w["translation"] != translation][:20]
    random.shuffle(others)
    options = [translation] + (others[:3] if len(others) >= 3 else others)
    random.shuffle(options)
    buttons = []
    for opt in options[:4]:
        if opt == translation:
            buttons.append(InlineKeyboardButton(opt, callback_data=f"review_ok_{vocab_id}"))
        else:
            buttons.append(InlineKeyboardButton(opt, callback_data=f"review_fail_{vocab_id}"))
    return InlineKeyboardMarkup([[b] for b in buttons])


async def _send_review_word(query, context, user_id: int, word_row: dict) -> None:
    """Отправить одно слово на повторение с кнопками выбора перевода."""
    keyboard = _make_review_keyboard(word_row["id"], word_row["translation"] or "", user_id)
    text = f"Как перевести?\n\n<b>{word_row['word']}</b>"
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')


async def add_word_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подсказка формата и включение режима добавления слова."""
    context.user_data["awaiting_add_word"] = True
    await update.message.reply_text(
        "➕ Напиши слово для добавления.\n\n"
        "• Только <b>слово</b> — перевод и транскрипция подставятся автоматически по API.\n"
        "• Или вручную: <code>слово — перевод</code> или <code>слово / перевод</code>.\n"
        "• Пример после точки: <code>слово — перевод. Пример.</code>",
        parse_mode='HTML'
    )
    track_activity(update.effective_user.id, "open_add_word")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текста: добавление слова (по формату) или кнопки меню, иначе приветствие."""
    user = update.effective_user
    message_text = (update.message.text or "").strip()
    
    # Режим «добавить слово»: парсим "слово — перевод" или одно слово (тогда автопополнение по API)
    if context.user_data.get("awaiting_add_word"):
        context.user_data.pop("awaiting_add_word", None)
        track_activity(user.id, "add_word")
        translation = ""
        transcription = ""
        example = ""
        word_part = ""
        match = re.match(r"^(.+?)\s*[—/\-]\s*(.+)$", message_text, re.DOTALL)
        if match:
            word_part = match.group(1).strip()
            rest = match.group(2).strip()
            if ". " in rest:
                trans_part, example = rest.split(". ", 1)
                translation = trans_part.strip()
                example = example.strip()
            else:
                translation = rest
        else:
            word_part = message_text.strip()
        if not word_part:
            await update.message.reply_text("Напиши слово (или формат: слово — перевод)")
            return
        # Автопополнение по API, если нет перевода/примера/транскрипции (в executor, чтобы не блокировать бота)
        if not translation or not example or not transcription:
            loop = asyncio.get_event_loop()
            api_data = await loop.run_in_executor(None, word_api.fetch_word_data, word_part)
            if api_data:
                if not transcription and api_data.get("transcription"):
                    transcription = api_data["transcription"]
                if not translation and api_data.get("translation"):
                    translation = api_data["translation"]
                if not example and api_data.get("example_sentence"):
                    example = api_data["example_sentence"]
        vid = database.add_word(user.id, word_part, translation=translation, transcription=transcription, example=example)
        if vid is None:
            await update.message.reply_text("Не удалось сохранить слово. Проверь подключение к базе.")
            return
        card = (
            f"✅ Слово добавлено! Давай закрепим.\n\n"
            f"<b>{word_part}</b>\n"
            + (f"🔊 <i>{transcription}</i>\n" if transcription else "")
            + (f"{translation}\n" if translation else "")
            + (f"<i>Пример: {example}</i>" if example else "")
        )
        await update.message.reply_text(card, parse_mode='HTML')
        logger.info(f"User {user.id} added word: {word_part}")
        return

    if (
        grammar_config.grammar_module_enabled()
        and GRAMMAR_RUNTIME_READY
        and context.user_data.get("grammar_state") == "awaiting_answer"
        and _expects_text_grammar_answer(context)
    ):
        response = await _run_sync(
            _build_and_handle_grammar,
            user.id, update.effective_chat.id, GrammarAction.SUBMIT_ANSWER,
            session_id=context.user_data.get("grammar_session_id"),
            payload={
                "answer": message_text,
                "exercise_id": context.user_data.get("grammar_exercise_id"),
                "exercise_index": context.user_data.get("grammar_exercise_index"),
            },
        )
        await _send_grammar_response(update, context, response)
        asyncio.get_running_loop().run_in_executor(_executor, track_activity, user.id, "grammar_submit_answer")
        return
    
    # Кнопки главного меню
    if message_text == "📘 Грамматика":
        await grammar_command(update, context)
        return
    if message_text == "📚 Слово дня":
        word_data = get_word_of_day()
        msg = (
            f"📚 <b>Слово дня:</b>\n"
            f"<b>{word_data['word']}</b>\n"
            f"🔊 <i>{word_data['transcription']}</i>\n"
            f"{word_data['translation']}\n"
            f"<i>Пример: {word_data['example']}</i>"
        )
        await update.message.reply_text(msg, parse_mode='HTML')
        track_activity(user.id, "open_word_of_day")
        return
    if message_text == "💬 Идиома дня":
        await idiom_of_day_command(update, context)
        return
    if message_text == "📖 Мои слова":
        await my_words_command(update, context)
        return
    if message_text == "➕ Добавить слово":
        await add_word_prompt(update, context)
        return
    if message_text == "⚙️ Настройки":
        await settings_command(update, context)
        return
    
    # Обычное сообщение — приветствие
    greetings = [
        f"Привет, {user.first_name}! 👋",
        f"Здравствуй, {user.first_name}! 😊",
        f"Добро пожаловать, {user.first_name}! 🎉",
        f"Приветик, {user.first_name}! ✨",
    ]
    greeting = random.choice(greetings)
    response = (
        f"{greeting}\n\n"
        f"Используй меню внизу: слово дня, идиома дня, мои слова или добавь новое слово. "
        f"/help — справка."
    )
    await update.message.reply_text(response)
    track_activity(user.id, "message")
    logger.info(f"User {user.id} sent a message: {message_text}")

_last_daily_word_date = None
_last_daily_idiom_date = None
_last_daily_grammar_date = None


async def send_daily_words(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет слово дня всем подписанным пользователям"""
    global _last_daily_word_date
    today = datetime.now(tz=timezone.utc).date()
    if _last_daily_word_date == today:
        logger.warning("send_daily_words already executed today (%s), skipping duplicate run", today)
        return
    _last_daily_word_date = today

    word_data = get_word_of_day()
    
    message = (
        f"🌅 <b>Слово дня:</b>\n"
        f"<b>{word_data['word']}</b>\n"
        f"🔊 <i>{word_data['transcription']}</i>\n"
        f"{word_data['translation']}\n"
        f"<i>Пример: {word_data['example']}</i>\n\n"
        f"Удачи в изучении английского! 📚✨\n\n"
        f"📘 Не забудь попрактиковать грамматику → /grammar"
    )
    
    # Берем пользователей из БД, чтобы рассылка работала и после рестарта.
    user_ids = database.get_all_user_ids()
    subscribed_users.update(user_ids)

    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Sent daily word to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send message to user {user_id}: {e}")
            # Удаляем пользователя из списка, если чат недоступен
            subscribed_users.discard(user_id)


async def send_daily_idiom(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рассылает идиому дня всем пользователям из БД (по их уровню)."""
    global _last_daily_idiom_date
    today = datetime.now(tz=timezone.utc).date()
    if _last_daily_idiom_date == today:
        logger.warning("send_daily_idiom already executed today (%s), skipping duplicate run", today)
        return
    _last_daily_idiom_date = today

    for user_id in database.get_all_user_ids():
        try:
            level = database.get_user_level(user_id)
            idiom = get_idiom_of_day(level)
            msg = (
                f"💬 <b>Идиома дня</b> (уровень {level})\n\n"
                f"<b>{idiom['idiom']}</b>\n"
                f"Значение: {idiom['meaning']}\n"
                f"<i>Пример: {idiom['example']}</i>\n\n"
                f"✏️ Напиши предложение с этой фразой — закрепишь!\n\n"
                f"📘 А ещё загляни в грамматику → /grammar"
            )
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')
            logger.info(f"Sent daily idiom to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send idiom to user {user_id}: {e}")


def _get_daily_grammar_topic(user_id: int) -> dict | None:
    level = _grammar_level(user_id)
    level_topics = [topic for topic in get_all_topics() if topic.level == level]
    if not level_topics:
        return None
    progress_map = grammar_repositories.list_topic_progress(str(user_id))
    level_topics.sort(
        key=lambda topic: (
            progress_map.get(topic.topic_id).mastery_score if progress_map.get(topic.topic_id) else 0,
            topic.order,
        )
    )
    topic = level_topics[0]
    progress = progress_map.get(topic.topic_id)
    return {
        "level": level,
        "title": topic.title,
        "topic_id": topic.topic_id,
        "mastery_score": progress.mastery_score if progress else 0,
    }


async def send_daily_grammar_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет opt-in напоминание по grammar."""
    if not grammar_config.grammar_module_enabled():
        return
    global _last_daily_grammar_date
    today = datetime.now(tz=timezone.utc).date()
    if _last_daily_grammar_date == today:
        logger.warning("send_daily_grammar_push already executed today (%s), skipping duplicate run", today)
        return
    _last_daily_grammar_date = today

    for user_id in database.get_users_with_grammar_notifications():
        try:
            topic = _get_daily_grammar_topic(user_id)
            if not topic:
                continue
            text = (
                "📘 <b>Напоминание по грамматике</b>\n\n"
                f"Сегодня советую потренировать тему: <b>{topic['title']}</b>\n"
                f"Уровень: {topic['level']}\n"
                f"Текущее освоение: {topic['mastery_score']}\n\n"
                "Открой /grammar и продолжи практику."
            )
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            logger.info("Sent daily grammar push to user %s", user_id)
        except Exception as e:
            logger.error("Failed to send grammar push to user %s: %s", user_id, e)


def main() -> None:
    """Основная функция запуска бота"""
    global GRAMMAR_RUNTIME_READY

    try:
        if not BOT_TOKEN:
            logger.error("BOT_TOKEN не найден в переменных окружения!")
            raise ValueError("BOT_TOKEN не найден! Убедитесь, что он указан в .env файле")
        
        logger.info(f"Токен бота загружен (длина: {len(BOT_TOKEN)} символов)")
        
        # Проверка подключения к PostgreSQL (alwaysdata и др.)
        try:
            database.init_db()
            database.init_grammar_db()
            usage_metrics.init_usage_metrics()
            subscribed_users.update(database.get_all_user_ids())
            logger.info("Подключение к БД успешно, таблицы проверены")
        except Exception as e:
            GRAMMAR_RUNTIME_READY = False
            logger.error("Ошибка подключения к БД: %s. Проверьте DATABASE_URL или PGHOST/PGUSER/PGPASSWORD в .env", e)
            raise

        if not database.wait_for_bot_lock():
            logger.error(
                "Could not acquire PostgreSQL singleton lock in time. "
                "Another instance is still running or BOT_LOCK_WAIT_SECONDS too low."
            )
            sys.exit(1)
        logger.info("Singleton lock acquired — this is the only running instance")

        if grammar_config.grammar_module_enabled():
            try:
                grammar_repositories.sync_catalog(get_all_topics(), get_all_exercises())
                GRAMMAR_RUNTIME_READY = True
                logger.info("Grammar catalog синхронизирован")
            except Exception as e:
                GRAMMAR_RUNTIME_READY = False
                logger.error("Grammar module init failed: %s", e)
        else:
            GRAMMAR_RUNTIME_READY = False
        
        # Создаем приложение
        logger.info("Создание приложения бота...")
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("Приложение бота создано успешно")
        
        # Регистрируем обработчики команд
        logger.info("Регистрация обработчиков команд...")
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("word", word_command))
        application.add_handler(CommandHandler("test", test_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("grammar", grammar_command))
        application.add_handler(CommandHandler("announce", announce_command))
        application.add_handler(CallbackQueryHandler(callback_level, pattern="^level_"))
        application.add_handler(CallbackQueryHandler(callback_review, pattern="^review"))
        application.add_handler(CallbackQueryHandler(callback_grammar, pattern="^grammar:"))
        logger.info("Обработчики команд зарегистрированы: /start, /help, /word, /test, /stats, /grammar + меню и SRS")
        
        # Регистрируем обработчик текстовых сообщений (в конце, чтобы не перехватывать команды)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Обработчик текстовых сообщений зарегистрирован")
        
        now = datetime.now()
        target_time_word = time(9, 0, tzinfo=timezone.utc)
        target_time_idiom = time(10, 0, tzinfo=timezone.utc)
        target_time_grammar = time(18, 0, tzinfo=timezone.utc)
        next_run = now  # для лога
        
        if application.job_queue is None:
            logger.warning("JobQueue недоступен. Ежедневные рассылки отключены. Установите: pip install 'python-telegram-bot[job-queue]==20.7'")
        else:
            next_run = datetime.combine(now.date() + timedelta(days=1), target_time_word)
            application.job_queue.run_daily(send_daily_words, time=target_time_word, name="daily_word")
            logger.info(f"Запланирована отправка слова дня в 9:00 (первый раз: {next_run.strftime('%d.%m.%Y %H:%M')})")

            next_idiom = datetime.combine(now.date() + timedelta(days=1), target_time_idiom)
            application.job_queue.run_daily(send_daily_idiom, time=target_time_idiom, name="daily_idiom")
            logger.info(f"Запланирована отправка идиомы дня в 10:00 (первый раз: {next_idiom.strftime('%d.%m.%Y %H:%M')})")

            if grammar_config.grammar_module_enabled():
                next_grammar = datetime.combine(now.date() + timedelta(days=1), target_time_grammar)
                application.job_queue.run_daily(send_daily_grammar_push, time=target_time_grammar, name="daily_grammar_push")
                logger.info(f"Запланирован grammar push в 18:00 (первый раз: {next_grammar.strftime('%d.%m.%Y %H:%M')})")
        
        logger.info("=" * 50)
        logger.info("Бот успешно запущен!")
        logger.info(f"Текущее время: {now.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Первая отправка слова дня будет в {next_run.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Подписанных пользователей: {len(subscribed_users)}")
        logger.info("Бот готов к работе. Ожидание сообщений...")
        logger.info("=" * 50)
        
        # Запускаем бота
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except Exception as e:
        logger.exception(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()
