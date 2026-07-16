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
                    # Asegurar campos de seguidores si no existen
                    if 'followers' not in data: data['followers'] = []
                    if 'following' not in data: data['following'] = []
                    accounts[data['github_username']] = data
                except json.JSONDecodeError:
                    continue
    return accounts

def save_ondev_account(account_data):
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    accounts = load_ondev_accounts()
    # Mantener seguidores y seguidos existentes si ya existen
    if account_data['github_username'] in accounts:
        existing = accounts[account_data['github_username']]
        account_data['followers'] = account_data.get('followers', existing.get('followers', []))
        account_data['following'] = account_data.get('following', existing.get('following', []))
    else:
        account_data['followers'] = account_data.get('followers', [])
        account_data['following'] = account_data.get('following', [])
        
    accounts[account_data['github_username']] = account_data
    
    with open(Config.ONDEV_DB_PATH, 'w') as f:
        for acc in accounts.values():
            f.write(json.dumps(acc) + '\n')

def update_local_profile(username, profile_data):
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    accounts = load_ondev_accounts()
    if username not in accounts:
        accounts[username] = {
            "github_username": username,
            "is_ondev": False,
            "packages": [],
            "followers": [],
            "following": []
        }
    
    accounts[username]["profile_override"] = profile_data
    
    with open(Config.ONDEV_DB_PATH, 'w') as f:
        for acc in accounts.values():
            f.write(json.dumps(acc) + '\n')

def get_local_profile(username):
    accounts = load_ondev_accounts()
    if username in accounts:
        return accounts[username].get("profile_override")
    return None

def toggle_follow(follower_username, target_username):
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    accounts = load_ondev_accounts()
    
    # Asegurar que ambos existan en la DB local (aunque sean perfiles básicos)
    for user in [follower_username, target_username]:
        if user not in accounts:
            accounts[user] = {
                "github_username": user,
                "is_ondev": False,
                "packages": [],
                "followers": [],
                "following": []
            }
    
    follower = accounts[follower_username]
    target = accounts[target_username]
    
    if follower_username in target['followers']:
        # Dejar de seguir
        target['followers'].remove(follower_username)
        follower['following'].remove(target_username)
        action = "unfollowed"
    else:
        # Seguir
        target['followers'].append(follower_username)
        follower['following'].append(target_username)
        action = "followed"
        
    # Guardar cambios
    with open(Config.ONDEV_DB_PATH, 'w') as f:
        for acc in accounts.values():
            f.write(json.dumps(acc) + '\n')
            
    return action, len(target['followers'])

def get_github_user_profile(username, access_token=None):
    """
    Intenta obtener el perfil del desarrollador desde su repo 'ismyself'
    """
    url = f"https://api.github.com/repos/{username}/ismyself/contents/profile.json"
    headers = {}
    if access_token:
        headers['Authorization'] = f"token {access_token}"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        import base64
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        return json.loads(content)
    return None

def get_catalog(username="JesusQuijada34"):
    """
    Obtiene el catálogo desde el repositorio 'ismyself' del usuario principal.
    """
    url = f"https://api.github.com/repos/{username}/ismyself/contents/catalog.json"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            import base64
            content = base64.b64decode(response.json()['content']).decode('utf-8')
            return json.loads(content)
    except Exception as e:
        print(f"Error cargando catálogo: {e}")
    
    # Fallback al catálogo local si falla el remoto
    if os.path.exists(Config.CATALOG_PATH):
        with open(Config.CATALOG_PATH, 'r') as f:
            return json.load(f)
    return {"packages": []}

def save_catalog(catalog_data):
    os.makedirs(os.path.dirname(Config.CATALOG_PATH), exist_ok=True)
    with open(Config.CATALOG_PATH, 'w') as f:
        json.dump(catalog_data, f, indent=4)
