import asyncio
import os
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask
from threading import Thread
from dotenv import load_dotenv
from questions import op_questions, general_questions, lean_questions, qr_questions
from hard_questions import questions as hard_questions

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/ping")
def ping():
    return "OK", 200

Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

load_dotenv()
TOKEN = os.getenv("TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

ADMIN_IDS = [710633503]
GROUP_ID = -1002786428793  
PING_INTERVAL = 6 * 60 * 60 


def is_blocked(user_id: int) -> bool:
    if not os.path.exists("blocked.txt"):
        return False
    with open("blocked.txt", "r", encoding="utf-8") as f:
        return str(user_id) in f.read().splitlines()


# ---------- Pending users ----------
def add_pending(user_id: int, full_name: str, username: str):
    """Додає користувача в pending.txt у форматі user_id|full_name|username"""
    entry = f"{user_id}|{full_name}|{username}"
    if not os.path.exists("pending.txt"):
        open("pending.txt", "w").close()

    with open("pending.txt", "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    if entry not in lines:
        with open("pending.txt", "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def is_pending(user_id: int) -> bool:
    """Перевіряє чи користувач в pending"""
    if not os.path.exists("pending.txt"):
        return False
    with open("pending.txt", "r", encoding="utf-8") as f:
        for line in f.read().splitlines():
            if line.startswith(str(user_id) + "|"):
                return True
    return False


def remove_pending(user_id: int):
    """Видаляє користувача з pending"""
    if not os.path.exists("pending.txt"):
        return

    with open("pending.txt", "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    with open("pending.txt", "w", encoding="utf-8") as f:
        for line in lines:
            if not line.startswith(str(user_id) + "|"):
                f.write(line + "\n")
# ----- Перевірка доступу -----
def has_access(user_id: int) -> bool:
    """Перевіряє, чи користувач дозволений (approved)"""
    if is_blocked(user_id):
        return False
    if not os.path.exists("approved.txt"):
        return False
    with open("approved.txt", "r", encoding="utf-8") as f:
        approved = f.read().splitlines()
    return str(user_id) in approved

# Запис користувача у users.txt без дублікатів
def save_user_if_new(user: types.User, section: str):
    full_name = user.full_name
    username = f"@{user.username}" if user.username else "-"

    if not os.path.exists("users.txt"):
        with open("users.txt", "w", encoding="utf-8") as uf:
            uf.write("")

    with open("users.txt", "a+", encoding="utf-8") as uf:
        uf.seek(0)
        existing = uf.read()
        entry = f"{user.id} | {full_name} | {username} | {section}\n"
        if entry.strip() not in [line.strip() for line in existing.strip().split("\n") if line.strip()]:
            uf.write(entry)

# Запис події до logs.txt + повідомлення адміну
def log_result(user: types.User, section: str, score: int = None, started: bool = False):
    full_name = f"{user.full_name}"
    username = f"@{user.username}" if user.username else "-"

    with open("logs.txt", "a", encoding="utf-8") as f:
        if started:
            f.write(f"{full_name} | {username} | {user.id} | Розпочав: {section}\n")
        else:
            f.write(f"{full_name} | {username} | {user.id} | Завершив: {section} | {score}%\n")

    # 🔕 Якщо це адмін — не надсилаємо повідомлення
    if user.id in ADMIN_IDS:
        return

    text = (
        f"👤 {full_name} ({username})\n"
        f"🆔 ID: {user.id}\n"
        f"🧪 {'Почав' if started else 'Закінчив'} розділ: {section}"
    )
    if score is not None:
        text += f"\n📊 Результат: {score}%"

    for admin_id in ADMIN_IDS:
        asyncio.create_task(bot.send_message(admin_id, text))


class QuizState(StatesGroup):
    category = State()
    question_index = State()
    selected_options = State()
    temp_selected = State()

class HardTestState(StatesGroup):
    question_index = State()
    selected_options = State()
    temp_selected = State()
    current_message_id = State()
    current_options = State()

sections = {
    "👮ОП👮": op_questions,
    "🎭Загальні🎭": general_questions,
    "🗿LEAN🗿": lean_questions,
    "🎲QR🎲": qr_questions
}

def main_keyboard(user_id: int):
    """
    Повертає клавіатуру для користувача.
    Адмін бачить кнопку ℹ️ Інфо, звичайний користувач – тільки розділи та Hard Test.
    """
    # Базові кнопки для всіх
    buttons = [types.KeyboardButton(text=section) for section in sections]
    buttons.append(types.KeyboardButton(text="👀Hard Test👀"))

    # Кнопка тільки для адмінів
    if user_id in ADMIN_IDS:
        buttons.append(types.KeyboardButton(text="ℹ️ Інфо"))

    # Формуємо ReplyKeyboardMarkup
    return types.ReplyKeyboardMarkup(
        keyboard=[[btn] for btn in buttons],
        resize_keyboard=True
    )

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    user = message.from_user
    user_id = user.id
    full_name = user.full_name
    username = f"@{user.username}" if user.username else "-"

    # 🔒 якщо користувач заблокований — нічого не показуємо
    if is_blocked(user_id):
        await message.answer("🚫Бот тимчасово не працює🔐")
        return

    # логування натискання /start
    with open("logs.txt", "a", encoding="utf-8") as f:
        f.write(f"{full_name} | {username} | {user_id} | Натиснув /start\n")

    # створюємо approved.txt, якщо його нема
    if not os.path.exists("approved.txt"):
        open("approved.txt", "w").close()

    # читаємо список дозволених користувачів
    with open("approved.txt", "r", encoding="utf-8") as f:
        approved = f.read().splitlines()

    # якщо користувач не дозволений
    if str(user_id) not in approved:
        if not is_pending(user_id):
            add_pending(user_id, full_name, username)  # додаємо в pending

            # кнопки для підтвердження адміну
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Дозволити", callback_data=f"approve_{user_id}")],
                    [InlineKeyboardButton(text="❌ Заборонити", callback_data=f"deny_{user_id}")]
                ]
            )

            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"👤 Новий користувач очікує підтвердження:\n\n"
                    f"👤 {full_name}\n"
                    f"🔗 {username}\n"
                    f"🆔 {user_id}",
                    reply_markup=keyboard
                )
        return  # користувачу нічого не показуємо

    # якщо користувач дозволений — показуємо меню
    await message.answer(
        "Вибери розділ для тесту:",
        reply_markup=main_keyboard(user_id)  # тут main_keyboard враховує чи адмін
    )


@dp.message(F.text.in_(sections.keys()))
async def start_quiz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # Перевіряємо доступ
    if not has_access(user_id):
        await message.answer("🚫Бот тимчасово непрацює🔐")
        return

    if is_blocked(user_id):
        await message.answer("🚫Бот тимчасово непрацює🔐")
        return

    category = message.text
    questions = sections[category]
    log_result(message.from_user, category, started=True)
    await state.set_state(QuizState.category)
    await state.update_data(
        category=category,
        question_index=0,
        selected_options=[],
        wrong_answers=[],
        questions=questions
    )
    await send_question(message, state)

async def send_question(message_or_callback, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    index = data["question_index"]

    if index >= len(questions):
        correct = 0
        wrongs = []
        for i, q in enumerate(questions):
            correct_answers = {j for j, (_, is_correct) in enumerate(q["options"]) if is_correct}
            user_selected = set(data["selected_options"][i])
            if correct_answers == user_selected:
                correct += 1
            else:
                wrongs.append({
                    "question": q["text"],
                    "options": q["options"],
                    "selected": list(user_selected),
                    "correct": list(correct_answers)
                })
        await state.update_data(wrong_answers=wrongs)
        percent = round(correct / len(questions) * 100)
        grade = "❌ Погано"
        if percent >= 90:
            grade = "💯 Відмінно"
        elif percent >= 70:
            grade = "👍 Добре"
        elif percent >= 50:
            grade = "👌 Задовільно"

        result = (
            "📊 *Результат тесту:*\n\n"
            f"✅ *Правильних відповідей:* {correct} з {len(questions)}\n"
            f"📈 *Успішність:* {percent}%\n"
            f"🏆 *Оцінка:* {grade}"
        )

        log_result(message_or_callback.from_user, data["category"], percent)
        save_user_if_new(message_or_callback.from_user, data["category"])

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Пройти ще раз", callback_data="restart")],
            [InlineKeyboardButton(text="📋 Детальна інформація", callback_data="details")]
        ])
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.answer(result, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message_or_callback.answer(result, reply_markup=keyboard, parse_mode="Markdown")
        return

    question = questions[index]
    total = len(questions)
    text = f"📌 {index + 1}/{total}\n\n{question['text']}"
    options = list(enumerate(question["options"]))
    random.shuffle(options)

    selected = data.get("temp_selected", set())
    buttons = [[InlineKeyboardButton(text=("✅ " if i in selected else "◻️ ") + label, callback_data=f"opt_{i}")] for i, (label, _) in options]
    buttons.append([InlineKeyboardButton(text="✅ Підтвердити", callback_data="confirm")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=keyboard)
    else:
        await message_or_callback.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "confirm")
async def confirm_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("temp_selected", set())
    selected_options = data.get("selected_options", [])
    selected_options.append(list(selected))
    await state.update_data(selected_options=selected_options, question_index=data["question_index"] + 1, temp_selected=set())
    await send_question(callback, state)

@dp.callback_query(F.data.startswith("opt_"))
async def toggle_option(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[1])
    data = await state.get_data()
    selected = data.get("temp_selected", set())
    selected.symmetric_difference_update({index})
    await state.update_data(temp_selected=selected)
    await send_question(callback, state)

@dp.callback_query(F.data == "details")
async def show_details(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    wrongs = data.get("wrong_answers", [])
    if not wrongs:
        await callback.message.answer("✅ Усі відповіді правильні!")
        return
    for item in wrongs:
        text = f"❌ *{item['question']}*\n"
        for idx, (opt_text, _) in enumerate(item["options"]):
            mark = "☑️" if idx in item["selected"] else "🔘"
            text += f"{mark} {opt_text}\n"
        selected_text = [item["options"][i][0] for i in item["selected"]] if item["selected"] else ["—"]
        correct_text = [item["options"][i][0] for i in item["correct"]]
        text += f"\n_Твоя відповідь:_ {', '.join(selected_text)}"
        text += f"\n_Правильна відповідь:_ {', '.join(correct_text)}"
        await callback.message.answer(text, parse_mode="Markdown")

@dp.callback_query(F.data == "restart")
async def restart_quiz(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")

    if not category or category not in sections:
        await state.clear()
        await callback.message.answer(
            "⚠️ Виникла помилка. Оберіть розділ заново:",
            reply_markup=main_keyboard(callback.from_user.id)
        )
        return

    questions = sections[category]  # або [:] якщо хочеш всі питання
    await state.clear()
    await state.set_state(QuizState.category)
    await state.update_data(
        category=category,
        question_index=0,
        selected_options=[],
        wrong_answers=[],
        questions=questions
    )
    await send_question(callback, state)


# ---------- HARD TEST ----------
@dp.message(F.text == "👀Hard Test👀")
async def start_hard_test(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # 🔒 Перевірка доступу
    if not has_access(user_id):
        await message.answer("🚫Бот тимчасово непрацює🔐")
        return

    if is_blocked(user_id):
        await message.answer("🚫Бот тимчасово непрацює🔐")
        return

    log_result(message.from_user, "👀Hard Test👀", started=True)
    await state.clear()
    await state.set_state(HardTestState.question_index)

    shuffled_questions = hard_questions.copy()
    random.shuffle(shuffled_questions)

    await state.update_data(
        question_index=0,
        selected_options=[],
        temp_selected=set(),
        questions=shuffled_questions
    )
    await send_hard_question(message.chat.id, state)


async def send_hard_question(chat_id, state: FSMContext):
    data = await state.get_data()
    index = data["question_index"]
    questions = data["questions"]

    if index >= len(questions):
        # Кінець тесту
        selected_all = data.get("selected_options", [])
        correct = 0
        for i, q in enumerate(questions):
            correct_indices = {j for j, (_, ok) in enumerate(q["options"]) if ok}
            user_selected = set(selected_all[i])
            if correct_indices == user_selected:
                correct += 1
        percent = round(correct / len(questions) * 100)

        user = await bot.get_chat(chat_id)
        log_result(user, "👀Hard Test👀", percent)
        save_user_if_new(user, "👀Hard Test👀")

        await bot.send_message(
            chat_id,
            text=f"📊 Результат тесту: {correct} з {len(questions)}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Детальна інформація", callback_data="hard_details")],
                    [InlineKeyboardButton(text="🔄 Пройти ще раз", callback_data="hard_retry")]
                ]
            )
        )
        return

    # Поточне питання
    question = questions[index]
    total = len(questions)
    text = f"📌 {index + 1}/{total}\n\n{question['text']}"
    options = list(enumerate(question["options"]))
    random.shuffle(options)
    await state.update_data(current_options=options, temp_selected=set())

    buttons = [[
        InlineKeyboardButton(
            text="◻️ " + opt_text,
            callback_data=f"hard_opt_{i}"
        )
    ] for i, (opt_text, _) in options]
    buttons.append([InlineKeyboardButton(text="✅ Підтвердити", callback_data="hard_confirm")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Видаляємо попереднє повідомлення
    previous_id = data.get("current_message_id")
    if previous_id:
        try:
            await bot.delete_message(chat_id, previous_id)
        except:
            pass

    # Відправляємо питання (з фото або без)
    if "image" in question and question["image"]:
        msg = await bot.send_photo(
            chat_id,
            photo=question["image"],
            caption=text,
            reply_markup=keyboard
        )
    else:
        msg = await bot.send_message(
            chat_id,
            text=text,
            reply_markup=keyboard
        )

    # Зберігаємо id поточного повідомлення
    await state.update_data(current_message_id=msg.message_id)


@dp.callback_query(F.data.startswith("hard_opt_"))
async def toggle_hard_option(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    selected = data.get("temp_selected", set())
    selected.symmetric_difference_update({index})
    await state.update_data(temp_selected=selected)

    options = data["current_options"]
    buttons = [[
        InlineKeyboardButton(
            text=("✅ " if i in selected else "◻️ ") + text,
            callback_data=f"hard_opt_{i}"
        )
    ] for i, (text, _) in options]
    buttons.append([InlineKeyboardButton(text="✅Підтвердити", callback_data="hard_confirm")])
    await bot.edit_message_reply_markup(
        chat_id=callback.message.chat.id,
        message_id=data["current_message_id"],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
@dp.callback_query(F.data == "hard_confirm")
async def confirm_hard_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("temp_selected", set())
    selected_all = data.get("selected_options", [])
    selected_all.append(list(selected))
    await state.update_data(selected_options=selected_all, question_index=data["question_index"] + 1, temp_selected=set())
    await send_hard_question(callback.message.chat.id, state)

@dp.callback_query(F.data == "hard_retry")
async def restart_hard_quiz(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    shuffled_questions = hard_questions.copy()
    random.shuffle(shuffled_questions)

    await state.set_state(HardTestState.question_index)
    await state.update_data(
        question_index=0,
        selected_options=[],
        temp_selected=set(),
        questions=shuffled_questions
    )

    await send_hard_question(callback.message.chat.id, state)

@dp.callback_query(F.data == "hard_details")
async def show_hard_details(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_all = data.get("selected_options", [])
    questions = data.get("questions", [])  # ✅ ті самі питання, що були в тесті

    blocks = []

    for i, q in enumerate(questions):
        correct = {j for j, (_, ok) in enumerate(q["options"]) if ok}
        user = set(selected_all[i]) if i < len(selected_all) else set()

        if correct != user:
            user_ans = [q["options"][j][0] for j in user]
            correct_ans = [q["options"][j][0] for j in correct]

            blocks.append(
                f"❓ *{q['text']}*\n"
                f"🔴 Ти вибрав: {', '.join(user_ans) if user_ans else 'нічого'}\n"
                f"✅ Правильно: {', '.join(correct_ans)}"
            )

    if not blocks:
        await callback.message.answer("🥳 Всі відповіді правильні!")
    else:
        for block in blocks:
            await callback.message.answer(block, parse_mode="Markdown")

    # 🔒 опціонально — завершуємо FSM
    await state.clear()

# 🛠 Обробка кнопок адмін-панелі
@dp.callback_query(F.data == "admin_users")
async def show_users_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    if not os.path.exists("users.txt"):
        await callback.message.answer("Жоден користувач ще не проходив тести.")
        return
    with open("users.txt", "r", encoding="utf-8") as f:
        text = f.read()
    await callback.message.answer(f"📋 Користувачі:\n\n{text}")


@dp.callback_query(F.data == "admin_stats")
async def all_stats_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
       return

    message = callback.message
    await callback.answer()  # закриває "loading"
    
    if not os.path.exists("logs.txt"):
        await message.answer("❗ Ще немає жодного проходження.")
        return

    stats = {}
    with open("logs.txt", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) < 5 or "Завершив" not in parts[3]:
                continue
            name = parts[0].strip()
            username = parts[1].strip()
            user_id = parts[2].strip()
            section = parts[3].replace("Завершив:", "").strip()
            score_str = parts[4].strip().replace("%", "")
            try:
                score = int(score_str)
            except:
                continue

            key = f"{name} ({username})"
            if key not in stats:
                stats[key] = {}
            if section not in stats[key]:
                stats[key][section] = []
            stats[key][section].append(score)

    if not stats:
        await message.answer("📭 Статистика порожня.")
        return

    result = "📊 *Статистика всіх користувачів:*\n\n"
    for user, sections in stats.items():
        result += f"👤 *{user}*\n"
        for sec, scores in sections.items():
            avg = round(sum(scores) / len(scores))
            count = len(scores)
            result += f"— {sec}: {avg}% (📈 {count} проходжень)\n"
        result += "\n"

    for chunk in [result[i:i+4000] for i in range(0, len(result), 4000)]:
        await message.answer(chunk, parse_mode="Markdown")


@dp.callback_query(F.data == "admin_blocked_list")
async def show_blocked_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
       return
    if not os.path.exists("blocked.txt"):
        await callback.message.answer("📁 Файл `blocked.txt` ще не створений.")
        return
    with open("blocked.txt", "r", encoding="utf-8") as f:
        lines = f.read().strip()
    if not lines:
        await callback.message.answer("✅ Немає заблокованих користувачів.")
    else:
        await callback.message.answer(f"⛔ Заблоковані користувачі:\n\n{lines}")

@dp.callback_query(F.data == "admin_pending")
async def show_pending(callback: CallbackQuery):

    if callback.from_user.id not in ADMIN_IDS:
        return

    if not os.path.exists("pending.txt"):
        await callback.message.answer("⏳ Немає користувачів які очікують підтвердження.")
        return

    with open("pending.txt", "r", encoding="utf-8") as f:
        users = f.read().splitlines()

    if not users:
        await callback.message.answer("✅ Ніхто не очікує підтвердження.")
        return

    for user_id in users:

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Дозволити", callback_data=f"approve_{user_id}")],
                [InlineKeyboardButton(text="❌ Заборонити", callback_data=f"deny_{user_id}")]
            ]
        )

        await callback.message.answer(
            f"👤 Користувач ID: {user_id}",
            reply_markup=keyboard
        )
@dp.callback_query(F.data == "admin_block")
async def ask_block_user(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("Введи ID користувача, якого потрібно ⛔ *заблокувати*:\n\nНапиши: `/blockID`", parse_mode="Markdown")


@dp.callback_query(F.data == "admin_unblock")
async def ask_unblock_user(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("Введи ID користувача, якого потрібно ✅ *розблокувати*:\n\nНапиши: `/unblockID`", parse_mode="Markdown")
# ---------- Підтвердження користувачів ----------
@dp.callback_query(F.data.startswith("approve_"))
async def approve_user(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    user_id = callback.data.split("_")[1]

    # Додаємо користувача в approved.txt
    if not os.path.exists("approved.txt"):
        open("approved.txt", "w").close()
    with open("approved.txt", "r", encoding="utf-8") as f:
        approved = f.read().splitlines()
    if user_id not in approved:
        with open("approved.txt", "a", encoding="utf-8") as f:
            f.write(user_id + "\n")

    # Видаляємо pending
    remove_pending(user_id)

    # Прибираємо кнопки у повідомленні адміну
    await callback.message.edit_reply_markup()

    # Підтвердження адміну
    await callback.answer("✅ Користувача дозволено", show_alert=True)

    # 🔹 Надсилаємо меню користувачу одразу
    try:
        user_id_int = int(user_id)
        keyboard = main_keyboard(user_id_int)
        await bot.send_message(
            chat_id=user_id_int,
            text="Виберіть розділ для тесту:",
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"❗ Не вдалося надіслати меню користувачу {user_id}: {e}")

@dp.callback_query(F.data.startswith("deny_"))
async def deny_user(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    user_id = callback.data.split("_")[1]

    if not is_blocked(user_id):
        with open("blocked.txt", "a", encoding="utf-8") as f:
            f.write(user_id + "\n")

    remove_pending(user_id)
    await callback.message.edit_reply_markup()  # видаляємо кнопки
    await callback.answer("❌ Користувача заборонено", show_alert=True)
@dp.message(F.text == "/my")
async def my_stats(message: types.Message):
    user_id = str(message.from_user.id)
    full_name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "-"

    # 🔹 Логування у файл
    with open("logs.txt", "a", encoding="utf-8") as f:
        f.write(f"{full_name} | {username} | {user_id} | Переглянув статистику (/my)\n")

    # 🔹 Повідомлення адміну
    for admin_id in ADMIN_IDS:
       await bot.send_message(admin_id, f"👁 {full_name} ({username}) переглянув свою статистику")

    # 🔸 Якщо логів ще немає
    if not os.path.exists("logs.txt"):
        await message.answer("📭 Ви ще не проходили жодного тесту.")
        return

    # 🔍 Збір результатів з логів
    section_scores = {}
    with open("logs.txt", "r", encoding="utf-8") as f:
        for line in f:
            if f"{user_id}" in line and "Завершив" in line and "|" in line:
                parts = line.strip().split("|")
                if len(parts) >= 5:
                    section = parts[3].replace("Завершив:", "").strip()
                    score_part = parts[4].strip()
                    try:
                        score = int(score_part.replace("%", "").strip())
                        if section not in section_scores:
                            section_scores[section] = []
                        section_scores[section].append(score)
                    except:
                        continue

    if not section_scores:
        await message.answer("📭 Ви ще не завершили жодного тесту.")
        return

    # 🧾 Формування відповіді
    total_sum = 0
    total_count = 0
    text = f"📊 *Ваша статистика, {full_name}:*\n\n"
    for section, scores in section_scores.items():
        avg = round(sum(scores) / len(scores))
        count = len(scores)
        text += f"{section}: {avg}% (📈 {count} разів)\n"
        total_sum += sum(scores)
        total_count += count

    total_avg = round(total_sum / total_count) if total_count > 0 else 0
    text += f"\n🏁 *Загальний середній результат:* {total_avg}%"

    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text.startswith("/block"))
async def block_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    user_id = message.text.replace("/block", "").strip()
    if not user_id.isdigit():
        await message.answer("❗ Формат: /blockUSER_ID (без пробілу)")
        return

    with open("blocked.txt", "a+", encoding="utf-8") as f:
        f.seek(0)
        blocked = f.read().splitlines()

        if user_id not in blocked:
            f.write(user_id + "\n")
            try:
                user = await bot.get_chat(user_id)
                name = f"{user.full_name} (@{user.username})" if user.username else user.full_name
            except:
                name = f"ID: {user_id}"
            await message.answer(f"⛔ Заблоковано: {name}\n/unblock{user_id}")
        else:
            await message.answer(f"⚠️ Користувач {user_id} вже заблокований.")


@dp.message(F.text.startswith("/unblock"))
async def unblock_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    user_id = message.text.replace("/unblock", "").strip()
    if not user_id.isdigit():
        await message.answer("❗ Формат: /unblockUSER_ID (без пробілу)")
        return

    if not os.path.exists("blocked.txt"):
        await message.answer("📂 Файл блокування ще не створено.")
        return

    with open("blocked.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open("blocked.txt", "w", encoding="utf-8") as f:
        f.writelines([line for line in lines if line.strip() != user_id])

    try:
        user = await bot.get_chat(user_id)
        name = f"{user.full_name} (@{user.username})" if user.username else user.full_name
    except:
        name = f"ID: {user_id}"

    await message.answer(f"✅ Розблоковано: {name}\n/block{user_id}")


@dp.message(F.text == "/all")
async def all_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    if not os.path.exists("logs.txt"):
        await message.answer("❗ Ще немає жодного проходження.")
        return

    stats = {}
    with open("logs.txt", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) < 5 or "Завершив" not in parts[3]:
                continue
            name = parts[0].strip()
            username = parts[1].strip()
            user_id = parts[2].strip()
            section = parts[3].replace("Завершив:", "").strip()
            score_str = parts[4].strip().replace("%", "")
            try:
                score = int(score_str)
            except:
                continue

            key = f"{name} ({username})"
            if key not in stats:
                stats[key] = {}
            if section not in stats[key]:
                stats[key][section] = []
            stats[key][section].append(score)

    if not stats:
        await message.answer("📭 Статистика порожня.")
        return

    # Формуємо текст
    result = "📊 *Статистика всіх користувачів:*\n\n"
    for user, sections in stats.items():
        result += f"👤 *{user}*\n"
        for sec, scores in sections.items():
            avg = round(sum(scores) / len(scores))
            count = len(scores)
            result += f"— {sec}: {avg}% (📈 {count} проходжень)\n"
        result += "\n"

    # Розбиваємо на частини, якщо довге
    for chunk in [result[i:i+4000] for i in range(0, len(result), 4000)]:
        await message.answer(chunk, parse_mode="Markdown")


@dp.message(F.text == "ℹ️ Інфо")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Користувачі", callback_data="admin_users")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⏳ Очікують підтвердження", callback_data="admin_pending")],
        [InlineKeyboardButton(text="⛔ Заблоковані", callback_data="admin_blocked_list")],
        [InlineKeyboardButton(text="🚫 Заблокувати", callback_data="admin_block")],
        [InlineKeyboardButton(text="✅ Розблокувати", callback_data="admin_unblock")]
    ])

    await message.answer("🛠 Адмін-панель:", reply_markup=keyboard)
         
async def send_ping():
    while True:
        try:
            await bot.send_message(GROUP_ID, "✅ Я працююю! ✅")
        except Exception as e:
            print(f"❗ Помилка надсилання пінгу: {e}")
        await asyncio.sleep(PING_INTERVAL)


async def main():
    asyncio.create_task(send_ping())  # 🚀 Запускає пінг-функцію
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
