import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
from datetime import datetime, timedelta, date, time, timezone
import re
import json
from pathlib import Path
from filelock import FileLock, Timeout  # pip install filelock
from logging.handlers import TimedRotatingFileHandler

# Завантажуємо .env
load_dotenv()

# Основні критичні змінні
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено в .env файлі!")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ALLOWED_CHAT_IDS_STR = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS = set()
if ALLOWED_CHAT_IDS_STR:
    try:
        ALLOWED_CHAT_IDS = {int(x.strip()) for x in ALLOWED_CHAT_IDS_STR.split(",") if x.strip()}
    except ValueError as e:
        print(f"Помилка парсингу ALLOWED_CHAT_IDS: {e}")

# Антифлуд-ліміти (можна налаштувати через .env)
DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", 200))
HOURLY_MESSAGE_LIMIT = int(os.getenv("HOURLY_MESSAGE_LIMIT", 100))
HOURLY_MUTE_MINUTES = int(os.getenv("HOURLY_MUTE_MINUTES", 15))
SHORT_TERM_MESSAGE_LIMIT = int(os.getenv("SHORT_TERM_MESSAGE_LIMIT", 10))
SHORT_TERM_WINDOW_MINUTES = int(os.getenv("SHORT_TERM_WINDOW_MINUTES", 5))
SHORT_TERM_MUTE_MINUTES = int(os.getenv("SHORT_TERM_MUTE_MINUTES", 3))
VOICE_MUTE_MINUTES = int(os.getenv("VOICE_MUTE_MINUTES", 30))
DAILY_MUTE_DAYS = int(os.getenv("DAILY_MUTE_DAYS", 7))

# Нові опції звільнення від антифлуд-лічильників
EXEMPT_OWNER_ANTIFLOOD = os.getenv("EXEMPT_OWNER_ANTIFLOOD", "true").lower() == "true"
EXEMPT_CREATOR_ANTIFLOOD = os.getenv("EXEMPT_CREATOR_ANTIFLOOD", "true").lower() == "true"
EXEMPT_ADMIN_ANTIFLOOD = os.getenv("EXEMPT_ADMIN_ANTIFLOOD", "true").lower() == "true"

# ─── Налаштування логування з ротацією за часом ───
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(
    filename="bot_moderation.log",
    when='midnight',
    interval=1,
    backupCount=30,
    encoding='utf-8'
)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# ────────────────────────────────────────────────────────────────
ALLOWED_GROUP_FILTER = filters.Chat(chat_id=ALLOWED_CHAT_IDS) & filters.ChatType.GROUPS

# ─── JSON збереження ────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DAILY_FILE = DATA_DIR / "daily_limits.json"
HOURLY_FILE = DATA_DIR / "hourly_data.json"
SHORT_FILE = DATA_DIR / "short_term_data.json"
MUTES_FILE = DATA_DIR / "mutes.json"

def save_json(path: Path, data):
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        with FileLock(lock_path, timeout=3):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
    except Timeout:
        logger.warning(f"Timeout lock {path}")
    except Exception as e:
        logger.error(f"Помилка збереження {path}: {e}")

def load_json(path: Path, default={}):
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Помилка читання {path}: {e}")
        return default

# Завантаження при старті
daily_limits = {}
raw = load_json(DAILY_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        date_str = v["date"]
        entry_date = datetime.fromisoformat(date_str).date()
        daily_limits[user_id] = {"date": entry_date, "count": int(v["count"])}
    except Exception as e:
        logger.warning(f"Помилка завантаження daily для {k}: {v} — {e}")

hourly_data = {}
raw = load_json(HOURLY_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        hourly_data[user_id] = [datetime.fromisoformat(t) for t in v]
    except Exception as e:
        logger.warning(f"Помилка завантаження hourly для {k}: {v} — {e}")

short_term_data = {}
raw = load_json(SHORT_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        short_term_data[user_id] = [datetime.fromisoformat(t) for t in v]
    except Exception as e:
        logger.warning(f"Помилка завантаження short_term для {k}: {v} — {e}")

# Мута — завантажуємо тільки активні
mutes = {}
raw_mutes = load_json(MUTES_FILE, default={})
now = datetime.now(timezone.utc)
for k, v in raw_mutes.items():
    try:
        until = datetime.fromisoformat(v)
        if until > now:
            mutes[int(k)] = until
    except Exception as e:
        logger.warning(f"Помилка завантаження mute для {k}: {v} — {e}")

logger.info(f"Завантажено: daily={len(daily_limits)}, hourly={len(hourly_data)}, "
            f"short={len(short_term_data)}, active mutes={len(mutes)}")

def save_daily():
    data = {str(k): {
        "date": datetime.combine(v["date"], time(0, 0), tzinfo=timezone.utc).isoformat(),
        "count": v["count"]
    } for k, v in daily_limits.items()}
    save_json(DAILY_FILE, data)

def save_hourly():
    data = {str(k): [t.isoformat() for t in v] for k, v in hourly_data.items()}
    save_json(HOURLY_FILE, data)

def save_short():
    data = {str(k): [t.isoformat() for t in v] for k, v in short_term_data.items()}
    save_json(SHORT_FILE, data)

def save_mutes():
    data = {str(k): v.isoformat() for k, v in mutes.items()}
    save_json(MUTES_FILE, data)

# Rate limit для приватних повідомлень від бота
last_private_msg: dict[int, datetime] = {}

# ─── Error handler ────────────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

# ─── Функції бота ────────────────────────────────────────────────────────────────
async def delete_command_message(message):
    if not message or message.chat.type == "private":
        return
    try:
        await message.delete()
    except TelegramError as e:
        logger.debug(f"Не вдалося видалити команду: {e}")

async def reply_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode=None):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    now = datetime.now(timezone.utc)
    if user_id != OWNER_ID:
        last = last_private_msg.get(user_id)
        if last and now - last < timedelta(minutes=1):
            logger.info(f"Rate limit приватного повідомлення для користувача {user_id}")
            return
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=text,
            parse_mode=parse_mode,
            disable_notification=True
        )
    except TelegramError as e:
        logger.info(f"Не вдалося надіслати в приват {user.id}: {e}")
        return
    if user_id != OWNER_ID:
        last_private_msg[user_id] = now

# ... (start, lock, unlock, stats, test_cmd — без змін)

async def manual_mute(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_id: int, minutes: int, reason: str):
    mute_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    mutes[target_id] = mute_until
    save_mutes()
    logger.info(f"Ручний мут {target_id} на {minutes} хв у чаті {chat_id}: {reason}")

# ... (mute15, mute60, mute24h, mute666, unmute, listmute — без змін)

async def apply_soft_mute(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int,
                         minutes: int, reason: str, mention_name: str = None):
    if user_id is None:
        return
    mute_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    mutes[user_id] = mute_until
    save_mutes()
    mention = f"<a href=\"tg://user?id={user_id}\">{mention_name or 'Користувач'}</a>"
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{mention} обмежено на {minutes} хв за: {reason}\nПовідомлення видалятимуться.",
            parse_mode="HTML",
            disable_notification=True
        )
    except:
        pass
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Тебе обмежено в групі на {minutes} хвилин за: {reason}."
        )
    except:
        pass
    logger.info(f"Soft-mute {user_id} → {minutes} хв: {reason}")

