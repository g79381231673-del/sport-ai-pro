import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sport-ai-pro")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
FREE_DAILY_LIMIT = 2
DB_PATH = os.getenv("DB_PATH", "/tmp/sport_ai.db")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

WELCOME = """🏟 SPORT RISK ANALYST PRO

Привет! 👋 Добро пожаловать.

🎁 У вас есть 2 бесплатных запроса в день.

Отправьте матч или скриншот линии — запрос будет передан аналитику.

⏱ Ответ на запрос — в течение 5 минут — 1 часа.

💳 Если бесплатных запросов недостаточно:
🔥 5 запросов в день — 250 ₽ / 7 дней | 500 ₽ / 14 дней
⚡ 10 запросов в день — 600 ₽ / 7 дней | 1 000 ₽ / 14 дней

📩 Для оплаты: @ZotickNick

После оплаты администратор активирует тариф."""

PRICES = """💳 ТАРИФЫ SPORT RISK ANALYST PRO

🎁 Бесплатно
• 2 запроса в день

🔥 Тариф 5
• 5 запросов в день
• 7 дней — 250 ₽
• 14 дней — 500 ₽

⚡ Тариф 10
• 10 запросов в день
• 7 дней — 600 ₽
• 14 дней — 1 000 ₽

📩 Для оплаты: @ZotickNick

После оплаты администратор активирует тариф."""

MAINTENANCE_TEXT = """🔧 ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ

Бот временно находится на техническом обслуживании.

Пожалуйста, попробуйте немного позже. Спасибо за понимание ❤️"""

