import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sport-ai-pro")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

WELCOME = """🏟 SPORT RISK ANALYST PRO

Отправь мне матч или скриншот линии.

Я передам запрос аналитику.

⏱ Вы получите ответ в течение 3–5 минут.

После этого администратор отправит вам готовый прогноз."""

request_targets: dict[int, int] = {}


def admin_id() -> int | None:
    try:
        return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except ValueError:
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_chat.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Отправь матч текстом или скриншот линии. Запрос будет передан администратору.\n\n"
        "⏱ Ответ — в течение 3–5 минут."
    )


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    admin = admin_id()

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

    if admin is None:
        await message.reply_text(
            "⚠️ Бот ещё не настроен. Администратор должен добавить ADMIN_CHAT_ID в Render."
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
            "📨 Запрос принят!\n\n⏱ Вы получите ответ в течение 3–5 минут."
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


app = FastAPI(title="Sport Risk Analyst Pro", version="0.2.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "service": "sport-ai-pro", "mode": "manual-relay"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sport-ai-pro", "mode": "manual-relay"}
