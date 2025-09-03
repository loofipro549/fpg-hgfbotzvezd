# -*- coding: utf-8 -*-
"""
LofiProMailer_Bot — Aiogram 2.25 с рабочей проверкой подписки через Telethon
"""

import asyncio
import logging
import os
import random
from datetime import date
from typing import List, Optional, Tuple

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.utils import executor

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ====== Telethon для проверки подписки ======
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import UserNotParticipantError

API_ID = 24484081
API_HASH = 'd80e82b5cadb9ba9201fdfbeccd24326'
BOT_TOKEN = os.getenv("TG_TOKEN", "7984506224:AAEd3y8AgaP-DjjFqVZ8RfW4Q71yOxgK65w")
client_tg = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

OPEN_CHANNEL_USERNAME = "gmaillofipro"  # без @

async def is_subscribed_open_channel(user_id: int) -> bool:
    try:
        await client_tg(GetParticipantRequest(
            channel=OPEN_CHANNEL_USERNAME,
            participant=user_id
        ))
        return True
    except UserNotParticipantError:
        return False
    except Exception as e:
        print(f"[Telethon] Ошибка проверки подписки: {e}")
        return False

# ===================== Настройки =====================
BOT_USERNAME = os.getenv("BOT_USERNAME", "LofiProMailer_Bot")
OWNER_ID = int(os.getenv("OWNER_ID", "595041765"))
DAILY_FREE_KEYS = 2
UNLIMITED_FOR_WHITELIST = True
BONUS_NAME_TEXT = "@LofiProMailer_Bot"
PHOTO_DIR = os.getenv("PHOTO_DIR", "photo")

SMTP_ACCOUNTS = {
    "fkspeoadfipa@gmail.com": "wdox jfrh tncs pwic",
    "ao6557424@gmail.com": "mnuy jepq yvyc hjbr",
    "dlyabravla655@gmail.com": "kprn ihvr bgia vdys",
    "extrage523@gmail.com": "mphz wjrz iibv rvbr",
    "graciocnachleni@gmail.com": "qavg mbmx lotz uoph",
    "lofi04976@gmail.com": "nhdw luwd axpx kgrj",
    "lofipro43@gmail.com": "dqks iuoj ynis badb",
    "lofisnos@gmail.com": "twya atav adpl klhe",
    "penisone48@gmail.com": "aisn nywc fxyh pgkk",
    "rtrueqw@gmail.com": "kzhu vuom lker yugq",
    "snos6244@gmail.com": "gnpy beqw nqkd wlgk",
    "worklofishop8@gmail.com": "uxhv rxxm meps sjof",
    "worklofishop0@gmail.com": "cbjb viiq xfph jbcs",
    "danaislava1488@gmail.com": "robi xhez pxdh fshw",
    "worklofishop215@gmail.com": "vuxf ndyv boje ledp",
    "asasadsjs@gmail.com": "qiuz edua zjfz utxi",
    "aleopo33@gmail.com": "gbfx svyk sdwq mpdv",
    "aumenaockovolosatoe38@gmail.com": "iqqr vtat oawj vczw",
    "gobllllllllll44@gmail.com": "ysxc xghk hgkf ffqg",
    "prostonaf7568@gmail.com": "lzjh tzbi uchb qfvv",
    "m4452736fdc@gmail.com": "mzai jzpk qpox zhxc",
    "rast34242@gmail.com": "qxqe jiba yxre bxtp",
}

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LofiProMailer_Bot")
DB_PATH = "LofiProMailer_Bot.db"

