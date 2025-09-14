import asyncio
import os
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from handlers.handlers import dp
from services.google_sheets_service import GoogleSheetsService
from utils.helpers import set_main_menu

load_dotenv()

TOKEN = os.getenv("TOKEN")
MAIN_ADMIN_ID = os.getenv("MAIN_ADMIN_ID")
login_token = os.getenv("login_token")
password_token = os.getenv("password_token")
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS")
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")

bot = Bot(token=TOKEN)

async def main():
    # Инициализация Google Sheets сервиса
    service = GoogleSheetsService(GOOGLE_SHEETS_CREDS, SPREADSHEET_KEY)
    await service.initialize()

    # Добавляем сервисы и данные в диспетчер
    dp["google_sheets_service"] = service
    dp["login_token"] = login_token
    dp["password_token"] = password_token
    dp["main_admin_id"] = int(MAIN_ADMIN_ID) if MAIN_ADMIN_ID else None
    dp.bot = bot

    # Запускаем периодические задачи
    asyncio.create_task(service.check_campus_periodically(bot))
    asyncio.create_task(service.reset_notified_daily())

    # Регистрируем обработчик запуска
    dp.startup.register(set_main_menu)

    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
