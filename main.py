# import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
import requests
import re
from html import escape
import os
from dotenv import load_dotenv

load_dotenv()  # Загружаем переменные из .env

TOKEN = os.getenv("TOKEN")
MAIN_ADMIN_ID = os.getenv("MAIN_ADMIN_ID")
login_token = os.getenv("login_token")
password_token = os.getenv("password_token")
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS")
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# Инициализация Google Sheets API
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_KEY).sheet1

bot = Bot(token=TOKEN)
dp = Dispatcher()

column_index = {}

class Form(StatesGroup):
    login = State()
    name = State()
    search = State()
    ping = State() 
    waiting_for_broadcast = State()
    waiting_for_broadcast_confirm = State()
    wanted = State()

# Функции для работы с Google Sheets
async def is_user_in_db(user_id: int):
    records = sheet.get_all_records()
    for record in records:
        if record['user_id'] == user_id:
            return (record['login'], record['name'])
    return None

async def add_user_to_db(user_id: int, login: str, name: str, telegram_username: str):
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    
    for i, record in enumerate(records, start=2):
        if record['user_id'] == user_id:
            sheet.update_cell(i, headers.index('login') + 1, login)
            sheet.update_cell(i, headers.index('name') + 1, name)
            sheet.update_cell(i, headers.index('telegram_username') + 1, telegram_username)
            return
    
    new_row = ['' for _ in headers]
    new_row[headers.index('user_id')] = user_id
    new_row[headers.index('login')] = login
    new_row[headers.index('name')] = name
    new_row[headers.index('telegram_username')] = telegram_username
    
    sheet.append_row(new_row)

async def find_user_by_login(login: str):
    records = sheet.get_all_records()
    for record in records:
        if record['login'] == login:
            return (record['user_id'], record['name'], record['telegram_username'])
    return None

async def get_users():
    records = sheet.get_all_records()
    return [record['user_id'] for record in records]

async def get_user_record(user_id: int) -> dict:
    """Возвращает запись пользователя как словарь или None."""
    all_values = sheet.get_all_values()
    if not all_values:
        return None
    headers = all_values[0]
    for row in all_values[1:]:
        if len(row) > 0 and row[0] == str(user_id):
            return {header: row[i] if i < len(row) else '' for i, header in enumerate(headers)}
    return None

async def update_user_wanted(user_id: int, wanted_login: str):
    """Обновляет столбец 'wanted' для пользователя."""
    record = await get_user_record(user_id)
    if not record:
        return False
    
    row_idx = list(sheet.col_values(1)).index(str(user_id)) + 1
    col_idx = list(column_index.keys()).index('wanted') + 1
    
    sheet.update_cell(row_idx, col_idx, wanted_login)
    sheet.update_cell(row_idx, column_index['notified'] + 1, "FALSE")
    return True

async def update_user_notified(user_id: int, notified: bool):
    """Обновляет столбец 'notified' для пользователя."""
    record = await get_user_record(user_id)
    if not record:
        return False
    
    row_idx = list(sheet.col_values(1)).index(str(user_id)) + 1
    col_idx = list(column_index.keys()).index('notified') + 1
    
    sheet.update_cell(row_idx, col_idx, "TRUE" if notified else "FALSE")
    return True

async def get_all_tracking_users():
    """Возвращает список кортежей (user_id, wanted_login) для отслеживания."""
    records = sheet.get_all_records()
    return [
        (int(record['user_id']), record['wanted'])
        for record in records
        if 'wanted' in record and record['wanted'] and 'notified' in record
    ]

BANNED_USERS_FILE = "banned_users.txt"

def load_banned_users():
    """Загружает список забаненных пользователей из файла."""
    try:
        with open(BANNED_USERS_FILE, "r") as file:
            return set(map(int, file.read().splitlines()))
    except FileNotFoundError:
        return set()

def save_banned_users(banned_users):
    """Сохраняет список забаненных пользователей в файл."""
    with open(BANNED_USERS_FILE, "w") as file:
        file.write("\n".join(map(str, banned_users)))

def add_banned_user(user_id):
    """Добавляет пользователя в список забаненных."""
    banned_users = load_banned_users()
    banned_users.add(user_id)
    save_banned_users(banned_users)

