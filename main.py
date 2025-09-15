from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon import TelegramClient, errors
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

# === НАСТРОЙКИ ===
TOKEN = "8077285651:AAEeKuRuxPVtmglrqmvC5AlIhmz8lKOLX9M"
ADMIN_ID = 595041765
ID_FILE = "id.txt"
INVITE_LINK = "https://t.me/+MlYM0ahLf6Y3ZGQ1"
API_ID = 29421966
API_HASH = "218fadbaffc01cc182577acfd63d6791"
SESSIONS = ["acc1.session", "acc2.session"]

# === AIROGRAM ===
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# === FSM ===
class Form(StatesGroup):
    q1 = State()
    q2 = State()
    osint_q1 = State()
    osint_q2 = State()
    osint_q3 = State()
    osint_q4 = State()
    q3 = State()
    q4 = State()

# === ВОПРОСЫ ===
questions = [
    {"text": "Готовы ли носить приписку клана?", "options": {"Да": 20, "Нет": 0}},
    {"text": "Кто вы в комьюнити?", "options": {"OSINT": 10, "Эдитор": 7, "Сносер": 7, "Соц инженер": 7, "Кодер": 7}},
    {"text": "Будете активным?", "options": {"Да": 20, "Нет": 0}},
    {"text": "Сколько в комьюнити?", "options": {"Больше года": 24, "1 год": 10, "Меньше года": 5}}
]

osint_questions = [
    {"text": "Какой из методов наиболее корректный для поиска человека по номеру телефона?",
     "options": {
         "Использовать OSINT-инструменты (GetContact, TrueCaller, пробив по мессенджерам)": 10,
         "Звонить и представляться другим человеком": -5,
         "Взломать SIM-карту или аккаунт мобильного оператора": -10,
         "Поиск по утечкам и кросс-поиск в социальных сетях": 7
     }},
    {"text": "OSINT — это:",
     "options": {
         "Методы анализа и сбора информации из открытых источников": 10,
         "Использование утечек паролей для доступа в аккаунты": -5,
         "Социальная инженерия и обман для получения данных": 0,
         "Инструмент для взлома закрытых баз данных": -10
     }},
    {"text": "Какой инструмент можно применить для поиска открытых камер, серверов и IoT-устройств?",
     "options": {"Shodan": 10, "Maltego": 7, "Excel": 1, "Photoshop": 0}},
    {"text": "Что стоит проверить в первую очередь при OSINT-анализе профиля человека?",
     "options": {
         "Фотографии и метаданные (EXIF)": 10,
         "Только список друзей": 3,
         "Пытаться угадать пароль": -10,
         "Игнорировать соцсети и смотреть только гос.реестры": 2
     }}
]

