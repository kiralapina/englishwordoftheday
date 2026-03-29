import asyncio
import logging
import os
import random
import re
from datetime import datetime, time, timedelta
from typing import Set
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

import database
import word_api

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
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📚 Слово дня"), KeyboardButton("💬 Идиома дня")],
            [KeyboardButton("📖 Мои слова"), KeyboardButton("➕ Добавить слово")],
            [KeyboardButton("⚙️ Настройки")],
        ],
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

def get_word_of_day() -> dict:
    """Получает слово дня на основе текущей даты"""
    day_of_year = datetime.now().timetuple().tm_yday
    word_index = (day_of_year - 1) % len(WORDS_OF_THE_DAY)
    word_data = WORDS_OF_THE_DAY[word_index]
    logger.info(f"Получено слово дня: {word_data['word']} (день года: {day_of_year}, индекс: {word_index})")
    return word_data

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
        f"Я бот для изучения английского языка. Каждый день — новое слово и идиома!\n\n"
        f"📚 <b>Слово дня сегодня:</b>\n"
        f"<b>{word_data['word']}</b>\n"
        f"🔊 <i>{word_data['transcription']}</i>\n"
        f"{word_data['translation']}\n"
        f"<i>Пример: {word_data['example']}</i>\n\n"
        f"Используй меню внизу или /help."
    )
    
    await update.message.reply_text(message, parse_mode='HTML', reply_markup=main_menu_keyboard())
    logger.info(f"User {user_id} ({user.first_name}) started the bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    user = update.effective_user
    message = (
        "📋 <b>Меню и команды:</b>\n\n"
        "📚 <b>Слово дня</b> — ежедневное слово с транскрипцией\n"
        "💬 <b>Идиома дня</b> — идиома под твой уровень (A1–C2)\n"
        "📖 <b>Мои слова</b> — твоя лексика и повторения (SRS)\n"
        "➕ <b>Добавить слово</b> — формат: <code>слово — перевод</code>\n"
        "⚙️ <b>Настройки</b> — смена уровня\n\n"
        "/start — главное меню | /word — слово дня | /help — эта справка | /test — проверка бота"
    )
    await update.message.reply_text(message, parse_mode='HTML', reply_markup=main_menu_keyboard())
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
    logger.info(f"User {user.id} tested the bot")


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
    logger.info(f"User {user.id} requested idiom of the day")


async def my_words_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Мои слова: показать количество на повторение и предложить повторить."""
    user = update.effective_user
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
    level = database.get_user_level(update.effective_user.id)
    await update.message.reply_text(
        f"⚙️ Твой уровень: <b>{level}</b>. Выбери новый уровень:",
        reply_markup=level_keyboard(),
        parse_mode='HTML'
    )


async def callback_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатия уровня (A1–C2)."""
    query = update.callback_query
    await query.answer()
    if not query.data or not query.data.startswith("level_"):
        return
    level = query.data.replace("level_", "")
    database.set_user_level(update.effective_user.id, level)
    await query.edit_message_text(f"✅ Уровень изменён на <b>{level}</b>. Идиомы дня теперь под твой уровень.", parse_mode='HTML')
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
            return
        context.user_data["review_list"] = due
        context.user_data["review_index"] = 0
        await query.edit_message_text("🔄 Выбери перевод ниже:")
        await _send_review_word(query, context, user_id, due[0])
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
        return
    
    if data.startswith("review_fail_"):
        await query.edit_message_text("❌ Неверно. Попробуй ещё раз позже в «Мои слова».")
        context.user_data.pop("review_list", None)
        context.user_data.pop("review_index", None)


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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текста: добавление слова (по формату) или кнопки меню, иначе приветствие."""
    user = update.effective_user
    message_text = (update.message.text or "").strip()
    
    # Режим «добавить слово»: парсим "слово — перевод" или одно слово (тогда автопополнение по API)
    if context.user_data.get("awaiting_add_word"):
        context.user_data.pop("awaiting_add_word", None)
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
    
    # Кнопки главного меню
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
    logger.info(f"User {user.id} sent a message: {message_text}")

async def send_daily_words(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет слово дня всем подписанным пользователям"""
    word_data = get_word_of_day()
    
    message = (
        f"🌅 <b>Слово дня:</b>\n"
        f"<b>{word_data['word']}</b>\n"
        f"🔊 <i>{word_data['transcription']}</i>\n"
        f"{word_data['translation']}\n"
        f"<i>Пример: {word_data['example']}</i>\n\n"
        f"Удачи в изучении английского! 📚✨"
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
    for user_id in database.get_all_user_ids():
        try:
            level = database.get_user_level(user_id)
            idiom = get_idiom_of_day(level)
            msg = (
                f"💬 <b>Идиома дня</b> (уровень {level})\n\n"
                f"<b>{idiom['idiom']}</b>\n"
                f"Значение: {idiom['meaning']}\n"
                f"<i>Пример: {idiom['example']}</i>\n\n"
                f"✏️ Напиши предложение с этой фразой — закрепишь!"
            )
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')
            logger.info(f"Sent daily idiom to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send idiom to user {user_id}: {e}")


def main() -> None:
    """Основная функция запуска бота"""
    try:
        if not BOT_TOKEN:
            logger.error("BOT_TOKEN не найден в переменных окружения!")
            raise ValueError("BOT_TOKEN не найден! Убедитесь, что он указан в .env файле")
        
        logger.info(f"Токен бота загружен (длина: {len(BOT_TOKEN)} символов)")
        
        # Проверка подключения к PostgreSQL (alwaysdata и др.)
        try:
            database.init_db()
            subscribed_users.update(database.get_all_user_ids())
            logger.info("Подключение к БД успешно, таблицы проверены")
        except Exception as e:
            logger.error("Ошибка подключения к БД: %s. Проверьте DATABASE_URL или PGHOST/PGUSER/PGPASSWORD в .env", e)
            raise
        
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
        application.add_handler(CallbackQueryHandler(callback_level, pattern="^level_"))
        application.add_handler(CallbackQueryHandler(callback_review, pattern="^review"))
        logger.info("Обработчики команд зарегистрированы: /start, /help, /word, /test + меню и SRS")
        
        # Регистрируем обработчик текстовых сообщений (в конце, чтобы не перехватывать команды)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Обработчик текстовых сообщений зарегистрирован")
        
        now = datetime.now()
        target_time_word = time(9, 0)
        target_time_idiom = time(10, 0)
        next_run = now  # для лога
        
        if application.job_queue is None:
            logger.warning("JobQueue недоступен. Ежедневные рассылки отключены. Установите: pip install 'python-telegram-bot[job-queue]==20.7'")
        else:
            if now.time() > target_time_word:
                next_run = datetime.combine(now.date() + timedelta(days=1), target_time_word)
            else:
                next_run = datetime.combine(now.date(), target_time_word)
            delay_word = (next_run - now).total_seconds()
            application.job_queue.run_once(send_daily_words, when=delay_word, name="daily_word")
            application.job_queue.run_daily(send_daily_words, time=target_time_word, name="daily_word_recurring")
            logger.info(f"Запланирована отправка слова дня в 9:00 (первый раз: {next_run.strftime('%d.%m.%Y %H:%M')})")
            if now.time() > target_time_idiom:
                next_idiom = datetime.combine(now.date() + timedelta(days=1), target_time_idiom)
            else:
                next_idiom = datetime.combine(now.date(), target_time_idiom)
            delay_idiom = (next_idiom - now).total_seconds()
            application.job_queue.run_once(send_daily_idiom, when=delay_idiom, name="daily_idiom")
            application.job_queue.run_daily(send_daily_idiom, time=target_time_idiom, name="daily_idiom_recurring")
            logger.info(f"Запланирована отправка идиомы дня в 10:00 (первый раз: {next_idiom.strftime('%d.%m.%Y %H:%M')})")
        
        logger.info("=" * 50)
        logger.info("Бот успешно запущен!")
        logger.info(f"Текущее время: {now.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Первая отправка слова дня будет в {next_run.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Подписанных пользователей: {len(subscribed_users)}")
        logger.info("Бот готов к работе. Ожидание сообщений...")
        logger.info("=" * 50)
        
        # Запускаем бота
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.exception(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()
