from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, BotCommand
from aiogram import Bot

# Keyboards
def menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Регистрация 📝", callback_data="register")],
        [InlineKeyboardButton(text="Полезные ссылки 📚", callback_data="links")],
        [InlineKeyboardButton(text="Поиск пира в тг 🕵️‍♂️", callback_data="search")],
        [InlineKeyboardButton(text="Напомнить о проверке 🔔", callback_data="ping")],
        [InlineKeyboardButton(text="Кто в кампусе 👀", callback_data="campus")],
        [InlineKeyboardButton(text="Реферальная ссылка ✉️", callback_data="ref")]
    ])

def links_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="FAQ Школы 21 🧠", callback_data="faq")],
        [InlineKeyboardButton(text="Правила Школы 21 📖", callback_data="rules")],
        [InlineKeyboardButton(text="Правила Рокетчата 🚀", callback_data="rocketchat")],
        [InlineKeyboardButton(text="Гайд по стажировке 📘", callback_data="internship_guide")],
        [InlineKeyboardButton(text="Список специальностей 📕", callback_data="specialties")],
        [InlineKeyboardButton(text="GigaCode 🤖", callback_data="gigacode")],
        [InlineKeyboardButton(text="Правила онлайн проверок 🤼‍♂️", callback_data="p2p")],
        [InlineKeyboardButton(text="Выпуск школы 🎓", callback_data="final")],
        [InlineKeyboardButton(text="Как получить коины 💰", callback_data="coins")],
        [InlineKeyboardButton(text="Форма гостя 🎫", callback_data="guests")],
        [InlineKeyboardButton(text="Почта якутского кампуса", callback_data="email")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="back")]
    ])

def registration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Регистрация", callback_data="register")]
    ])

def re_registration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="re_register")],
        [InlineKeyboardButton(text="Нет", callback_data="cancel")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]]
    )

def broadcast_decision_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="Отмена", callback_data="broadcast_cancel")
        ]]
    )

# Functions
async def send_menu(message: Message):
    await message.answer('Выберите пункты меню:', reply_markup=menu_keyboard())

BANNED_USERS_FILE = "banned_users.txt"

def load_banned_users():
    try:
        with open(BANNED_USERS_FILE, "r") as file:
            return set(map(int, file.read().splitlines()))
    except FileNotFoundError:
        return set()

def save_banned_users(banned_users):
    with open(BANNED_USERS_FILE, "w") as file:
        file.write("\n".join(map(str, banned_users)))

def add_banned_user(user_id):
    banned_users = load_banned_users()
    banned_users.add(user_id)
    save_banned_users(banned_users)

def remove_banned_user(user_id):
    banned_users = load_banned_users()
    banned_users.discard(user_id)
    save_banned_users(banned_users)

def is_user_banned(user_id):
    return user_id in load_banned_users()

async def check_ban(user_id: int, message: Message = None, callback = None):
    if is_user_banned(user_id):
        if message:
            await message.answer("Вы забанены и не можете использовать бота 🚫")
        elif callback:
            await callback.message.answer("Вы забанены и не можете использовать бота 🚫")
            await callback.answer()
        return True
    return False

async def send_media_preview(media_message: Message, chat_id: int):
    if media_message.text:
        await media_message.bot.send_message(chat_id, media_message.text)
    elif media_message.photo:
        await media_message.bot.send_photo(chat_id, media_message.photo[-1].file_id, caption=media_message.caption)
    elif media_message.document:
        await media_message.bot.send_document(chat_id, media_message.document.file_id, caption=media_message.caption)
    elif media_message.video:
        await media_message.bot.send_video(chat_id, media_message.video.file_id, caption=media_message.caption)

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command='/links', description='Полезные ссылки 📚'),
        BotCommand(command='/search', description='Поиск пира в тг 🕵️‍♂️'),
        BotCommand(command='/ping', description='Напомнить о проверке 🔔'),
        BotCommand(command='/campus', description='Кто в кампусе 👀'),
        BotCommand(command='/ref', description='Реферальная ссылка ✉️'),
        BotCommand(command='/wanted', description='Отслеживать пира 🐈'),
    ]
    await bot.set_my_commands(main_menu_commands)