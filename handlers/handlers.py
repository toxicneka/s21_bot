import re
from html import escape
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from utils.states import Form
from utils.helpers import (
    menu_keyboard, links_keyboard, registration_keyboard,
    re_registration_keyboard, cancel_keyboard, broadcast_decision_keyboard,
    check_ban, send_menu, send_media_preview, is_user_banned,
    add_banned_user, remove_banned_user
)

dp = Dispatcher()

# Admin commands
@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != int(dp["main_admin_id"]):
        return await message.answer("У вас нет прав ⛔")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите логин или ID: /ban <логин/ID>")

    target = args[1]
    
    if target.isdigit():
        user_id = int(target)
        if not await dp["google_sheets_service"].is_user_in_db(user_id):
            return await message.answer(f"Пользователь с ID {user_id} не найден 🔍")
    else:
        user_info = await dp["google_sheets_service"].find_user_by_login(target)
        if not user_info:
            return await message.answer(f"Пользователь {target} не найден 🔍")
        user_id = user_info[0]

    add_banned_user(user_id)
    await message.answer(f"Пользователь {target} (ID: {user_id}) забанен ☑️")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != int(dp["main_admin_id"]):
        return await message.answer("У вас нет прав ⛔")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите логин или ID: /unban <логин/ID>")

    target = args[1]
    
    if target.isdigit():
        user_id = int(target)
        if not await dp["google_sheets_service"].is_user_in_db(user_id):
            return await message.answer(f"Пользователь с ID {user_id} не найден 🔍")
    else:
        user_info = await dp["google_sheets_service"].find_user_by_login(target)
        if not user_info:
            return await message.answer(f"Пользователь {target} не найден 🔍")
        user_id = user_info[0]

    remove_banned_user(user_id)
    await message.answer(f"Пользователь {target} (ID: {user_id}) разбанен ☑️")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != int(dp["main_admin_id"]):
        return await message.answer("У вас нет прав ⛔")
    
    await state.set_state(Form.waiting_for_broadcast)
    await message.answer("Введите сообщение для рассылки:")

