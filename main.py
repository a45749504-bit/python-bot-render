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
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import uvicorn

# ==================== КОНФИГ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", "8000"))

ALLOWED_IDS = set()
if ALLOWED_USERS:
    ALLOWED_IDS = {int(x.strip()) for x in ALLOWED_USERS.split(",") if x.strip()}

def is_allowed(user_id: int) -> bool:
    return (not ALLOWED_IDS) or (user_id in ALLOWED_IDS)

# ==================== USER STATE ====================
user_cwd = {}

def get_cwd(user_id: int) -> str:
    return user_cwd.get(user_id, os.getcwd())

def set_cwd(user_id: int, path: str):
    user_cwd[user_id] = path

# ==================== LIVE OUTPUT ====================
class LiveOutput:
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

_last_edit_ts = {}

async def edit_live(message, text: str, key: str, min_interval: float = 1.0):
    now = time.time()
    last = _last_edit_ts.get(key, 0)
    if now - last < min_interval:
        return False
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
        "<b>Код:</b>\n"
        "/python <код> — выполнить Python\n"
        "/bash <команда> — выполнить Bash\n"
        "📎 Отправь любой файл — сохраню или выполню\n\n"
        "<b>Файловый менеджер:</b>\n"
        "/pwd — текущая папка\n"
        "/ls — список файлов\n"
        "/cd <путь> — сменить папку\n"
        "/cat <файл> — просмотр файла\n"
        "/download <файл> — скачать файл\n\n"
        "✅ <b>Полный доступ. Без ограничений.</b>",
        parse_mode="HTML"
    )

async def pwd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    await update.message.reply_text(f"📁 <code>{get_cwd(uid)}</code>", parse_mode="HTML")

async def ls_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    cwd = get_cwd(uid)
    try:
        items = os.listdir(cwd)
        lines = []
        for item in sorted(items):
            full = os.path.join(cwd, item)
            prefix = "📁" if os.path.isdir(full) else "📄"
            size = os.path.getsize(full) if os.path.isfile(full) else ""
            size_str = f" ({size} bytes)" if size else ""
            lines.append(f"{prefix} {item}{size_str}")
        text = "\n".join(lines) if lines else "(пусто)"
        await update.message.reply_text(f"<b>{cwd}</b>\n\n<code>{_esc(text)}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def cd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    path = " ".join(context.args)
    if not path:
        await update.message.reply_text("Использование: /cd /app или /cd ..")
        return
    cwd = get_cwd(uid)
    new_path = os.path.abspath(os.path.join(cwd, path))
    if os.path.isdir(new_path):
        set_cwd(uid, new_path)
        await update.message.reply_text(f"📁 <code>{new_path}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Не папка: <code>{new_path}</code>", parse_mode="HTML")

async def cat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    fname = " ".join(context.args)
    if not fname:
        await update.message.reply_text("Использование: /cat file.txt")
        return
    cwd = get_cwd(uid)
    fpath = os.path.join(cwd, fname) if not os.path.isabs(fname) else fname
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 4000:
            content = content[:4000] + "\n\n...[truncated]"
        await update.message.reply_text(f"<b>{os.path.basename(fpath)}</b>\n<pre>{_esc(content)}</pre>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def download_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    fname = " ".join(context.args)
    if not fname:
        await update.message.reply_text("Использование: /download file.txt")
        return
    cwd = get_cwd(uid)
    fpath = os.path.join(cwd, fname) if not os.path.isabs(fname) else fname
    if not os.path.isfile(fpath):
        await update.message.reply_text(f"❌ Файл не найден: <code>{fpath}</code>", parse_mode="HTML")
        return
    try:
        with open(fpath, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename=os.path.basename(fpath)),
                caption=f"📥 <code>{os.path.basename(fpath)}</code>",
                parse_mode="HTML"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка отправки: {e}")

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
    cwd = get_cwd(uid)

    def run():
        old = os.getcwd()
        try:
            os.chdir(cwd)
            with redirect_stdout(live), redirect_stderr(live):
                exec(code, globals(), locals())
        except Exception:
            traceback.print_exc()
        finally:
            os.chdir(old)

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
    cwd = get_cwd(uid)

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd
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

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    doc = update.message.document
    if not doc:
        return

    fname = doc.file_name or "uploaded_file"
    cwd = get_cwd(uid)
    file = await context.bot.get_file(doc.file_id)

    # Сохраняем файл в текущую папку пользователя
    save_path = os.path.join(cwd, fname)
    await file.download_to_drive(save_path)

    # Если .py — выполняем через python
    if fname.endswith(".py"):
        msg = await update.message.reply_text(f"📥 Сохранено: <code>{save_path}</code>\n🐍 Выполняю Python...", parse_mode="HTML")
        key = f"{uid}_{msg.message_id}"
        proc = subprocess.Popen(
            [sys.executable, save_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd
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
        return

    # Если .sh — выполняем через bash
    if fname.endswith(".sh"):
        msg = await update.message.reply_text(f"📥 Сохранено: <code>{save_path}</code>\n💻 Выполняю Bash...", parse_mode="HTML")
        key = f"{uid}_{msg.message_id}"
        os.chmod(save_path, 0o755)
        proc = subprocess.Popen(
            ["bash", save_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd
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
        return

    # Любой другой файл — просто сохраняем
    size = os.path.getsize(save_path)
    await update.message.reply_text(
        f"📥 Файл сохранён:\n<code>{save_path}</code>\n\n📏 Размер: {size} bytes",
        parse_mode="HTML"
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Отправь команду:\n/python <код>\n/bash <команда>\n\n"
        "Или просто пришли любой файл — сохраню его."
    )

# Регистрация хендлеров
ptb.add_handler(CommandHandler("start", start))
ptb.add_handler(CommandHandler("pwd", pwd_cmd))
ptb.add_handler(CommandHandler("ls", ls_cmd))
ptb.add_handler(CommandHandler("cd", cd_cmd))
ptb.add_handler(CommandHandler("cat", cat_cmd))
ptb.add_handler(CommandHandler("download", download_cmd))
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
        print("❌ Укажи BOT_TOKEN!")
        return
    await ptb.initialize()
    await ptb.start()
    if WEBHOOK_URL:
        wh = f"{WEBHOOK_URL}/webhook"
        await ptb.bot.set_webhook(wh)
        print(f"🚀 Webhook: {wh}")
    else:
        print("⚠️ Polling mode (local)")

@app.on_event("shutdown")
async def on_shutdown():
    await ptb.stop()
    await ptb.shutdown()

if __name__ == "__main__":
    if not WEBHOOK_URL:
        ptb.run_polling()
    else:
        uvicorn.run(app, host="0.0.0.0", port=PORT)
