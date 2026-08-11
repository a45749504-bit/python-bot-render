# 🤖 Telegram Code Bot — Render Edition

Бот для удалённого выполнения Python/Bash кода через Telegram. 
**Полный доступ. Без ограничений. Живое обновление сообщения.**

## ⚡ Фичи

- **/python** — выполняет Python-код с полным доступом к `globals()`
- **/bash** — выполняет любые shell-команды (без blacklist)
- **Файлы** — отправь `.py` или `.sh`, бот выполнит их
- **Live edit** — сообщение постепенно обновляется по мере выполнения
- **Webhook API** — работает через FastAPI, идеально для Render

## 🚀 Деплой на Render

### 1. Подготовка
1. Загрузи этот проект на **GitHub**
2. Получи токен у [@BotFather](https://t.me/botfather)
3. Узнай свой Telegram ID у [@userinfobot](https://t.me/userinfobot)

### 2. Создание сервиса
1. [render.com](https://render.com) → **New +** → **Web Service**
2. Подключи свой GitHub-репозиторий
3. Render автоматически найдёт `render.yaml`

### 3. Переменные окружения
В разделе **Environment** добавь:

| Переменная | Значение |
|------------|----------|
| `BOT_TOKEN` | Токен от BotFather |
| `ALLOWED_USERS` | Твой Telegram ID (через запятую, если несколько) |
| `WEBHOOK_URL` | Оставь пустым — Render подставит `RENDER_EXTERNAL_URL` автоматически |

> Если `RENDER_EXTERNAL_URL` не подставляется, укажи вручную: `https://<имя-сервиса>.onrender.com`

### 4. Запуск
Нажми **Create Web Service**. Бот автоматически установит webhook и начнёт работать.

## 🖥 Локальный запуск (polling)

```bash
pip install -r requirements.txt
export BOT_TOKEN=your_token
export ALLOWED_USERS=your_id
python main.py
```

Локально бот работает в режиме **polling** (если `WEBHOOK_URL` не задан).

## 📋 Команды

| Команда | Пример |
|---------|--------|
| `/python` | `/python import os; print(os.listdir('.'))` |
| `/bash` | `/bash apt list --installed` |
| Файл `.py` | Загрузи файл, бот выполнит `python файл.py` |
| Файл `.sh` | Загрузи файл, бот выполнит `bash файл.sh` |

## 🔧 Архитектура

- **FastAPI** — принимает webhook от Telegram
- **python-telegram-bot v21+** — обработка команд
- **LiveOutput** — потокобезопасный перехват stdout/stderr
- **Throttled edit** — сообщение обновляется каждую секунду, пока идёт выполнение
