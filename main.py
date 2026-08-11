import os
import sys
import io
import subprocess
import threading
import time
import asyncio
import tempfile
import traceback
from contextlib import redirect_stdout, redirect_stderr

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import uvicorn

# ==================== КОНФИГ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")
# Render сам даёт RENDER_EXTERNAL_URL, но можно переопределить
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", "8000"))

ALLOWED_IDS = set()
if ALLOWED_USERS:
    ALLOWED_IDS = {int(x.strip()) for x in ALLOWED_USERS.split(",") if x.strip()}

def is_allowed(user_id: int) -> bool:
    return (not ALLOWED_IDS) or (user_id in ALLOWED_IDS)

# ==================== LIVE OUTPUT ====================
class LiveOutput:
    """Потокобезопасный буфер для перехвата stdout/stderr."""
    def __init__(self):
        self._buf = []
        self._lock = threading.Lock()

    def write(self, s: str):
        with self._lock:
            self._buf.append(s)

    def flush(self):
        pass

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._buf)

# ==================== THROTTLED EDIT ====================
_last_edit_ts = {}

async def edit_live(message, text: str, key: str, min_interval: float = 1.0):
    """Редактирует сообщение с throttling."""
    now = time.time()
    last = _last_edit_ts.get(key, 0)
    if now - last < min_interval:
        return False
    # Telegram лимит 4096, показываем конец (актуальное)
    if len(text) > 4000:
        text = "...[truncated start]...\n" + text[-3800:]
    try:
        await message.edit_text(f"<pre>{_esc(text)}</pre>", parse_mode="HTML")
        _last_edit_ts[key] = now
        return True
    except Exception:
        return False

def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ==================== PTB APPLICATION ====================
ptb = Application.builder().token(BOT_TOKEN).build()

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 Бот для удалённого выполнения кода.\n\n"
        "<b>Команды:</b>\n"
        "/python <код> — выполнить Python\n"
        "/bash <команда> — выполнить Bash\n\n"
        "📎 Отправь .py или .sh файл — выполню его.\n\n"
        "✅ <b>Полный доступ. Без ограничений.</b>",
        parse_mode="HTML"
    )

async def python_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    code = " ".join(context.args)
    if not code:
        await update.message.reply_text("Использование: /python print('hello')")
        return

    msg = await update.message.reply_text("🐍 Выполняю Python...")
    key = f"{uid}_{msg.message_id}"

    live = LiveOutput()

    def run():
        # Полный доступ: globals() и locals() без ограничений
        with redirect_stdout(live), redirect_stderr(live):
            try:
                exec(code, globals(), locals())
            except Exception:
                traceback.print_exc()

    t = threading.Thread(target=run)
    t.start()

    output = ""
    while t.is_alive():
        await asyncio.sleep(0.5)
        new_out = live.getvalue()
        if new_out != output:
            output = new_out
            await edit_live(msg, output, key)

    t.join()
    final = live.getvalue()
    await msg.edit_text(f"<pre>{_esc(final)}</pre>", parse_mode="HTML")

async def bash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    cmd = " ".join(context.args)
    if not cmd:
        await update.message.reply_text("Использование: /bash ls -la")
        return

    msg = await update.message.reply_text("💻 Выполняю Bash...")
    key = f"{uid}_{msg.message_id}"

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=os.getcwd()
    )

    output = ""
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            output += line
            await edit_live(msg, output, key)
        await asyncio.sleep(0.05)

    # Дочитываем остаток
    remainder = proc.stdout.read()
    if remainder:
        output += remainder

    if output:
        await msg.edit_text(f"<pre>{_esc(output)}</pre>", parse_mode="HTML")
    else:
        await msg.edit_text("✅ Выполнено (без вывода)")

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    doc = update.message.document
    if not doc:
        return

    fname = doc.file_name or ""
    if not (fname.endswith(".py") or fname.endswith(".sh")):
        await update.message.reply_text("📎 Принимаю только .py и .sh файлы.")
        return

    msg = await update.message.reply_text(f"📥 Загружаю {fname}...")
    key = f"{uid}_{msg.message_id}"

    file = await context.bot.get_file(doc.file_id)

    with tempfile.NamedTemporaryFile(mode="wb", suffix=fname, delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        path = tmp.name

    try:
        if fname.endswith(".py"):
            proc = subprocess.Popen(
                [sys.executable, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
        else:
            os.chmod(path, 0o755)
            proc = subprocess.Popen(
                ["bash", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

        output = ""
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                output += line
                await edit_live(msg, output, key)
            await asyncio.sleep(0.05)

        remainder = proc.stdout.read()
        if remainder:
            output += remainder

        if output:
            await msg.edit_text(f"<pre>{_esc(output)}</pre>", parse_mode="HTML")
        else:
            await msg.edit_text("✅ Выполнено (без вывода)")

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")
    finally:
        try:
            os.remove(path)
        except:
            pass

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Отправь команду:\n/python <код>\n/bash <команда>\n\nИли файл .py / .sh"
    )

# Регистрация хендлеров
ptb.add_handler(CommandHandler("start", start))
ptb.add_handler(CommandHandler("python", python_cmd))
ptb.add_handler(CommandHandler("bash", bash_cmd))
ptb.add_handler(MessageHandler(filters.Document.ALL, doc_handler))
ptb.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# ==================== FASTAPI ====================
app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb.bot)
    await ptb.process_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok", "bot": "telegram-code-bot"}

@app.on_event("startup")
async def on_startup():
    if not BOT_TOKEN:
        print("❌ Укажи BOT_TOKEN в переменных окружения!")
        return
    await ptb.initialize()
    await ptb.start()
    if WEBHOOK_URL:
        wh = f"{WEBHOOK_URL}/webhook"
        await ptb.bot.set_webhook(wh)
        print(f"🚀 Webhook установлен: {wh}")
    else:
        print("⚠️ WEBHOOK_URL не задан. Локально используй polling.")

@app.on_event("shutdown")
async def on_shutdown():
    await ptb.stop()
    await ptb.shutdown()

# ==================== MAIN ====================
if __name__ == "__main__":
    if not WEBHOOK_URL:
        # Локальный запуск — polling
        print("🔄 Запуск в режиме polling (локально)...")
        ptb.run_polling()
    else:
        # Render / Railway — webhook через uvicorn
        uvicorn.run(app, host="0.0.0.0", port=PORT)
