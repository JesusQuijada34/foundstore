"""
storage.py - Capa de persistencia y cache para foundstore.

Modelos MongoDB (collections):
  - users:           cuenta de GitHub vinculada, con su telegram_id si lo tiene
  - otp_tokens:      codigos OTP activos (TTL index los borra al expirar)
  - linked_sessions: auditoria de vinculaciones (cuando se hizo, desde donde)
  - notifications:   bandeja de notificaciones en tiempo real (para SSE)

Cache L1 (in-process, TTL): para evitar pegar a Mongo en cada mensaje del bot
Cache L2 (MongoDB): persistencia real

Si MongoDB no esta disponible, todo cae a fallback JSONL (services.py)
para que la app siga funcionando.
"""
import json
import os
import time
import threading
import hashlib
import secrets
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone

from config import Config


# =====================================================================
# MongoDB (opcional, con reconexion y reintentos)
# =====================================================================
try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
    from pymongo.server_api import ServerApi
    from pymongo.errors import (
        ServerSelectionTimeoutError, ConfigurationError,
        OperationFailure, ConnectionFailure, AutoReconnect, DuplicateKeyError,
    )
    _MONGO_OK = True
except Exception:
    _MONGO_OK = False


class _Mongo:
    """Wrapper ligero sobre pymongo con reconexion y healthcheck."""
    def __init__(self):
        self.client = None
        self.db = None
        self.ok = False
        self.last_error = None
        self._lock = threading.RLock()
        self._connect()

    def _connect(self):
        if not Config.MONGO_URI or not _MONGO_OK:
            self.last_error = "MONGO_URI vacio o pymongo no instalado"
            return
        try:
            self.client = MongoClient(
                Config.MONGO_URI,
                server_api=ServerApi('1'),
                serverSelectionTimeoutMS=4000,
                connectTimeoutMS=4000,
                socketTimeoutMS=4000,
            )
            self.client.admin.command('ping')
            self.db = self.client.get_default_database()
            self.ok = True
            self.last_error = None
            self._ensure_indexes()
            print(f"[storage] Conectado a MongoDB OK")
        except ServerSelectionTimeoutError as e:
            self.last_error = f"Timeout: {e}"
        except ConfigurationError as e:
            self.last_error = f"Config: {e}"
        except OperationFailure as e:
            self.last_error = f"Permiso: {e}"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        if not self.ok:
            print(f"[storage] MongoDB no disponible: {self.last_error}")
            print(f"[storage] >> Usando fallback JSONL local.")

    def _ensure_indexes(self):
        """Crea los indices necesarios (idempotente)."""
        if not self.ok:
            return
        try:
            # users
            self.db.users.create_index("github_username", unique=True, name="ux_user_gh")
            self.db.users.create_index("telegram_id", name="ix_user_tg")
            # otp_tokens: TTL index en expires_at (borra auto tras expirar)
            self.db.otp_tokens.create_index("expires_at", expireAfterSeconds=0, name="ttl_otp")
            self.db.otp_tokens.create_index(
                [("github_username", ASCENDING), ("created_at", DESCENDING)],
                name="ix_otp_user"
            )
            self.db.otp_tokens.create_index("code_hash", name="ix_otp_hash")
            # linked_sessions
            self.db.linked_sessions.create_index([("github_username", ASCENDING), ("created_at", DESCENDING)], name="ix_sess_user")
            self.db.linked_sessions.create_index("telegram_id", name="ix_sess_tg")
            # notifications
            self.db.notifications.create_index([("user", ASCENDING), ("created_at", DESCENDING)], name="ix_notif_user")
            self.db.notifications.create_index("created_at", expireAfterSeconds=60*60*24*30, name="ttl_notif_30d")
        except Exception as e:
            print(f"[storage] Aviso creando indices: {e}")

    def reconnect(self):
        with self._lock:
            self._connect()

    def ping(self) -> bool:
        if not self.ok or self.client is None:
            self.reconnect()
        if not self.ok:
            return False
        try:
            self.client.admin.command('ping')
            return True
        except Exception:
            self.ok = False
            return False


mongo = _Mongo()


