# Installation Guide for ABCWarrior_bot 😈

ABCWarrior_bot — your merciless Telegram bodyguard. Deletes voice messages, punishes flooders with harsh mutes without warnings.

**Requirements**

- Python 3.8 or higher
- Git
- Linux server with systemd (recommended for 24/7 operation)
- Administrator rights in the group for the bot
- Bot token from @BotFather

## Step 1: Cloning the repository

git clone https://github.com/heorhclub/ABCWarrior_bot.git\
cd ABCWarrior_bot

## Step 2: Installing dependencies

Recommended to use virtualenv:

python3 -m venv venv\
source venv/bin/activate\
pip install -r requirements.txt\

Or globally:

pip install -r requirements.txt

Contents of requirements.txt:

python-telegram-bot>=20.0\
python-dotenv\
filelock\
pytz

## Step 3: Configuring .env

cp .env.example .env

Edit .env:

BOT_TOKEN=your_token_from_BotFather\
OWNER_ID=your_Telegram_ID\
ALLOWED_CHAT_IDS=-100xxxxxxxxxx  # Group IDs separated by commas\

### Limits (can be changed)
DAILY_MESSAGE_LIMIT=200\
HOURLY_MESSAGE_LIMIT=100\
HOURLY_MUTE_MINUTES=15\
SHORT_TERM_MESSAGE_LIMIT=10\
SHORT_TERM_WINDOW_MINUTES=5\
SHORT_TERM_MUTE_MINUTES=3\
VOICE_MUTE_MINUTES=30\
DAILY_MUTE_DAYS=7

### Admins/owner are exempt from flood counting
EXEMPT_OWNER_ANTIFLOOD=true\
EXEMPT_CREATOR_ANTIFLOOD=true\
EXEMPT_ADMIN_ANTIFLOOD=true

**Important:**
- Give the bot admin rights (delete messages, mute users).
- Get your ID via @userinfobot.

## Step 4: Test run

python bot.py

Stop: Ctrl+C

## Step 5: Run as service (24/7)

sudo bash create_daemon.sh

The script will create abcwarrior_bot.service and start it.

**Management:**

systemctl status abcwarrior_bot.service
systemctl restart abcwarrior_bot.service
journalctl -u abcwarrior_bot.service -f  # logs

**Additional**

- Logs: bot_moderation.log (rotation 30 days)
- Data: data/ folder
• Update: git pull → systemctl restart abcwarrior_bot.service

Done! Your telegram-warrior is active. 🔥
