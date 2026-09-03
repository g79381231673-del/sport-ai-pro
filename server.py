import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sport-ai-pro")
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN"); ADMIN_CHAT_ID=os.getenv("ADMIN_CHAT_ID"); FREE_DAILY_LIMIT=2; DB_PATH=os.getenv("DB_PATH","/tmp/sport_ai.db")
if not BOT_TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
WELCOME="""🏟 SPORT RISK ANALYST PRO

Привет! 👋 Добро пожаловать!

🎁 У вас есть 2 бесплатных запроса в день.

📩 Отправьте матч или скриншот линии — запрос будет передан аналитику.
⏱ Ответ — в течение 5 минут — 1 часа.

💳 Если бесплатных запросов недостаточно — откройте раздел «💳 Тарифы»."""
PRICES="""💳 ТАРИФЫ SPORT RISK ANALYST PRO

🎁 Бесплатно
• 2 запроса в день

🔥 Тариф PRO 5
• 5 запросов в день
• 7 дней — 250 ₽
• 14 дней — 500 ₽

⚡ Тариф PRO 10
• 10 запросов в день
• 7 дней — 600 ₽
• 14 дней — 1 000 ₽

📩 Для оплаты: @ZotickNick

После оплаты администратор активирует тариф."""
MAINTENANCE_TEXT="""🔧 ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ

Бот временно находится на техническом обслуживании.

Пожалуйста, попробуйте немного позже. Спасибо за понимание ❤️"""
request_targets={}; maintenance_mode=False

def db():
    c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row; return c

def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".",exist_ok=True)
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, created_at TEXT NOT NULL, last_seen TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS usage (user_id INTEGER NOT NULL, usage_date TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id,usage_date))")
        c.execute("CREATE TABLE IF NOT EXISTS paid_plans (user_id INTEGER PRIMARY KEY, daily_limit INTEGER NOT NULL, expires_at TEXT NOT NULL)"); c.commit()

def save_user(chat):
    now=datetime.now().isoformat()
    with db() as c:
        c.execute("INSERT INTO users(user_id,username,first_name,last_name,created_at,last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,last_seen=excluded.last_seen",(chat.id,chat.username,chat.first_name,chat.last_name,now,now)); c.commit()

def admin_id():
    try: return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    except ValueError: return None

def get_plan(uid):
    with db() as c:
        r=c.execute("SELECT daily_limit,expires_at FROM paid_plans WHERE user_id=?",(uid,)).fetchone()
        if not r:return None
        try:
            if datetime.fromisoformat(r["expires_at"])>datetime.now():return r
        except ValueError:pass
        c.execute("DELETE FROM paid_plans WHERE user_id=?",(uid,));c.commit()
    return None

def current_limit(uid):
    p=get_plan(uid);return int(p["daily_limit"]) if p else FREE_DAILY_LIMIT

def get_used_today(uid):
    today=datetime.now().date().isoformat()
    with db() as c:
        r=c.execute("SELECT used FROM usage WHERE user_id=? AND usage_date=?",(uid,today)).fetchone()
    return int(r["used"]) if r else 0

def check_and_use_request(uid):
    limit=current_limit(uid);today=datetime.now().date().isoformat()
    with db() as c:
        r=c.execute("SELECT used FROM usage WHERE user_id=? AND usage_date=?",(uid,today)).fetchone();used=int(r["used"]) if r else 0
        if used>=limit:return False,0,limit
        used+=1;c.execute("INSERT INTO usage(user_id,usage_date,used) VALUES(?,?,?) ON CONFLICT(user_id,usage_date) DO UPDATE SET used=excluded.used",(uid,today,used));c.commit()
    return True,limit-used,limit

def menu():
    return ReplyKeyboardMarkup([[KeyboardButton("🏟 Сделать анализ"),KeyboardButton("💳 Тарифы")],[KeyboardButton("👤 Мой профиль"),KeyboardButton("📊 Мои запросы")],[KeyboardButton("ℹ️ Как это работает"),KeyboardButton("👨‍💻 Поддержка")]],resize_keyboard=True)

