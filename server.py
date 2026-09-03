import logging
import os
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
daily_usage: dict[int, tuple[str, int]] = {}
paid_plans: dict[int, tuple[int, str]] = {}
welcomed_users: set[int] = set()
maintenance_mode = False
def admin_id() -> int | None:
    try: return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except ValueError: return None
def current_limit(user_id: int) -> int:
    plan = paid_plans.get(user_id)
    if not plan: return FREE_DAILY_LIMIT
    limit, expires = plan
    try:
        if datetime.fromisoformat(expires) > datetime.now(): return limit
    except ValueError: pass
    paid_plans.pop(user_id, None)
    return FREE_DAILY_LIMIT
def check_and_use_request(user_id: int) -> tuple[bool, int, int]:
    limit = current_limit(user_id); today = datetime.now().date().isoformat()
    saved_date, used = daily_usage.get(user_id, (today, 0))
    if saved_date != today: used = 0
    if used >= limit:
        daily_usage[user_id] = (today, used); return False, 0, limit
    used += 1; daily_usage[user_id] = (today, used); return True, limit-used, limit
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MAINTENANCE_TEXT if maintenance_mode else WELCOME)
async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_chat.id}")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MAINTENANCE_TEXT if maintenance_mode else "Отправь матч текстом или скриншот линии. Запрос будет передан администратору.\n\n🎁 Бесплатно: 2 запроса в день.\n💳 Тарифы: /prices\n⏱ Ответ — в течение 5 минут — 1 часа.")
async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(PRICES)
async def give_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin = admin_id()
    if admin is None or update.effective_chat.id != admin: return
    if len(context.args) != 3:
        await update.message.reply_text("Формат: /give USER_ID LIMIT DAYS\nНапример: /give 5907925729 10 7"); return
    try:
        user_id=int(context.args[0]); limit=int(context.args[1]); days=int(context.args[2])
        if limit not in (5,10) or days not in (7,14): raise ValueError
    except ValueError:
        await update.message.reply_text("Ошибка. LIMIT: 5 или 10. DAYS: 7 или 14."); return
    expires=datetime.now()+timedelta(days=days); paid_plans[user_id]=(limit,expires.isoformat()); daily_usage.pop(user_id,None)
    await update.message.reply_text(f"✅ Тариф активирован\n👤 {user_id}\n⚡ {limit} запросов/день\n📅 {days} дней\n⏳ До: {expires.strftime('%d.%m.%Y %H:%M')}")
    try: await context.bot.send_message(chat_id=user_id,text=f"✅ Вам активирован тариф: {limit} запросов в день на {days} дней.\n\nТариф действует до {expires.strftime('%d.%m.%Y %H:%M')}.")
    except Exception: log.exception("failed to notify user about paid plan")
async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global maintenance_mode
    admin=admin_id()
    if admin is None or update.effective_chat.id != admin: return
    if len(context.args) != 1 or context.args[0].lower() not in ("on","off"):
        await update.message.reply_text("Формат: /maintenance on или /maintenance off"); return
    maintenance_mode=context.args[0].lower()=="on"
    await update.message.reply_text("🔧 Техническое обслуживание ВКЛЮЧЕНО." if maintenance_mode else "✅ Техническое обслуживание ВЫКЛЮЧЕНО. Бот снова принимает запросы.")
async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global maintenance_mode
    message=update.effective_message; chat=update.effective_chat
    if not message or not chat: return
    admin=admin_id()
    if admin is not None and chat.id==admin:
        reply=message.reply_to_message
        if reply and reply.message_id in request_targets:
            target_chat=request_targets[reply.message_id]
            try:
                await context.bot.copy_message(chat_id=target_chat,from_chat_id=chat.id,message_id=message.message_id); await message.reply_text("✅ Ответ отправлен пользователю.")
            except Exception: log.exception("failed to send admin response")
        return
    if maintenance_mode:
        await message.reply_text(MAINTENANCE_TEXT); return
    if admin is None:
        await message.reply_text("⚠️ Бот ещё не настроен. Администратор должен добавить ADMIN_CHAT_ID в Render."); return
    if chat.id not in welcomed_users:
        welcomed_users.add(chat.id); await message.reply_text(WELCOME)
    allowed,remaining,limit=check_and_use_request(chat.id)
    if not allowed:
        await message.reply_text(f"⚠️ Лимит {limit} запросов на сегодня исчерпан.\n\n💳 Для продолжения доступны тарифы:\n🔥 5 запросов/день — 250 ₽ за 7 дней или 500 ₽ за 14 дней\n⚡ 10 запросов/день — 600 ₽ за 7 дней или 1 000 ₽ за 14 дней\n\n📩 Для оплаты: @ZotickNick\nПодробнее: /prices"); return
    try:
        await context.bot.send_message(chat_id=admin,text=("📨 НОВЫЙ ЗАПРОС\n"+f"👤 {chat.first_name or ''} {chat.last_name or ''}".strip()+f"\n🆔 {chat.id}"+(f"\n🔗 @{chat.username}" if chat.username else "")+f"\n🎁 Осталось запросов сегодня: {remaining}/{limit}"+"\n\n⏱ Клиенту сообщено: ответ в течение 5 минут — 1 часа.\n\nОтветь на пересланное сообщение готовым анализом."))
        forwarded=await context.bot.forward_message(chat_id=admin,from_chat_id=chat.id,message_id=message.message_id); request_targets[forwarded.message_id]=chat.id
        await message.reply_text(f"📨 Запрос принят!\n\n⏱ Ответ на ваш запрос — в течение 5 минут — 1 часа.\n🎁 Осталось запросов сегодня: {remaining}/{limit}")
    except Exception:
        log.exception("failed to relay user message"); await message.reply_text("⚠️ Не удалось передать запрос. Попробуй ещё раз.")
bot_app=Application.builder().token(BOT_TOKEN).build()
bot_app.add_handler(CommandHandler("start",start)); bot_app.add_handler(CommandHandler("id",get_id)); bot_app.add_handler(CommandHandler("help",help_command)); bot_app.add_handler(CommandHandler("prices",prices_command)); bot_app.add_handler(CommandHandler("give",give_command)); bot_app.add_handler(CommandHandler("maintenance",maintenance_command)); bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,relay_message))
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot_app.initialize(); await bot_app.start(); await bot_app.updater.start_polling(); log.info("Telegram relay bot started")
    try: yield
    finally: await bot_app.updater.stop(); await bot_app.stop(); await bot_app.shutdown()
app=FastAPI(title="Sport Risk Analyst Pro",version="0.7.0",lifespan=lifespan)
@app.get("/")
async def root(): return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","maintenance":maintenance_mode}
@app.get("/health")
async def health(): return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","maintenance":maintenance_mode}