@dp.message(Form.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if not message.text and not message.photo and not message.document and not message.video:
        return await message.answer("Сообщение не может быть пустым 🛑")

    await state.update_data(broadcast_message=message)
    await state.set_state(Form.waiting_for_broadcast_confirm)
    await send_media_preview(message, message.chat.id)
    await message.answer("Отправить рассылку?", reply_markup=broadcast_decision_keyboard())

@dp.callback_query(F.data == "broadcast_confirm", Form.waiting_for_broadcast_confirm)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    broadcast_message = data.get("broadcast_message")
    users = await dp["google_sheets_service"].get_users()
    
    success, failed = 0, 0
    for user_id in users:
        try:
            await dp.bot.copy_message(user_id, broadcast_message.chat.id, broadcast_message.message_id)
            success += 1
        except:
            failed += 1

    await callback.message.delete()
    await callback.message.answer(f"Рассылка завершена ☑️\nУспешно: {success}\nНе удалось: {failed}")
    await state.clear()

@dp.callback_query(F.data == "broadcast_cancel", Form.waiting_for_broadcast_confirm)
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("Рассылка отменена ✖️")
    await state.clear()

# Main commands
@dp.message(CommandStart())
async def cmd_start(message: Message):
    if is_user_banned(message.from_user.id):
        return await message.answer("Вы забанены и не можете использовать бота 🚫")

    user_data = await dp["google_sheets_service"].is_user_in_db(message.from_user.id)
    
    welcome_text = """<b>Привет! 👋🏻</b>
Это телеграм бот для Школы 21 YKS 🦣

<b>Какие функции имеет бот?</b>
• Полезные ссылки
• Найти пира в телеграмме
• Напомнить о проверке пиру
• Узнать, кто сейчас в кампусе

<b>Давайте быть на одной волне!</b> 🌊"""
    
    if user_data:
        login, name = user_data
        await message.answer(f"<b>Привет, {name}! 👋🏻</b>\n{welcome_text}", 
                           reply_markup=menu_keyboard(), parse_mode="HTML")
    else:
        await message.answer(f"<b>Вы не зарегистрированы 📝</b>\n{welcome_text}", 
                           reply_markup=registration_keyboard(), parse_mode="HTML")

@dp.message(Command("wanted"))
async def wanted_message(message: Message, state: FSMContext):
    user_data = await dp["google_sheets_service"].get_user_record(message.from_user.id)
    if not user_data:
        return await message.answer("Сначала зарегистрируйтесь с помощью /start")

    current_wanted = user_data.get('wanted', '')
    if current_wanted:
        await message.answer(f"Вы уже отслеживаете пира: <b>{current_wanted}</b>\nВведите <b>новый логин</b> для отслеживания:", 
                           parse_mode="HTML", reply_markup=cancel_keyboard())
    else:
        await message.answer("Введите логин пира для отслеживания:")
    
    await state.set_state(Form.wanted)

@dp.message(Form.wanted)
async def process_wanted(message: Message, state: FSMContext):
    login = message.text.strip()
    
    if not re.fullmatch(r'^[a-z]{8}$', login):
        return await message.answer("Неверный формат логина! Используйте 8 маленьких латинских букв ❌")
    
    all_records = dp["google_sheets_service"].sheet.get_all_records()
    if not any(record.get('login') == login for record in all_records):
        return await message.answer("Пир с таким логином не найден в базе")
    
    if await dp["google_sheets_service"].update_user_wanted(message.from_user.id, login):
        await message.answer(f"Теперь вы отслеживаете пира: <b>{login}</b>", parse_mode="HTML")
    else:
        await message.answer("Ошибка при обновлении данных ❌")
    
    await state.clear()

# Links section
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

# Link handlers (kept minimal)
link_mapping = {
    "faq": ("FAQ Школы 21", "https://applicant.21-school.ru/faq"),
    "rules": ("Правила Школы 21", "https://applicant.21-school.ru/rules_yak"),
    "rocketchat": ("Правила Рокетчата", "https://applicant.21-school.ru/rocketchat"),
    "internship_guide": ("Гайд по стажировке", "https://applicant.21-school.ru/internship_guide"),
    "specialties": ("Список специальностей", "https://applicant.21-school.ru/specialties"),
    "gigacode": ("GigaCode", "https://applicant.21-school.ru/gigacode"),
    "p2p": ("Правила онлайн проверок", "https://applicant.21-school.ru/onlineeducation"),
    "final": ("Что нужно для выпуска", "https://applicant.21-school.ru/final"),
    "email": ("Почта Школы 21 YKS", "yks@21-school.ru\nhttps://applicant.21-school.ru/sla"),
    "coins": ("Как зарабатывать коины", "https://applicant.21-school.ru/manual_points"),
    "guests": ("Форма гостя", "https://forms.yandex.ru/u/65320571068ff019572c037e/\nhttps://applicant.21-school.ru/guests"),
}

for key, (title, content) in link_mapping.items():
    @dp.callback_query(F.data == key)
    async def handler(callback: CallbackQuery, key=key, title=title, content=content):
        await callback.message.answer(f"{title}\n{content}")
        await callback.answer()

# Campus
async def handle_campus_command(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return
    
    campus_data = await dp["google_sheets_service"].get_campus_data(force_refresh=False)
    
    if not campus_data or "cluster_map" not in campus_data:
        await message.answer("🔄 Получаю данные о кампусе...")
        campus_data = await dp["google_sheets_service"].get_campus_data(force_refresh=True)
    
    if not campus_data or "cluster_map" not in campus_data:
        return await message.answer("❌ Не удалось получить данные о кампусе")
    
    cluster_id_to_name = {"36621": "ay", "36622": "er", "36623": "tu", "36624": "si"}
    floors = [{"clusters": ["36621", "36622"], "name": "2-й этаж"},
              {"clusters": ["36623", "36624"], "name": "3-й этаж"}]
    
    floor_groups, total_peers = [], 0
    cluster_map = campus_data["cluster_map"]
    
    for floor in floors:
        floor_results = []
        for cluster_id in floor["clusters"]:
            if cluster_id in cluster_map:
                cluster_name = cluster_id_to_name.get(cluster_id, cluster_id)
                for participant in cluster_map[cluster_id]:
                    if login := participant.get("login", ""):
                        row, number = participant.get("row", ""), participant.get("number", "")
                        floor_results.append(f"👤 <b>{login}</b> {cluster_name}-{row}{number}")
                        total_peers += 1
        
        if floor_results:
            floor_results.sort(key=lambda x: x.split()[1].lower())
            floor_groups.append(floor_results)
    
    if not floor_groups:
        return await message.answer("😴 В кампусе никого нет")
    
    header = f"👥 <b>Людей в кампусе: {total_peers}</b>\n\n"
    all_lines = []
    for group in floor_groups:
        all_lines.extend(group)
    
    chunk_size = 90
    chunks = []
    current_chunk = []
    
    for line in all_lines:
        if len("\n".join(current_chunk + [line])) > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
        current_chunk.append(line)
    
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    if chunks:
        await message.answer(header + chunks[0], parse_mode="HTML")
        for chunk in chunks[1:]:
            await message.answer(chunk, parse_mode="HTML")

@dp.callback_query(F.data == "campus")
async def cmd_campus_callback(callback: CallbackQuery):
    await handle_campus_command(callback.message)
    await callback.answer()

@dp.message(Command("campus"))
async def cmd_campus_message(message: Message):
    await handle_campus_command(message)

# Search
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
    user_data = await dp["google_sheets_service"].find_user_by_login(login)
    
    if user_data:
        user_id, name, telegram_username = user_data
        name = escape(name)
        
        if telegram_username:
            text = f"Пользователь найден ✅\n\n<b>{name} <a href='tg://user?id={user_id}'>@{escape(telegram_username)}</a></b>"
        else:
            text = f"Пользователь найден ✅\n\n<b>{name} ID: {user_id}</b>"
        
        await message.answer(text, parse_mode="HTML", reply_markup=menu_keyboard())
    else:
        await message.answer("Пользователь с таким логином не найден ❓", reply_markup=cancel_keyboard())
    
    await state.clear()

@dp.message(Form.search)
async def process_search(message: Message, state: FSMContext):
    await process_search_common(message, state)

# Ref
async def handle_ref_command(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return
    
    user_data = await dp["google_sheets_service"].is_user_in_db(message.from_user.id)
    if user_data:
        login = user_data[0]
        ref_link = f"https://21-school.ru/?utm_source=school21&utm_medium=student_yak&utm_campaign={login}__"
        await message.answer(f"🔗 Ваша реферальная ссылка:\n\n<code>{ref_link}</code>", parse_mode="HTML")
    else:
        await message.answer("Для получения реферальной ссылки необходимо пройти регистрацию 🚀", 
                           reply_markup=registration_keyboard())

@dp.callback_query(F.data == "ref")
async def cmd_ref_command(callback: CallbackQuery):
    await handle_ref_command(callback.message)
    await callback.answer()

@dp.message(Command("ref"))
async def cmd_ref_message(message: Message):
    await handle_ref_command(message)

# Ping
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
    user_data = await dp["google_sheets_service"].find_user_by_login(login)
    
    if user_data:
        sender_data = await dp["google_sheets_service"].is_user_in_db(message.from_user.id)
        if sender_data:
            await message.bot.send_message(
                user_data[0],
                f"Напоминание от <b>{sender_data[0]}:</b> 📢\n\n<b>У нас проверка! 🔔</b>",
                parse_mode="HTML"
            )
            await message.answer(f"Сообщение отправлено пользователю {user_data[1]} ✉️", 
                               reply_markup=menu_keyboard())
    else:
        await message.answer("Пользователь с таким логином не найден ❓", reply_markup=cancel_keyboard())
    
    await state.clear()

@dp.message(Form.ping)
async def process_ping(message: Message, state: FSMContext):
    await process_ping_common(message, state)

# Registration
@dp.callback_query(F.data == "register")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    
    user_data = await dp["google_sheets_service"].is_user_in_db(callback.from_user.id)
    if user_data:
        await callback.message.answer(
            f'Вы уже зарегистрированы!\nВаш логин {user_data[0]} и имя {user_data[1]}\n\nХотите изменить данные?',
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
        await message.answer("Неверный формат логина! 🚫\n8 маленьких английских букв", 
                           reply_markup=cancel_keyboard())

@dp.message(Form.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 20:
        return await message.answer("Имя: 2-20 символов 🚫", reply_markup=cancel_keyboard())
    
    data = await state.get_data()
    telegram_username = message.from_user.username or ''
    await dp["google_sheets_service"].add_user_to_db(message.from_user.id, data['login'], name, telegram_username)
    await message.answer("Регистрация успешно завершена! ☑️", reply_markup=menu_keyboard())
    await state.clear()

# Cancel/Back
@dp.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await state.clear()
    await callback.message.answer('Операция отменена ❎', reply_markup=menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery, state: FSMContext):
    if await check_ban(callback.from_user.id, callback=callback):
        return
    await state.clear()
    await callback.message.answer('Назад к меню ↩️', reply_markup=menu_keyboard())
    await callback.answer()

# Fallback
@dp.message()
async def handle_any_message(message: Message):
    if await check_ban(message.from_user.id, message=message):
        return

    if await dp["google_sheets_service"].is_user_in_db(message.from_user.id):
        await send_menu(message)
    else:
        await message.answer('Вы не зарегистрированы 🚫\nЗарегистрируйтесь, чтобы пользоваться ботом 📝',
                           reply_markup=registration_keyboard())