#!/bin/bash

# Скрипт створення systemd-сервісу для ABCWarrior_bot з підтримкою virtualenv
# Запускати від root (sudo bash create_daemon.sh)

set -e

SERVICE_NAME="abcwarrior_bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
   echo "Цей скрипт потрібно запускати від root (sudo)."
   exit 1
fi

echo "=== Створення systemd-сервісу для ABCWarrior_bot ==="
echo

# Шлях до директорії бота
read -p "Введіть повний шлях до директорії з ботом (наприклад /home/user/ABCWarrior_bot): " BOT_DIR
BOT_DIR=$(echo "$BOT_DIR" | sed 's:/$::')

if [[ ! -f "$BOT_DIR/bot.py" && ! -f "$BOT_DIR/main.py" ]]; then
    echo "Помилка: У вказаній директорії не знайдено бот-файл (bot.py або main.py)."
    exit 1
fi

# Визначаємо назву основного файлу
if [[ -f "$BOT_DIR/bot.py" ]]; then
    BOT_SCRIPT="bot.py"
else
    BOT_SCRIPT="main.py"
fi

# Користувач, від якого запускати
read -p "Введіть ім'я користувача, від якого запускати бота (рекомендовано не root): " BOT_USER
if [[ -z "$BOT_USER" ]]; then
    BOT_USER=$(who am i | awk '{print $1}')
    echo "Використано поточного користувача: $BOT_USER"
fi

# Virtualenv?
read -p "Чи використовуєте virtualenv? (y/n, за замовчуванням n): " USE_VENV
USE_VENV=$(echo "$USE_VENV" | tr '[:upper:]' '[:lower:]')

if [[ "$USE_VENV" == "y" || "$USE_VENV" == "yes" ]]; then
    read -p "Введіть шлях до директорії virtualenv (наприклад $BOT_DIR/venv): " VENV_DIR
    VENV_DIR=$(echo "$VENV_DIR" | sed 's:/$::')
    if [[ ! -f "$VENV_DIR/bin/python" ]]; then
        echo "Помилка: Не знайдено python у вказаному venv ($VENV_DIR/bin/python)."
        exit 1
    fi
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    PYTHON_BIN=$(which python3)
fi

# Створюємо unit-файл
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ABCWarrior Telegram Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$BOT_DIR
ExecStart=$PYTHON_BIN $BOT_DIR/$BOT_SCRIPT
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "Створено файл сервісу: $SERVICE_FILE"
echo "Використовуваний Python: $PYTHON_BIN"

# Перезавантажуємо systemd
systemctl daemon-reload

# Вмикаємо автозапуск
systemctl enable "$SERVICE_NAME.service"

# Запускаємо сервіс
systemctl start "$SERVICE_NAME.service"

echo
echo "=== Готово! ==="
echo "Сервіс створено та запущено."
echo "Статус: systemctl status $SERVICE_NAME.service"
echo "Логи: journalctl -u $SERVICE_NAME.service -f"
echo "Зупинити: systemctl stop $SERVICE_NAME.service"
echo "Перезапустити: systemctl restart $SERVICE_NAME.service"