def remove_banned_user(user_id):
    """Удаляет пользователя из списка забаненных."""
    banned_users = load_banned_users()
    banned_users.discard(user_id)
    save_banned_users(banned_users)

def is_user_banned(user_id):
    """Проверяет, забанен ли пользователь."""
    return user_id in load_banned_users()

async def send_media_preview(media_message: Message, chat_id: int):
    if media_message.text:
        await bot.send_message(chat_id, media_message.text)
    elif media_message.photo:
        await bot.send_photo(chat_id, media_message.photo[-1].file_id, caption=media_message.caption)
    elif media_message.document:
        await bot.send_document(chat_id, media_message.document.file_id, caption=media_message.caption)
    elif media_message.video:
        await bot.send_video(chat_id, media_message.video.file_id, caption=media_message.caption)

async def set_main_menu(bot: Bot):

    # Создаем список с командами и их описанием для кнопки menu
    main_menu_commands = [
        # BotCommand(command='/register',
        #            description='Регистрация 📝'),
        BotCommand(command='/links',
                   description='Полезные ссылки 📚'),
        BotCommand(command='/search',
                   description='Поиск пира в тг 🕵️‍♂️'),
        BotCommand(command='/ping',
                   description='Напомнить о проверке 🔔'),
        BotCommand(command='/campus',
                   description='Кто в кампусе 👀'),
        BotCommand(command='/ref',
                   description='Реферальная ссылка ✉️'),
        BotCommand(command='/wanted', 
                   description='Отслеживать пира 🐈'),
    ]

    await bot.set_my_commands(main_menu_commands)

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
        [InlineKeyboardButton(text="Code Review 📋", callback_data="codereview")],
        [InlineKeyboardButton(text="Выпуск школы 🎓", callback_data="final")],
        [InlineKeyboardButton(text="Как получить коины 💰", callback_data="coins")],
        [InlineKeyboardButton(text="Форма гостя 🎫", callback_data="guests")],
        [InlineKeyboardButton(text="Почта якутского кампуса Школы 21", callback_data="email")],
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


async def send_menu(message: Message):
    await message.answer(
        'Выберите пункты меню:', 
        reply_markup=menu_keyboard()
    )


async def check_ban(user_id: int, message: Message = None, callback: CallbackQuery = None):
    if is_user_banned(user_id):
        if message:
            await message.answer("Вы забанены и не можете использовать бота 🚫")
        elif callback:
            await callback.message.answer("Вы забанены и не можете использовать бота 🚫")
            await callback.answer()
        return True
    return False

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.answer("У вас нет прав для выполнения этой команды ⛔")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите логин или ID пользователя: /ban <логин/ID>:")
        return

    target = args[1]
    user_id = None

    if target.isdigit():
        user_id = int(target)
        user_data = await is_user_in_db(user_id)
        if not user_data:
            await message.answer(f"Пользователь с ID {user_id} не найден 🔍")
            return
    else:
        user_info = await find_user_by_login(target)
        if not user_info:
            await message.answer(f"Пользователь с логином {target} не найден 🔍")
            return
        user_id = user_info[0]

    add_banned_user(user_id)
    await message.answer(f"Пользователь {target} (ID: {user_id}) забанен ☑️")


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.answer("У вас нет прав для выполнения этой команды ⛔")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите логин или ID пользователя: /unban <логин/ID> ✏️")
        return

    target = args[1]
    user_id = None

    if target.isdigit():
        user_id = int(target)
        user_data = await is_user_in_db(user_id)
        if not user_data:
            await message.answer(f"Пользователь с ID {user_id} не найден 🔍")
            return
    else:
        user_info = await find_user_by_login(target)
        if not user_info:
            await message.answer(f"Пользователь с логином {target} не найден 🔍")
            return
        user_id = user_info[0]

    remove_banned_user(user_id)
    await message.answer(f"Пользователь {target} (ID: {user_id}) разбанен ☑️")



@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.answer("У вас нет прав для использования этой команды ⛔")
        return
    await state.set_state(Form.waiting_for_broadcast)
    await message.answer("Введите сообщение для рассылки:")

