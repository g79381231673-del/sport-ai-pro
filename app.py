import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sport-ai-pro")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
PROMPT_PATH = Path(__file__).parent / "prompts" / "risk_analyst_v10_4.md"

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is not configured")

client = AsyncOpenAI()
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

WELCOME = """🏟 SPORT RISK ANALYST PRO\n\nОтправь мне матч, например:\n\n⚽ ЦСКА — Ростов, 10.09.2027\n🎾 Sinner — Alcaraz, 10.09.2027\n🏒 СКА — ЦСКА, 10.09.2027\n\nСначала я сделаю предварительный анализ без коэффициента.\nПосле этого ты сможешь прислать скриншот линии для финальной проверки."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Отправь название матча и дату. Бот работает в два этапа: сначала анализ матча, затем проверка линии по скриншоту."
    )

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    status = await update.message.reply_text("🔎 Идентифицирую матч и собираю анализ…")
    try:
        response = await client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=(
                "Выполни ЭТАП 1 V10.4 для запроса пользователя. "
                "Не используй и не ищи букмекерские коэффициенты. "
                "Пользовательский запрос:\n" + text
            ),
        )
        answer = response.output_text.strip()
        if not answer:
            answer = "🔴 ПРОПУСК\n\nМодель не вернула надёжный анализ."
        await status.edit_text(answer)
    except Exception:
        log.exception("analysis failed")
        await status.edit_text(
            "⚠️ Не удалось выполнить анализ. Проверь настройки API и попробуй ещё раз."
        )

bot_app = Application.builder().token(BOT_TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    log.info("Telegram bot started")
    try:
        yield
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        log.info("Telegram bot stopped")

app = FastAPI(title="Sport Risk Analyst Pro", version="0.1.1", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok", "service": "sport-ai-pro"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "sport-ai-pro"}
