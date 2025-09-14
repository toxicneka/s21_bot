from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("TOKEN")
MAIN_ADMIN_ID = os.getenv("MAIN_ADMIN_ID")
login_token = os.getenv("login_token")
password_token = os.getenv("password_token")
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS")
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
