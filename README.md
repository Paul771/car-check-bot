# Car Check Bot 🤖🚗

Telegram-бот для проверки номеров автомобилей по базе из **публичной Google Sheets**.
Если номер не найден — пользователь может отправить фото, которое будет
переслано в указанную Telegram-группу для разбора.

Не требует API-ключей Google, OAuth или Service Account — таблица загружается
через публичный CSV-экспорт (доступна по ссылке "на чтение").

## 📋 Функции

- `/start` — приветствие
- `/stats` — количество номеров в базе
- Отправка **текста с номером** → проверка по Google Sheets
- Отправка **фото** (после того, как номер не найден) → пересылка в группу разбора

## 🗂️ Структура проекта

```
car-check-bot/
├── bot/
│   ├── __init__.py
│   ├── config.py      # Загрузка конфигурации
│   ├── handlers.py    # Обработчики сообщений Telegram
│   ├── main.py        # Точка входа
│   ├── sheets.py      # Загрузка данных из Google Sheets (CSV без авторизации)
│   └── utils.py       # Кэш номеров
├── .env               # Конфигурация (секреты)
├── .env.example       # Пример конфигурации
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```

## 🔧 Настройка

### 1. Telegram Bot

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Создайте нового бота командой `/newbot`
3. Получите **токен бота** (строка вида `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Целевая Telegram-группа

1. Создайте группу в Telegram
2. Добавьте бота в группу как **администратора**
3. Узнайте `chat_id` группы:
   - Добавьте бота [@getmyid_bot](https://t.me/getmyid_bot) в группу → он покажет Group ID
   - Или через API: напишите сообщение в группу, откройте `https://api.telegram.org/bot<ТОКЕН>/getUpdates`
   - Найдите `"chat":{"id":-100...` — это и есть ID группы

### 3. Конфигурация

Скопируйте `.env.example` в `.env`:

```bash
cp .env.example .env
```

Заполните параметры:

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram бота |
| `TARGET_GROUP_ID` | ID группы для пересылки (например, `-1001234567890`) |
| `GOOGLE_SHEET_ID` | ID таблицы (уже указан по умолчанию) |
| `SHEET_NAME` | Имя листа (по умолч. `Sheet1`) |
| `COLUMN_INDEX` | Номер колонки с номерами (1 = колонка A) |

> **Google таблица должна быть доступна по ссылке "на чтение"**
> (у вас уже настроено — таблица открыта).

### 4. Убедитесь, что таблица опубликована

Перед запуском проверьте в браузере, открывается ли CSV:
```
https://docs.google.com/spreadsheets/d/1NPuVFYQi0_T2qH5vxRYXH2SKhW498YslS3FxOxg9lT4/export?format=csv
```
Если видите данные (не страницу входа) — всё готово.

## 🚀 Быстрый запуск

### Локально (Python)

```bash
pip install -r requirements.txt
python -m bot.main
```

### Через Docker

```bash
docker compose up -d
docker compose logs -f
```

## ☁️ Деплой на сервер Ubuntu

### 1. Установка Docker

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Запуск бота

```bash
# Копирование проекта на сервер
git clone <ваш-репозиторий> car-check-bot
cd car-check-bot

# Создание .env с настройками
nano .env   # вставьте BOT_TOKEN и TARGET_GROUP_ID

# Запуск
docker compose up -d

# Проверка логов
docker compose logs -f
```

Бот автоматически перезапускается при старте сервера (`restart: unless-stopped`).

## 🛠️ Использование

1. Откройте Telegram и найдите вашего бота
2. Отправьте `/start`
3. Отправьте номер автомобиля текстом (например, `А123ВС777`)
4. Если номер есть в базе → ✅ "Номер найден в базе данных"
5. Если номера нет → ❌ "Номер не числится в базе" + предложение отправить фото
6. Отправьте фото → оно будет переслано в группу разбора

## ⚙️ Минимальные требования к серверу

- **CPU**: 1 vCPU
- **RAM**: 128 MB
- **Disk**: 500 MB (для Docker-образа и логов)
- **OS**: Ubuntu 20.04+ (или любой Linux с Docker)