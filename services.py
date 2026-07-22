import json
import os
import requests
from config import Config
from pymongo import MongoClient
from pymongo.server_api import ServerApi

# Inicialización opcional de MongoDB
db = None
if Config.MONGO_URI:
    try:
        client = MongoClient(Config.MONGO_URI, server_api=ServerApi('1'))
        db = client.get_default_database()
        print("Conectado a MongoDB")
    except Exception as e:
        print(f"Error conectando a MongoDB: {e}")

def link_telegram_to_github(github_username, telegram_data):
    accounts = load_ondev_accounts()
    if github_username not in accounts:
        accounts[github_username] = {
            "github_username": github_username,
            "is_ondev": False,
            "packages": [],
            "followers": [],
            "following": []
        }
    
    accounts[github_username]["telegram_id"] = telegram_data.get("id")
    accounts[github_username]["telegram_username"] = telegram_data.get("username")
    accounts[github_username]["telegram_name"] = f"{telegram_data.get('first_name', '')} {telegram_data.get('last_name', '')}".strip()
    
    # Crear links predeterminados
    if "profile_override" not in accounts[github_username]:
        accounts[github_username]["profile_override"] = {
            "links": []
        }
    
    links = accounts[github_username]["profile_override"].get("links", [])
    # Evitar duplicados
    if not any(l['name'] == 'GitHub' for l in links):
        links.append({"name": "GitHub", "url": f"https://github.com/{github_username}"})
    if telegram_data.get("username") and not any(l['name'] == 'Telegram' for l in links):
        links.append({"name": "Telegram", "url": f"https://t.me/{telegram_data.get('username')}"})
    
    accounts[github_username]["profile_override"]["links"] = links
    
    # Guardar en MongoDB si está disponible
    if db is not None:
        try:
            db.users.update_one(
                {"github_username": github_username},
                {"$set": accounts[github_username]},
                upsert=True
            )
        except Exception as e:
            print(f"Error guardando en MongoDB: {e}")
            
    # Fallback local
    # Persistencia atómica para evitar corrupción de archivos
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    temp_path = f"{Config.ONDEV_DB_PATH}.tmp"
    try:
        with open(temp_path, 'w') as f:
            for acc in accounts.values():
                f.write(json.dumps(acc) + '\n')
        os.replace(temp_path, Config.ONDEV_DB_PATH)
    except Exception as e:
        print(f"Error en persistencia de datos: {e}")

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
    
    # Persistencia atómica para evitar corrupción de archivos
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    temp_path = f"{Config.ONDEV_DB_PATH}.tmp"
    try:
        with open(temp_path, 'w') as f:
            for acc in accounts.values():
                f.write(json.dumps(acc) + '\n')
        os.replace(temp_path, Config.ONDEV_DB_PATH)
    except Exception as e:
        print(f"Error en persistencia de datos: {e}")

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
    
    # Persistencia atómica para evitar corrupción de archivos
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    temp_path = f"{Config.ONDEV_DB_PATH}.tmp"
    try:
        with open(temp_path, 'w') as f:
            for acc in accounts.values():
                f.write(json.dumps(acc) + '\n')
        os.replace(temp_path, Config.ONDEV_DB_PATH)
    except Exception as e:
        print(f"Error en persistencia de datos: {e}")

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
    # Persistencia atómica para evitar corrupción de archivos
    os.makedirs(os.path.dirname(Config.ONDEV_DB_PATH), exist_ok=True)
    temp_path = f"{Config.ONDEV_DB_PATH}.tmp"
    try:
        with open(temp_path, 'w') as f:
            for acc in accounts.values():
                f.write(json.dumps(acc) + '\n')
        os.replace(temp_path, Config.ONDEV_DB_PATH)
    except Exception as e:
        print(f"Error en persistencia de datos: {e}")
            
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


# =====================================================================
# Catalogo global de paquetes Fluthin (misma logica que
# jesusquijada34.netlify.app / catalog repo, portada al backend)
# =====================================================================

GLOBAL_CATALOG_URL = "https://raw.githubusercontent.com/JesusQuijada34/catalog/refs/heads/main/repo.list"
GLOBAL_XML_PATH = "refs/heads/main/details.xml"
GLOBAL_RAW_BASE = "https://raw.githubusercontent.com/JesusQuijada34"

# Mismo mapeo usado por packagemaker (lib/github.py, lib/BuildThread.py, lib/cliHandler.py)
PLATFORM_TO_CATEGORY = {
    "Knosthalij": "Windows",
    "Danenone": "Linux/Mac",
    "AlphaCube": "Multiplataforma",
}

# Cache simple en memoria (evita golpear la API de GitHub en cada request)
_global_catalog_cache = {"data": [], "ts": 0}
_GLOBAL_CATALOG_TTL = 300  # segundos

_release_cache = {}
_RELEASE_TTL = 300