@dp.message(Form.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if not message.text and not message.photo and not message.document and not message.video:
        await message.answer("Сообщение не может быть пустым 🛑\n\nОтправьте текст или медиа:")
        return

    await state.update_data(broadcast_message=message)
    await state.set_state(Form.waiting_for_broadcast_confirm)
    await send_media_preview(message, message.chat.id)
    await message.answer("Отправить рассылку:", reply_markup=broadcast_decision_keyboard())


@dp.callback_query(F.data == "broadcast_confirm", Form.waiting_for_broadcast_confirm)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    broadcast_message = data.get("broadcast_message")
    users = await get_users()
    success = 0
    failed = 0
    from_chat_id = broadcast_message.chat.id
    message_id = broadcast_message.message_id

    for user_id in users:
        try:
            await bot.copy_message(user_id, from_chat_id, message_id)
            success += 1
        except Exception as e:
            failed += 1
        await asyncio.sleep(0.1)

    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    await callback.message.answer(f"Рассылка завершена ☑️\nуспешно: {success}\nне удалось: {failed}")
    await state.clear()

@dp.callback_query(F.data == "broadcast_cancel", Form.waiting_for_broadcast_confirm)
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    await callback.message.answer("Рассылка отменена ✖️")
    await state.clear()



@dp.message(CommandStart())
async def cmd_start(message: Message):
    if is_user_banned(message.from_user.id):
        await message.answer("Вы забанены и не можете использовать бота 🚫")
        return

    user_data = await is_user_in_db(message.from_user.id)
    if user_data:
        login, name = user_data
        await message.answer(
            f"""<b>Привет, {name}! 👋🏻</b>
Это телеграм бот для Школы 21 YKS 🦣

<b>Какие функции имеет бот?</b>

    • Полезные ссылки \n<i>гайд по стажировке/форма гостя и т.д.</i>

    • Найти пира в телеграмме \n<i>работает если пир зарегистрирован в боте</i>

    • Напомнить о проверке пиру \n<i>работает если пир зарегистрирован в боте</i>

    • Узнать, кто сейчас в кампусе \n<i>показывает список пиров в кампусе</i>

<b>Давайте быть на одной волне!</b> 🌊""",
            reply_markup=menu_keyboard(), parse_mode="HTML"
        )
    else:
        await message.answer(
            """<b>Вы не зарегистрированы, чтобы начать пользоваться ботом нужно пройти регистрацию 📝</b>

<b>Какие функции имеет бот?</b>

    • Полезные ссылки \n<i>гайд по стажировке/форма гостя и т.д.</i>

    • Найти пира в телеграмме \n<i>работает если пир зарегистрирован в боте</i>

    • Напомнить о проверке пиру \n<i>работает если пир зарегистрирован в боте</i>

    • Узнать, кто сейчас в кампусе <i>показывает список пиров в кампусе</i>
    
<b>Давайте быть на одной волне!</b> 🌊""",
            reply_markup=registration_keyboard(), parse_mode="HTML"
        )

@dp.message(Command("wanted"))
async def wanted_message(message: Message, state: FSMContext):
    user_data = await get_user_record(message.from_user.id)
    if not user_data:
        await message.answer("Сначала зарегистрируйтесь с помощью /start")
        return
    
    current_wanted = user_data.get('wanted', '')
    if current_wanted:
        await message.answer(
            f"Вы уже отслеживаете пира: <b>{current_wanted}</b>\n"
            "Введите <b>новый логин</b> для отслеживания или отмените операцию 👀",
                parse_mode="HTML",
                reply_markup=cancel_keyboard()
                             )
    else:
        await message.answer("Введите логин пира для отслеживания:")
    
    await state.set_state(Form.wanted)

@dp.message(Form.wanted)
async def process_wanted(message: Message, state: FSMContext):
    login = message.text.strip()
    
    if not re.fullmatch(r'^[a-z]{8}$', login):
        await message.answer("Неверный формат логина! Используйте 8 маленьких латинских букв ❌")
        return
    
    # Проверяем существует ли пир в базе
    all_records = sheet.get_all_records()
    peer_exists = any(record.get('login') == login for record in all_records)
    
    if not peer_exists:
        await message.answer("Пир с таким логином не найден в базе")
        return
    
    # Обновляем запись пользователя
    if await update_user_wanted(message.from_user.id, login):
        await message.answer(f"Теперь вы отслеживаете пира: \n<b>{login}</b>", parse_mode="HTML")
    else:
        await message.answer("Ошибка при обновлении данных. Попробуйте позже ❌")
    
    await state.clear()

async def check_campus_periodically():
    """Периодическая проверка присутствия пиров в кампусе."""
    while True:
        try:
            # Получаем список присутствующих
            token = await get_access_token(login_token, password_token)
            if not token:
                await asyncio.sleep(60)
                continue
            
            clusters = ["36621", "36622", "36623", "36624"]
            present_logins = set()
            
            for cluster_id in clusters:
                cluster_info = await get_cluster_info(cluster_id, token)
                if cluster_info:
                    for participant in cluster_info.get("clusterMap", []):
                        login = participant.get("login")
                        if login:
                            present_logins.add(login)
            
            # Сохраняем в файл
            with open("wanted.txt", "w") as f:
                f.write("\n".join(present_logins))
            
            # Получаем пользователей для отслеживания
            tracking_users = await get_all_tracking_users()
            
            for user_id, wanted_login in tracking_users:
                # Проверяем нужно ли отправлять уведомление
                user_data = await get_user_record(user_id)
                if not user_data:
                    continue
                
                notified = user_data.get('notified', 'FALSE') == 'TRUE'
                
                if wanted_login in present_logins and not notified:
                    try:
                        await bot.send_message(
                            user_id, 
                            f"🚨 Ваш отслеживаемый пир {wanted_login} сейчас в кампусе!"
                        )
                        await update_user_notified(user_id, True)
                    except Exception as e:
                        print(f"Ошибка отправки уведомления {user_id}: {e}")
            
        except Exception as e:
            print(f"Ошибка в check_campus_periodically: {e}")
        
        await asyncio.sleep(60)  # Проверка каждую минуту

async def reset_notified_daily():
    """Ежедневный сброс флагов уведомлений."""
    while True:
        now = datetime.now()
        # Вычисляем время до следующего сброса (00:01)
        next_reset = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0)
        wait_seconds = (next_reset - now).total_seconds()
        
        await asyncio.sleep(wait_seconds)
        
        # Сбрасываем флаги для всех пользователей
        all_records = sheet.get_all_records()
        for record in all_records:
            if 'user_id' in record and 'notified' in record:
                try:
                    user_id = int(record['user_id'])
                    await update_user_notified(user_id, False)
                except:
                    continue

