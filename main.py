# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import random
import re
import aiosqlite
from datetime import date
from typing import List, Optional, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ===================== НАСТРОЙКИ =====================
API_TOKEN = "7984506224:AAEd3y8AgaP-DjjFqVZ8RfW4Q71yOxgK65w"
BOT_USERNAME = "LofiProMailer_Bot"
OWNER_ID = 865648878
OPEN_CHANNEL = "gmaillofipro"  # без @
PRIVATE_CHANNEL_FAKE_NAME = "Канал 2"
DAILY_FREE_KEYS = 2
BONUS_NAME_TEXT = "@LofiProMailer_Bot"
PHOTO_DIR = "photo"
TMP_DIR = "tmp"


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

DB_PATH = "LofiProMailer_Bot.db"

# ===================== ЛОГИ =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LofiProMailer_Bot")

# ===================== FSM =====================
class SendMailStates(StatesGroup):
    asking_target = State()
    asking_subject = State()
    asking_body = State()
    asking_photos = State()
    collecting_photos = State()
    confirming = State()

# ===================== ХЕЛПЕРЫ =====================
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            keys_today INTEGER DEFAULT 0,
            last_reset DATE,
            subscribed INTEGER DEFAULT 0,
            whitelisted INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referrals_count INTEGER DEFAULT 0,
            private_confirmed INTEGER DEFAULT 0,
            bonus_name_last DATE
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS mail_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            to_email TEXT,
            subject TEXT,
            body TEXT,
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            smtp_used TEXT,
            day TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS used_smtp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            smtp_login TEXT,
            day TEXT
        )""")
        await db.commit()

async def get_or_create_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await db.execute("INSERT INTO users (user_id, keys_today, last_reset) VALUES (?, ?, ?)",
                             (user_id, DAILY_FREE_KEYS, date.today().isoformat()))
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row)

async def reset_daily_if_needed(user: dict) -> dict:
    today = date.today().isoformat()
    if user["last_reset"] != today:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET keys_today=?, last_reset=? WHERE user_id=?",
                             (DAILY_FREE_KEYS, today, user["user_id"]))
            await db.execute("DELETE FROM used_smtp WHERE user_id=? AND day!=?", (user["user_id"], today))
            await db.commit()
        user["keys_today"] = DAILY_FREE_KEYS
        user["last_reset"] = today
    return user

async def apply_name_bonus_if_needed(user: dict, full_name: str) -> dict:
    today = date.today().isoformat()
    if user.get("bonus_name_last") != today and full_name and BONUS_NAME_TEXT.replace("@","").lower() in full_name.replace("@","").lower():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET keys_today = keys_today + 1, bonus_name_last=? WHERE user_id=?",
                             (today, user["user_id"]))
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
    pwd = SMTP_ACCOUNTS[login].replace(" ","")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO used_smtp (user_id, smtp_login, day) VALUES (?, ?, ?)", (user_id, login, today))
        await db.commit()
    return login, pwd

async def send_email_via_smtp(from_login, from_pwd, to_email, subject, body, attachments: List[str]) -> Tuple[bool,str]:
    msg = MIMEMultipart()
    msg['From'] = from_login
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain','utf-8'))
    for path in attachments:
        try:
            with open(path,'rb') as f:
                part = MIMEBase('application','octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(path)}"')
            msg.attach(part)
        except Exception as e:
            logger.warning(f"Attachment error {path}: {e}")
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(from_login, from_pwd)
        server.send_message(msg)
        server.quit()
        return True,"OK"
    except Exception as e:
        return False,str(e)

async def send_with_photo(bot: Bot, chat_id: int, text: str, reply_markup=None):
    os.makedirs(PHOTO_DIR, exist_ok=True)
    try:
        files = [f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg",".jpeg",".png"))]
        if files:
            path = os.path.join(PHOTO_DIR, random.choice(files))
            with open(path,'rb') as ph:
                await bot.send_photo(chat_id, ph, caption=text, reply_markup=reply_markup, parse_mode="HTML")
            return
    except: pass
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")

# ===================== КЛАВИАТУРЫ =====================
def menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💳 Купить подписку", callback_data="buy"),
           types.InlineKeyboardButton("👥 Реферальная система", callback_data="ref"))
    kb.add(types.InlineKeyboardButton("✉️ Отправить письмо", callback_data="send"),
           types.InlineKeyboardButton("👤 Профиль", callback_data="profile"))
    return kb

def sub_check_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("Канал 1", url=f"https://t.me/{OPEN_CHANNEL}"))
    kb.add(types.InlineKeyboardButton(PRIVATE_CHANNEL_FAKE_NAME, url="https://t.me/+tF_oI1s4EGFhOWUy"))
    kb.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="confirm_private"),
           types.InlineKeyboardButton("🔁 Проверить", callback_data="recheck"))
    return kb

def confirm_mail_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ Да", callback_data="confirm_send"),
           types.InlineKeyboardButton("❌ Нет", callback_data="cancel_send"))
    return kb

# ===================== БОТ =====================
bot = Bot(API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# /start
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    user = await reset_daily_if_needed(user)
    full_name = " ".join(filter(None,[message.from_user.first_name,message.from_user.last_name or ""]))
    user = await apply_name_bonus_if_needed(user, full_name)
    await send_with_photo(bot, message.chat.id,
                          "<b>Добро пожаловать!</b>\n\n"
                          "<b>Канал 1</b> — подпишись.\n"
                          f"<b>Канал 2</b> — подпишись.\n\n"
                          "После подписки нажми <b>Проверить</b> для доступа.",
                          reply_markup=sub_check_kb())
