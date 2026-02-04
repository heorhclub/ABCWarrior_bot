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
OWNER_PRIVATE_ID = int(os.getenv("OWNER_PRIVATE_ID", str(OWNER_ID)))  # fallback на OWNER_ID
ALLOWED_CHAT_IDS_STR = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS = set()
if ALLOWED_CHAT_IDS_STR:
    try:
        ALLOWED_CHAT_IDS = {int(x.strip()) for x in ALLOWED_CHAT_IDS_STR.split(",") if x.strip()}
    except ValueError as e:
        print(f"Помилка парсингу ALLOWED_CHAT_IDS: {e}")

# Антифлуд-ліміти
DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", 200))
HOURLY_MESSAGE_LIMIT = int(os.getenv("HOURLY_MESSAGE_LIMIT", 100))
HOURLY_MUTE_MINUTES = int(os.getenv("HOURLY_MUTE_MINUTES", 15))
SHORT_TERM_MESSAGE_LIMIT = int(os.getenv("SHORT_TERM_MESSAGE_LIMIT", 10))
SHORT_TERM_WINDOW_MINUTES = int(os.getenv("SHORT_TERM_WINDOW_MINUTES", 5))
SHORT_TERM_MUTE_MINUTES = int(os.getenv("SHORT_TERM_MUTE_MINUTES", 3))
VOICE_MUTE_MINUTES = int(os.getenv("VOICE_MUTE_MINUTES", 30))
DAILY_MUTE_DAYS = int(os.getenv("DAILY_MUTE_DAYS", 7))

# Exempt опції
EXEMPT_OWNER_ANTIFLOOD = os.getenv("EXEMPT_OWNER_ANTIFLOOD", "true").lower() == "true"
EXEMPT_CREATOR_ANTIFLOOD = os.getenv("EXEMPT_CREATOR_ANTIFLOOD", "true").lower() == "true"
EXEMPT_ADMIN_ANTIFLOOD = os.getenv("EXEMPT_ADMIN_ANTIFLOOD", "true").lower() == "true"

# ─── Налаштування логування ───
logger = logging.getLogger(__name__)
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

# Динамічний рівень логування з .env
LOGGER_LEVEL_STR = os.getenv("LOGGER_LEVEL", "INFO").upper()
valid_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}
logger.setLevel(valid_levels.get(LOGGER_LEVEL_STR, logging.INFO))
logger.info(f"Встановлено рівень логування: {LOGGER_LEVEL_STR}")

# Фільтр для дозволених груп
ALLOWED_GROUP_FILTER = filters.Chat(chat_id=ALLOWED_CHAT_IDS) & filters.ChatType.GROUPS

# ─── JSON збереження ───
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DAILY_FILE = DATA_DIR / "daily_limits.json"
HOURLY_FILE = DATA_DIR / "hourly_data.json"
SHORT_FILE = DATA_DIR / "short_term_data.json"
MUTES_FILE = DATA_DIR / "mutes.json"

def save_json(path: Path, data):
    logger.debug(f"Збереження JSON у файл {path}")
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        with FileLock(lock_path, timeout=3):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
    except Timeout:
        logger.warning(f"Timeout lock для {path}")
    except Exception as e:
        logger.error(f"Помилка збереження {path}: {e}")

def load_json(path: Path, default={}):
    logger.debug(f"Читання JSON з файлу {path}")
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Помилка читання {path}: {e}")
        return default