async def start(update,context):
    chat=update.effective_chat
    if not chat:return
    save_user(chat)
    limit=current_limit(chat.id); used=get_used_today(chat.id); remaining=max(0,limit-used)
    if maintenance_mode:
        text=MAINTENANCE_TEXT
    elif used==0:
        text=WELCOME
    elif remaining>0:
        text=f"👋 С возвращением!\n\n📊 Сегодня у вас осталось: {remaining} из {limit} запросов.\n\n🏟 Можете отправить следующий матч или выбрать нужный раздел ниже."
    else:
        text=f"👋 С возвращением!\n\n⚠️ Все {limit} запросов на сегодня уже использованы.\n\n💳 Посмотреть доступные тарифы можно в разделе «💳 Тарифы»."
    await update.message.reply_text(text,reply_markup=menu())

async def get_id(update,context):
    if update.effective_chat:save_user(update.effective_chat)
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_chat.id}",reply_markup=menu())
async def prices_command(update,context):
    if update.effective_chat:save_user(update.effective_chat)
    await update.message.reply_text(PRICES,reply_markup=menu())
async def profile_command(update,context):
    chat=update.effective_chat
    if not chat:return
    save_user(chat);p=get_plan(chat.id);limit=int(p["daily_limit"]) if p else FREE_DAILY_LIMIT;used=get_used_today(chat.id)
    plan_text=(f"⚡ PRO {limit}\n📅 Действует до: {datetime.fromisoformat(p['expires_at']).strftime('%d.%m.%Y %H:%M')}" if p else "🎁 Бесплатный тариф")
    await update.message.reply_text(f"👤 МОЙ ПРОФИЛЬ\n\n{plan_text}\n📊 Сегодня: {used}/{limit} запросов\n🟢 Осталось: {max(0,limit-used)}",reply_markup=menu())
async def my_requests_command(update,context):
    chat=update.effective_chat
    if not chat:return
    save_user(chat);used=get_used_today(chat.id);limit=current_limit(chat.id)
    await update.message.reply_text(f"📊 ВАШИ ЗАПРОСЫ\n\nСегодня использовано: {used}/{limit}\nОсталось сегодня: {max(0,limit-used)}",reply_markup=menu())
async def how_command(update,context): await update.message.reply_text("ℹ️ КАК ЭТО РАБОТАЕТ\n\n1️⃣ Отправьте матч или скриншот линии.\n2️⃣ Бот передаст запрос администратору.\n3️⃣ Аналитик проведёт проверку.\n4️⃣ Готовый ответ придёт вам в этот чат.\n\n⏱ Обычно ответ приходит в течение 5 минут — 1 часа.",reply_markup=menu())
async def support_command(update,context): await update.message.reply_text("👨‍💻 ПОДДЕРЖКА\n\nПо вопросам оплаты и доступа: @ZotickNick",reply_markup=menu())
async def help_command(update,context): await how_command(update,context)
async def give_command(update,context):
    admin=admin_id()
    if admin is None or update.effective_chat.id!=admin:return
    if len(context.args)!=3:await update.message.reply_text("Формат: /give USER_ID LIMIT DAYS\nНапример: /give 5907925729 10 7");return
    try:
        uid=int(context.args[0]);limit=int(context.args[1]);days=int(context.args[2])
        if limit not in(5,10) or days not in(7,14):raise ValueError
    except ValueError:await update.message.reply_text("Ошибка. LIMIT: 5 или 10. DAYS: 7 или 14.");return
    exp=datetime.now()+timedelta(days=days)
    with db() as c:c.execute("INSERT INTO paid_plans(user_id,daily_limit,expires_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit,expires_at=excluded.expires_at",(uid,limit,exp.isoformat()));c.commit()
    await update.message.reply_text(f"✅ Тариф активирован\n👤 {uid}\n⚡ {limit} запросов/день\n📅 {days} дней\n⏳ До: {exp.strftime('%d.%m.%Y %H:%M')}")
    try:await context.bot.send_message(chat_id=uid,text=f"✅ Вам активирован тариф: {limit} запросов в день на {days} дней.\n\nТариф действует до {exp.strftime('%d.%m.%Y %H:%M')}.")
    except Exception:log.exception("failed to notify user")
