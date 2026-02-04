# Інструкція по встановленню ABCWarrior_bot 😈

**ABCWarrior_bot** — безжалісний охоронець твоєї групи. Видаляє голосові, карає флудерів жорсткими мутами без попереджень.

**Вимоги**

- Python 3.8 або вище
- Git
- Linux-сервер з systemd (рекомендовано для 24/7 роботи)
- Права адміністратора в групі для бота
- Токен від @BotFather

## Крок 1: Клонування репозиторію

git clone https://github.com/heorhclub/ABCWarrior_bot.git \
cd ABCWarrior_bot

## Крок 2: Встановлення залежностей

Рекомендовано virtualenv:

python3 -m venv venv\
source venv/bin/activate\
pip install -r requirements.txt

Або глобально:

pip install -r requirements.txt

**Вміст requirements.txt:**

python-telegram-bot>=20.0\
python-dotenv\
filelock\
pytz

## Крок 3: Налаштування .env

cp .env.example .env

Відредагуй .env:

BOT_TOKEN=твій_токен_від_BotFather\
OWNER_ID=твій_Telegram_ID\
ALLOWED_CHAT_IDS=-100xxxxxxxxxx  # ID груп через кому

**Опціонально:** окремий ID для надсилання приватних повідомлень власнику\
Корисно, коли постиш від імені каналу (анонімно в групі коментарів)\
Якщо залишити порожнім — використовується OWNER_ID

OWNER_PRIVATE_ID=

### Ліміти (можна міняти)

DAILY_MESSAGE_LIMIT=200\
HOURLY_MESSAGE_LIMIT=100\
HOURLY_MUTE_MINUTES=15\
SHORT_TERM_MESSAGE_LIMIT=10\
SHORT_TERM_WINDOW_MINUTES=5\
SHORT_TERM_MUTE_MINUTES=3\
VOICE_MUTE_MINUTES=30\
DAILY_MUTE_DAYS=7

### Адміни/власник не рахуються у флуді

EXEMPT_OWNER_ANTIFLOOD=true\
EXEMPT_CREATOR_ANTIFLOOD=true\
EXEMPT_ADMIN_ANTIFLOOD=true

**Важливо:**
- Дай боту права адміна (видаляти повідомлення, мутити).
- Свій ID — через @userinfobot.

## Крок 4: Тестовий запуск

python bot.py

Зупинити: Ctrl+C

## Крок 5: Запуск як сервіс (24/7)

sudo bash create_daemon.sh

Скрипт створить сервіс abcwarrior_bot.service і запустить його.

## Керування:

systemctl status abcwarrior_bot.service\
systemctl restart abcwarrior_bot.service\
journalctl -u abcwarrior_bot.service -f  # логи

## Додатково

• Логи: bot_moderation.log (ротація 30 днів)\
• Дані: папка data/\
• Оновлення: git pull → systemctl restart abcwarrior_bot.service

Готово! Твій бот-охоронець активний. Порушники тремтіть 🔥
