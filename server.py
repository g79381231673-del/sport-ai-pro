import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sport-ai-pro")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DAILY_LIMIT = 2

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

WELCOME = """🏟 SPORT RISK ANALYST PRO

Отправь мне матч или скриншот линии.

🎁 У тебя 2 бесплатных запроса в день.

⏱ Вы получите ответ в течение 3–5 минут.

После этого администратор отправит вам готовый прогноз."""

request_targets: dict[int, int] = {}
# user_id -> [date string, number of requests today]
daily_usage: dict[int, tuple[str, int]] = {}


def admin_id() -> int | None:
    try:
        return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except ValueError:
        return None


def check_and_use_request(user_id: int) -> tuple[bool, int]:
    today = datetime.now().date().isoformat()
    saved_date, used = daily_usage.get(user_id, (today, 0))
    if saved_date != today:
        used = 0
    if used >= DAILY_LIMIT:
        daily_usage[user_id] = (today, used)
        return False, 0
    used += 1
    daily_usage[user_id] = (today, used)
    return True, DAILY_LIMIT - used


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_chat.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Отправь матч текстом или скриншот линии. Запрос будет передан администратору.\n\n"
        "🎁 Бесплатно: 2 запроса в день.\n"
        "⏱ Ответ — в течение 3–5 минут."
    )


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    admin = admin_id()

    # Admin replies directly to a forwarded request: copy the response to the user.
    if admin is not None and chat.id == admin:
        reply = message.reply_to_message
        if reply and reply.message_id in request_targets:
            target_chat = request_targets[reply.message_id]
            try:
                await context.bot.copy_message(
                    chat_id=target_chat,
                    from_chat_id=chat.id,
                    message_id=message.message_id,
                )
                await message.reply_text("✅ Ответ отправлен пользователю.")
            except Exception:
                log.exception("failed to send admin response")
                await message.reply_text("⚠️ Не удалось отправить ответ пользователю.")
        return

    # Every non-command message from a regular user consumes one daily request.
    if admin is None:
        await message.reply_text(
            "⚠️ Бот ещё не настроен. Администратор должен добавить ADMIN_CHAT_ID в Render."
        )
        return

    allowed, remaining = check_and_use_request(chat.id)
    if not allowed:
        await message.reply_text(
            "⚠️ На сегодня бесплатные запросы закончились.\n\n"
            "🎁 Лимит — 2 запроса в день. Попробуйте завтра."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=admin,
            text=(
                "📨 НОВЫЙ ЗАПРОС\n"
                f"👤 {chat.first_name or ''} {chat.last_name or ''}".strip()
                + f"\n🆔 {chat.id}"
                + (f"\n🔗 @{chat.username}" if chat.username else "")
                + f"\n🎁 Осталось бесплатных запросов сегодня: {remaining}"
                + "\n\n⏱ Клиенту сообщено: ответ в течение 3–5 минут."
                + "\n\nОтветь на пересланное сообщение готовым анализом."
            ),
        )
        forwarded = await context.bot.forward_message(
            chat_id=admin,
            from_chat_id=chat.id,
            message_id=message.message_id,
        )
        request_targets[forwarded.message_id] = chat.id
        await message.reply_text(
            f"📨 Запрос принят!\n\n⏱ Вы получите ответ в течение 3–5 минут.\n"
            f"🎁 Осталось бесплатных запросов сегодня: {remaining}"
        )
    except Exception:
        log.exception("failed to relay user message")
        await message.reply_text("⚠️ Не удалось передать запрос. Попробуй ещё раз.")


bot_app = Application.builder().token(BOT_TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("id", get_id))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, relay_message))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    log.info("Telegram relay bot started")
    try:
        yield
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        log.info("Telegram relay bot stopped")


app = FastAPI(title="Sport Risk Analyst Pro", version="0.3.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "service": "sport-ai-pro", "mode": "manual-relay", "daily_limit": DAILY_LIMIT}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sport-ai-pro", "mode": "manual-relay"}
