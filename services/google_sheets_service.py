
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
import aiohttp
from datetime import datetime, timedelta
from collections import defaultdict

class GoogleSheetsService:
    def __init__(self, creds_file, spreadsheet_key, login_token, password_token):
        self.scope = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key).sheet1
        self.column_index = {}
        
        # Токены для API Школы 21
        self.login_token = login_token
        self.password_token = password_token
        
        # КЭШ токена
        self._access_token = None
        self._token_expiry = None
        
        # КЭШ данных кампуса
        self._campus_data_cache = None
        self._cache_timestamp = None
        self._cache_lock = asyncio.Lock()  # Блокировка для безопасного доступа к кэшу
        
        # Защита от спама - храним когда последний раз обновлялся кэш по запросу
        self._last_api_call = None
        self._min_cache_seconds = 30  # Минимальное время между обновлениями кэша
        self._max_cache_seconds = 300  # Максимальное время жизни кэша (5 минут)
        
        # Счетчик для отладки
        self.api_call_counter = {"token": 0, "campus": 0, "wanted": 0}
        
        # Кэш для отслеживаемых пиров
        self._tracking_cache = None
        self._tracking_cache_timestamp = None
        
    async def get_access_token(self) -> str:
        """Получение токена с кэшированием"""
        now = datetime.now()
        
        if (self._access_token and 
            self._token_expiry and 
            now < self._token_expiry):
            return self._access_token
        
        print(f"[API] Получение нового токена... (запрос #{self.api_call_counter['token'] + 1})")
        self.api_call_counter["token"] += 1
        
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
                        print(f"[API] Токен получен. Действителен до: {self._token_expiry}")
                        return self._access_token
                    else:
                        text = await response.text()
                        print(f"[API] Ошибка получения токена: {response.status}")
                        return None
        except Exception as e:
            print(f"[API] Исключение при получении токена: {e}")
            return None
    
    async def get_campus_data(self, force_refresh=False) -> dict:
        """Получение данных кампуса с защитой от спама"""
        now = datetime.now()
        
        async with self._cache_lock:
            # Проверяем, можно ли использовать кэш
            if (not force_refresh and 
                self._campus_data_cache and 
                self._cache_timestamp):
                
                cache_age = (now - self._cache_timestamp).total_seconds()
                
                # Если кэш свежий (меньше 30 секунд), возвращаем его
                if cache_age < self._min_cache_seconds:
                    print(f"[CACHE] Используем кэш кампуса (возраст: {cache_age:.0f} сек)")
                    return self._campus_data_cache
                
                # Если кто-то недавно уже обновил кэш (меньше 30 секунд назад), ждем
                if (self._last_api_call and 
                    (now - self._last_api_call).total_seconds() < self._min_cache_seconds):
                    print(f"[CACHE] Используем кэш (обновление было {self._min_cache_seconds} сек назад)")
                    return self._campus_data_cache
                
                # Если кэш слишком старый (больше 5 минут), обновляем
                if cache_age > self._max_cache_seconds:
                    print(f"[CACHE] Кэш устарел ({cache_age:.0f} сек), требуется обновление")
                    force_refresh = True
            
            # Если требуется обновление
            if force_refresh or not self._campus_data_cache:
                print(f"[API] Получение данных кампуса... (запрос #{self.api_call_counter['campus'] + 1})")
                self.api_call_counter["campus"] += 1
                self._last_api_call = now
                
                token = await self.get_access_token()
                if not token:
                    print("[API] Не удалось получить токен")
                    return self._campus_data_cache or {}
                
                clusters = ["36621", "36622", "36623", "36624"]
                cluster_id_to_name = {
                    "36621": "ay",
                    "36622": "er", 
                    "36623": "tu",
                    "36624": "si"
                }
                
                present_logins = set()
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
                            login = participant.get("login")
                            if login:
                                present_logins.add(login)
                                if cluster_id not in cluster_map:
                                    cluster_map[cluster_id] = []
                                cluster_map[cluster_id].append({
                                    "login": login,
                                    "row": participant.get("row"),
                                    "number": participant.get("number"),
                                    "cluster_name": cluster_id_to_name.get(cluster_id, cluster_id)
                                })
                    
                    # Сохраняем в кэш
                    self._campus_data_cache = {
                        "present_logins": present_logins,
                        "cluster_map": cluster_map,
                        "timestamp": now
                    }
                    self._cache_timestamp = now
                    
                    # Обновляем кэш для wanted
                    await self._update_wanted_cache(present_logins)
                    
                    print(f"[API] Данные кампуса обновлены. Пиров: {len(present_logins)}")
                    
                except Exception as e:
                    print(f"[API] Ошибка получения данных кампуса: {e}")
            
            return self._campus_data_cache or {}
    
    async def _update_wanted_cache(self, present_logins):
        """Обновляет кэш для отслеживаемых пиров"""
        try:
            tracking_users = await self.get_all_tracking_users()
            self._tracking_cache = {
                "present_logins": present_logins,
                "tracking_users": tracking_users,
                "timestamp": datetime.now()
            }
            self._tracking_cache_timestamp = datetime.now()
        except Exception as e:
            print(f"[CACHE] Ошибка обновления кэша wanted: {e}")
    
    async def _fetch_cluster(self, url, headers, cluster_id):
        """Запрос данных одного кластера"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        print(f"[API] Ошибка кластера {cluster_id}: {response.status}")
                        return None
        except Exception as e:
            print(f"[API] Ошибка запроса кластера {cluster_id}: {e}")
            return None
    
    async def check_campus_periodically(self, bot):
        """Периодическая проверка - раз в 5 минут, использует тот же кэш"""
        print("[ПЕРИОДИЧЕСКАЯ ПРОВЕРКА] Запущена с интервалом 5 минут")
        
        while True:
            try:
                # Получаем обновленные данные кампуса
                campus_data = await self.get_campus_data(force_refresh=True)
                present_logins = campus_data.get("present_logins", set())
                
                if present_logins:
                    # Используем кэшированные данные отслеживания
                    if (self._tracking_cache and 
                        self._tracking_cache_timestamp and 
                        (datetime.now() - self._tracking_cache_timestamp).total_seconds() < 300):
                        
                        tracking_users = self._tracking_cache["tracking_users"]
                    else:
                        tracking_users = await self.get_all_tracking_users()
                    
                    notified_count = 0
                    
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
                                notified_count += 1
                            except Exception as e:
                                print(f"Ошибка отправки уведомления {user_id}: {e}")
                    
                    if notified_count > 0:
                        print(f"[УВЕДОМЛЕНИЯ] Отправлено {notified_count} уведомлений")
                
                print(f"[ПЕРИОДИЧЕСКАЯ ПРОВЕРКА] Ожидание 5 минут...")
                await asyncio.sleep(300)
                
            except Exception as e:
                print(f"[ПЕРИОДИЧЕСКАЯ ПРОВЕРКА] Ошибка: {e}")
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