# Завантаження даних при старті
daily_limits = {}
raw = load_json(DAILY_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        entry_date = datetime.fromisoformat(v["date"]).date()
        daily_limits[user_id] = {"date": entry_date, "count": int(v["count"])}
    except Exception as e:
        logger.warning(f"Помилка завантаження daily для {k}: {e}")

hourly_data = {}
raw = load_json(HOURLY_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        hourly_data[user_id] = [datetime.fromisoformat(t) for t in v]
    except Exception as e:
        logger.warning(f"Помилка завантаження hourly для {k}: {e}")

short_term_data = {}
raw = load_json(SHORT_FILE)
for k, v in raw.items():
    try:
        user_id = int(k)
        short_term_data[user_id] = [datetime.fromisoformat(t) for t in v]
    except Exception as e:
        logger.warning(f"Помилка завантаження short_term для {k}: {e}")

mutes = {}
raw_mutes = load_json(MUTES_FILE, default={})
now = datetime.now(timezone.utc)
for k, v in raw_mutes.items():
    try:
        until = datetime.fromisoformat(v)
        if until > now:
            mutes[int(k)] = until
    except Exception as e:
        logger.warning(f"Помилка завантаження mute для {k}: {e}")

logger.info(f"Завантажено: daily={len(daily_limits)}, hourly={len(hourly_data)}, short={len(short_term_data)}, active mutes={len(mutes)}")

def save_daily():
    data = {str(k): {"date": datetime.combine(v["date"], time(0, 0), tzinfo=timezone.utc).isoformat(), "count": v["count"]} for k, v in daily_limits.items()}
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

# Rate limit для приватних повідомлень
last_private_msg: dict[int, datetime] = {}

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

# Функції бота з debug-логуванням викликів
async def delete_command_message(message):
    if not message or message.chat.type == "private":
        return
    logger.debug(f"Спроба видалити команду {message.message_id} в чаті {message.chat.id}")
    try:
        await message.delete()
        logger.info(f"Видалено команду {message.message_id} від {message.from_user.id if message.from_user else 'анонім'} в чаті {message.chat.id}")
    except TelegramError as e:
        logger.debug(f"Не вдалося видалити команду {message.message_id}: {e}")

async def reply_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode=None):
    message = update.message
    if not message:
        return
    
    logger.debug(f"reply_in_private викликано для повідомлення {message.message_id} в чаті {message.chat.id}")

    if OWNER_PRIVATE_ID != 0:
        if message.from_user is None:
            target_id = OWNER_PRIVATE_ID
            logger.debug("Анонімне повідомлення — target_id = OWNER_PRIVATE_ID")
        elif message.from_user and message.from_user.id == OWNER_ID:
            target_id = OWNER_PRIVATE_ID
            logger.debug("Від OWNER_ID — target_id = OWNER_PRIVATE_ID")
        else:
            target_id = message.from_user.id
            logger.debug(f"Звичайний користувач — target_id = {target_id}")
    else:
        if message.from_user is None:
            target_id = OWNER_ID
            logger.debug("Fallback: анонімне — target_id = OWNER_ID")
        else:
            target_id = message.from_user.id
            logger.debug(f"Звичайний користувач — target_id = {target_id}")
    
    if target_id is None or target_id == 0:
        logger.warning("Немає валідного target_id для надсилання")
        return
    
    logger.debug(f"Надсилання в чат {target_id} (текст: {text[:50]}...)")

    now = datetime.now(timezone.utc)
    if target_id != OWNER_ID:
        last = last_private_msg.get(target_id)
        if last and now - last < timedelta(minutes=1):
            logger.info(f"Rate limit для чату {target_id}")
            return
    
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=text,
            parse_mode=parse_mode,
            disable_notification=True
        )
        logger.debug(f"Успішно надіслано в чат {target_id}")
    except TelegramError as e:
        logger.warning(f"Не вдалося надіслати в чат {target_id}: {e}")
        return
    
    if target_id != OWNER_ID:
        last_private_msg[target_id] = now
        logger.debug(f"Оновлено timestamp rate limit для {target_id}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /start від {message.from_user.id if message.from_user else 'анонім'} в чаті {message.chat.id}")
    is_group = message.chat.type in ("group", "supergroup")
    text = (
        "Бот модерації активний!\n\n"
        "Команди (працюють тільки в дозволених групах):\n"
        " /lock — заблокувати групу\n"
        " /unlock — розблокувати\n"
        " /stats — статистика (завжди в приват)\n"
        " /test — тестова (не видаляється від власника)\n\n"
        "Для власника:\n"
        " /mute15 /mute60 /mute24h /mute666 /unmute /listmute"
    )
    if is_group:
        await delete_command_message(message)
        text += "\n\nВідповідь надіслано в приват."
    await reply_in_private(update, context, text)

