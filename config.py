import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    GITHUB_OAUTH_CLIENT_ID = os.environ.get('GITHUB_OAUTH_CLIENT_ID')
    GITHUB_OAUTH_CLIENT_SECRET = os.environ.get('GITHUB_OAUTH_CLIENT_SECRET')
    
    # MongoDB
    MONGO_URI = os.environ.get('MONGO_URI')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    TELEGRAM_WIDGET_ID = os.environ.get('TELEGRAM_WIDGET_ID')

    ONDEV_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ondev_accounts.list')
    CATALOG_PATH = os.path.join(os.path.dirname(__file__), 'data', 'catalog.json')
