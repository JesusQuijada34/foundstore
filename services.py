import json
import os
import requests
from config import Config

def load_ondev_accounts():
    accounts = {}
    if os.path.exists(Config.ONDEV_DB_PATH):
        with open(Config.ONDEV_DB_PATH, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    accounts[data['github_username']] = data
                except json.JSONDecodeError:
                    continue
    return accounts

def save_ondev_account(account_data):
    accounts = load_ondev_accounts()
    accounts[account_data['github_username']] = account_data
    
    with open(Config.ONDEV_DB_PATH, 'w') as f:
        for acc in accounts.values():
            f.write(json.dumps(acc) + '\n')

def get_github_user_profile(username, access_token=None):
    """
    Intenta obtener el perfil del desarrollador desde su repo 'ismyself'
    """
    url = f"https://api.github.com/repos/{username}/ismyself/contents/profile.json"
    headers = {}
    if access_token:
        headers['Authorization'] = f"token {access_token}"
    
    response = requests.get(url, headers=headers)
    if response.status_status == 200:
        import base64
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        return json.loads(content)
    return None

def get_catalog():
    if os.path.exists(Config.CATALOG_PATH):
        with open(Config.CATALOG_PATH, 'r') as f:
            return json.load(f)
    return {"packages": []}

def save_catalog(catalog_data):
    with open(Config.CATALOG_PATH, 'w') as f:
        json.dump(catalog_data, f, indent=4)
