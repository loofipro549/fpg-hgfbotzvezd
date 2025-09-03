# -*- coding: utf-8 -*-
"""
LofiProMailer_Bot — Telegram-бот на aiogram 2.25

Функции:
- Старт, проверка подписки на 2 канала (1 реальная проверка открытого канала, 1 — фейк-подтверждение закрытого)
- Меню: Купить подписку | Реферальная система | Отправить письмо | Профиль
- Профиль с ID, ключами (лимит/остаток на сегодня), статусом подписки
- Реферальная система: 1 ключ за переход по ссылке, бонус за имя (@LofiProMailer_Bot) 1 раз в день
- Отправка письма с подтверждением, вложениями (фото) через случайный SMTP
- К каждому сообщению бота прикрепляется случайная картинка из ./photo/
- Простые админ-команды для вайтлиста/подписки

Проверено под aiogram==2.25.1

Подготовка:
1) Python 3.9+
2) pip install aiogram==2.25.1 aiosqlite==0.19.0
3) В папке проекта создайте папку ./photo/ и положите туда хотя бы 1 изображение (jpg/png)
4) Замените токен бота и имя открытого канала ниже
5) Запуск: python bot.py

ВНИМАНИЕ: пароли SMTP ниже — это БЫЛИ присланы пользователем. Не коммитьте файл в публичные репозитории!
"""
import asyncio
import logging
import os
import random
import re
import string
import aiosqlite
from datetime import datetime, date
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
BOT_USERNAME = os.getenv("BOT_USERNAME", "LofiProMailer_Bot")  # Без @ для построения ссылок
OWNER_ID = int(os.getenv("OWNER_ID", "865648878"))       # Админ для команд

# Каналы
OPEN_CHANNEL = os.getenv("OPEN_CHANNEL", "@gmaillofipro")  # Открытый канал (реальная проверка)
PRIVATE_CHANNEL_FAKE_NAME = "Канал 2"  # Отображение в UI (проверка — кнопкой "Я подписался")

# Лимиты
DAILY_FREE_KEYS = int(os.getenv("DAILY_FREE_KEYS", "2"))       # 3 по ТЗ (можно сменить на 1)
UNLIMITED_FOR_WHITELIST = True
BONUS_NAME_TEXT = "@LofiProMailer_Bot"  # Бонус +1 ключ в день, если имя содержит это

# Папка с фото, которые прикрепляются к каждому сообщению
PHOTO_DIR = os.getenv("PHOTO_DIR", "photo")

# SMTP-аккаунты (логин: app_password). Пробелы в паролях будут удалены при логине.
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LofiProMailer_Bot")

# ===================== ХРАНИЛИЩЕ =====================
DB_PATH = "LofiProMailer_Bot.db"

CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    keys_today INTEGER DEFAULT 0,
    last_reset DATE,
    subscribed INTEGER DEFAULT 0,    -- флаг покупки подписки (полный доступ, безлимит)
    whitelisted INTEGER DEFAULT 0,   -- вайтлист (если включено — безлимит)
    referrer_id INTEGER,
    referrals_count INTEGER DEFAULT 0,
    private_confirmed INTEGER DEFAULT 0, -- подтверждение подписки на закрытый канал
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
            # первая инициализация
            await db.execute(
                "INSERT INTO users (user_id, keys_today, last_reset) VALUES (?, ?, ?)",
                (user_id, 0, date.today().isoformat()),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row)

async def reset_daily_if_needed(user: dict) -> dict:
    today = date.today().isoformat()
    if user["last_reset"] != today:
        # сбрасываем дневные ключи
        keys = DAILY_FREE_KEYS
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET keys_today=?, last_reset=? WHERE user_id=?",
                (keys, today, user["user_id"]),
            )
            await db.execute("DELETE FROM used_smtp WHERE user_id=? AND day != ?", (user["user_id"], today))
            await db.commit()
        user["keys_today"] = keys
        user["last_reset"] = today
    return user

