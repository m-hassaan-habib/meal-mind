import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY','dev')
DB_HOST = os.getenv('DB_HOST','127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT','3306'))
DB_NAME = os.getenv('DB_NAME','mealmind')
DB_USER = os.getenv('DB_USER','root')
DB_PASS = os.getenv('DB_PASS','')
COOLDOWN_DAYS = int(os.getenv('COOLDOWN_DAYS','4'))
SUGGESTION_TIME = os.getenv('SUGGESTION_TIME','19:00')
DEV_ROTATE_SECONDS = int(os.getenv('DEV_ROTATE_SECONDS','0'))