group_locked = False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global group_locked, daily_limits, hourly_data, short_term_data, mutes
    message = update.message
    if not message:
        return
    chat_id = message.chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        return
    current_time = message.date
    user_id = message.from_user.id if message.from_user else None
    is_anonymous = user_id is None

    # Перевірка мута + очищення лічильників при автоматичній експірації
    if user_id and user_id in mutes:
        if datetime.now(timezone.utc) < mutes[user_id]:
            try:
                await message.delete()
            except:
                pass
            return
        else:
            # Мут закінчився — знімаємо та очищаємо short_term + hourly
            del mutes[user_id]
            save_mutes()
            if user_id in short_term_data:
                del short_term_data[user_id]
                save_short()
                logger.info(f"Short-term data очищено для {user_id} після автоматичної експірації мута")
            if user_id in hourly_data:
                del hourly_data[user_id]
                save_hourly()
                logger.info(f"Hourly data очищено для {user_id} після автоматичної експірації мута")

    # ... (решта коду handle_message без змін: group_locked, voice, exempt, антифлуд-блоки)

    save_daily()
    save_hourly()
    save_short()

# ... (auto_delete_commands, main блок — без змін)

# =============================================================================
# ─── ВЕРСІЇ ТА ІНСТРУКЦІЇ ДЛЯ МАЙБУТНЬОГО GROK ───────────────────────────────
# =============================================================================
#
# Поточна версія: 0.0.25
#
# Правила зміни версії (обов’язково виконуй при кожному повному виводі коду):
#
# 1. Версія завжди в форматі MAJOR.MINOR.PATCH
# • MAJOR = 0 → експериментальна / альфа-версія
# • MINOR = збільшуй при суттєвих змінах функціоналу, рефакторингу, нових фіч
# • PATCH = збільшуй при виправленні багів, дрібних покращень, оптимізації
#
# 2. При кожному новому повному виводі коду — завжди:
# а) збільшуй PATCH на +1, якщо це лише виправлення/дрібні зміни
# б) збільшуй MINOR на +1 і скидай PATCH на 0, якщо додана нова велика фіча
# або значний рефакторинг
# в) ніколи не залишай версію такою ж
#
# 3. У верхньому рядку блоку завжди оновлюй: Поточна версія: X.Y.Z
#
# 4. Додавай у changelog новий запис:
# • X.Y.Z YYYY-MM-DD Короткий опис змін
#
# Changelog:
# • 0.0.25 2026-02-03 Виправлено ланцюжок мутів: при автоматичній експірації мута тепер очищаються short_term та hourly лічильники (як у /unmute).
# • 0.0.24 2026-02-03 Виправлено видалення owner-only команд від неавторизованих користувачів. Виправлена опечатка в логуванні short_term.
# • 0.0.23 2026-01-31 Дрібне підвищення версії за правилами (повний вивід коду без функціональних змін)
# • 0.0.22 2026-01-31 Додано обмеження приватних повідомлень від бота: максимум 1 на хвилину для звичайних користувачів (OWNER звільнений)
# • 0.0.21 2026-01-31 Додано опції EXEMPT_*_ANTIFLOOD у .env для окремого звільнення OWNER, creator та administrator від антифлуд-лічильників (за замовчуванням увімкнено)
# • 0.0.20 2026-01-31 Реалізовано ротацію логів за часом (TimedRotatingFileHandler, щодня опівночі, 30 днів)
# • 0.0.19 2025-07-14 Додано блок версій, changelog та інструкції
# • 0.0.18 (раніше) Початкова версія
#
# 5. Якщо користувач попросить конкретну стару версію — вказуй, що це регрес,
# і пропонуй зберегти поточну як окрему гілку
#
# 6. Найважливіші майбутні покращення (пріоритетність):
# • Перейти на per-chat locked status та мути
# • Додати періодичне збереження JSON через JobQueue
# • Додати graceful shutdown (збереження даних при SIGTERM)
# • Додати команду /reloadconfig
#
# =============================================================================