# =====================================================================
# Cache L1 - in-process, TTL
# =====================================================================
class TTLCache:
    """Cache L1 thread-safe con TTL por entrada. Usado para evitar pegar
    a Mongo en cada mensaje del bot."""

    def __init__(self, default_ttl: int = 60):
        self._d: Dict[str, Any] = {}
        self._exp: Dict[str, float] = {}
        self.default_ttl = default_ttl
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            exp = self._exp.get(key)
            if exp is None:
                return None
            if exp < time.time():
                self._d.pop(key, None)
                self._exp.pop(key, None)
                return None
            return self._d.get(key)

    def set(self, key: str, value: Any, ttl: int = None):
        with self._lock:
            self._d[key] = value
            self._exp[key] = time.time() + (ttl or self.default_ttl)

    def delete(self, key: str):
        with self._lock:
            self._d.pop(key, None)
            self._exp.pop(key, None)

    def clear(self, prefix: str = None):
        with self._lock:
            if prefix is None:
                self._d.clear(); self._exp.clear()
            else:
                for k in [k for k in self._d if k.startswith(prefix)]:
                    self._d.pop(k, None); self._exp.pop(k, None)


# Cache de vinculacion telegram_id -> github_user
# TTL corto (60s) porque el bot consulta en cada mensaje
linked_users_cache = TTLCache(default_ttl=60)

# Cache de username -> user doc (mas largo, 5 min)
user_docs_cache = TTLCache(default_ttl=300)

# Cache de codigos OTP activos por username
otp_cache = TTLCache(default_ttl=30)


# =====================================================================
# MODELOS / OPERACIONES
# =====================================================================

def _now_ts() -> int:
    return int(time.time())


def _hash_code(code: str) -> str:
    """Hash del codigo OTP para no guardarlo en claro en MongoDB."""
    return hashlib.sha256(f"fs-otp:{code}".encode()).hexdigest()


# === USERS ===

def upsert_user_from_github(github_username: str, profile: dict = None) -> Optional[dict]:
    """Crea o actualiza el user de GitHub. Devuelve el doc o None si Mongo no esta."""
    if not mongo.ok:
        return None
    try:
        doc = {
            "github_username": github_username,
            "updated_at": _now_ts(),
        }
        if profile:
            doc["profile"] = profile
        # No sobreescribir telegram_id si ya existe
        result = mongo.db.users.find_one_and_update(
            {"github_username": github_username},
            {"$set": doc, "$setOnInsert": {"created_at": _now_ts(), "telegram_id": None}},
            upsert=True,
            return_document=True,  # ReturnDocument.AFTER
        )
        user_docs_cache.delete(f"user:{github_username}")
        return result
    except Exception as e:
        print(f"[storage] upsert_user error: {e}")
        return None


def get_user(github_username: str) -> Optional[dict]:
    """Lee user con cache L1."""
    cache_key = f"user:{github_username}"
    cached = user_docs_cache.get(cache_key)
    if cached is not None:
        # Si el cache tiene un dict vacio, devolver None
        return cached if cached else None
    if not mongo.ok:
        return None
    try:
        doc = mongo.db.users.find_one({"github_username": github_username})
        if doc and "_id" in doc:
            try:
                doc["_id"] = str(doc["_id"])  # serializable
            except Exception:
                pass
        # Cachear incluso None por un rato para no martillar Mongo
        user_docs_cache.set(cache_key, doc or {}, ttl=300)
        return doc or None
    except Exception as e:
        print(f"[storage] get_user error: {e}")
        return None


def get_user_by_telegram_id(telegram_id: int) -> Optional[dict]:
    """Resuelve telegram_id -> github_username. Cacheado en L1."""
    cache_key = f"tg:{telegram_id}"
    cached = linked_users_cache.get(cache_key)
    if cached is not None:
        return cached
    if not mongo.ok:
        return None
    try:
        doc = mongo.db.users.find_one({"telegram_id": telegram_id, "is_active": {"$ne": False}})
        result = None
        if doc:
            result = {
                "github_username": doc["github_username"],
                "telegram_username": doc.get("telegram_username"),
                "telegram_name": doc.get("telegram_name"),
            }
        linked_users_cache.set(cache_key, result, ttl=60)
        return result
    except Exception as e:
        print(f"[storage] get_user_by_telegram_id error: {e}")
        return None


def link_telegram(github_username: str, telegram_id: int,
                  telegram_username: str = None, telegram_name: str = None) -> bool:
    """Asocia una cuenta de Telegram a un user de GitHub. Invalida caches."""
    if not mongo.ok:
        return False
    try:
        now = _now_ts()
        # 1) Quitar esta cuenta de Telegram de cualquier otro user
        mongo.db.users.update_many(
            {"telegram_id": telegram_id, "github_username": {"$ne": github_username}},
            {"$set": {"telegram_id": None, "updated_at": now}}
        )
        # 2) Asignar a este user
        mongo.db.users.update_one(
            {"github_username": github_username},
            {"$set": {
                "telegram_id": telegram_id,
                "telegram_username": telegram_username,
                "telegram_name": telegram_name,
                "linked_at": now,
                "is_active": True,
                "updated_at": now,
            }},
            upsert=True,
        )
        # 3) Auditoria
        mongo.db.linked_sessions.insert_one({
            "github_username": github_username,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "action": "linked",
            "created_at": now,
        })
        # 4) Invalidar caches
        linked_users_cache.delete(f"tg:{telegram_id}")
        user_docs_cache.delete(f"user:{github_username}")
        return True
    except Exception as e:
        print(f"[storage] link_telegram error: {e}")
        return False


