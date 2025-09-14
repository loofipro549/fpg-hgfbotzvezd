# -*- coding: utf-8 -*-
"""
LofiProMailer_Bot — улучшенная версия (aiogram 2.25.1)

Замените константы (TG_TOKEN, OWNER_ID, OPEN_CHANNEL) при необходимости.
"""
import asyncio
import logging
import os
import random
import re
import aiosqlite
import shutil
import time
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

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

# ===================== НАСТРОЙКИ =====================
API_TOKEN = os.getenv("TG_TOKEN", "7984506224:AAEd3y8AgaP-DjjFqVZ8RfW4Q71yOxgK65w")
BOT_USERNAME = os.getenv("BOT_USERNAME", "LofiProMailer_Bot")  # без @
OWNER_ID = int(os.getenv("OWNER_ID", "865648878"))

# Каналы
OPEN_CHANNEL = os.getenv("OPEN_CHANNEL", "@gmaillofipro")  # публичный канал (реальная проверка)
PRIVATE_CHANNEL_FAKE_NAME = "Канал 2"

# Лимиты
DAILY_FREE_KEYS = int(os.getenv("DAILY_FREE_KEYS", "2"))
UNLIMITED_FOR_WHITELIST = True
BONUS_NAME_TEXT = "@LofiProMailer_Bot"  # если строка встречается в имени — +1 ключ/день

# Папка с фото
PHOTO_DIR = os.getenv("photo", "1")
TMP_DIR = "tmp"

# SMTP-настройки (оставлены ваши)
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

# ===================== ЛОГИ =====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("LofiProMailer_Bot")

# ===================== БД =====================
DB_PATH = "LofiProMailer_Bot.db"

