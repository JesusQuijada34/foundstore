"""
Sistema de notificaciones y eventos en tiempo real (SSE).

- Cada usuario autenticado tiene su propia cola de eventos en memoria.
- /api/events devuelve un stream SSE persistente.
- El bot de Telegram (o cualquier parte del codigo) puede llamar a
  notify_user(username, event) para empujar un evento al navegador
  de ese usuario en tiempo real.
- Si en el futuro hay multiples procesos, mover las colas a Redis pub/sub.
"""
import json
import queue
import threading
import time
from typing import Dict, Optional

_lock = threading.RLock()
_user_queues: Dict[str, "queue.Queue[str]"] = {}
_pending_offers: Dict[str, dict] = {}  # code -> {username, code, expires_at, telegram_id}


def _get_queue(username: str) -> "queue.Queue[str]":
    with _lock:
        if username not in _user_queues:
            _user_queues[username] = queue.Queue(maxsize=100)
        return _user_queues[username]


def publish(username: str, event_type: str, data: dict) -> bool:
    """
    Envia un evento SSE a un usuario. Si su cola esta llena, se descarta
    el evento mas viejo para no bloquear al publicador.
    """
    if not username:
        return False
    payload = json.dumps({"type": event_type, **data})
    q = _get_queue(username)
    with _lock:
        try:
            q.put_nowait(payload)
            return True
        except queue.Full:
            try:
                q.get_nowait()  # descartar el mas viejo
                q.put_nowait(payload)
                return True
            except Exception:
                return False


def notify_user(username: str, *, title: str, desc: str = "",
                icon: str = "info", toast: bool = True, link: str = None) -> bool:
    """Helper de alto nivel: publica una notificacion + toast."""
    return publish(username, "notification", {
        "title": title,
        "desc": desc,
        "type": icon,
        "toast": toast,
        "link": link,
        "ts": int(time.time() * 1000),
        "id": f"n_{int(time.time()*1000)}_{username}",
        "unread": True,
    })


def stream_for(username: str):
    """
    Generador SSE. Mantiene la conexion abierta y yield-a los eventos
    publicados a este usuario. Envia un ping cada 25s para que el proxy
    no cierre la conexion.
    """
    q = _get_queue(username)
    last_ping = time.time()
    # mensaje inicial de "conectado"
    yield f"event: connected\ndata: {json.dumps({'user': username, 'ts': int(time.time()*1000)})}\n\n"
    while True:
        try:
            payload = q.get(timeout=20)
            yield f"event: notification\ndata: {payload}\n\n"
            last_ping = time.time()
        except queue.Empty:
            # keep-alive
            if time.time() - last_ping > 25:
                yield f"event: ping\ndata: {int(time.time()*1000)}\n\n"
                last_ping = time.time()


# =====================================================================
# Sistema de codigos de verificacion (web -> Telegram -> web)
# =====================================================================
import secrets
import os
import time as _time

CODE_TTL_SECONDS = 5 * 60       # el codigo vive 5 minutos
VERIFIED_TTL_SECONDS = 24 * 3600  # una vez verificado, dura 24h


def _codes_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "verification_codes.jsonl")


def issue_code(github_username: str, telegram_id: int = None) -> str:
    """
    Genera un codigo de 6 digitos, lo asocia al usuario y lo persiste.
    Devuelve el codigo (en texto plano, el bot lo manda al usuario).
    """
    code = f"{secrets.randbelow(1000000):06d}"
    entry = {
        "github_username": github_username,
        "telegram_id": telegram_id,
        "code": code,
        "issued_at": int(_time.time()),
        "expires_at": int(_time.time()) + CODE_TTL_SECONDS,
        "used": False,
    }
    with _lock:
        _pending_offers[code] = entry
    _persist_codes()
    return code


def _persist_codes():
    """Vuelca las ofertas pendientes (no expiradas) a disco."""
    now = int(_time.time())
    # limpiar expirados
    with _lock:
        expired = [c for c, e in _pending_offers.items() if e.get("expires_at", 0) < now]
        for c in expired:
            del _pending_offers[c]
        rows = list(_pending_offers.values())
    try:
        with open(_codes_path(), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    except Exception:
        pass


def _load_codes():
    """Carga los codigos pendientes desde disco al arrancar."""
    path = _codes_path()
    if not os.path.exists(path):
        return
    now = int(_time.time())
    with _lock:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        e = json.loads(line)
                        if e.get("expires_at", 0) > now and not e.get("used"):
                            _pending_offers[e["code"]] = e
                    except Exception:
                        continue
        except Exception:
            pass


def consume_code(github_username: str, code: str) -> bool:
    """
    Valida un codigo. Lo marca como usado y devuelve True si era valido.
    """
    code = (code or "").strip()
    if not code:
        return False
    now = int(_time.time())
    with _lock:
        entry = _pending_offers.get(code)
        if not entry:
            return False
        if entry.get("used"):
            return False
        if entry.get("expires_at", 0) < now:
            del _pending_offers[code]
            _persist_codes()
            return False
        if entry.get("github_username", "").lower() != (github_username or "").lower():
            return False
        entry["used"] = True
        entry["used_at"] = now
        del _pending_offers[code]
    _persist_codes()
    return True


def pending_code_for(username: str) -> Optional[dict]:
    """Devuelve el codigo pendiente mas reciente del usuario (si hay)."""
    name = (username or "").lower()
    now = int(_time.time())
    candidates = [e for e in _pending_offers.values()
                  if e.get("github_username", "").lower() == name
                  and not e.get("used")
                  and e.get("expires_at", 0) > now]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e.get("issued_at", 0))


# Carga inicial
_load_codes()