def _xml_text(node, tag):
    if node is None:
        return ""
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _fetch_app_details(repo):
    """
    Replica fetchApp() del front de Netlify: descarga details.xml del repo
    y lo lee EXACTAMENTE con los mismos campos e identificadores
    (publisher, app, name, version, correlationid, rate, author, platform).
    """
    import xml.etree.ElementTree as ET

    xml_url = f"{GLOBAL_RAW_BASE}/{repo}/{GLOBAL_XML_PATH}"
    try:
        res = requests.get(xml_url, timeout=10)
        if res.status_code != 200:
            return None
        root = ET.fromstring(res.text)
        node = root if root.tag == "app" else root.find(".//app")
        if node is None:
            return None

        app = {
            "repo": repo,
            "publisher": _xml_text(node, "publisher"),
            "packagename": _xml_text(node, "app"),
            "name": _xml_text(node, "name"),
            "version": _xml_text(node, "version"),
            "correlationid": _xml_text(node, "correlationid"),
            "rate": _xml_text(node, "rate"),
            "author": _xml_text(node, "author"),
            "platform": _xml_text(node, "platform"),
        }

        # Validacion de campos esenciales, igual que el front (fetchApp)
        required = ["name", "publisher", "author", "packagename", "version", "correlationid", "rate", "platform"]
        if not all(app.get(f) for f in required):
            return None

        app["category"] = PLATFORM_TO_CATEGORY.get(app["platform"], "Otros")
        app["icon"] = _resolve_icon_url(repo)
        app["splash"] = _resolve_splash_url(repo) or app["icon"]
        return app
    except Exception as e:
        print(f"[global_catalog] Error leyendo {repo}: {e}")
        return None


def _resolve_icon_url(repo):
    candidates = [
        f"{GLOBAL_RAW_BASE}/{repo}/main/app/app-icon.ico",
        f"{GLOBAL_RAW_BASE}/{repo}/main/assets/product_logo.png",
    ]
    for url in candidates:
        try:
            r = requests.head(url, timeout=5)
            if r.status_code == 200:
                return url
        except Exception:
            continue
    return None


def _resolve_splash_url(repo):
    url = f"{GLOBAL_RAW_BASE}/{repo}/main/assets/splash.png"
    try:
        r = requests.head(url, timeout=5)
        return url if r.status_code == 200 else None
    except Exception:
        return None


def get_global_fluthin_catalog(force_refresh=False):
    """
    Descubre todos los paquetes Fluthin (.iflapp) publicados por cualquier
    usuario, listados en el repo 'catalog/repo.list', y los identifica
    con la misma logica que usa la tienda web de Netlify.
    """
    import time
    now = time.time()
    if not force_refresh and _global_catalog_cache["data"] and (now - _global_catalog_cache["ts"] < _GLOBAL_CATALOG_TTL):
        return _global_catalog_cache["data"]

    apps = []
    try:
        res = requests.get(GLOBAL_CATALOG_URL, timeout=10)
        if res.status_code == 200:
            repos = [r.strip() for r in res.text.split(",") if r.strip()]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(_fetch_app_details, repos))
            apps = [a for a in results if a]
    except Exception as e:
        print(f"[global_catalog] Error cargando catalogo global: {e}")

    _global_catalog_cache["data"] = apps
    _global_catalog_cache["ts"] = now
    return apps


# =====================================================================
# Resolucion de descargas por plataforma (misma logica que
# packagemaker/lib/github.py, rama render)
# =====================================================================

FLUTHIN_PROTOCOL_BASE = "flarmstore://JesusQuijada34"


def detect_platform_key(user_agent_string):
    """
    Detecta la plataforma del visitante y la traduce a las claves internas
    que usa packagemaker: Knosthalij (Windows), Danenone (Linux/Mac),
    AlphaCube (Multiplataforma / desconocido).
    """
    ua = (user_agent_string or "").lower()
    if "windows" in ua:
        return "Knosthalij"
    if "linux" in ua and "android" not in ua:
        return "Danenone"
    if "mac os" in ua or "macintosh" in ua:
        return "Danenone"
    return "AlphaCube"


def get_latest_release(repo, token=None):
    """Igual que packagemaker/lib/github.py -> get_latest_release()"""
    import time
    cache_key = repo
    cached = _release_cache.get(cache_key)
    if cached and (time.time() - cached["ts"] < _RELEASE_TTL):
        return cached["data"]

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=headers, timeout=10)
        data = r.json() if r.status_code == 200 else None
        _release_cache[cache_key] = {"data": data, "ts": time.time()}
        return data
    except Exception as e:
        print(f"[releases] Error obteniendo release de {repo}: {e}")
        return None


def resolve_download_for_visitor(repo, user_agent_string, package_name=None):
    """
    Dado un repo con releases en GitHub, resuelve el asset correcto segun
    la plataforma desde la que se visita el sitio (misma heuristica que
    get_release_downloads() de packagemaker: busca 'windows'/'knosthalij'
    y 'linux'/'danenone' en el nombre de los assets).
    """
    platform_key = detect_platform_key(user_agent_string)
    release = get_latest_release(repo)

    fluthin_protocol_url = f"{FLUTHIN_PROTOCOL_BASE}.{package_name or repo}/"

    result = {
        "platform": platform_key,
        "category": PLATFORM_TO_CATEGORY.get(platform_key, "Otros"),
        "fluthin_url": fluthin_protocol_url,
        "direct_url": None,
        "asset_name": None,
        "release_tag": None,
    }

    if not release:
        return result

    result["release_tag"] = release.get("tag_name")
    assets = release.get("assets", [])
    windows_url, linux_url = None, None
    windows_name, linux_name = None, None

    for a in assets:
        n = a.get("name", "").lower()
        if "windows" in n or "knosthalij" in n:
            windows_url, windows_name = a["browser_download_url"], a["name"]
        elif "linux" in n or "danenone" in n or "mac" in n:
            linux_url, linux_name = a["browser_download_url"], a["name"]

    if platform_key == "Knosthalij":
        result["direct_url"], result["asset_name"] = windows_url, windows_name
    elif platform_key == "Danenone":
        result["direct_url"], result["asset_name"] = linux_url, linux_name
    else:  # AlphaCube / desconocido: preferir lo que haya disponible
        result["direct_url"] = windows_url or linux_url
        result["asset_name"] = windows_name or linux_name

    return result
