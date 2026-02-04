#!/bin/bash
# Скрипт створення/оновлення systemd-сервісу для ABCWarrior_bot з підтримкою virtualenv та .env
# Запускати від root (sudo bash create_daemon.sh)
set -e

SERVICE_NAME="abcwarrior_bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
   echo "Цей скрипт потрібно запускати від root (sudo)."
   exit 1
fi

echo "=== Створення/оновлення systemd-сервісу для ABCWarrior_bot ==="
echo

# Шлях до директорії бота
read -p "Введіть повний шлях до директорії з ботом (наприклад /home/user/ABCWarrior_bot): " BOT_DIR
BOT_DIR=$(echo "$BOT_DIR" | sed 's:/$::')

if [[ ! -d "$BOT_DIR" ]]; then
    echo "Помилка: Директорія $BOT_DIR не існує."
    exit 1
fi

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
read -p "Введіть ім'я користувача, від якого запускати бота (рекомендовано не root, за замовчуванням поточний): " BOT_USER
if [[ -z "$BOT_USER" ]]; then
    BOT_USER=$(who am i | awk '{print $1}' || echo "www-data")
    echo "Використано користувача за замовчуванням: $BOT_USER"
fi

# Перевірка існування користувача
if ! id "$BOT_USER" &>/dev/null; then
    echo "Помилка: Користувач $BOT_USER не існує."
    exit 1
fi

# Virtualenv
DEFAULT_VENV="$BOT_DIR/venv"
if [[ -d "$DEFAULT_VENV" && -f "$DEFAULT_VENV/bin/python" ]]; then
    read -p "Виявлено virtualenv у $DEFAULT_VENV. Використовувати його? (Y/n): " USE_DEFAULT
    USE_DEFAULT=$(echo "$USE_DEFAULT" | tr '[:upper:]' '[:lower:]')
    if [[ "$USE_DEFAULT" != "n" && "$USE_DEFAULT" != "no" ]]; then
        PYTHON_BIN="$DEFAULT_VENV/bin/python"
        USE_VENV="y"
    fi
fi

if [[ "$USE_VENV" != "y" ]]; then
    read -p "Чи використовуєте virtualenv? (y/n, за замовчуванням n): " USE_VENV
    USE_VENV=$(echo "$USE_VENV" | tr '[:upper:]' '[:lower:]')
    if [[ "$USE_VENV" == "y" || "$USE_VENV" == "yes" ]]; then
        read -p "Введіть шлях до директорії virtualenv (наприклад $DEFAULT_VENV): " VENV_DIR
        VENV_DIR=$(echo "$VENV_DIR" | sed 's:/$::')
        if [[ ! -f "$VENV_DIR/bin/python" ]]; then
            echo "Помилка: Не знайдено python у вказаному venv ($VENV_DIR/bin/python)."
            exit 1
        fi
        PYTHON_BIN="$VENV_DIR/bin/python"
    else
        PYTHON_BIN=$(which python3)
    fi
else
    PYTHON_BIN="$DEFAULT_VENV/bin/python"
fi

# Створюємо/оновлюємо unit-файл
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ABCWarrior Telegram Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$BOT_DIR
ExecStart=$PYTHON_BIN $BOT_DIR/$BOT_SCRIPT
ExecStop=/bin/kill -SIGTERM \$MAINPID
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
$( [[ -f "$BOT_DIR/.env" ]] && echo "EnvironmentFile=$BOT_DIR/.env" )

[Install]
WantedBy=multi-user.target
EOF

echo "Створено/оновлено файл сервісу: $SERVICE_FILE"
echo "Використовуваний Python: $PYTHON_BIN"
[[ -f "$BOT_DIR/.env" ]] && echo "Додано EnvironmentFile=.env"

# Перезавантажуємо systemd
systemctl daemon-reload

# Якщо сервіс вже існує — restart, інакше enable + start
if systemctl is-active --quiet "$SERVICE_NAME.service"; then
    echo "Сервіс вже запущений — перезапускаємо..."
    systemctl restart "$SERVICE_NAME.service"
else
    systemctl enable "$SERVICE_NAME.service"
    systemctl start "$SERVICE_NAME.service"
fi

echo
echo "=== Готово! ==="
echo "Сервіс створено/оновлено та запущено."
echo "Статус: systemctl status $SERVICE_NAME.service"
echo "Логи: journalctl -u $SERVICE_NAME.service -f"
echo "Зупинити: systemctl stop $SERVICE_NAME.service"
echo "Перезапустити: systemctl restart $SERVICE_NAME.service"
echo "Видалити сервіс: systemctl stop $SERVICE_NAME.service && systemctl disable $SERVICE_NAME.service && rm $SERVICE_FILE && systemctl daemon-reload"
