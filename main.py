import logging
import asyncio
import dotenv
import os
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)

app = Flask(__name__)

dotenv.load_dotenv()

# ================== НАСТРОЙКИ ИЗ ENV ==================
TOKEN = os.getenv('TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '6617541179').split(',')))
TARGET_CHAT_ID = int(os.getenv('TARGET_CHAT_ID', '-1002390894383'))

# Тексты из env или значения по умолчанию
TEXTS = {
    "must_join": os.getenv('TEXT_MUST_JOIN', "⚠️ Для использования бота нужно состоять в нашем канале."),
    "start": os.getenv('TEXT_START', "📤 Привет! Отправь свой скриншот!.\n"
             "После модерации он будет опубликован."),
    "sent_for_review": os.getenv('TEXT_SENT_FOR_REVIEW', "⏳ Ваша работа отправлена на модерацию. Ожидайте решения!"),
    "approved": os.getenv('TEXT_APPROVED', "✅ Ваша работа одобрена и опубликована!"),
    "rejected": os.getenv('TEXT_REJECTED', "❌ Ваша работа отклонена модератором."),
}

# Хэштег для публикации
PUBLICATION_HASHTAG = os.getenv('PUBLICATION_HASHTAG', '#Ваши_скриншоты')

# ======================================================


@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", 5000))  # Render всегда задаёт PORT
    app.run(host="0.0.0.0", port=port)

# Данные заявок
pending_approvals = {}

# Проверка членства
async def is_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(TARGET_CHAT_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.error(f"Ошибка проверки участника: {e}")
        return False

# ==== Handlers ====
router = Router()

@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot):
    if not await is_member(bot, message.from_user.id):
        await message.answer(TEXTS["must_join"])
        return
    await message.answer(TEXTS["start"])


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    if not await is_member(bot, message.from_user.id):
        await message.answer(TEXTS["must_join"])
        return

    photo = message.photo[-1].file_id
    caption = message.caption or ""

    pending_id = message.message_id
    pending_approvals[pending_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "photo": photo,
        "caption": caption
    }

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{pending_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{pending_id}")
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo,
                caption=f"От: @{message.from_user.username or 'без ника'}\nКомментарий: {caption}",
                reply_markup=kb
            )
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")

    await message.answer(
        TEXTS["sent_for_review"],
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="/start")]],
            resize_keyboard=True
        )
    )


@router.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_"))
async def button_callback(query: CallbackQuery, bot: Bot):
    action, pending_id = query.data.split("_")
    pending_id = int(pending_id)

    data = pending_approvals.get(pending_id)
    if not data:
        await query.answer("⚠️ Заявка уже обработана", show_alert=True)
        return

    if query.from_user.id not in ADMIN_IDS:
        await query.answer("❌ У вас нет прав модератора!", show_alert=True)
        return

    if not await is_member(bot, data["user_id"]):
        await query.message.edit_caption("❌ Пользователь покинул группу!")
        del pending_approvals[pending_id]
        return

    if action == "approve":
        try:
            await bot.send_photo(
                chat_id=TARGET_CHAT_ID,
                photo=data["photo"],
                caption=f"{data['caption']}\n\n{PUBLICATION_HASHTAG}\n\nПрислать скриншот: @{(await bot.get_me()).username}"
            )
            await bot.send_message(data["user_id"], TEXTS["approved"])
            result_text = "✅ Решение принято: Одобрено"
        except Exception as e:
            logging.error(f"Ошибка публикации: {e}")
            await query.message.answer("⚠️ Не удалось опубликовать!")
            return
    else:
        try:
            await bot.send_message(data["user_id"], TEXTS["rejected"])
        except Exception as e:
            logging.error(f"Ошибка уведомления: {e}")
        result_text = "✅ Решение принято: Отклонено"

    del pending_approvals[pending_id]

    # пробуем обновить подпись к фото
    try:
        await query.message.edit_caption(result_text)
    except:
        # если фото без подписи → просто шлём новое сообщение
        await query.message.answer(result_text)


# ==== RUN ====
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":

    Thread(target=run_flask).start()
    
    asyncio.run(main())