async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return
    logger.debug(f"Команда /lock від {message.from_user.id} в чаті {message.chat.id}")
    await delete_command_message(message)
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        logger.debug(f"Статус користувача для /lock: {member.status}")
        if member.status not in ("administrator", "creator"):
            await reply_in_private(update, context, "Тільки адміни можуть використовувати цю команду.")
            return
    except Exception as e:
        logger.error(f"/lock get_chat_member error: {e}")
        return
    global group_locked
    group_locked = True
    await reply_in_private(update, context, "Група заблокована (тільки адміни можуть писати).")
    logger.info("Група заблокована")

async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return
    logger.debug(f"Команда /unlock від {message.from_user.id} в чаті {message.chat.id}")
    await delete_command_message(message)
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        logger.debug(f"Статус користувача для /unlock: {member.status}")
        if member.status not in ("administrator", "creator"):
            await reply_in_private(update, context, "Тільки адміни можуть використовувати цю команду.")
            return
    except Exception as e:
        logger.error(f"/unlock get_chat_member error: {e}")
        return
    global group_locked
    group_locked = False
    await reply_in_private(update, context, "Група розблокована.")
    logger.info("Група розблокована")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return
    logger.debug(f"Команда /stats від {message.from_user.id} в чаті {message.chat.id}")
    await delete_command_message(message)
    chat_id = message.chat.id
    requester_id = message.from_user.id
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        logger.debug(f"/stats у reply на {target_user.id}")
    else:
        target_user = message.from_user
        logger.debug("/stats своя статистика")
    target_id = target_user.id
    if target_id != requester_id:
        try:
            member = await context.bot.get_chat_member(chat_id, requester_id)
            if member.status not in ("administrator", "creator"):
                await reply_in_private(update, context,
                                      "Ви можете переглядати тільки свою статистику або в reply на повідомлення іншого користувача.")
                return
        except Exception as e:
            logger.error(f"/stats перевірка прав: {e}")
            return
    now = datetime.now(timezone.utc)
    short_list = short_term_data.get(target_id, [])
    cutoff_short = now - timedelta(minutes=SHORT_TERM_WINDOW_MINUTES)
    filtered_short = [t for t in short_list if t >= cutoff_short]
    short_count = len(filtered_short)
    if len(filtered_short) != len(short_list):
        short_term_data[target_id] = filtered_short
        save_short()
        logger.debug(f"Очищено short_term для {target_id}")
    hourly_list = hourly_data.get(target_id, [])
    cutoff_hour = now - timedelta(hours=1)
    filtered_hourly = [t for t in hourly_list if t >= cutoff_hour]
    hourly_count = len(filtered_hourly)
    if len(filtered_hourly) != len(hourly_list):
        hourly_data[target_id] = filtered_hourly
        save_hourly()
        logger.debug(f"Очищено hourly для {target_id}")
    today_count = daily_limits.get(target_id, {"count": 0})["count"]
    user_mention = f"{target_user.full_name} (id {target_id})"
    text = (
        f"Статистика для {user_mention}:\n\n"
        f"Сьогодні: {today_count} / {DAILY_MESSAGE_LIMIT}\n"
        f"Остання година: {hourly_count} / {HOURLY_MESSAGE_LIMIT}\n"
        f"Останні {SHORT_TERM_WINDOW_MINUTES} хв: {short_count} / {SHORT_TERM_MESSAGE_LIMIT}\n"
        f"Група: {'Заблокована' if group_locked else 'Розблокована'}"
    )
    if target_id != OWNER_ID:
        if target_id in mutes:
            mute_until = mutes[target_id]
            if now < mute_until:
                remaining = mute_until - now
                total_minutes = int(remaining.total_seconds() / 60)
                if total_minutes <= 0:
                    del mutes[target_id]
                    save_mutes()
                else:
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    time_left = ""
                    if hours > 0:
                        time_left += f"{hours} год "
                    time_left += f"{minutes} хв"
                    text += f"\n\n🔒 Ви під мутом ще на {time_left.strip()}"
            else:
                del mutes[target_id]
                save_mutes()
        else:
            text += "\n\nСтатус мута: активний відсутній"
    await reply_in_private(update, context, text)

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.from_user:
        return
    logger.debug(f"Команда /test від {message.from_user.id} в чаті {message.chat.id}")
    user_id = message.from_user.id
    if user_id == OWNER_ID:
        await message.reply_text("Тест OK від власника")
    else:
        await delete_command_message(message)
        await reply_in_private(update, context, "Команда /test доступна тільки для власника")

