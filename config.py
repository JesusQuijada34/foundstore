import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    GITHUB_OAUTH_CLIENT_ID = os.environ.get('GITHUB_OAUTH_CLIENT_ID')
    GITHUB_OAUTH_CLIENT_SECRET = os.environ.get('GITHUB_OAUTH_CLIENT_SECRET')
    ONDEV_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ondev_accounts.list')
    CATALOG_PATH = os.path.join(os.path.dirname(__file__), 'data', 'catalog.json')
