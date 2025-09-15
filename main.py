from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon import TelegramClient, errors
import os
import asyncio

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
    cast_choice = State()  # новое состояние для выбора каст
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
     "options": {"Использовать OSINT-инструменты (GetContact, TrueCaller, пробив по мессенджерам)": 10,
                 "Звонить и представляться другим человеком": -5,
                 "Взломать SIM-карту или аккаунт мобильного оператора": -10,
                 "Поиск по утечкам и кросс-поиск в социальных сетях": 7}},
    {"text": "OSINT — это:",
     "options": {"Методы анализа и сбора информации из открытых источников": 10,
                 "Использование утечек паролей для доступа в аккаунты": -5,
                 "Социальная инженерия и обман для получения данных": 0,
                 "Инструмент для взлома закрытых баз данных": -10}},
    {"text": "Какой инструмент можно применить для поиска открытых камер, серверов и IoT-устройств?",
     "options": {"Shodan": 10, "Maltego": 7, "Excel": 1, "Photoshop": 0}},
    {"text": "Что стоит проверить в первую очередь при OSINT-анализе профиля человека?",
     "options": {"Фотографии и метаданные (EXIF)": 10,
                 "Только список друзей": 3,
                 "Пытаться угадать пароль": -10,
                 "Игнорировать соцсети и смотреть только гос.реестры": 2}}
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
                    print(f"[FAIL] {s}: Пользователь {username} не найден через username")
                    continue

                await client.send_message(entity, f"✅ Добро пожаловать!\n{INVITE_LINK}")
                print(f"[OK] Сообщение отправлено с {s} пользователю {username}")
                await asyncio.sleep(2)
                return True

        except errors.FloodWaitError as e:
            print(f"[LIMIT] {s} достиг лимита, ждём {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            continue
        except errors.ChatWriteForbiddenError:
            print(f"[FAIL] {s} не может писать пользователю {username}")
            continue
        except Exception as e:
            print(f"[ERROR] {s}: {e}")
            continue

    print(f"[FAIL] Не удалось отправить пользователю {username}")
    return False


# === Хэндлеры ===
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
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "start_no")
async def process_no(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Спасибо, что пришли. Ждём вас ещё.")
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "start_yes")
async def process_yes(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(score=0, osint=False)
    await ask_question(call.message, state, 0)


async def ask_question(message, state, index):
    kb = InlineKeyboardMarkup()
    for option in questions[index]["options"]:
        kb.add(InlineKeyboardButton(option, callback_data=f"q{index}_{option}"))
    await message.answer(questions[index]["text"], reply_markup=kb)
    await state.set_state(getattr(Form, f"q{index+1}"))


@dp.callback_query_handler(lambda c: c.data.startswith("q"), state=[Form.q1, Form.q2, Form.q3, Form.q4])
async def process_answer(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx, option = call.data.split("_", 1)
    idx = int(idx[1:])
    points = questions[idx]["options"][option]
    data["score"] += points
    await state.update_data(score=data["score"], osint=data.get("osint", False))

    if idx == 1:
        await ask_cast_question(call.message, state)
        return


    if idx + 1 < len(questions):
        await ask_question(call.message, state, idx + 1)
    else:
        await finish_form(call, state)


async def ask_osint_question(message, state, index):
    kb = InlineKeyboardMarkup()
    options = list(osint_questions[index]["options"].keys())
    for i, option in enumerate(options):
        kb.add(InlineKeyboardButton(option, callback_data=f"osint_{index}_{i}"))
    await message.answer(osint_questions[index]["text"], reply_markup=kb)
    await state.set_state(getattr(Form, f"osint_q{index+1}"))


@dp.callback_query_handler(lambda c: c.data.startswith("osint_"),
                           state=[Form.osint_q1, Form.osint_q2, Form.osint_q3, Form.osint_q4])
async def process_osint_answer(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    _, idx, opt_idx = call.data.split("_")
    idx, opt_idx = int(idx), int(opt_idx)
    option_text = list(osint_questions[idx]["options"].keys())[opt_idx]
    points = osint_questions[idx]["options"][option_text]
    data["score"] += points
    await state.update_data(score=data["score"], osint=True)

    if idx + 1 < len(osint_questions):
        await ask_osint_question(call.message, state, idx + 1)
    else:
        await ask_question(call.message, state, 2)

async def ask_cast_question(message, state):
    kb = InlineKeyboardMarkup()
    casts = ["OSINT", "Эдитор", "Сносер", "Соц инженер", "Кодер"]
    for c in casts:
        kb.add(InlineKeyboardButton(c, callback_data=f"cast_{c}"))
    await message.answer("Выберите вашу касту:", reply_markup=kb)
    await state.set_state(Form.cast_choice) 


async def finish_form(call: types.CallbackQuery, state: FSMContext):
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

@dp.callback_query_handler(lambda c: c.data.startswith("cast_"), state=Form.cast_choice)
async def process_cast(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    cast = call.data.split("_")[1]
    
    # Сохраняем выбранную касту
    await state.update_data(selected_cast=cast)
    
    if cast == "OSINT":
        # Если OSINT — задаем OSINT-вопросы
        await ask_osint_question(call.message, state, 0)
    else:
        # Иначе продолжаем обычные вопросы
        await ask_question(call.message, state, 2)

@dp.callback_query_handler(lambda c: c.data == "send_application")
async def send_application(call: types.CallbackQuery):
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
            "⚠️ У вас нет username, поэтому ссылка в ЛС не отправлена. Чтобы получить ссылку на вступление в клан, перешлийте это сообщение @BloodyLofiPro_bot."
        )


# === Запуск ===
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