# === Работа с ID ===
def load_ids():
    if not os.path.exists(ID_FILE):
        return set()
    with open(ID_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_id(user_id):
    with open(ID_FILE, "a", encoding="utf-8") as f:
        f.write(str(user_id) + "\n")

# === Telethon invite по username ===
async def send_invite(username: str):
    for s in SESSIONS:
        try:
            async with TelegramClient(s, API_ID, API_HASH) as client:
                try:
                    result = await client(ResolveUsernameRequest(username[1:]))
                    entity = result.users[0]
                except IndexError:
                    logging.info(f"[FAIL] {s}: Пользователь {username} не найден через username")
                    continue
                await client.send_message(entity, f"✅ Добро пожаловать!\n{INVITE_LINK}")
                logging.info(f"[OK] Сообщение отправлено с {s} пользователю {username}")
                await asyncio.sleep(2)
                return True
        except errors.FloodWaitError as e:
            logging.warning(f"[LIMIT] {s} достиг лимита, ждём {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            continue
        except errors.ChatWriteForbiddenError:
            logging.info(f"[FAIL] {s} не может писать пользователю {username}")
            continue
        except Exception as e:
            logging.exception(f"[ERROR] {s}: {e}")
            continue
    logging.info(f"[FAIL] Не удалось отправить пользователю {username}")
    return False

# === Исправленная логика опроса (callback_data — индексы) ===
@dp.message_handler(commands="start")
async def start(message: types.Message, state: FSMContext):
    user_ids = load_ids()
    if str(message.from_user.id) in user_ids:
        await message.answer("❌ Вы уже проходили тест. Повторно пройти нельзя.")
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Да", callback_data="start_yes"))
    kb.add(InlineKeyboardButton("Нет", callback_data="start_no"))
    await message.answer(
        'Чтобы подать заявку на вступление в клан "Кровавое Господство" необходимо иметь юз. Хотите ли вы вступить?',
        reply_markup=kb
    )
    # начинаем с чистых данных (на всякий случай)
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "start_no")
async def process_no(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("Спасибо, что пришли. Ждём вас ещё.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "start_yes")
async def process_yes(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(score=0, osint=False)
    await ask_question(call.message, state, 0)

async def ask_question(message, state, index):
    kb = InlineKeyboardMarkup()
    options = list(questions[index]["options"].keys())
    for i, opt_text in enumerate(options):
        # callback: q{question_index}_{option_index}
        kb.add(InlineKeyboardButton(opt_text, callback_data=f"q{index}_{i}"))
    await message.answer(questions[index]["text"], reply_markup=kb)
    await state.set_state(getattr(Form, f"q{index+1}"))

@dp.callback_query_handler(lambda c: c.data.startswith("q"), state=[Form.q1, Form.q2, Form.q3, Form.q4])
async def process_answer(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        data = await state.get_data()
        score = data.get("score", 0)
        # формат callback: q{question_index}_{option_index}
        qpart, opt_idx_str = call.data.split("_", 1)
        q_idx = int(qpart[1:])  # 'q0' -> 0
        opt_idx = int(opt_idx_str)
        option_text = list(questions[q_idx]["options"].keys())[opt_idx]
        points = questions[q_idx]["options"][option_text]
        score += points
        await state.update_data(score=score, osint=data.get("osint", False))
        logging.info(f"User {call.from_user.id} answered Q{q_idx} -> '{option_text}' (+{points}), total={score}")

        # если на втором вопросе выбран OSINT — задаём OSINT-блок
        if q_idx == 1 and option_text == "OSINT":
            await ask_osint_question(call.message, state, 0)
            return

        # иначе идём дальше по основным вопросам
        if q_idx + 1 < len(questions):
            await ask_question(call.message, state, q_idx + 1)
        else:
            await finish_form(call, state)
    except Exception as e:
        logging.exception("Error in process_answer")
        # уведомим админа (опционально) и пользователя
        await bot.send_message(ADMIN_ID, f"Error in process_answer: {e}")
        await call.message.answer("Произошла ошибка при обработке ответа. Попробуйте ещё раз.")
        await state.finish()

async def ask_osint_question(message, state, index):
    kb = InlineKeyboardMarkup()
    options = list(osint_questions[index]["options"].keys())
    for i, opt_text in enumerate(options):
        kb.add(InlineKeyboardButton(opt_text, callback_data=f"osint_{index}_{i}"))
    await message.answer(osint_questions[index]["text"], reply_markup=kb)
    await state.set_state(getattr(Form, f"osint_q{index+1}"))

@dp.callback_query_handler(lambda c: c.data.startswith("osint_"), state=[Form.osint_q1, Form.osint_q2, Form.osint_q3, Form.osint_q4])
async def process_osint_answer(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        data = await state.get_data()
        score = data.get("score", 0)
        # формат callback: osint_{index}_{option_index}
        parts = call.data.split("_")
        # parts = ["osint", "{index}", "{option_index}"]
        idx = int(parts[1])
        opt_idx = int(parts[2])
        option_text = list(osint_questions[idx]["options"].keys())[opt_idx]
        points = osint_questions[idx]["options"][option_text]
        score += points
        await state.update_data(score=score, osint=True)
        logging.info(f"User {call.from_user.id} OSINT Q{idx} -> '{option_text}' (+{points}), total={score}")

        if idx + 1 < len(osint_questions):
            await ask_osint_question(call.message, state, idx + 1)
        else:
            # вернуться к основным вопросам, к третьему вопросу (index 2)
            await ask_question(call.message, state, 2)
    except Exception as e:
        logging.exception("Error in process_osint_answer")
        await bot.send_message(ADMIN_ID, f"Error in process_osint_answer: {e}")
        await call.message.answer("Произошла ошибка при обработке OSINT-ответа. Попробуйте ещё раз.")
        await state.finish()

async def finish_form(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    score = data.get("score", 0)
    user_id = call.from_user.id
    username = f"@{call.from_user.username}" if call.from_user.username else "Без username"
    save_id(user_id)
    if score >= 50:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Бот 1", url="https://t.me/BloodyDominationRobot"))
        kb.add(InlineKeyboardButton("Бот 2", url="https://t.me/BloodyDomination_Bot"))
        kb.add(InlineKeyboardButton("Отправить заявку", callback_data="send_application"))
        await call.message.answer(
            f"✅ Вы набрали {score}%!\nЧтобы отправить заявку на рассмотрение, необходимо добавить двух ботов в контакты. "
            f"Это позволит ботам отправить вам ссылку на вход в клан.",
            reply_markup=kb
        )
    else:
        await call.message.answer(f"❌ К сожалению, вы не прошли отбор. Вы набрали {score}%.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "send_application")
async def send_application(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    username = f"@{call.from_user.username}" if call.from_user.username else "Без username"
    await bot.send_message(
        ADMIN_ID,
        f"📋 Новая заявка!\nID пользователя: {user_id}\nUsername: {username}\nНужна проверка."
    )
    if username != "Без username":
        success = await send_invite(username)
        if success:
            await call.message.answer("✅ Ссылка на вступление отправлена в ЛС!")
        else:
            await call.message.answer("⚠️ Не удалось отправить ссылку. Попробуйте еще раз, или перешлите это сообщение в @BloodyLofiPro_bot.")
    else:
        await call.message.answer(
            "⚠️ У вас нет username, поэтому ссылка в ЛС не отправлена. "
            "Чтобы получить ссылку на вступление в клан, перешлите это сообщение @BloodyLofiPro_bot."
        )

# === Запуск ===
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