request_targets: dict[int, int] = {}
maintenance_mode = False
welcomed_users: set[int] = set()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER NOT NULL,
            usage_date TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS paid_plans (
            user_id INTEGER PRIMARY KEY,
            daily_limit INTEGER NOT NULL,
            expires_at TEXT NOT NULL
        )""")
        conn.commit()


def save_user(chat):
    now = datetime.now().isoformat()
    with db() as conn:
        conn.execute("""INSERT INTO users(user_id, username, first_name, last_name, created_at, last_seen)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
                       first_name=excluded.first_name, last_name=excluded.last_name,
                       last_seen=excluded.last_seen""",
                     (chat.id, chat.username, chat.first_name, chat.last_name, now, now))
        conn.commit()


def admin_id() -> int | None:
    try:
        return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except ValueError:
        return None


def current_limit(user_id: int) -> int:
    with db() as conn:
        row = conn.execute("SELECT daily_limit, expires_at FROM paid_plans WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return FREE_DAILY_LIMIT
        try:
            if datetime.fromisoformat(row["expires_at"]) > datetime.now():
                return int(row["daily_limit"])
        except ValueError:
            pass
        conn.execute("DELETE FROM paid_plans WHERE user_id=?", (user_id,))
        conn.commit()
    return FREE_DAILY_LIMIT


def check_and_use_request(user_id: int) -> tuple[bool, int, int]:
    limit = current_limit(user_id)
    today = datetime.now().date().isoformat()
    with db() as conn:
        row = conn.execute("SELECT used FROM usage WHERE user_id=? AND usage_date=?", (user_id, today)).fetchone()
        used = int(row["used"]) if row else 0
        if used >= limit:
            return False, 0, limit
        used += 1
        conn.execute("INSERT INTO usage(user_id, usage_date, used) VALUES(?,?,?) ON CONFLICT(user_id, usage_date) DO UPDATE SET used=excluded.used", (user_id, today, used))
        conn.commit()
    return True, limit - used, limit


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        save_user(update.effective_chat)
    await update.message.reply_text(MAINTENANCE_TEXT if maintenance_mode else WELCOME)


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        save_user(update.effective_chat)
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_chat.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        save_user(update.effective_chat)
    await update.message.reply_text(MAINTENANCE_TEXT if maintenance_mode else "Отправь матч текстом или скриншот линии. Запрос будет передан администратору.\n\n🎁 Бесплатно: 2 запроса в день.\n💳 Тарифы: /prices\n⏱ Ответ — в течение 5 минут — 1 часа.")


async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        save_user(update.effective_chat)
    await update.message.reply_text(PRICES)


async def give_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin = admin_id()
    if admin is None or update.effective_chat.id != admin:
        return
    if len(context.args) != 3:
        await update.message.reply_text("Формат: /give USER_ID LIMIT DAYS\nНапример: /give 5907925729 10 7")
        return
    try:
        user_id = int(context.args[0]); limit = int(context.args[1]); days = int(context.args[2])
        if limit not in (5, 10) or days not in (7, 14):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Ошибка. LIMIT: 5 или 10. DAYS: 7 или 14.")
        return
    expires = datetime.now() + timedelta(days=days)
    with db() as conn:
        conn.execute("INSERT INTO paid_plans(user_id,daily_limit,expires_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit, expires_at=excluded.expires_at", (user_id, limit, expires.isoformat()))
        conn.execute("DELETE FROM usage WHERE user_id=? AND usage_date=?", (user_id, datetime.now().date().isoformat()))
        conn.commit()
    await update.message.reply_text(f"✅ Тариф активирован\n👤 {user_id}\n⚡ {limit} запросов/день\n📅 {days} дней\n⏳ До: {expires.strftime('%d.%m.%Y %H:%M')}")
    try:
        await context.bot.send_message(chat_id=user_id, text=f"✅ Вам активирован тариф: {limit} запросов в день на {days} дней.\n\nТариф действует до {expires.strftime('%d.%m.%Y %H:%M')}.")
    except Exception:
        log.exception("failed to notify user about paid plan")


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global maintenance_mode
    admin = admin_id()
    if admin is None or update.effective_chat.id != admin:
        return
    if len(context.args) != 1 or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text("Формат: /maintenance on или /maintenance off")
        return
    maintenance_mode = context.args[0].lower() == "on"
    await update.message.reply_text("🔧 Техническое обслуживание ВКЛЮЧЕНО." if maintenance_mode else "✅ Техническое обслуживание ВЫКЛЮЧЕНО. Бот снова принимает запросы.")


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message; chat = update.effective_chat
    if not message or not chat: return
    save_user(chat)
    admin = admin_id()
    if admin is not None and chat.id == admin:
        reply = message.reply_to_message
        if reply and reply.message_id in request_targets:
            target_chat = request_targets[reply.message_id]
            try:
                await context.bot.copy_message(chat_id=target_chat, from_chat_id=chat.id, message_id=message.message_id)
                await message.reply_text("✅ Ответ отправлен пользователю.")
            except Exception: log.exception("failed to send admin response")
        return
    if maintenance_mode:
        await message.reply_text(MAINTENANCE_TEXT); return
    if admin is None:
        await message.reply_text("⚠️ Бот ещё не настроен. Администратор должен добавить ADMIN_CHAT_ID в Render."); return
    if chat.id not in welcomed_users:
        welcomed_users.add(chat.id); await message.reply_text(WELCOME)
    allowed, remaining, limit = check_and_use_request(chat.id)
    if not allowed:
        await message.reply_text(f"⚠️ Лимит {limit} запросов на сегодня исчерпан.\n\n💳 Для продолжения доступны тарифы:\n🔥 5 запросов/день — 250 ₽ за 7 дней или 500 ₽ за 14 дней\n⚡ 10 запросов/день — 600 ₽ за 7 дней или 1 000 ₽ за 14 дней\n\n📩 Для оплаты: @ZotickNick\nПодробнее: /prices"); return
    try:
        await context.bot.send_message(chat_id=admin, text=("📨 НОВЫЙ ЗАПРОС\n" + f"👤 {chat.first_name or ''} {chat.last_name or ''}".strip() + f"\n🆔 {chat.id}" + (f"\n🔗 @{chat.username}" if chat.username else "") + f"\n🎁 Осталось запросов сегодня: {remaining}/{limit}" + "\n\n⏱ Клиенту сообщено: ответ в течение 5 минут — 1 часа.\n\nОтветь на пересланное сообщение готовым анализом."))
        forwarded = await context.bot.forward_message(chat_id=admin, from_chat_id=chat.id, message_id=message.message_id)
        request_targets[forwarded.message_id] = chat.id
        await message.reply_text(f"📨 Запрос принят!\n\n⏱ Ответ на ваш запрос — в течение 5 минут — 1 часа.\n🎁 Осталось запросов сегодня: {remaining}/{limit}")
    except Exception:
        log.exception("failed to relay user message")
        await message.reply_text("⚠️ Не удалось передать запрос. Попробуй ещё раз.")


bot_app = Application.builder().token(BOT_TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("id", get_id))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("prices", prices_command))
bot_app.add_handler(CommandHandler("give", give_command))
bot_app.add_handler(CommandHandler("maintenance", maintenance_command))
bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, relay_message))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await bot_app.initialize(); await bot_app.start(); await bot_app.updater.start_polling()
    log.info("Telegram relay bot started")
    try: yield
    finally: await bot_app.updater.stop(); await bot_app.stop(); await bot_app.shutdown()


app = FastAPI(title="Sport Risk Analyst Pro", version="0.8.0", lifespan=lifespan)

@app.get("/")
async def root(): return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","database":"sqlite"}

@app.get("/health")
async def health(): return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","database":"sqlite"}