@dp.message(Command("links"))
async def cmd_links_message(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return
    await message.answer('Полезные ссылки:', reply_markup=links_keyboard())

@dp.callback_query(F.data == "links")
async def cmd_links(callback: CallbackQuery):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await callback.message.answer('Полезные ссылки:', reply_markup=links_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "faq")
async def cmd_faq(callback: CallbackQuery):
    await callback.message.answer('FAQ Школы 21\nhttps://applicant.21-school.ru/faq')
    await callback.answer()

@dp.callback_query(F.data == "rules")
async def cmd_rules(callback: CallbackQuery):
    await callback.message.answer('Правила Школы 21\nhttps://applicant.21-school.ru/rules_yak')
    await callback.answer()

@dp.callback_query(F.data == "rocketchat")
async def cmd_rocketchat(callback: CallbackQuery):
    await callback.message.answer('Правила Рокетчата\nhttps://applicant.21-school.ru/rocketchat')
    await callback.answer()

@dp.callback_query(F.data == "internship_guide")
async def cmd_internship_guide(callback: CallbackQuery):
    await callback.message.answer('Гайд по стажировке\nhttps://applicant.21-school.ru/internship_guide')
    await callback.answer()

@dp.callback_query(F.data == "specialties")
async def cmd_specialties(callback: CallbackQuery):
    await callback.message.answer('Список специальностей для стажировки\nhttps://applicant.21-school.ru/specialties')
    await callback.answer()
    
@dp.callback_query(F.data == "gigacode")
async def cmd_gigacode(callback: CallbackQuery):
    await callback.message.answer('Общая позиция «Школы 21» в ИИ\nhttps://applicant.21-school.ru/gigacode')
    await callback.answer()
    
@dp.callback_query(F.data == "p2p")
async def cmd_p2p(callback: CallbackQuery):
    await callback.message.answer('Правила онлайн проверок\nhttps://applicant.21-school.ru/onlineeducation')
    await callback.answer()

@dp.callback_query(F.data == "codereview")
async def cmd_codereview(callback: CallbackQuery):
    await callback.message.answer('Гайд по Код Ревью\nhttps://applicant.21-school.ru/code_review')
    await callback.answer()

@dp.callback_query(F.data == "final")
async def cmd_final(callback: CallbackQuery):
    await callback.message.answer('Что нужно для выпуска\nhttps://applicant.21-school.ru/final')
    await callback.answer()
    
@dp.callback_query(F.data == "email")
async def cmd_email(callback: CallbackQuery):
    await callback.message.answer('Почта Школы 21 YKS\nyks@21-school.ru\nПорядок отправки обращения\nhttps://applicant.21-school.ru/sla')
    await callback.answer()
    
@dp.callback_query(F.data == "coins")
async def cmd_coins(callback: CallbackQuery):
    await callback.message.answer('Как зарабатывать коины\nhttps://applicant.21-school.ru/manual_points')
    await callback.answer()

@dp.callback_query(F.data == "guests")
async def cmd_guests(callback: CallbackQuery):
    await callback.message.answer('Форма гостя\nhttps://forms.yandex.ru/u/65320571068ff019572c037e/\nПорядок проведения гостей в кампус\nhttps://applicant.21-school.ru/guests')
    await callback.answer()




async def get_access_token(login_token: str, password_token: str) -> str:
    url = "https://auth.sberclass.ru/auth/realms/EduPowerKeycloak/protocol/openid-connect/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': 's21-open-api',
        'username': login_token,
        'password': password_token,
        'grant_type': 'password'
    }
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    return None