CREATE_USERS_SQL = """
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

# ===================== УТИЛИТЫ =====================
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
                (user_id, DAILY_FREE_KEYS, date.today().isoformat()),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        data = dict(row)
        # гарантируем поля
        defaults = {
            "keys_today": DAILY_FREE_KEYS,
            "last_reset": date.today().isoformat(),
            "subscribed": 0,
            "whitelisted": 0,
            "referrer_id": None,
            "referrals_count": 0,
            "private_confirmed": 0,
            "bonus_name_last": None,
        }
        for k, v in defaults.items():
            if data.get(k) is None:
                data[k] = v
        return data

async def reset_daily_if_needed(user: dict) -> dict:
    today = date.today().isoformat()
    if user.get("last_reset") != today:
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
        user["keys_today"] = user.get("keys_today", 0) + 1
        user["bonus_name_last"] = today
    return user

async def inc_ref_for_referrer(referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET referrals_count = referrals_count + 1, keys_today = keys_today + 1 WHERE user_id=?", (referrer_id,))
        await db.commit()

async def save_referrer_if_first_time(user_id: int, referrer_id: Optional[int]):
    if not referrer_id or referrer_id == user_id:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row["referrer_id"] is None:
            await db.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id))
            await db.commit()
            await inc_ref_for_referrer(referrer_id)

async def pick_smtp_for_today(user_id: int) -> Tuple[str, str]:
    all_logins = list(SMTP_ACCOUNTS.keys())
    if not all_logins:
        raise RuntimeError("SMTP_ACCOUNTS is empty")
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT smtp_login FROM used_smtp WHERE user_id=? AND day=?", (user_id, today))
        rows = await cur.fetchall()
        used = {r["smtp_login"] for r in rows} if rows else set()
    available = [x for x in all_logins if x not in used] or all_logins
    login = random.choice(available)
    pwd = SMTP_ACCOUNTS[login].replace(" ", "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO used_smtp (user_id, smtp_login, day) VALUES (?, ?, ?)", (user_id, login, today))
        await db.commit()
    return login, pwd

async def send_email_via_smtp(from_login: str, from_pwd: str, to_email: str, subject: str, body: str, attachments: List[str]) -> Tuple[bool, str]:
    msg = MIMEMultipart()
    msg["From"] = from_login
    msg["To"] = to_email
    msg["Subject"] = subject or "(без темы)"
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    for path in attachments or []:
        try:
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
            msg.attach(part)
        except Exception as e:
            logger.warning("Не удалось прикрепить файл %s: %s", path, e)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(from_login, from_pwd)
            server.send_message(msg)
        return True, "OK"
    except Exception as e:
        logger.exception("SMTP error")
        return False, str(e)

async def cleanup_tmp_files(files: List[str]=None, keep_hours: int=24):
    """
    Если files переданы — попытаться удалить конкретные файлы.
    И удалить все файлы старше keep_hours в TMP_DIR.
    """
    try:
        if files:
            for p in files:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    logger.warning("Не удалось удалить временный файл %s", p)
        # удаляем старые
        if os.path.isdir(TMP_DIR):
            now = time.time()
            for fname in os.listdir(TMP_DIR):
                fpath = os.path.join(TMP_DIR, fname)
                try:
                    if os.path.isfile(fpath):
                        mtime = os.path.getmtime(fpath)
                        if now - mtime > keep_hours * 3600:
                            os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        logger.exception("cleanup_tmp_files error")

async def send_with_photo(bot: Bot, chat_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup]=None):
    try:
        if os.path.isdir(PHOTO_DIR):
            files = [f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))]
            if files:
                path = os.path.join(PHOTO_DIR, random.choice(files))
                with open(path, "rb") as ph:
                    await bot.send_photo(chat_id, photo=ph, caption=text, reply_markup=reply_markup, parse_mode=types.ParseMode.HTML)
                return
    except Exception:
        logger.exception("send_with_photo error")
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=types.ParseMode.HTML)

# ===================== КЛАВИАТУРЫ =====================
def menu_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💳 Купить подписку", callback_data="buy"),
           types.InlineKeyboardButton("👥 Реферальная система", callback_data="ref"))
    kb.add(types.InlineKeyboardButton("✉️ Отправить письмо", callback_data="send"),
           types.InlineKeyboardButton("👤 Профиль", callback_data="profile"))
    return kb

def sub_check_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("Канал 1", url=f"https://t.me/{OPEN_CHANNEL.replace('@','')}"))
    kb.add(types.InlineKeyboardButton(PRIVATE_CHANNEL_FAKE_NAME, url="https://t.me/+tF_oI1s4EGFhOWUy"))
    kb.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="confirm_private"),
           types.InlineKeyboardButton("🔁 Проверить", callback_data="recheck"))
    return kb

def confirm_mail_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ Да", callback_data="confirm_send"),
           types.InlineKeyboardButton("❌ Нет", callback_data="cancel_send"))
    return kb

# ===================== БОТ =====================
bot = Bot(API_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=MemoryStorage())

# централизованный обработчик ошибок (логирование)
@dp.errors_handler()
async def global_errors_handler(update, exception):
    logger.exception("Unhandled error: %s | update: %s", exception, getattr(update, "update_id", update))
    return True  # считаем ошибку обработанной

# ===================== ХЭНДЛЕРЫ =====================
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    try:
        args_raw = message.get_args() or ""
        args = args_raw.strip()
        user = await get_or_create_user(message.from_user.id)
        user = await reset_daily_if_needed(user)

        full_name = " ".join(filter(None, [message.from_user.first_name, (message.from_user.last_name or "")]))
        user = await apply_name_bonus_if_needed(user, full_name)

        referrer_id = None
        try:
            if args:
                referrer_id = int(args)
        except Exception:
            referrer_id = None
        await save_referrer_if_first_time(message.from_user.id, referrer_id)

        await send_with_photo(bot, message.chat.id,
            "<b>Добро пожаловать!</b>\n\n"
            "<b>Канал 1</b> — подпишись.\n"
            f"<b>Канал 2</b> — подпишись.\n\n"
            "После подписки нажми <b>Проверить</b> для доступа.",
            reply_markup=sub_check_kb()
        )
    except Exception:
        logger.exception("cmd_start error")
        await message.reply("Внутренняя ошибка. Попробуйте позже.")

async def is_subscribed_open_channel(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(OPEN_CHANNEL, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception:
        return False

@dp.callback_query_handler(lambda c: c.data == "confirm_private")
async def on_confirm_private(call: types.CallbackQuery):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET private_confirmed=1 WHERE user_id=?", (call.from_user.id,))
            await db.commit()
        await call.answer("Подтверждение сохранено ✅")
    except Exception:
        logger.exception("confirm_private error")
        await call.answer("Ошибка сохранения", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "recheck")
async def on_recheck(call: types.CallbackQuery):
    try:
        user = await get_or_create_user(call.from_user.id)
        user = await reset_daily_if_needed(user)
        full_name = " ".join(filter(None, [call.from_user.first_name, call.from_user.last_name or ""]))
        user = await apply_name_bonus_if_needed(user, full_name)
        subscribed_open = await is_subscribed_open_channel(call.from_user.id)
        if subscribed_open and user.get("private_confirmed") == 1:
            await call.answer("Доступ открыт!", show_alert=False)
            await send_with_photo(bot, call.message.chat.id, "<b>Главное меню</b>\n\nВыберите действие ниже.", reply_markup=menu_kb())
        else:
            await call.answer("Подписка не подтверждена", show_alert=True)
    except Exception:
        logger.exception("recheck error")
        await call.answer("Ошибка проверки", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "profile")
async def on_profile(call: types.CallbackQuery):
    try:
        user = await get_or_create_user(call.from_user.id)
        user = await reset_daily_if_needed(user)
        unlimited = (user.get("subscribed") == 1) or (UNLIMITED_FOR_WHITELIST and user.get("whitelisted") == 1)
        status = "Активна" if unlimited else "Не активна"
        keys_text = "∞" if unlimited else str(user.get("keys_today", 0))
        await send_with_photo(bot, call.message.chat.id,
            "<b>👤 Профиль</b>\n\n"
            f"<b>🆔 ID:</b> <code>{call.from_user.id}</code>\n"
            f"<b>🔷 Ключи:</b> {keys_text}\n"
            f"<b>🎟 Подписка:</b> {status}",
            reply_markup=menu_kb()
        )
        await call.answer()
    except Exception:
        logger.exception("on_profile error")
        await call.answer("Ошибка", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "ref")
async def on_ref(call: types.CallbackQuery):
    try:
        link = f"https://t.me/{BOT_USERNAME}?start={call.from_user.id}"
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT referrals_count FROM users WHERE user_id=?", (call.from_user.id,))
            row = await cur.fetchone()
            count = (row["referrals_count"] if row else 0) or 0
        await send_with_photo(bot, call.message.chat.id,
            "<b>👥 Реферальная система</b>\n\n"
            f"<b>Рефералы:</b> {count}\n\n"
            f"<b>🔗 Реферальная ссылка:</b>\n<code>{link}</code>\n\n"
            "За один переход по рефке — <b>+1 ключ</b>.\n"
            f"🎁 Бонус за имя: укажите <b>{BONUS_NAME_TEXT}</b> в имени — получите <b>+1 ключ</b> при первом запуске бота в день.",
            reply_markup=menu_kb()
        )
        await call.answer()
    except Exception:
        logger.exception("on_ref error")
        await call.answer("Ошибка", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "buy")
async def on_buy(call: types.CallbackQuery):
    await send_with_photo(bot, call.message.chat.id,
        "<b>Оформление подписки</b>\n\n"
        "<b>💠 После покупки вы получаете:</b>\n"
        "• Полный доступ к письмам\n"
        "• Неограниченное время пользования ботом\n"
        "• Безлимитные отправки письма\n\n"
        "<b>💰 Цена:</b> 0.9$\n\n"
        "<b>Приобрести подписку —</b> <a href=\"https://t.me/bloodylofipro\">написать менеджеру</a>",
        reply_markup=menu_kb()
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "send")
async def on_send(call: types.CallbackQuery, state: FSMContext):
    try:
        user = await get_or_create_user(call.from_user.id)
        user = await reset_daily_if_needed(user)
        unlimited = (user.get("subscribed") == 1) or (UNLIMITED_FOR_WHITELIST and user.get("whitelisted") == 1)
        if (not unlimited) and user.get("keys_today", 0) <= 0:
            await send_with_photo(bot, call.message.chat.id, "<b>У вас нет ключей на сегодня.</b> Купите подписку или получите ключ по рефералке/бонусу имени.", reply_markup=menu_kb())
            await call.answer()
            return
        await state.update_data(attachments=[])
        await SendMailStates.asking_target.set()
        await send_with_photo(bot, call.message.chat.id, "<b>Вы действительно хотите отправить письмо?</b>\n\nОтправьте <b>email получателя</b>.")
        await call.answer()
    except Exception:
        logger.exception("on_send error")
        await call.answer("Ошибка", show_alert=True)

@dp.message_handler(state=SendMailStates.asking_target, content_types=types.ContentTypes.TEXT)
async def fsm_target(message: types.Message, state: FSMContext):
    to_email = (message.text or "").strip()
    if not EMAIL_REGEX.match(to_email):
        await send_with_photo(bot, message.chat.id, "Введите корректный email получателя.")
        return
    await state.update_data(to_email=to_email)
    await SendMailStates.asking_subject.set()
    await send_with_photo(bot, message.chat.id, "📧 <b>Введите тему письма:</b>")

@dp.message_handler(state=SendMailStates.asking_subject, content_types=types.ContentTypes.TEXT)
async def fsm_subject(message: types.Message, state: FSMContext):
    subject = (message.text or "").strip()
    await state.update_data(subject=subject or "(без темы)")
    await SendMailStates.asking_body.set()
    await send_with_photo(bot, message.chat.id, "📝 <b>Введите текст письма:</b>")

@dp.message_handler(state=SendMailStates.asking_body, content_types=types.ContentTypes.TEXT)
async def fsm_body(message: types.Message, state: FSMContext):
    body = (message.text or "").strip()
    await state.update_data(body=body)
    await SendMailStates.asking_photos.set()
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Да", callback_data="add_photos_yes"), types.InlineKeyboardButton("Нет", callback_data="add_photos_no"))
    await send_with_photo(bot, message.chat.id, "🖼 <b>Хотите добавить фотографии?</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ("add_photos_yes", "add_photos_no"), state=SendMailStates.asking_photos)
async def fsm_photos_choice(call: types.CallbackQuery, state: FSMContext):
    if call.data == "add_photos_yes":
        await SendMailStates.collecting_photos.set()
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Готово", callback_data="photos_done"))
        await send_with_photo(bot, call.message.chat.id, "📎 <b>Отправляйте фотографии одно за другим.</b>\nКогда закончите — нажмите <b>Готово</b>.", reply_markup=kb)
    else:
        data = await state.get_data()
        await SendMailStates.confirming.set()
        await send_with_photo(bot, call.message.chat.id,
            "<b>Подтверждение отправки</b>\n\n"
            f"Кому: <code>{data.get('to_email')}</code>\n"
            f"Тема: {data.get('subject')}\n\n"
            "Отправить?",
            reply_markup=confirm_mail_kb()
        )
    await call.answer()

@dp.message_handler(content_types=types.ContentTypes.PHOTO, state=SendMailStates.collecting_photos)
async def fsm_collect_photos(message: types.Message, state: FSMContext):
    os.makedirs(TMP_DIR, exist_ok=True)
    if not message.photo:
        return
    biggest = message.photo[-1]
    dst = os.path.join(TMP_DIR, f"{message.from_user.id}_{biggest.file_unique_id}.jpg")
    try:
        # стараемся использовать message.download (наиболее надёжно)
        await message.download(destination_file=dst)
    except Exception:
        try:
            file = await bot.get_file(biggest.file_id)
            await bot.download_file(file.file_path, dst)
        except Exception:
            logger.exception("download photo error")
            return
    data = await state.get_data()
    atts = list(data.get("attachments", []))
    atts.append(dst)
    await state.update_data(attachments=atts)
    await send_with_photo(bot, message.chat.id, f"Добавлено фото. Всего вложений: <b>{len(atts)}</b>.")

@dp.callback_query_handler(lambda c: c.data == "photos_done", state=SendMailStates.collecting_photos)
async def fsm_photos_done(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await SendMailStates.confirming.set()
    await send_with_photo(bot, call.message.chat.id,
        "<b>Подтверждение отправки</b>\n\n"
        f"Кому: <code>{data.get('to_email')}</code>\n"
        f"Тема: {data.get('subject')}\n"
        f"Вложений: {len(data.get('attachments', []))}\n\n"
        "Отправить?",
        reply_markup=confirm_mail_kb()
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data in ("confirm_send", "cancel_send"), state=SendMailStates.confirming)
async def fsm_confirm_send(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel_send":
        await state.finish()
        await send_with_photo(bot, call.message.chat.id, "Отменено.", reply_markup=menu_kb())
        await call.answer()
        return

    data = await state.get_data()
    to_email = data.get("to_email")
    subject = data.get("subject", "(без темы)")
    body = data.get("body", "")
    attachments = data.get("attachments", []) or []

    user = await get_or_create_user(call.from_user.id)
    user = await reset_daily_if_needed(user)
    unlimited = (user.get("subscribed") == 1) or (UNLIMITED_FOR_WHITELIST and user.get("whitelisted") == 1)

    try:
        login, pwd = await pick_smtp_for_today(call.from_user.id)
    except Exception:
        logger.exception("pick_smtp_for_today error")
        await send_with_photo(bot, call.message.chat.id, "<b>Ошибка:</b> нет доступных SMTP.", reply_markup=menu_kb())
        await state.finish()
        await call.answer()
        return

    ok, err = await send_email_via_smtp(login, pwd, to_email, subject, body, attachments)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO mail_log (user_id, to_email, subject, body, smtp_used, day) VALUES (?, ?, ?, ?, ?, ?)",
                         (call.from_user.id, to_email, subject, body, login, date.today().isoformat()))
        if ok and (not unlimited):
            await db.execute("UPDATE users SET keys_today = keys_today - 1 WHERE user_id=?", (call.from_user.id,))
        await db.commit()

    # удаляем временные файлы, только те что использовались
    await cleanup_tmp_files(files=attachments, keep_hours=24)

    await state.finish()

    if ok:
        await send_with_photo(bot, call.message.chat.id,
            "<b>Готово!</b> Письмо отправлено.\n\n"
            f"<b>Кому:</b> <code>{to_email}</code>\n"
            f"<b>Тема:</b> {subject}\n"
            f"<b>SMTP:</b> <code>{login}</code>\n"
            f"<b>Вложений:</b> {len(attachments)}",
            reply_markup=menu_kb()
        )
    else:
        await send_with_photo(bot, call.message.chat.id, f"<b>Ошибка отправки:</b> {err}", reply_markup=menu_kb())
    await call.answer()

# ===================== АДМИН-КОМАНДЫ =====================
@dp.message_handler(commands=["sub_on"])
async def cmd_sub_on(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int((message.get_args() or "").strip())
    except Exception:
        await message.reply("/sub_on <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET subscribed=1 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Подписка включена: {uid}")

@dp.message_handler(commands=["sub_off"])
async def cmd_sub_off(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int((message.get_args() or "").strip())
    except Exception:
        await message.reply("/sub_off <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET subscribed=0 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Подписка выключена: {uid}")

@dp.message_handler(commands=["wl_on"])
async def cmd_wl_on(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int((message.get_args() or "").strip())
    except Exception:
        await message.reply("/wl_on <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET whitelisted=1 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Вайтлист включён: {uid}")

@dp.message_handler(commands=["wl_off"])
async def cmd_wl_off(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int((message.get_args() or "").strip())
    except Exception:
        await message.reply("/wl_off <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET whitelisted=0 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Вайтлист выключен: {uid}")

@dp.message_handler(commands=["keys"])
async def cmd_keys(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        args = (message.get_args() or "").split()
        uid, amount = int(args[0]), int(args[1])
    except Exception:
        await message.reply("/keys <user_id> <amount>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET keys_today = keys_today + ? WHERE user_id=?", (amount, uid))
        await db.commit()
    await message.reply(f"Выдано ключей: +{amount} для {uid}")

# ===================== ФОЛБЭК =====================
@dp.message_handler()
async def fallback(message: types.Message):
    await send_with_photo(bot, message.chat.id, "Нажмите кнопку ниже:", reply_markup=menu_kb())

# ===================== MAIN =====================
async def on_startup(dp: Dispatcher):
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    await init_db()
    logger.info("DB ready")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
