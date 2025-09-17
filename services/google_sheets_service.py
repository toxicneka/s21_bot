import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
import requests
from datetime import datetime, timedelta
from config import login_token, password_token

class GoogleSheetsService:
    def __init__(self, creds_file, spreadsheet_key):
        self.scope = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key).sheet1
        self.column_index = {}

    async def initialize(self):
        try:
            headers = self.sheet.row_values(1)
            if not headers:
                self.sheet.update('A1', [['user_id', 'login', 'name', 'telegram_username', 'wanted', 'notified']])
                headers = self.sheet.row_values(1)

            # Добавляем отсутствующие столбцы
            new_columns = {'wanted': '', 'notified': 'FALSE'}
            update_needed = False

            for col, default_value in new_columns.items():
                if col not in headers:
                    headers.append(col)
                    update_needed = True

            if update_needed:
                self.sheet.update([headers], 'A1')

            # Создаем индекс столбцов
            self.column_index = {header: idx for idx, header in enumerate(headers)}

        except Exception as e:
            print(f"Ошибка инициализации таблицы: {e}")

    async def is_user_in_db(self, user_id: int):
        records = self.sheet.get_all_records()
        for record in records:
            if record['user_id'] == user_id:
                return (record['login'], record['name'])
        return None

    async def add_user_to_db(self, user_id: int, login: str, name: str, telegram_username: str):
        records = self.sheet.get_all_records()
        headers = self.sheet.row_values(1)

        for i, record in enumerate(records, start=2):
            if record['user_id'] == user_id:
                self.sheet.update_cell(i, headers.index('login') + 1, login)
                self.sheet.update_cell(i, headers.index('name') + 1, name)
                self.sheet.update_cell(i, headers.index('telegram_username') + 1, telegram_username)
                return

        new_row = ['' for _ in headers]
        new_row[headers.index('user_id')] = user_id
        new_row[headers.index('login')] = login
        new_row[headers.index('name')] = name
        new_row[headers.index('telegram_username')] = telegram_username

        self.sheet.append_row(new_row)

    async def find_user_by_login(self, login: str):
        records = self.sheet.get_all_records()
        for record in records:
            if record['login'] == login:
                return (record['user_id'], record['name'], record['telegram_username'])
        return None

    async def get_users(self):
        records = self.sheet.get_all_records()
        return [record['user_id'] for record in records]

    async def get_user_record(self, user_id: int) -> dict:
        """Возвращает запись пользователя как словарь или None."""
        all_values = self.sheet.get_all_values()
        if not all_values:
            return None
        headers = all_values[0]
        for row in all_values[1:]:
            if len(row) > 0 and row[0] == str(user_id):
                return {header: row[i] if i < len(row) else '' for i, header in enumerate(headers)}
        return None

    async def update_user_wanted(self, user_id: int, wanted_login: str):
        """Обновляет столбец 'wanted' для пользователя."""
        record = await self.get_user_record(user_id)
        if not record:
            return False

        row_idx = list(self.sheet.col_values(1)).index(str(user_id)) + 1
        col_idx = list(self.column_index.keys()).index('wanted') + 1

        self.sheet.update_cell(row_idx, col_idx, wanted_login)
        self.sheet.update_cell(row_idx, self.column_index['notified'] + 1, "FALSE")
        return True

    async def update_user_notified(self, user_id: int, notified: bool):
        """Обновляет столбец 'notified' для пользователя."""
        record = await self.get_user_record(user_id)
        if not record:
            return False

        row_idx = list(self.sheet.col_values(1)).index(str(user_id)) + 1
        col_idx = list(self.column_index.keys()).index('notified') + 1

        self.sheet.update_cell(row_idx, col_idx, "TRUE" if notified else "FALSE")
        return True

    async def get_all_tracking_users(self):
        """Возвращает список кортежей (user_id, wanted_login) для отслеживания."""
        records = self.sheet.get_all_records()
        return [
            (int(record['user_id']), record['wanted'])
            for record in records
            if 'wanted' in record and record['wanted'] and 'notified' in record
        ]

    async def get_access_token(self, login_token: str, password_token: str) -> str:
        url = "https://dev21-school.ru.pcbltools.ru/auth/realms/EduPowerKeycloak/protocol/openid-connect/token"
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

    async def get_cluster_info(self, cluster_id: str, token: str) -> dict:
        url = f"https://platform.21-school.ru/services/21-school/api/v1/clusters/{cluster_id}/map?limit=100&offset=0"
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return None

    async def check_campus_periodically(self, bot):
        """Периодическая проверка присутствия пиров в кампусе."""
        while True:
            try:
                # Получаем список присутствующих
                token = await self.get_access_token(login_token, password_token)
                if not token:
                    await asyncio.sleep(60)
                    continue

                clusters = ["36621", "36622", "36623", "36624"]
                present_logins = set()

                for cluster_id in clusters:
                    cluster_info = await self.get_cluster_info(cluster_id, token)
                    if cluster_info:
                        for participant in cluster_info.get("clusterMap", []):
                            login = participant.get("login")
                            if login:
                                present_logins.add(login)

                # Сохраняем в файл
                with open("wanted.txt", "w") as f:
                    f.write("\n".join(present_logins))

                # Получаем пользователей для отслеживания
                tracking_users = await self.get_all_tracking_users()

                for user_id, wanted_login in tracking_users:
                    # Проверяем нужно ли отправлять уведомление
                    user_data = await self.get_user_record(user_id)
                    if not user_data:
                        continue

                    notified = user_data.get('notified', 'FALSE') == 'TRUE'

                    if wanted_login in present_logins and not notified:
                        try:
                            await bot.send_message(
                                user_id,
                                f"🚨 Ваш отслеживаемый пир {wanted_login} сейчас в кампусе!"
                            )
                            await self.update_user_notified(user_id, True)
                        except Exception as e:
                            print(f"Ошибка отправки уведомления {user_id}: {e}")

            except Exception as e:
                print(f"Ошибка в check_campus_periodically: {e}")

            await asyncio.sleep(60)  # Проверка каждую минуту

    async def reset_notified_daily(self):
        """Ежедневный сброс флагов уведомлений."""
        while True:
            now = datetime.now()
            # Вычисляем время до следующего сброса (00:01)
            next_reset = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0)
            wait_seconds = (next_reset - now).total_seconds()

            await asyncio.sleep(wait_seconds)

            # Сбрасываем флаги для всех пользователей
            all_records = self.sheet.get_all_records()
            for record in all_records:
                if 'user_id' in record and 'notified' in record:
                    try:
                        user_id = int(record['user_id'])
                        await self.update_user_notified(user_id, False)
                    except:
                        continue
