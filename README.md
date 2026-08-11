# 🤖 Telegram Code Bot — Render Edition

Бот для удалённого выполнения Python/Bash кода через Telegram.
**Полный доступ. Без ограничений. Живое обновление. Файловый менеджер.**

## ⚡ Фичи

- **/python** — выполняет Python-код с полным доступом к `globals()`
- **/bash** — выполняет любые shell-команды
- **Файлы** — отправь `.py` или `.sh`, бот выполнит их
- **Live edit** — сообщение постепенно обновляется по мере выполнения
- **Файловый менеджер** — ходить по папкам, смотреть и скачивать файлы
- **Память** — у каждого пользователя своя текущая директория

## 🚀 Деплой на Render

### 1. Подготовка
1. Загрузи проект на **GitHub**
2. Получи токен у [@BotFather](https://t.me/botfather)
3. Узнай свой Telegram ID у [@userinfobot](https://t.me/userinfobot)

### 2. Создание сервиса
1. [render.com](https://render.com) → **New +** → **Web Service**
2. Подключи свой GitHub-репозиторий
3. Выбери **Docker** или **Python** runtime

### 3. Переменные окружения (Environment)

| Переменная | Значение |
|------------|----------|
| `BOT_TOKEN` | Токен от BotFather |
| `ALLOWED_USERS` | Твой Telegram ID (через запятую, если несколько) |
| `WEBHOOK_URL` | Оставь пустым — Render подставит `RENDER_EXTERNAL_URL` |

### 4. Запуск
Нажми **Deploy Web Service**. Бот сам установит webhook.

## 🖥 Локальный запуск (polling)

```bash
pip install -r requirements.txt
export BOT_TOKEN=your_token
export ALLOWED_USERS=your_id
python main.py
```

## 📋 Команды

| Команда | Описание |
|---------|----------|
| `/python <код>` | Выполнить Python |
| `/bash <команда>` | Выполнить Bash |
| `/pwd` | Текущая папка |
| `/ls` | Список файлов и папок |
| `/cd <путь>` | Сменить папку (`..` — назад) |
| `/cat <файл>` | Просмотр содержимого файла |
| `/download <файл>` | Скачать файл в чат |
| Файл `.py` / `.sh` | Загрузи файл — бот выполнит его |

## 📂 Файловый менеджер

Бот помнит, в какой папке ты находишься. Все команды (`/bash`, `/python`, `/ls`, `/cat`, `/download`) работают относительно твоей текущей директории.

Пример:
```
/pwd
→ /app

/ls
→ 📁 data
→ 📄 main.py

/cd data
→ 📁 /app/data

/cat log.txt
→ (содержимое файла)

/download log.txt
→ (бот отправит файл в чат)
```