def unlink_telegram(github_username: str) -> bool:
    """Desvincula la cuenta de Telegram de un user."""
    if not mongo.ok:
        return False
    try:
        now = _now_ts()
        user = mongo.db.users.find_one({"github_username": github_username})
        if not user or not user.get("telegram_id"):
            return True  # nada que hacer
        tg_id = user["telegram_id"]
        mongo.db.users.update_one(
            {"github_username": github_username},
            {"$set": {"telegram_id": None, "is_active": False, "updated_at": now}}
        )
        mongo.db.linked_sessions.insert_one({
            "github_username": github_username,
            "telegram_id": tg_id,
            "action": "unlinked",
            "created_at": now,
        })
        linked_users_cache.delete(f"tg:{tg_id}")
        user_docs_cache.delete(f"user:{github_username}")
        return True
    except Exception as e:
        print(f"[storage] unlink_telegram error: {e}")
        return False


def get_link_status(github_username: str) -> dict:
    """Devuelve el estado de vinculacion de un user para mostrar en /settings."""
    user = get_user(github_username) or {}
    sessions = []
    if mongo.ok:
        try:
            for s in mongo.db.linked_sessions.find(
                {"github_username": github_username}
            ).sort("created_at", -1).limit(10):
                s["_id"] = str(s["_id"])
                sessions.append(s)
        except Exception:
            pass
    return {
        "github_username": github_username,
        "telegram_id": user.get("telegram_id"),
        "telegram_username": user.get("telegram_username"),
        "telegram_name": user.get("telegram_name"),
        "linked_at": user.get("linked_at"),
        "is_active": user.get("is_active", False),
        "sessions": sessions,
    }


# === OTP TOKENS ===

def create_otp(github_username: str, ttl_seconds: int = 300) -> Optional[dict]:
    """
    Crea un codigo OTP de 6 digitos, guarda en Mongo con TTL auto-expiry,
    y en cache L1 para que el bot lo vea al instante.
    Devuelve {code, expires_at, ttl} o None.
    """
    if not mongo.ok:
        return None
    try:
        code = f"{secrets.randbelow(1000000):06d}"
        now = _now_ts()
        expires_at = now + ttl_seconds
        doc = {
            "github_username": github_username,
            "code_hash": _hash_code(code),
            "created_at": now,
            "expires_at": expires_at,
            "used": False,
            "attempts": 0,
        }
        # Inserta (puede haber varios activos por user, el bot usa el mas reciente)
        mongo.db.otp_tokens.insert_one(doc)
        # Cache para que el bot lo vea sin pegar a Mongo
        otp_cache.set(f"otp:{github_username}", {
            "code_hash": _hash_code(code),
            "expires_at": expires_at,
        }, ttl=ttl_seconds)
        return {
            "code": code,
            "expires_at": expires_at,
            "ttl": ttl_seconds,
        }
    except Exception as e:
        print(f"[storage] create_otp error: {e}")
        return None


def consume_otp(github_username: str, code: str) -> dict:
    """
    Valida y consume un codigo OTP. Devuelve:
      {"ok": True} si valido
      {"ok": False, "error": "..."} si invalido
    Maneja rate-limit: max 5 intentos por codigo.
    """
    if not mongo.ok:
        return {"ok": False, "error": "storage_unavailable"}

    code = (code or "").strip()
    if not code or len(code) != 6 or not code.isdigit():
        return {"ok": False, "error": "invalid_format"}

    now = _now_ts()
    code_hash = _hash_code(code)

    # Buscar el codigo activo mas reciente para este user
    try:
        otp = mongo.db.otp_tokens.find_one({
            "github_username": github_username,
            "used": False,
            "expires_at": {"$gt": now},
        }, sort=[("created_at", -1)])

        if not otp:
            return {"ok": False, "error": "no_active_code"}

        if otp.get("attempts", 0) >= 5:
            return {"ok": False, "error": "too_many_attempts"}

        if otp["code_hash"] != code_hash:
            # Incrementar intentos (incluso si era un codigo vacio)
            mongo.db.otp_tokens.update_one(
                {"_id": otp["_id"]},
                {"$inc": {"attempts": 1}}
            )
            return {"ok": False, "error": "invalid_code"}

        # OK - marcar usado
        mongo.db.otp_tokens.update_one(
            {"_id": otp["_id"]},
            {"$set": {"used": True, "used_at": now}}
        )
        otp_cache.delete(f"otp:{github_username}")
        return {"ok": True, "otp_id": str(otp["_id"])}
    except Exception as e:
        print(f"[storage] consume_otp error: {e}")
        return {"ok": False, "error": "storage_error"}


