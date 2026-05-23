import os
import sys
import re
import time
import logging
import configparser
import requests
from bs4 import BeautifulSoup
from tabulate import tabulate

# --- Загрузка конфигурации ---
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.cfg')

def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        print(f"Критическая ошибка: Файл {CONFIG_FILE} не найден!")
        sys.exit(1)
    config.read(CONFIG_FILE, encoding='utf-8')
    try:
        return {
            'user': config.get('AdminVPS', 'username'),
            'pass': config.get('AdminVPS', 'password'),
            'zone': config.get('AdminVPS', 'zone_id'),
            'log': config.get('AdminVPS', 'log_file', fallback='dns_manager.log')
        }
    except Exception as e:
        print(f"Ошибка в структуре config.cfg: {e}")
        sys.exit(1)

cfg = load_config()

# --- Настройка логирования ---
def setup_logging(log_path):
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Запись в файл
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # Вывод в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

setup_logging(cfg['log'])
logger = logging.getLogger(__name__)

# --- Основной класс управления DNS ---
class AdminVPSDNS:
    def __init__(self):
        self.session = requests.Session()
        self.api_url = "https://adminvps.ru"
        self.login_url = "https://adminvps.ru"

    def login(self):
        try:
            resp = self.session.get(self.login_url)
            token = re.search(r"var csrfToken = '([a-f0-9]+)'", resp.text).group(1)
            data = {'token': token, 'username': cfg['user'], 'password': cfg['pass']}
            res = self.session.post(self.login_url, data=data)
            if "logout" not in res.text.lower():
                raise Exception("Авторизация не удалась (проверьте логин/пароль)")
            logger.info("Авторизация на AdminVPS прошла успешно.")
        except Exception as e:
            logger.error(f"Ошибка логина: {e}")
            sys.exit(1)

    def list_dns(self):
        resp = self.session.get(f"{self.api_url}&mg-action=editZone&zone_id={cfg['zone']}")
        soup = BeautifulSoup(resp.text, 'html.parser')
        dns_list = []
        
        for row in soup.find_all('tr', class_='record'):
            try:
                row_id = row.get('id', '').replace('record', '')
                res = {
                    "id": row_id,
                    "name": row.find('input', {'name': lambda x: x and '[name]' in x})['value'],
                    "type": row.find('input', {'name': lambda x: x and '[type]' in x})['value'],
                    "ttl": row.find('input', {'name': lambda x: x and '[ttl]' in x})['value'],
                }
                # Поиск значения (может быть в поле address или txtdata)
                val_inp = row.find('input', {'name': lambda x: x and ('[address]' in x or '[txtdata]' in x)})
                res["value"] = val_inp['value'] if val_inp else ""
                dns_list.append(res)
            except: continue
        return dns_list

    def add_record(self, name, validation):
        payload = {
            'zone_id': cfg['zone'], 'name': name, 'type': 'TXT', 'ttl': '3600',
            'field[txtdata]': f'"{validation}"', 'mg-action': 'addRecordSave'
        }
        self.session.post(f"{self.api_url}&json=1", data=payload)
        logger.info(f"Запись {name} добавлена. Ожидание 60 секунд...")
        time.sleep(60)

    def delete_record(self, name):
        records = self.list_dns()
        target = name if name.endswith('.') else f"{name}."
        found = [r for r in records if r['name'] == target and r['type'] == 'TXT']
        
        if not found:
            logger.warning(f"Записи для {name} не найдены.")
            return

        for rec in found:
            payload = {
                'zone_id': cfg['zone'], 'mg-action': 'removeRecord',
                f"record[{rec['id']}][name]": rec['name'],
                f"record[{rec['id']}][type]": 'TXT',
                f"record[{rec['id']}][line]": f"{rec['name']}|TXT|0"
            }
            self.session.post(f"{self.api_url}&json=1", data=payload)
            logger.info(f"Удалена запись ID {rec['id']} ({rec['name']})")

def main():
    if len(sys.argv) < 2:
        print("Использование: python script.py [auth|cleanup|list]")
        sys.exit(1)

    action = sys.argv[1]
    domain = os.environ.get('CERTBOT_DOMAIN', 'example.com')
    validation = os.environ.get('CERTBOT_VALIDATION', 'token')
    record_name = f"_acme-challenge.{domain}"

    dns_tool = AdminVPSDNS()
    dns_tool.login()

    if action == 'auth':
        dns_tool.add_record(record_name, validation)
    elif action == 'cleanup':
        dns_tool.delete_record(record_name)
    elif action == 'list':
        records = dns_tool.list_dns()
        print(tabulate(records, headers="keys", tablefmt="grid"))

if __name__ == "__main__":
    main()