# ===================== SQL =====================
CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    keys_today INTEGER DEFAULT 0,
    last_reset DATE,
    whitelisted INTEGER DEFAULT 0,
    bonus_name_last DATE
);
"""

CREATE_MAIL_LOG_SQL = """
CREATE TABLE IF NOT EXISTS mail_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    to_email TEXT,
    subject TEXT,
    body TEXT,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    smtp_used TEXT,
    day TEXT
);
"""

CREATE_USED_SMTP_SQL = """
CREATE TABLE IF NOT EXISTS used_smtp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    smtp_login TEXT,
    day TEXT
);
"""

# ===================== FSM =====================
class SendMailStates(StatesGroup):
    asking_target = State()
    asking_subject = State()
    asking_body = State()
    asking_photos = State()
    collecting_photos = State()
    confirming = State()

# ===================== Утилиты =====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_USERS_SQL)
        await db.execute(CREATE_MAIL_LOG_SQL)
        await db.execute(CREATE_USED_SMTP_SQL)
        await db.commit()

async def get_or_create_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await db.execute("INSERT INTO users (user_id, keys_today, last_reset) VALUES (?, ?, ?)", (user_id, 0, date.today().isoformat()))
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row)

async def reset_daily_if_needed(user: dict) -> dict:
    today = date.today().isoformat()
    if user["last_reset"] != today:
        keys = DAILY_FREE_KEYS
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET keys_today=?, last_reset=? WHERE user_id=?", (keys, today, user["user_id"]))
            await db.execute("DELETE FROM used_smtp WHERE user_id=? AND day != ?", (user["user_id"], today))
            await db.commit()
        user["keys_today"] = keys
        user["last_reset"] = today
    return user

async def apply_name_bonus_if_needed(user: dict, full_name: str) -> dict:
    today = date.today().isoformat()
    if user.get("bonus_name_last") == today:
        return user
    if full_name and BONUS_NAME_TEXT.replace("@", "").lower() in full_name.replace("@", "").lower():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET keys_today = keys_today + 1, bonus_name_last=? WHERE user_id=?", (today, user["user_id"]))
            await db.commit()
        user["keys_today"] += 1
        user["bonus_name_last"] = today
    return user

async def pick_smtp_for_today(user_id: int) -> Tuple[str, str]:
    all_logins = list(SMTP_ACCOUNTS.keys())
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT smtp_login FROM used_smtp WHERE user_id=? AND day=?", (user_id, today))
        used = {r["smtp_login"] for r in await cur.fetchall()}
    available = [x for x in all_logins if x not in used]
    login = random.choice(available if available else all_logins)
    pwd = SMTP_ACCOUNTS[login].replace(" ", "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO used_smtp (user_id, smtp_login, day) VALUES (?, ?, ?)", (user_id, login, today))
        await db.commit()
    return login, pwd

async def send_with_photo(bot: Bot, chat_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup]=None, parse_mode: str = "HTML"):
    try:
        files = [f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))]
        if files:
            path = os.path.join(PHOTO_DIR, random.choice(files))
            with open(path, 'rb') as ph:
                await bot.send_photo(chat_id, photo=ph, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
    except Exception as e:
        logger.warning(f"Ошибка отправки фото: {e}")
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ===================== Клавиатуры =====================
def menu_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💳 Купить подписку", callback_data="buy"),
        types.InlineKeyboardButton("👥 Реферальная система", callback_data="ref"),
    )
    kb.add(
        types.InlineKeyboardButton("✉️ Отправить письмо", callback_data="send"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
    )
    return kb

def sub_check_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Канал 1", url=f"https://t.me/{OPEN_CHANNEL_USERNAME}"),
    )
    kb.add(
        types.InlineKeyboardButton("🔁 Проверить", callback_data="recheck")
    )
    return kb

# ===================== Бот =====================
bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# --------------------- /start ---------------------
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    user = await reset_daily_if_needed(user)
    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name or ""]))
    user = await apply_name_bonus_if_needed(user, full_name)

    await send_with_photo(
        bot,
        message.chat.id,
        "<b>Добро пожаловать!</b>\n\n"
        "Подпишитесь на канал ниже и нажмите Проверить.",
        reply_markup=sub_check_kb()
    )

# --------------------- Проверка подписки ---------------------
@dp.callback_query_handler(lambda c: c.data == "recheck")
async def recheck_subscription(call: types.CallbackQuery):
    user = await get_or_create_user(call.from_user.id)
    subscribed_open = await is_subscribed_open_channel(call.from_user.id)
    if subscribed_open:
        await call.answer("Доступ открыт!", show_alert=False)
        await send_with_photo(
            bot,
            call.message.chat.id,
            "<b>Главное меню</b>\n\nВыберите действие ниже.",
            reply_markup=menu_kb()
        )
    else:
        await call.answer("Вы не подписаны на канал.", show_alert=True)

# ===================== MAIN =====================
async def on_startup(dp: Dispatcher):
    await init_db()
    logger.info("DB ready")
    # Запуск Telethon клиента
    await client_tg.start()
    logger.info("Telethon ready")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