async def get_cluster_info(cluster_id: str, token: str) -> dict:
    url = f"https://platform-api.21-school.ru/services/21-school/api/v1/clusters/{cluster_id}/map?limit=100&offset=0"
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None



async def handle_campus_command(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return

    token = await get_access_token(login_token, password_token)
    if not token:
        await message.answer("Ошибка аутентификации ❌\n\nПроверьте логин и пароль")
        return

    cluster_id_to_name = {
        "36621": "ay",
        "36622": "er",
        "36623": "tu",
        "36624": "si"
    }
    
    floors = [
        {"clusters": ["36621", "36622"], "name": "2nd Floor"},
        {"clusters": ["36623", "36624"], "name": "3rd Floor"}
    ]
    
    floor_groups = []
    
    # Собираем данные по этажам
    for floor in floors:
        floor_results = []
        for cluster_id in floor["clusters"]:
            cluster_info = await get_cluster_info(cluster_id, token)
            if cluster_info:
                cluster_name = cluster_id_to_name.get(cluster_id)
                for participant in cluster_info.get("clusterMap", []):
                    login = participant.get("login")
                    row = participant.get("row")
                    number = participant.get("number")
                    if login is not None:
                        floor_results.append(f"👤  <b>{login}</b>   {cluster_name}-{row}{number}")
        
        floor_results.sort(key=lambda x: x.split()[1].lower())
        if floor_results:
            floor_groups.append(floor_results)

    # Добавляем разделитель между этажами
    results = []
    for i, group in enumerate(floor_groups):
        if i > 0:
            results.append("")  # Пустая строка как разделитель
        results.extend(group)

    if results:
        chunk_size = 100
        for i in range(0, len(results), chunk_size):
            chunk = "\n".join(results[i:i + chunk_size])
            await message.answer(chunk, parse_mode="HTML")
    else:
        await message.answer("В кампусе никого нет 😭")

# Обработчик для кнопки
@dp.callback_query(F.data == "campus")
async def cmd_campus_callback(callback: CallbackQuery):
    await handle_campus_command(callback.message)
    await callback.answer()

# Обработчик для текстовой команды
@dp.message(Command("campus"))
async def cmd_campus_message(message: Message):
    await handle_campus_command(message)


@dp.message(Command("search"))
async def cmd_search_message(message: Message, state: FSMContext):
    if await check_ban(message.from_user.id, message=message):
        return
    await message.answer('Введите школьный логин пользователя:')
    await state.set_state(Form.search)

@dp.callback_query(F.data == "search")
async def cmd_search(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await callback.message.answer('Введите школьный логин пользователя:')
    await state.set_state(Form.search)
    await callback.answer()

async def process_search_common(message: Message, state: FSMContext):
    login = message.text.strip()
    user_data = await find_user_by_login(login)
    if user_data:
        user_id = user_data[0]
        name = escape(user_data[1])
        telegram_username = user_data[2]
        
        if telegram_username:
            username_escaped = escape(telegram_username)
            text = f"Пользователь найден ✅\n\n<b>{name} <a href='tg://user?id={user_id}'>@{username_escaped}</a></b>"
        else:
            text = f"Пользователь найден ✅\n\n<b>{name} ID: {user_id}</b>"
        
        await message.answer(
            text, 
            parse_mode="HTML", 
            reply_markup=menu_keyboard()
        )
        await state.clear()
    else:
        await message.answer(
            "Пользователь с таким логином не найден ❓\n\nВведите снова логин (8 маленьких английских букв):",
            reply_markup=cancel_keyboard()
        )

# Обработчик новых сообщений
@dp.message(Form.search)
async def process_search(message: Message, state: FSMContext):
    await process_search_common(message, state)

# Обработчик отредактированных сообщений
@dp.edited_message(Form.search)
async def process_search_edit(edited_message: Message, state: FSMContext):
    await process_search_common(edited_message, state)


async def handle_ref_command(message: Message):
    """Обработчик реферальной ссылки"""
    if await check_ban(message.from_user.id, message=message):
        return
    # Получаем данные пользователя
    user_data = await is_user_in_db(message.from_user.id)
    
    if user_data:
        login = user_data[0]
        ref_link = f"https://21-school.ru/?utm_source=school21&utm_medium=student_yak&utm_campaign={login}__"
        await message.answer(
            f"🔗 Ваша реферальная ссылка:\n\n<code>{ref_link}</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "Для получения реферальной ссылки необходимо пройти регистрацию 🚀",
            reply_markup=registration_keyboard()
        )

# Обработчик для кнопки
@dp.callback_query(F.data == "ref")
async def cmd_ref_command(callback: CallbackQuery):
    """Обработчик реферальной ссылки"""
    if await check_ban(callback.from_user.id, callback=callback):
        return
    # Получаем данные пользователя
    user_data = await is_user_in_db(callback.from_user.id)
    
    if user_data:
        login = user_data[0]
        ref_link = f"https://21-school.ru/?utm_source=school21&utm_medium=student_yak&utm_campaign={login}__"
        await callback.message.answer(
            f"🔗 Ваша реферальная ссылка:\n\n<code>{ref_link}</code>",
            parse_mode="HTML"
        )
    else:
        await callback.answer(
            "Для получения реферальной ссылки необходимо пройти регистрацию 🚀",
            reply_markup=registration_keyboard()
        )
    await callback.answer()

# Обработчик для текстовой команды
@dp.message(Command("ref"))
async def cmd_ref_message(message: Message):
    await handle_ref_command(message)
    
    
    
@dp.message(Command("ping"))
async def cmd_ping_message(message: Message, state: FSMContext):
    if await check_ban(message.from_user.id, message=message):
        return
    await message.answer('Введите школьный логин пользователя:')
    await state.set_state(Form.ping)


@dp.callback_query(F.data == "ping")
async def cmd_ping(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await callback.message.answer('Введите школьный логин пользователя:')
    await state.set_state(Form.ping)
    await callback.answer()

async def process_ping_common(message: Message, state: FSMContext):
    login = message.text.strip()
    user_data = await find_user_by_login(login)
    if user_data:
        sender_data = await is_user_in_db(message.from_user.id)
        if sender_data:
            await message.bot.send_message(
                user_data[0], 
                f"Напоминание от <b>{sender_data[0]}:</b> 📢\n\n<b>У нас проверка! 🔔</b>", 
                parse_mode="HTML"
            )
            await message.answer(
                f"Сообщение отправлено пользователю {user_data[1]} ✉️", 
                reply_markup=menu_keyboard()
            )
            await state.clear()
    else:
        await message.answer(
            "Пользователь с таким логином не найден ❓\n\nВведите снова логин (8 маленьких английских букв):",
            reply_markup=cancel_keyboard()
        )

# Обработчик новых сообщений
@dp.message(Form.ping)
async def process_ping(message: Message, state: FSMContext):
    await process_ping_common(message, state)

# Обработчик отредактированных сообщений
@dp.edited_message(Form.ping)
async def process_ping_edit(edited_message: Message, state: FSMContext):
    await process_ping_common(edited_message, state)
    



# @dp.message(Command("register"))
# async def cmd_register(message: Message, state: FSMContext):
#     if await check_ban(message.from_user.id, message=message):
#         return
#     user_data = await is_user_in_db(message.from_user.id)
#     if user_data:
#         await message.answer(
#             f'Вы уже зарегистрированы!\nВаш логин {user_data[0]} и имя {user_data[1]}\n\nХотите изменить свои данные?',
#             reply_markup=re_registration_keyboard()
#         )
#     else:
#         await message.answer("Введите школьный логин:")
#         await state.set_state(Form.login)

@dp.callback_query(F.data == "register")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    user_data = await is_user_in_db(callback.from_user.id)
    if user_data:
        await callback.message.answer(
            f'Вы уже зарегистрированы!\nВаш логин {user_data[0]} и имя {user_data[1]}\n\nХотите изменить свои данные?',
            reply_markup=re_registration_keyboard()
        )
        return
    await callback.message.answer("Введите школьный логин:")
    await state.set_state(Form.login)
    await callback.answer()

@dp.callback_query(F.data == "re_register")
async def re_register(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await callback.message.answer("Введите новый школьный логин:")
    await state.set_state(Form.login)
    await callback.answer()

@dp.message(Form.login)
async def process_login(message: Message, state: FSMContext):
    login = message.text.strip()
    if re.fullmatch(r'^[a-z]{8}$', login):
        await state.update_data(login=login)
        await message.answer("Теперь введите ваше имя:")
        await state.set_state(Form.name)
    else:
        await message.answer(
            "Неверный формат логина! 🚫\nДолжно быть ровно 8 маленьких английских букв!\n\nПопробуйте еще раз или отмените операцию",
                             reply_markup=cancel_keyboard()
                             )


@dp.message(Form.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 20:
        await message.answer(
            "Имя должно содержать минимум 2 символа и не более 20 символов 🚫\n\nПопробуйте еще раз или отмените операцию",
                             reply_markup=cancel_keyboard()
                             )

        return
    
    data = await state.get_data()
    telegram_username = message.from_user.username or ''
    await add_user_to_db(message.from_user.id, data['login'], name, telegram_username)
    await message.answer("Регистрация успешно завершена! ☑️", 
        reply_markup=menu_keyboard())
    await state.clear()

@dp.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    
    # current_state = await state.get_state()
    # logger.info(f"Текущее состояние перед очисткой: {current_state}")
    
    # Очищаем состояние
    await state.clear()
    
    # logger.info(f"Состояние после очистки: {await state.get_state()}")
    
    # Отправляем пользователю меню
    await callback.message.answer('Операция отменена ❎', reply_markup=menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    
    # current_state = await state.get_state()
    # logger.info(f"Текущее состояние перед очисткой: {current_state}")
    
    # Очищаем состояние
    await state.clear()
    
    # logger.info(f"Состояние после очистки: {await state.get_state()}")
    
    # Отправляем пользователю меню
    await callback.message.answer('Назад к меню ↩️', reply_markup=menu_keyboard())
    await callback.answer()
    



@dp.message()
async def handle_any_message(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return
    
    user_data = await is_user_in_db(message.from_user.id)
    if user_data:
        await send_menu(message)
    else:
        await message.answer(
            'Вы не зарегистрированы 🚫\n\nЗарегистрируйтесь, чтобы пользоваться ботом 📝',
            reply_markup=registration_keyboard()
        )

async def main():
    # Инициализация таблицы
    try:
        headers = sheet.row_values(1)
        if not headers:
            sheet.update('A1', [['user_id', 'login', 'name', 'telegram_username', 'wanted', 'notified']])
            headers = sheet.row_values(1)
        
        # Добавляем отсутствующие столбцы
        new_columns = {'wanted': '', 'notified': 'FALSE'}
        update_needed = False
        
        for col, default_value in new_columns.items():
            if col not in headers:
                headers.append(col)
                update_needed = True
        
        if update_needed:
            sheet.update([headers], 'A1')
        
        # Создаем индекс столбцов
        global column_index
        column_index = {header: idx for idx, header in enumerate(headers)}
        
    except Exception as e:
        print(f"Ошибка инициализации таблицы: {e}")
    
    # Запускаем периодические задачи
    asyncio.create_task(check_campus_periodically())
    asyncio.create_task(reset_notified_daily())
    
    dp.startup.register(set_main_menu)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
