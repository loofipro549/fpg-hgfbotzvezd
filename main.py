# -*- coding: utf-8 -*-
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

from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import UserNotParticipantError

# ===================== НАСТРОЙКИ =====================
API_TOKEN = "7984506224:AAEd3y8AgaP-DjjFqVZ8RfW4Q71yOxgK65w"
BOT_USERNAME = "LofiProMailer_Bot"
OWNER_ID = 595041765

API_ID = 24484081
API_HASH = "d80e82b5cadb9ba9201fdfbeccd24326"

OPEN_CHANNEL = "gmaillofipro"  # Публичный канал для проверки
OPTIONAL_CHANNEL_NAME = "Канал 2"
OPTIONAL_CHANNEL_LINK = "https://t.me/+tF_oI1s4EGFhOWUy"  # Необязательный

DAILY_FREE_KEYS = 2
BONUS_NAME_TEXT = "@LofiProMailer_Bot"
PHOTO_DIR = "photo"


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
    referrer_id INTEGER,
    referrals_count INTEGER DEFAULT 0,
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
    smtp_used TEXT
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
    confirming = State()

# ===================== TELETHON =====================
telethon_client = TelegramClient('bot', API_ID, API_HASH)

async def is_subscribed_open_channel(user_id: int) -> bool:
    await telethon_client.start()
    try:
        await telethon_client(GetParticipantRequest(channel=OPEN_CHANNEL, participant=user_id))
        return True
    except UserNotParticipantError:
        return False
    except Exception as e:
        logger.warning(f"Ошибка проверки подписки: {e}")
        return False

# ===================== БД =====================
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
            await db.execute(
                "INSERT INTO users (user_id, keys_today, last_reset) VALUES (?, ?, ?)",
                (user_id, 0, date.today().isoformat())
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row)

async def reset_daily_if_needed(user: dict) -> dict:
    today = date.today().isoformat()
    if user["last_reset"] != today:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET keys_today=?, last_reset=? WHERE user_id=?",
                (DAILY_FREE_KEYS, today, user["user_id"])
            )
            await db.execute("DELETE FROM used_smtp WHERE user_id=? AND day!=?", (user["user_id"], today))
            await db.commit()
        user["keys_today"] = DAILY_FREE_KEYS
        user["last_reset"] = today
    return user

async def apply_name_bonus_if_needed(user: dict, full_name: str) -> dict:
    today = date.today().isoformat()
    if user.get("bonus_name_last") == today:
        return user
    if full_name and BONUS_NAME_TEXT.replace("@","").lower() in full_name.replace("@","").lower():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET keys_today = keys_today + 1, bonus_name_last=? WHERE user_id=?",
                (today, user["user_id"])
            )
            await db.commit()
        user["keys_today"] += 1
        user["bonus_name_last"] = today
    return user

async def save_referrer_if_first_time(user_id: int, referrer_id: Optional[int]):
    if not referrer_id or referrer_id == user_id:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row["referrer_id"] is None:
            await db.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id))
            await db.execute("UPDATE users SET referrals_count = referrals_count + 1, keys_today = keys_today + 1 WHERE user_id=?", (referrer_id,))
            await db.commit()

# ===================== КЛАВИАТУРЫ =====================
def menu_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💳 Купить подписку", callback_data="buy"),
        types.InlineKeyboardButton("👥 Реферальная система", callback_data="ref"),
        types.InlineKeyboardButton("✉️ Отправить письмо", callback_data="send"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile")
    )
    return kb

def sub_check_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Канал 1", url=f"https://t.me/{OPEN_CHANNEL}"),
        types.InlineKeyboardButton(f"{OPTIONAL_CHANNEL_NAME}", url=OPTIONAL_CHANNEL_LINK)
    )
    kb.add(
        types.InlineKeyboardButton("✅ Я подписался", callback_data="recheck")
    )
    return kb

# ===================== БОТ =====================
bot = Bot(API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    args = message.get_args().strip()
    user = await get_or_create_user(message.from_user.id)
    user = await reset_daily_if_needed(user)
    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name or ""]))
    user = await apply_name_bonus_if_needed(user, full_name)
    try:
        referrer_id = int(args) if args else None
    except:
        referrer_id = None
    await save_referrer_if_first_time(message.from_user.id, referrer_id)

    await message.answer(
        "<b>Добро пожаловать!</b>\n\nПодпишитесь на каналы ниже и нажмите ✅ Я подписался",
        reply_markup=sub_check_kb()
    )

@dp.callback_query_handler(lambda c: c.data == "recheck")
async def recheck_subscription(call: types.CallbackQuery):
    subscribed = await is_subscribed_open_channel(call.from_user.id)
    if subscribed:
        await call.message.edit_text(
            "<b>Главное меню</b>\nВыберите действие ниже.",
            reply_markup=menu_kb()
        )
        await call.answer("Доступ открыт!", show_alert=False)
    else:
        await call.answer("Подписка на канал не подтверждена.", show_alert=True)

# ===================== MAIN =====================
async def on_startup(dp: Dispatcher):
    await init_db()
    logger.info("БД готова")
    await telethon_client.start()
    logger.info("Telethon готов")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
