import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
import aiohttp
from datetime import datetime, timedelta

class GoogleSheetsService:
    def __init__(self, creds_file, spreadsheet_key, login_token, password_token):
        self.scope = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key).sheet1
        
        self.login_token = login_token
        self.password_token = password_token
        
        # Cache
        self._access_token = None
        self._token_expiry = None
        self._campus_data_cache = None
        self._cache_timestamp = None
        self._cache_lock = asyncio.Lock()
        
        # Cache timing
        self._min_cache_seconds = 30
        self._max_cache_seconds = 300
    
    async def get_access_token(self) -> str:
        now = datetime.now()
        
        if (self._access_token and self._token_expiry and now < self._token_expiry):
            return self._access_token
        
        url = "https://auth.21-school.ru/auth/realms/EduPowerKeycloak/protocol/openid-connect/token"
        data = {
            'client_id': 's21-open-api',
            'username': self.login_token,
            'password': self.password_token,
            'grant_type': 'password'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        self._access_token = token_data.get('access_token')
                        expires_in = token_data.get('expires_in', 3600)
                        self._token_expiry = now + timedelta(seconds=expires_in - 300)
                        return self._access_token
        except:
            return None
    
    async def get_campus_data(self, force_refresh=False) -> dict:
        now = datetime.now()
        
        async with self._cache_lock:
            if (not force_refresh and self._campus_data_cache and self._cache_timestamp):
                cache_age = (now - self._cache_timestamp).total_seconds()
                if cache_age < self._min_cache_seconds:
                    return self._campus_data_cache
                if cache_age > self._max_cache_seconds:
                    force_refresh = True
            
            if force_refresh or not self._campus_data_cache:
                token = await self.get_access_token()
                if not token:
                    return self._campus_data_cache or {}
                
                clusters = ["36621", "36622", "36623", "36624"]
                cluster_map = {}
                
                try:
                    headers = {'Authorization': f'Bearer {token}'}
                    tasks = []
                    for cluster_id in clusters:
                        url = f"https://platform.21-school.ru/services/21-school/api/v1/clusters/{cluster_id}/map"
                        tasks.append(self._fetch_cluster(url, headers, cluster_id))
                    
                    results = await asyncio.gather(*tasks)
                    
                    for i, result in enumerate(results):
                        cluster_id = clusters[i]
                        if not result:
                            continue
                            
                        for participant in result.get("clusterMap", []):
                            if login := participant.get("login"):
                                if cluster_id not in cluster_map:
                                    cluster_map[cluster_id] = []
                                cluster_map[cluster_id].append({
                                    "login": login,
                                    "row": participant.get("row"),
                                    "number": participant.get("number")
                                })
                    
                    self._campus_data_cache = {"cluster_map": cluster_map}
                    self._cache_timestamp = now
                    
                except:
                    pass
            
            return self._campus_data_cache or {}
    
    async def _fetch_cluster(self, url, headers, cluster_id):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
        except:
            return None
    
    async def check_campus_periodically(self, bot):
        while True:
            try:
                campus_data = await self.get_campus_data(force_refresh=True)
                present_logins = {p["login"] for cluster in campus_data.get("cluster_map", {}).values() 
                                for p in cluster}
                
                if present_logins:
                    tracking_users = await self.get_all_tracking_users()
                    
                    for user_id, wanted_login in tracking_users:
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
                            except:
                                pass
                
                await asyncio.sleep(300)
                
            except:
                await asyncio.sleep(60)

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
        all_values = self.sheet.get_all_values()
        if not all_values:
            return None
        headers = all_values[0]
        for row in all_values[1:]:
            if len(row) > 0 and row[0] == str(user_id):
                return {header: row[i] if i < len(row) else '' for i, header in enumerate(headers)}
        return None

    async def update_user_wanted(self, user_id: int, wanted_login: str):
        record = await self.get_user_record(user_id)
        if not record:
            return False

        row_idx = list(self.sheet.col_values(1)).index(str(user_id)) + 1
        col_idx = self.sheet.row_values(1).index('wanted') + 1 if 'wanted' in self.sheet.row_values(1) else None
        
        if col_idx:
            self.sheet.update_cell(row_idx, col_idx, wanted_login)
            
            notified_idx = self.sheet.row_values(1).index('notified') + 1 if 'notified' in self.sheet.row_values(1) else None
            if notified_idx:
                self.sheet.update_cell(row_idx, notified_idx, "FALSE")
            
            return True
        return False

    async def update_user_notified(self, user_id: int, notified: bool):
        record = await self.get_user_record(user_id)
        if not record:
            return False

        row_idx = list(self.sheet.col_values(1)).index(str(user_id)) + 1
        col_idx = self.sheet.row_values(1).index('notified') + 1 if 'notified' in self.sheet.row_values(1) else None
        
        if col_idx:
            self.sheet.update_cell(row_idx, col_idx, "TRUE" if notified else "FALSE")
            return True
        return False

    async def get_all_tracking_users(self):
        records = self.sheet.get_all_records()
        return [
            (int(record['user_id']), record['wanted'])
            for record in records
            if 'wanted' in record and record['wanted'] and 'notified' in record
        ]

    async def reset_notified_daily(self):
        while True:
            now = datetime.now()
            next_reset = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0)
            wait_seconds = (next_reset - now).total_seconds()

            await asyncio.sleep(wait_seconds)

            records = self.sheet.get_all_records()
            for record in records:
                if 'user_id' in record and 'notified' in record:
                    try:
                        user_id = int(record['user_id'])
                        await self.update_user_notified(user_id, False)
                    except:
                        continue

    async def initialize(self):
        try:
            headers = self.sheet.row_values(1)
            if not headers:
                self.sheet.update('A1', [['user_id', 'login', 'name', 'telegram_username', 'wanted', 'notified']])
                headers = self.sheet.row_values(1)

            new_columns = {'wanted': '', 'notified': 'FALSE'}
            update_needed = False

            for col in new_columns:
                if col not in headers:
                    headers.append(col)
                    update_needed = True

            if update_needed:
                self.sheet.update([headers], 'A1')
                
        except Exception as e:
            raise e