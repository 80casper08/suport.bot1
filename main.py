import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Flask сервер для пінгу
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот працює ✅"

@app.route("/ping")
def ping():
    return "OK", 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# Завантаження токена
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class Form(StatesGroup):
    waiting_for_question = State()

menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📞 Зв’язатися з оператором")],
        [KeyboardButton(text="❓ Часті запитання")],
        [KeyboardButton(text="📝 Залишити заявку")],
    ],
    resize_keyboard=True
)

@dp.message(F.command("start"))
async def start(message: Message):
    await message.answer("👋 Привіт! Я бот підтримки. Чим можу допомогти?", reply_markup=menu)


@dp.message(F.text == "📞 Зв’язатися з оператором")
async def contact_operator(message: Message):
    await message.answer("Очікуйте, оператор незабаром з вами зв’яжеться.")
    await bot.send_message(ADMIN_ID, f"🔔 Користувач @{message.from_user.username} хоче зв’язатись з оператором.")

@dp.message(F.text == "❓ Часті запитання")
async def faq(message: Message):
    await message.answer("Ось часті питання:\n\n1. Як оформити замовлення?\n2. Як скасувати заявку?\n3. Які умови доставки?")

@dp.message(F.text == "📝 Залишити заявку")
async def ask_question(message: Message, state: FSMContext):
    await message.answer("Напишіть своє питання, і ми відповімо якнайшвидше:")
    await state.set_state(Form.waiting_for_question)

@dp.message(Form.waiting_for_question)
async def receive_question(message: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📨 Нова заявка від @{message.from_user.username}:\n{message.text}")
    await message.answer("✅ Дякуємо! Ми скоро з вами зв’яжемось.", reply_markup=menu)
    await state.clear()
@dp.message()
async def get_chat_id(message: types.Message):
    await message.answer(f"Chat ID: {message.chat.id}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