async def apply_name_bonus_if_needed(user: dict, full_name: str) -> dict:
    today = date.today().isoformat()
    if user["bonus_name_last"] == today:
        return user
    # проверяем содержимое имени
    if full_name and BONUS_NAME_TEXT.replace("@", "").lower() in full_name.replace("@", "").lower():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET keys_today = keys_today + 1, bonus_name_last=? WHERE user_id=?",
                (today, user["user_id"]),
            )
            await db.commit()
        user["keys_today"] += 1
        user["bonus_name_last"] = today
    return user

async def inc_ref_for_referrer(referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET referrals_count = referrals_count + 1, keys_today = keys_today + 1 WHERE user_id=?",
            (referrer_id,),
        )
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

# Выбор случайного SMTP, не повторяя в этот день (если возможно)
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
    # запишем в used
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO used_smtp (user_id, smtp_login, day) VALUES (?, ?, ?)", (user_id, login, today))
        await db.commit()
    return login, pwd

# Отправка письма
async def send_email_via_smtp(from_login: str, from_pwd: str, to_email: str, subject: str, body: str, attachments: List[str]) -> Tuple[bool, str]:
    msg = MIMEMultipart()
    msg['From'] = from_login
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    for path in attachments:
        try:
            with open(path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)
        except Exception as e:
            logger.warning(f"Не удалось прикрепить файл {path}: {e}")

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(from_login, from_pwd)
        server.send_message(msg)
        server.quit()
        return True, "OK"
    except Exception as e:
        return False, str(e)

# Красивая отправка с фото
async def send_with_photo(bot: Bot, chat_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup]=None, parse_mode: str = "HTML"):
    # Выбираем случайную фотку из PHOTO_DIR; если нет — просто текст
    try:
        files = [f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))]
        if files:
            path = os.path.join(PHOTO_DIR, random.choice(files))
            with open(path, 'rb') as ph:
                await bot.send_photo(chat_id, photo=ph, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
    except Exception as e:
        logger.warning(f"Ошибка отправки фото: {e}")
    # fallback: просто текст
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ===================== КЛАВИАТУРЫ =====================

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
        types.InlineKeyboardButton("Канал 1", url=f"https://t.me/{OPEN_CHANNEL.replace('@','')}")
    )
    kb.add(
        types.InlineKeyboardButton(f"{PRIVATE_CHANNEL_FAKE_NAME}", url="https://t.me/+tF_oI1s4EGFhOWUy"),
    )
    kb.add(
        types.InlineKeyboardButton("✅ Я подписался", callback_data="confirm_private"),
        types.InlineKeyboardButton("🔁 Проверить", callback_data="recheck"),
    )
    return kb


def confirm_mail_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Да", callback_data="confirm_send"),
        types.InlineKeyboardButton("❌ Нет", callback_data="cancel_send"),
    )
    return kb

# ===================== БОТ =====================

bot = Bot(API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# /start с рефкодом
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    args = message.get_args().strip()
    user = await get_or_create_user(message.from_user.id)
    user = await reset_daily_if_needed(user)
    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name or ""]))
    user = await apply_name_bonus_if_needed(user, full_name)

    # Сохраняем реферала при первом запуске
    try:
        referrer_id = int(args) if args else None
    except:
        referrer_id = None
    await save_referrer_if_first_time(message.from_user.id, referrer_id)

    await send_with_photo(
        bot,
        message.chat.id,
        (
            "<b>Добро пожаловать!</b>\n\n"
            "<b>Канал 1</b> — подпишись.\n"
            f"<b>Канал 2</b> — подпишись.\n\n"
            "После подписки нажми <b>Проверить</b> для доступа."
        ),
        reply_markup=sub_check_kb()
    )