def consume_otp_by_hash(code: str) -> dict:
    """
    Variante usada por el bot: valida el codigo buscando por HASH en
    TODOS los usuarios activos (no necesita saber el username de antemano).
    Maneja el rate-limit de 5 intentos por codigo.
    """
    if not mongo.ok:
        return {"ok": False, "error": "storage_unavailable"}
    code = (code or "").strip()
    if not code or len(code) != 6 or not code.isdigit():
        return {"ok": False, "error": "invalid_format"}
    now = _now_ts()
    code_hash = _hash_code(code)
    try:
        otp = mongo.db.otp_tokens.find_one({
            "code_hash": code_hash,
            "used": False,
            "expires_at": {"$gt": now},
        })
        if not otp:
            return {"ok": False, "error": "no_active_code"}
        if otp.get("attempts", 0) >= 5:
            return {"ok": False, "error": "too_many_attempts"}
        # OK
        mongo.db.otp_tokens.update_one(
            {"_id": otp["_id"]},
            {"$set": {"used": True, "used_at": now, "telegram_id": None}}
        )
        return {
            "ok": True,
            "github_username": otp["github_username"],
            "otp_id": str(otp["_id"]),
        }
    except Exception as e:
        print(f"[storage] consume_otp_by_hash error: {e}")
        return {"ok": False, "error": "storage_error"}


def increment_otp_attempts(code: str) -> None:
    """Incrementa el contador de intentos de un codigo (rate-limit)."""
    if not mongo.ok: return
    try:
        h = _hash_code(code)
        mongo.db.otp_tokens.update_one(
            {"code_hash": h, "used": False},
            {"$inc": {"attempts": 1}}
        )
    except Exception:
        pass


def get_active_otp(github_username: str) -> Optional[dict]:
    """Devuelve el codigo OTP activo de un user (para el bot, sin el codigo en si)."""
    if not mongo.ok:
        return None
    try:
        return mongo.db.otp_tokens.find_one({
            "github_username": github_username,
            "used": False,
            "expires_at": {"$gt": _now_ts()},
        }, sort=[("created_at", -1)], projection={"code_hash": 0})
    except Exception:
        return None


# === NOTIFICATIONS (bandeja persistente) ===

def push_notification(user: str, *, title: str, desc: str = "",
                      icon: str = "info", link: str = None) -> Optional[dict]:
    """Guarda una notificacion en Mongo y la devuelve."""
    if not mongo.ok or not user:
        return None
    try:
        doc = {
            "user": user,
            "title": title,
            "desc": desc,
            "icon": icon,
            "link": link,
            "read": False,
            "created_at": _now_ts(),
        }
        result = mongo.db.notifications.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc
    except Exception as e:
        print(f"[storage] push_notification error: {e}")
        return None


def list_notifications(user: str, limit: int = 30, only_unread: bool = False) -> List[dict]:
    if not mongo.ok or not user:
        return []
    try:
        q = {"user": user}
        if only_unread:
            q["read"] = False
        cur = mongo.db.notifications.find(q).sort("created_at", -1).limit(limit)
        out = []
        for d in cur:
            d["_id"] = str(d["_id"])
            out.append(d)
        return out
    except Exception:
        return []


def mark_notifications_read(user: str, ids: List[str] = None) -> int:
    if not mongo.ok or not user:
        return 0
    try:
        q = {"user": user, "read": False}
        if ids:
            q["_id"] = {"$in": [ObjectId(i) for i in ids if len(i) == 24]}
        result = mongo.db.notifications.update_many(q, {"$set": {"read": True, "read_at": _now_ts()}})
        return result.modified_count
    except Exception:
        return 0


# Para ObjectId cuando se busca por _id
try:
    from bson import ObjectId
except Exception:
    class ObjectId:
        def __init__(self, s): self.s = s
        def __eq__(self, o): return isinstance(o, ObjectId) and self.s == o.s
        def __hash__(self): return hash(self.s)


# =====================================================================
# HEALTH
# =====================================================================
def health() -> dict:
    return {
        "mongo_enabled": bool(Config.MONGO_URI),
        "mongo_ok": mongo.ok,
        "mongo_error": mongo.last_error,
        "cache_l1_linked_users": len(linked_users_cache._d),
        "cache_l1_user_docs": len(user_docs_cache._d),
        "cache_l1_otp": len(otp_cache._d),
    }