async def maintenance_command(update,context):
    global maintenance_mode
    if admin_id() is None or update.effective_chat.id!=admin_id():return
    if len(context.args)!=1 or context.args[0].lower() not in("on","off"):await update.message.reply_text("Формат: /maintenance on или /maintenance off");return
    maintenance_mode=context.args[0].lower()=="on";await update.message.reply_text("🔧 Техническое обслуживание ВКЛЮЧЕНО." if maintenance_mode else "✅ Техническое обслуживание ВЫКЛЮЧЕНО. Бот снова принимает запросы.")
async def relay_message(update,context):
    message=update.effective_message;chat=update.effective_chat
    if not message or not chat:return
    admin=admin_id()
    if admin is not None and chat.id==admin:
        reply=message.reply_to_message
        if reply and reply.message_id in request_targets:
            try:await context.bot.copy_message(chat_id=request_targets[reply.message_id],from_chat_id=chat.id,message_id=message.message_id);await message.reply_text("✅ Ответ отправлен пользователю.")
            except Exception:log.exception("failed to send admin response")
        return
    save_user(chat)
    if maintenance_mode:await message.reply_text(MAINTENANCE_TEXT,reply_markup=menu());return
    if admin is None:await message.reply_text("⚠️ Бот ещё не настроен.",reply_markup=menu());return
    text=message.text or ""
    if text=="💳 Тарифы":await prices_command(update,context);return
    if text=="👤 Мой профиль":await profile_command(update,context);return
    if text=="📊 Мои запросы":await my_requests_command(update,context);return
    if text=="ℹ️ Как это работает":await how_command(update,context);return
    if text=="👨‍💻 Поддержка":await support_command(update,context);return
    if text=="🏟 Сделать анализ":await message.reply_text("🏟 Отлично! Отправьте матч или скриншот линии сюда 👇",reply_markup=menu());return
    allowed,remaining,limit=check_and_use_request(chat.id)
    if not allowed:
        await message.reply_text(f"⚠️ Лимит {limit} запросов на сегодня исчерпан.\n\n💳 Для продолжения доступны тарифы:\n🔥 5 запросов/день — 250 ₽ за 7 дней или 500 ₽ за 14 дней\n⚡ 10 запросов/день — 600 ₽ за 7 дней или 1 000 ₽ за 14 дней\n\n📩 Для оплаты: @ZotickNick\nПодробнее: /prices",reply_markup=menu());return
    try:
        await context.bot.send_message(chat_id=admin,text=("📨 НОВЫЙ ЗАПРОС\n"+f"👤 {chat.first_name or ''} {chat.last_name or ''}".strip()+f"\n🆔 {chat.id}"+(f"\n🔗 @{chat.username}" if chat.username else "")+f"\n📊 Осталось сегодня: {remaining}/{limit}\n\n⏱ Клиенту сообщено: ответ в течение 5 минут — 1 часа.\n\nОтветь на пересланное сообщение готовым анализом."))
        forwarded=await context.bot.forward_message(chat_id=admin,from_chat_id=chat.id,message_id=message.message_id);request_targets[forwarded.message_id]=chat.id
        await message.reply_text(f"📨 Запрос принят!\n\n⏱ Ответ — в течение 5 минут — 1 часа.\n📊 Осталось сегодня: {remaining}/{limit}",reply_markup=menu())
    except Exception:log.exception("failed to relay user message");await message.reply_text("⚠️ Не удалось передать запрос. Попробуй ещё раз.",reply_markup=menu())

bot_app=Application.builder().token(BOT_TOKEN).build()
for command,handler in [("start",start),("id",get_id),("help",help_command),("prices",prices_command),("profile",profile_command),("requests",my_requests_command),("give",give_command),("maintenance",maintenance_command)]:bot_app.add_handler(CommandHandler(command,handler))
bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,relay_message))
@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db();await bot_app.initialize();await bot_app.start();await bot_app.updater.start_polling();log.info("Telegram relay bot started")
    try:yield
    finally:await bot_app.updater.stop();await bot_app.stop();await bot_app.shutdown()
app=FastAPI(title="Sport Risk Analyst Pro",version="1.0.1",lifespan=lifespan)
@app.get("/")
async def root():return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","database":"sqlite","maintenance":maintenance_mode}
@app.get("/health")
async def health():return {"status":"ok","service":"sport-ai-pro","mode":"manual-relay","database":"sqlite","maintenance":maintenance_mode}