# Проверка подписки на открытый канал + фейковое подтверждение второго
async def is_subscribed_open_channel(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(OPEN_CHANNEL, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception:
        return False

@dp.callback_query_handler(lambda c: c.data == "confirm_private")
async def on_confirm_private(call: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET private_confirmed=1 WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.answer("Подтверждение сохранено")

@dp.callback_query_handler(lambda c: c.data == "recheck")
async def on_recheck(call: types.CallbackQuery):
    user = await get_or_create_user(call.from_user.id)
    user = await reset_daily_if_needed(user)
    full_name = " ".join(filter(None, [call.from_user.first_name, call.from_user.last_name or ""]))
    user = await apply_name_bonus_if_needed(user, full_name)

    subscribed_open = await is_subscribed_open_channel(call.from_user.id)
    if subscribed_open and user.get("private_confirmed") == 1:
        await call.answer("Доступ открыт!", show_alert=False)
        await send_with_photo(
            bot,
            call.message.chat.id,
            (
                "<b>Главное меню</b>\n\n"
                "Выберите действие ниже."
            ),
            reply_markup=menu_kb()
        )
    else:
        await call.answer("Подписка не подтверждена", show_alert=True)

# Главное меню — обработчики
@dp.callback_query_handler(lambda c: c.data == "profile")
async def on_profile(call: types.CallbackQuery):
    user = await get_or_create_user(call.from_user.id)
    user = await reset_daily_if_needed(user)
    status = "Активна" if (user["subscribed"] or (UNLIMITED_FOR_WHITELIST and user["whitelisted"])) else "Не активна"
    await send_with_photo(
        bot,
        call.message.chat.id,
        (
            "<b>👤 Профиль</b>\n\n"
            f"<b>🆔 ID:</b> <code>{call.from_user.id}</code>\n"
            f"<b>🔷 Ключи:</b> {('∞' if status=='Активна' else user['keys_today'])}\n"
            f"<b>🎟 Подписка:</b> {status}"
        ),
        reply_markup=menu_kb()
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "ref")
async def on_ref(call: types.CallbackQuery):
    link = f"https://t.me/{BOT_USERNAME}?start={call.from_user.id}"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT referrals_count FROM users WHERE user_id=?", (call.from_user.id,))
        row = await cur.fetchone()
        count = row["referrals_count"] if row else 0
    await send_with_photo(
        bot,
        call.message.chat.id,
        (
            "<b>👥 Реферальная система</b>\n\n"
            f"<b>Рефералы:</b> {count}\n\n"
            f"<b>🔗 Реферальная ссылка:</b>\n<code>{link}</code>\n\n"
            "За один переход по рефке даётся <b>+1 ключ</b>.\n"
            f"🎁 Бонус за имя: Укажите <b>{BONUS_NAME_TEXT}</b> в имени — получите <b>+1 ключ</b> при первом запуске бота в день."
        ),
        reply_markup=menu_kb()
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "buy")
async def on_buy(call: types.CallbackQuery):
    await send_with_photo(
        bot,
        call.message.chat.id,
        (
            "<b>Оформление подписки</b>\n\n"
            "<b>💠 После покупки вы получаете:</b>\n"
            "• Полный доступ к письмам\n"
            "• Неограниченное время пользования ботом\n"
            "• Безлимитные отправки письма\n\n"
            "<b>💰 Цена:</b> 0.9$\n\n"
            "<b>Приобрести подписку —</b> <a href=\"https://t.me/bloodylofipro\">написать менеджеру</a>"
        ),
        reply_markup=menu_kb()
    )
    await call.answer()

# Отправка письма — запуск сценария
@dp.callback_query_handler(lambda c: c.data == "send")
async def on_send(call: types.CallbackQuery, state: FSMContext):
    user = await get_or_create_user(call.from_user.id)
    user = await reset_daily_if_needed(user)

    unlimited = user["subscribed"] or (UNLIMITED_FOR_WHITELIST and user["whitelisted"])    
    if not unlimited and user["keys_today"] <= 0:
        await send_with_photo(
            bot,
            call.message.chat.id,
            "<b>У вас нет ключей на сегодня.</b> Приобретите подписку или получите ключ по рефералке/бонусу имени.",
            reply_markup=menu_kb()
        )
        await call.answer()
        return

    await state.update_data(attachments=[])
    await SendMailStates.asking_target.set()
    await send_with_photo(
        bot,
        call.message.chat.id,
        "<b>Вы действительно хотите отправить письмо?</b>\n\nОтправьте <b>email получателя</b>.",
    )
    await call.answer()

# Шаги FSM
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

@dp.message_handler(lambda m: True, state=SendMailStates.asking_target, content_types=types.ContentTypes.TEXT)
async def fsm_target(message: types.Message, state: FSMContext):
    to_email = message.text.strip()
    if not EMAIL_REGEX.match(to_email):
        await send_with_photo(bot, message.chat.id, "Введите корректный email получателя.")
        return
    await state.update_data(to_email=to_email)
    await SendMailStates.next()
    await send_with_photo(bot, message.chat.id, "📧 <b>Введите тему письма:</b>")

@dp.message_handler(lambda m: True, state=SendMailStates.asking_subject, content_types=types.ContentTypes.TEXT)
async def fsm_subject(message: types.Message, state: FSMContext):
    subject = message.text.strip()
    await state.update_data(subject=subject)
    await SendMailStates.next()
    await send_with_photo(bot, message.chat.id, "📝 <b>Введите текст жалобы:</b>")

@dp.message_handler(lambda m: True, state=SendMailStates.asking_body, content_types=types.ContentTypes.TEXT)
async def fsm_body(message: types.Message, state: FSMContext):
    body = message.text.strip()
    await state.update_data(body=body)
    await SendMailStates.next()
    kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("Да", callback_data="add_photos_yes"),
        types.InlineKeyboardButton("Нет", callback_data="add_photos_no"),
    )
    await send_with_photo(bot, message.chat.id, "🖼 <b>Хотите добавить фотографии?</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ("add_photos_yes", "add_photos_no"), state=SendMailStates.asking_photos)
async def fsm_photos_choice(call: types.CallbackQuery, state: FSMContext):
    if call.data == "add_photos_yes":
        await SendMailStates.collecting_photos.set()
        kb = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("Готово", callback_data="photos_done")
        )
        await send_with_photo(bot, call.message.chat.id, "📎 <b>Пожалуйста, отправьте фотографии</b> (одно или несколько).\nКогда закончите, нажмите <b>Готово</b>.", reply_markup=kb)
    else:
        data = await state.get_data()
        await SendMailStates.confirming.set()
        await send_with_photo(
            bot,
            call.message.chat.id,
            (
                "<b>Подтверждение отправки</b>\n\n"
                f"Вы хотите отправить письмо на адрес: <code>{data.get('to_email')}</code>?"
            ),
            reply_markup=confirm_mail_kb()
        )
    await call.answer()

@dp.message_handler(content_types=types.ContentTypes.PHOTO, state=SendMailStates.collecting_photos)
async def fsm_collect_photos(message: types.Message, state: FSMContext):
    # Сохраняем фото во временный каталог ./tmp/
    os.makedirs("tmp", exist_ok=True)
    photos = message.photo
    if not photos:
        return
    biggest = photos[-1]
    file = await bot.get_file(biggest.file_id)
    dst = os.path.join("tmp", f"{message.from_user.id}_{biggest.file_unique_id}.jpg")
    await bot.download_file(file.file_path, dst)

    data = await state.get_data()
    atts = data.get("attachments", [])
    atts.append(dst)
    await state.update_data(attachments=atts)

    await send_with_photo(bot, message.chat.id, f"Добавлено фото. Всего вложений: <b>{len(atts)}</b>.")

@dp.callback_query_handler(lambda c: c.data == "photos_done", state=SendMailStates.collecting_photos)
async def fsm_photos_done(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await SendMailStates.confirming.set()
    await send_with_photo(
        bot,
        call.message.chat.id,
        (
            "<b>Подтверждение отправки</b>\n\n"
            f"Вы хотите отправить письмо на адрес: <code>{data.get('to_email')}</code>?"
        ),
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

    # confirm_send
    user = await get_or_create_user(call.from_user.id)
    user = await reset_daily_if_needed(user)
    unlimited = user["subscribed"] or (UNLIMITED_FOR_WHITELIST and user["whitelisted"])    

    data = await state.get_data()
    to_email = data.get("to_email")
    subject = data.get("subject", "(без темы)")
    body = data.get("body", "")
    attachments = data.get("attachments", [])

    login, pwd = await pick_smtp_for_today(call.from_user.id)
    ok, err = await send_email_via_smtp(login, pwd, to_email, subject, body, attachments)

    # лог
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mail_log (user_id, to_email, subject, body, smtp_used, day) VALUES (?, ?, ?, ?, ?, ?)",
            (call.from_user.id, to_email, subject, body, login, date.today().isoformat()),
        )
        if ok and (not unlimited):
            await db.execute("UPDATE users SET keys_today = keys_today - 1 WHERE user_id=?", (call.from_user.id,))
        await db.commit()

    await state.finish()

    if ok:
        text = (
            "<b>Готово!</b> Письмо отправлено.\n\n"
            f"<b>Кому:</b> <code>{to_email}</code>\n"
            f"<b>Тема:</b> {subject}\n"
            f"<b>SMTP:</b> <code>{login}</code>\n"
            f"<b>Вложений:</b> {len(attachments)}"
        )
        await send_with_photo(bot, call.message.chat.id, text, reply_markup=menu_kb())
    else:
        await send_with_photo(bot, call.message.chat.id, f"<b>Ошибка отправки:</b> {err}", reply_markup=menu_kb())

    await call.answer()

# ===================== АДМИН-КОМАНДЫ =====================

@dp.message_handler(commands=["sub_on"])  # включить подписку пользователю
async def cmd_sub_on(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int(message.get_args())
    except:
        await message.reply("/sub_on <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET subscribed=1 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Подписка включена: {uid}")

@dp.message_handler(commands=["sub_off"])  # выключить подписку пользователю
async def cmd_sub_off(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int(message.get_args())
    except:
        await message.reply("/sub_off <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET subscribed=0 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Подписка выключена: {uid}")

@dp.message_handler(commands=["wl_on"])   # добавить в вайтлист
async def cmd_wl_on(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int(message.get_args())
    except:
        await message.reply("/wl_on <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET whitelisted=1 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Вайтлист включён: {uid}")

@dp.message_handler(commands=["wl_off"])  # удалить из вайтлиста
async def cmd_wl_off(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int(message.get_args())
    except:
        await message.reply("/wl_off <user_id>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET whitelisted=0 WHERE user_id=?", (uid,))
        await db.commit()
    await message.reply(f"Вайтлист выключен: {uid}")

@dp.message_handler(commands=["keys"])    # выдать ключи пользователю
async def cmd_keys(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid, amount = map(int, message.get_args().split())
    except:
        await message.reply("/keys <user_id> <amount>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET keys_today = keys_today + ? WHERE user_id=?", (amount, uid))
        await db.commit()
    await message.reply(f"Выдано ключей: +{amount} для {uid}")

# ===================== ХЭНДЛЕР ПО УМОЛЧАНИЮ =====================
@dp.message_handler()
async def fallback(message: types.Message):
    await send_with_photo(bot, message.chat.id, "Нажмите кнопку ниже:", reply_markup=menu_kb())

# ===================== MAIN =====================
async def on_startup(dp: Dispatcher):
    await init_db()
    logger.info("DB ready")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