async def manual_mute(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_id: int, minutes: int, reason: str):
    logger.debug(f"Ручний мут {target_id} на {minutes} хв (причина: {reason})")
    mute_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    mutes[target_id] = mute_until
    save_mutes()
    logger.info(f"Ручний мут {target_id} на {minutes} хв у чаті {chat_id}: {reason}")

async def mute15(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /mute15 від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await reply_in_private(update, context, "Потрібно відповісти на повідомлення користувача.")
        return
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    await manual_mute(context, message.chat.id, target_id, 15, "ручний мут 15 хв")
    await reply_in_private(update, context, f"{target_name} (id {target_id}) замучений на 15 хвилин.")

async def mute60(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /mute60 від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await reply_in_private(update, context, "Потрібно відповісти на повідомлення користувача.")
        return
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    await manual_mute(context, message.chat.id, target_id, 60, "ручний мут 60 хв")
    await reply_in_private(update, context, f"{target_name} (id {target_id}) замучений на 60 хвилин.")

async def mute24h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /mute24h від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await reply_in_private(update, context, "Потрібно відповісти на повідомлення користувача.")
        return
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    await manual_mute(context, message.chat.id, target_id, 1440, "ручний мут 24 години")
    await reply_in_private(update, context, f"{target_name} (id {target_id}) замучений на 24 години.")

async def mute666(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /mute666 від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await reply_in_private(update, context, "Потрібно відповісти на повідомлення користувача.")
        return
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    await manual_mute(context, message.chat.id, target_id, 365 * 24 * 60, "ручний мут 365 днів")
    await reply_in_private(update, context, f"{target_name} (id {target_id}) замучений на 365 днів.")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /unmute від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await reply_in_private(update, context, "Потрібно відповісти на повідомлення користувача.")
        return
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    if target_id in mutes:
        del mutes[target_id]
        save_mutes()
        if target_id in short_term_data:
            del short_term_data[target_id]
            save_short()
            logger.info(f"Short-term data очищено для {target_id} після /unmute")
        if target_id in hourly_data:
            del hourly_data[target_id]
            save_hourly()
            logger.info(f"Hourly data очищено для {target_id} після /unmute")
        if target_id in daily_limits:
            del daily_limits[target_id]
            save_daily()
            logger.info(f"Daily limits очищено для {target_id} після /unmute")
        await reply_in_private(update, context,
            f"Мут знято з {target_name} (id {target_id}).\n"
            f"Очищено всі лічильники антифлуду (short_term, hourly, daily).")
    else:
        await reply_in_private(update, context,
            f"У {target_name} (id {target_id}) немає активного мута.")

async def listmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    logger.debug(f"Команда /listmute від {message.from_user.id}")
    await delete_command_message(message)
    if message.from_user.id != OWNER_ID:
        return
    if not mutes:
        await reply_in_private(update, context, "Наразі немає замучених користувачів.")
        return
    lines = ["Поточні мути:"]
    now = datetime.now(timezone.utc)
    cleaned = False
    for uid in list(mutes.keys()):
        until = mutes[uid]
        remaining = until - now
        if remaining.total_seconds() <= 0:
            del mutes[uid]
            cleaned = True
            continue
        minutes_left = int(remaining.total_seconds() / 60)
        hours = minutes_left // 60
        mins = minutes_left % 60
        time_str = f"{hours} год {mins} хв" if hours else f"{mins} хв"
        lines.append(f"• id {uid} — залишилось {time_str}")
    if cleaned:
        save_mutes()
    if len(lines) == 1:
        await reply_in_private(update, context, "Наразі немає активних мутів.")
    else:
        await reply_in_private(update, context, "\n".join(lines))

async def apply_soft_mute(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int,
                         minutes: int, reason: str, mention_name: str = None):
    if user_id is None:
        return
    logger.debug(f"Застосування soft-mute для {user_id} на {minutes} хв (причина: {reason})")
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
        logger.debug(f"Ігнор повідомлення в недозволеному чаті {chat_id}")
        return
    current_time = message.date
    user_id = message.from_user.id if message.from_user else None
    is_anonymous = user_id is None
    logger.debug(f"=== Обробка повідомлення {message.message_id} від user_id={user_id} (анонім: {is_anonymous}) в чаті {chat_id} ===")
    logger.debug(f"Дата повідомлення: {current_time}")

    if user_id and user_id in mutes:
        if datetime.now(timezone.utc) < mutes[user_id]:
            logger.debug(f"Користувач {user_id} під мутом — видаляємо")
            try:
                await message.delete()
                logger.info(f"Видалено повідомлення {message.message_id} від {user_id} (під мутом)")
            except:
                pass
            return
        else:
            logger.info(f"Мут для {user_id} експірувався")
            del mutes[user_id]
            save_mutes()
            if user_id in short_term_data:
                del short_term_data[user_id]
                save_short()
            if user_id in hourly_data:
                del hourly_data[user_id]
                save_hourly()

    if group_locked:
        logger.debug("Група заблокована — перевірка статусу")
        try:
            member = await context.bot.get_chat_member(chat_id, user_id) if user_id else None
            is_admin = member and member.status in ("administrator", "creator")
            if not is_admin:
                logger.debug(f"Не-адмін {user_id} в заблокованій групі — видаляємо")
                await message.delete()
                logger.info(f"Видалено повідомлення {message.message_id} від {user_id} (група заблокована)")
                return
        except:
            await message.delete()
            logger.info(f"Видалено повідомлення {message.message_id} (помилка перевірки статусу в locked групі)")
            return

    if message.voice:
        logger.debug("Голосове повідомлення — видаляємо")
        try:
            await message.delete()
            logger.info(f"Видалено голосове {message.message_id} від {user_id}")
        except:
            pass
        if not is_anonymous and user_id:
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                if member.status not in ("administrator", "creator"):
                    display_name = message.from_user.full_name
                    await apply_soft_mute(context, chat_id, user_id, VOICE_MUTE_MINUTES, "голосове повідомлення", display_name)
            except:
                pass
        return

    if is_anonymous:
        logger.debug("Анонімне повідомлення — ігнор")
        return

    logger.debug("Перевірка exempt")
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        status = member.status
        logger.debug(f"Статус {user_id}: {status}")
    except Exception as e:
        logger.debug(f"Помилка отримання статусу {user_id}: {e}")
        status = None

    exempt = False
    if user_id == OWNER_ID and EXEMPT_OWNER_ANTIFLOOD:
        exempt = True
        logger.debug("Exempt: OWNER")
    elif status == "creator" and EXEMPT_CREATOR_ANTIFLOOD:
        exempt = True
        logger.debug("Exempt: creator")
    elif status == "administrator" and EXEMPT_ADMIN_ANTIFLOOD:
        exempt = True
        logger.debug("Exempt: admin")
    if exempt:
        logger.debug(f"{user_id} exempt — пропуск")
        return

    short_term_data.setdefault(user_id, []).append(current_time)
    cutoff = current_time - timedelta(minutes=SHORT_TERM_WINDOW_MINUTES)
    short_term_data[user_id] = [t for t in short_term_data[user_id] if t >= cutoff]
    logger.debug(f"Short_term для {user_id}: {len(short_term_data[user_id])}")
    if len(short_term_data[user_id]) > SHORT_TERM_MESSAGE_LIMIT:
        logger.debug(f"Короткостроковий флуд {user_id}")
        display_name = message.from_user.full_name
        await apply_soft_mute(context, chat_id, user_id, SHORT_TERM_MUTE_MINUTES,
                              f"флуд >{SHORT_TERM_MESSAGE_LIMIT} за {SHORT_TERM_WINDOW_MINUTES} хв", display_name)
        try:
            await message.delete()
            logger.info(f"Видалено {message.message_id} від {user_id} (short флуд)")
        except:
            pass
        save_short()
        return

    hourly_data.setdefault(user_id, []).append(current_time)
    cutoff_hour = current_time - timedelta(hours=1)
    hourly_data[user_id] = [t for t in hourly_data[user_id] if t >= cutoff_hour]
    logger.debug(f"Hourly для {user_id}: {len(hourly_data[user_id])}")
    if len(hourly_data[user_id]) > HOURLY_MESSAGE_LIMIT:
        logger.debug(f"Годинний флуд {user_id}")
        display_name = message.from_user.full_name
        await apply_soft_mute(context, chat_id, user_id, HOURLY_MUTE_MINUTES,
                              f"флуд >{HOURLY_MESSAGE_LIMIT} за годину", display_name)
        try:
            await message.delete()
            logger.info(f"Видалено {message.message_id} від {user_id} (hourly флуд)")
        except:
            pass
        save_hourly()
        return

    today = current_time.date()
    if user_id not in daily_limits:
        daily_limits[user_id] = {"date": today, "count": 1}
        logger.debug(f"Новий daily для {user_id}: 1")
    else:
        entry = daily_limits[user_id]
        if entry["date"] != today:
            entry["date"] = today
            entry["count"] = 1
            logger.debug(f"Ролловер daily для {user_id}")
        else:
            entry["count"] += 1
            logger.debug(f"Daily для {user_id}: {entry['count']}")
    if daily_limits[user_id]["count"] > DAILY_MESSAGE_LIMIT:
        logger.debug(f"Денний флуд {user_id}")
        display_name = message.from_user.full_name
        await apply_soft_mute(context, chat_id, user_id, DAILY_MUTE_DAYS * 1440,
                              f"флуд >{DAILY_MESSAGE_LIMIT} за день", display_name)
        try:
            await message.delete()
            logger.info(f"Видалено {message.message_id} від {user_id} (daily флуд)")
        except:
            pass
        save_daily()
        return

    save_daily()
    save_hourly()
    save_short()
    logger.debug(f"Повідомлення {message.message_id} оброблено нормально")

async def auto_delete_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return
    if not message.text or not message.text.strip().startswith('/'):
        return
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
    command_match = re.match(r'^/([a-zA-Z0-9_]+)(@|$|\s)', message.text.strip())
    if not command_match:
        return
    command = command_match.group(1).lower()
    logger.debug(f"Автовидалення команди /{command} від {user_id}")
    if user_id == OWNER_ID and command == "test":
        return
    try:
        await message.delete()
        logger.info(f"Видалено команду /{command} ({message.message_id}) від {user_id} в чаті {message.chat.id}")
    except TelegramError as e:
        if "message to delete not found" not in str(e):
            logger.debug(f"Не вдалося видалити команду /{command}: {e}")

if __name__ == "__main__":
    logger.info("Запуск бота | мути в окремому файлі mutes.json | логи ротація щодня")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("test", test_cmd, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("start", start, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("lock", lock, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("unlock", unlock, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("stats", stats, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("mute15", mute15, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("mute60", mute60, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("mute24h", mute24h, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("mute666", mute666, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("unmute", unmute, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(CommandHandler("listmute", listmute, filters=ALLOWED_GROUP_FILTER))
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=ALLOWED_CHAT_IDS) &
        filters.ChatType.GROUPS &
        filters.COMMAND,
        auto_delete_commands
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ALLOWED_GROUP_FILTER,
        handle_message
    ))
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

# =============================================================================
# ─── ВЕРСІЇ ТА ІНСТРУКЦІЇ ДЛЯ МАЙБУТНЬОГО GROK ───────────────────────────────
# =============================================================================
#
# Поточна версія: 0.0.29
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
# • 0.0.29 2026-02-04 Додано динамічний рівень логування LOGGER_LEVEL (DEBUG включає все INFO + детальні виклики функцій, перевірки, лічильники, помилки). Попередні 0.0.29 і 0.0.30 відміняються.
# • 0.0.28 2026-02-04 Додано OWNER_PRIVATE_ID для надійних приватних повідомлень власнику при постах від каналу (анонімно). Виправлено reply_in_private для анонімних постів.
# • 0.0.27 2026-02-03 При автоматичній експірації мута тепер очищається hourly_data (разом з short_term). /unmute скидає всі лічильники.
# • 0.0.26 2026-02-03 Виправлено логіку очищення лічильників при експірації мута: тепер очищається ТІЛЬКИ short_term (hourly накопичується для досягнення наступного рівня).
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
