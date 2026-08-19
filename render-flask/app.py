"""Foundstore Flask service for the `render` branch.

This service is intentionally separate from the React/tRPC application on `main`.
It exposes a direct public catalog route plus a small, authenticated DaneDesk agent
API. Device commands are delivered through one long-poll request at a time, not
through a busy loop.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, render_template, request

CATALOG_OWNER = os.environ.get("CATALOG_OWNER", "JesusQuijada34")
CATALOG_REPOSITORY = os.environ.get("CATALOG_REPOSITORY", "catalog")
DEFAULT_LONG_POLL_SECONDS = 25
MAX_LONG_POLL_SECONDS = 25
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def device_command_key(master_key: str, device_id: str) -> str:
    return hmac.new(master_key.encode("utf-8"), device_id.encode("utf-8"), hashlib.sha256).hexdigest()


def command_signature(command_key: str, command: dict[str, Any]) -> str:
    signed = {key: command.get(key) for key in ("id", "deviceId", "type", "payload", "expiresAt")}
    canonical = json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(command_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def category_for(slug: str, description: str | None = None, topics: list[str] | None = None) -> str:
    candidate = f"{slug} {description or ''} {' '.join(topics or [])}".lower()
    if any(word in candidate for word in ("emoji", "twemoji", "noto")):
        return "Emojis"
    if any(word in candidate for word in ("camera", "reels", "media", "video", "audio", "vlc", "download", "insta")):
        return "Multimedia"
    if any(word in candidate for word in ("python", "code", "packagemaker", "leviathan", "webnode", "git", "editor", "math", "developer")):
        return "Desarrollo"
    if any(word in candidate for word in ("settings", "system", "debian", "dane", "energy", "flarm", "handler", "desktop", "panel")):
        return "Sistema"
    return "Utilidades"


def title_for(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


class DeviceStore(Protocol):
    backend_name: str

    def create_pairing_code(self, display_name: str, restore_apps: list[dict[str, str]]) -> dict[str, Any]: ...
    def claim_device(self, code: str, display_name: str) -> dict[str, Any] | None: ...
    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None: ...
    def pending_commands(self, device_id: str) -> list[dict[str, Any]]: ...
    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any]) -> dict[str, Any] | None: ...
    def update_heartbeat(self, device_id: str, location: dict[str, float] | None) -> bool: ...
    def restore_apps(self, device_id: str) -> list[dict[str, str]]: ...
    def list_devices(self) -> list[dict[str, Any]]: ...
    def record_event(self, device_id: str, topic: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def events_after(self, device_id: str, after: str | None) -> list[dict[str, Any]]: ...
    def maintain(self) -> dict[str, int]: ...


class LocalStore:
    """SQLite fallback. Attach Render's paid persistent disk to DATA_DIR for durability."""

    backend_name = "sqlite-fallback"

    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "foundstore-render.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                  code_hash TEXT PRIMARY KEY,
                  display_name TEXT NOT NULL,
                  restore_apps_json TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS devices (
                  id TEXT PRIMARY KEY,
                  display_name TEXT NOT NULL,
                  agent_token_hash TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'active',
                  location_protection INTEGER NOT NULL DEFAULT 1,
                  last_seen_at TEXT NOT NULL,
                  location_json TEXT,
                  restore_apps_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                  id TEXT PRIMARY KEY,
                  device_id TEXT NOT NULL,
                  command_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  expires_at TEXT NOT NULL,
                  delivered_at TEXT,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_events (
                  id TEXT PRIMARY KEY,
                  device_id TEXT NOT NULL,
                  topic TEXT NOT NULL,
                  data_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_device_events_device_time
                  ON device_events(device_id, created_at);
                """
            )

    def create_pairing_code(self, display_name: str, restore_apps: list[dict[str, str]]) -> dict[str, Any]:
        code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
        expires_at = utc_now() + timedelta(minutes=10)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pairing_codes(code_hash, display_name, restore_apps_json, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(code), display_name, json.dumps(restore_apps), expires_at.isoformat()),
            )
        return {"code": code, "expiresAt": expires_at.isoformat()}

    def claim_device(self, code: str, display_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            pair = conn.execute("SELECT * FROM pairing_codes WHERE code_hash = ?", (token_hash(code),)).fetchone()
            if not pair or pair["used_at"] or parse_iso(pair["expires_at"]) <= utc_now():
                return None
            device_id = secrets.token_urlsafe(18)
            agent_token = secrets.token_urlsafe(32)
            now = iso_now()
            conn.execute(
                """INSERT INTO devices(id, display_name, agent_token_hash, last_seen_at, restore_apps_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (device_id, display_name, token_hash(agent_token), now, pair["restore_apps_json"]),
            )
            conn.execute("UPDATE pairing_codes SET used_at = ? WHERE code_hash = ?", (now, token_hash(code)))
        self.record_event(device_id, "device.paired", {"displayName": display_name})
        return {"id": device_id, "agentToken": agent_token, "platform": "Danenone"}

    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            device = conn.execute(
                "SELECT * FROM devices WHERE id = ? AND agent_token_hash = ? AND status != 'revoked'",
                (device_id, token_hash(agent_token)),
            ).fetchone()
            if not device:
                return None
            conn.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (iso_now(), device_id))
            return dict(device)

    def pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        now = iso_now()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM commands WHERE device_id = ? AND status = 'pending' AND expires_at > ?
                   ORDER BY created_at ASC""",
                (device_id, now),
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            if identifiers:
                conn.executemany("UPDATE commands SET status = 'delivered', delivered_at = ? WHERE id = ?", [(now, item) for item in identifiers])
                conn.executemany(
                    "INSERT INTO device_events(id, device_id, topic, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    [(secrets.token_urlsafe(18), device_id, "command.delivered", json.dumps({"commandId": item}), now) for item in identifiers],
                )
        return [{"id": row["id"], "type": row["command_type"], "payload": json.loads(row["payload_json"]), "expiresAt": row["expires_at"]} for row in rows]

    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._connect() as conn:
            device = conn.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not device:
                return None
            command_id = secrets.token_urlsafe(18)
            expires_at = utc_now() + timedelta(minutes=5)
            conn.execute(
                """INSERT INTO commands(id, device_id, command_type, payload_json, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (command_id, device_id, command_type, json.dumps(payload), expires_at.isoformat(), iso_now()),
            )
            conn.execute(
                "INSERT INTO device_events(id, device_id, topic, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (secrets.token_urlsafe(18), device_id, "command.queued", json.dumps({"commandId": command_id, "type": command_type}), iso_now()),
            )
        return {"id": command_id, "expiresAt": expires_at.isoformat()}

    def update_heartbeat(self, device_id: str, location: dict[str, float] | None) -> bool:
        with self._connect() as conn:
            device = conn.execute("SELECT location_protection, status FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not device:
                return False
            stored_location = json.dumps(location) if location and device["location_protection"] and device["status"] == "lost" else None
            conn.execute("UPDATE devices SET last_seen_at = ?, location_json = COALESCE(?, location_json) WHERE id = ?", (iso_now(), stored_location, device_id))
        return True

    def restore_apps(self, device_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            row = conn.execute("SELECT restore_apps_json FROM devices WHERE id = ?", (device_id,)).fetchone()
        return json.loads(row["restore_apps_json"]) if row else []

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, display_name, status, location_protection, last_seen_at FROM devices ORDER BY last_seen_at DESC").fetchall()
        return [{"id": row["id"], "displayName": row["display_name"], "status": row["status"], "locationProtection": bool(row["location_protection"]), "lastSeenAt": row["last_seen_at"]} for row in rows]

    def record_event(self, device_id: str, topic: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"id": secrets.token_urlsafe(18), "topic": topic, "data": data, "createdAt": iso_now()}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO device_events(id, device_id, topic, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event["id"], device_id, topic, json.dumps(data), event["createdAt"]),
            )
        return event

    def events_after(self, device_id: str, after: str | None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, topic, data_json, created_at FROM device_events WHERE device_id = ? AND created_at > ? ORDER BY created_at ASC LIMIT 100",
                (device_id, after or ""),
            ).fetchall()
        return [{"id": row["id"], "topic": row["topic"], "data": json.loads(row["data_json"]), "createdAt": row["created_at"]} for row in rows]

    def maintain(self) -> dict[str, int]:
        now = iso_now()
        with self._connect() as conn:
            pairings = conn.execute("DELETE FROM pairing_codes WHERE used_at IS NOT NULL OR expires_at <= ?", (now,)).rowcount
            commands = conn.execute("DELETE FROM commands WHERE expires_at <= ?", (now,)).rowcount
        return {"expiredPairingCodes": pairings, "expiredCommands": commands}


class MongoStore:
    backend_name = "mongodb"

    def __init__(self, uri: str, database_name: str):
        from pymongo import MongoClient

        self.client = MongoClient(uri, connectTimeoutMS=5_000, serverSelectionTimeoutMS=5_000)
        self.client.admin.command("ping")
        self.db = self.client[database_name]
        self.db.pairing_codes.create_index("expiresAt", expireAfterSeconds=0)
        self.db.commands.create_index("expiresAt", expireAfterSeconds=0)
        self.db.device_events.create_index([("deviceId", 1), ("createdAt", 1)])

    def create_pairing_code(self, display_name: str, restore_apps: list[dict[str, str]]) -> dict[str, Any]:
        code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
        expires_at = utc_now()
        expires_at += timedelta(minutes=10)
        self.db.pairing_codes.insert_one({"codeHash": token_hash(code), "displayName": display_name, "restoreApps": restore_apps, "expiresAt": expires_at, "usedAt": None})
        return {"code": code, "expiresAt": expires_at.isoformat()}

    def claim_device(self, code: str, display_name: str) -> dict[str, Any] | None:
        pair = self.db.pairing_codes.find_one_and_update(
            {"codeHash": token_hash(code), "usedAt": None, "expiresAt": {"$gt": utc_now()}},
            {"$set": {"usedAt": utc_now()}},
        )
        if not pair:
            return None
        device_id = secrets.token_urlsafe(18)
        agent_token = secrets.token_urlsafe(32)
        self.db.devices.insert_one({"id": device_id, "displayName": display_name, "agentTokenHash": token_hash(agent_token), "status": "active", "locationProtection": True, "lastSeenAt": utc_now(), "restoreApps": pair.get("restoreApps", [])})
        self.record_event(device_id, "device.paired", {"displayName": display_name})
        return {"id": device_id, "agentToken": agent_token, "platform": "Danenone"}

    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None:
        device = self.db.devices.find_one_and_update({"id": device_id, "agentTokenHash": token_hash(agent_token), "status": {"$ne": "revoked"}}, {"$set": {"lastSeenAt": utc_now()}}, return_document=True)
        return device

    def pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        now = utc_now()
        commands = list(self.db.commands.find({"deviceId": device_id, "status": "pending", "expiresAt": {"$gt": now}}).sort("createdAt", 1))
        identifiers = [command["id"] for command in commands]
        if identifiers:
            self.db.commands.update_many({"id": {"$in": identifiers}}, {"$set": {"status": "delivered", "deliveredAt": now}})
            self.db.device_events.insert_many([{"id": secrets.token_urlsafe(18), "deviceId": device_id, "topic": "command.delivered", "data": {"commandId": item}, "createdAt": now} for item in identifiers])
        return [{"id": command["id"], "type": command["type"], "payload": command["payload"], "expiresAt": command["expiresAt"].isoformat()} for command in commands]

    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.db.devices.find_one({"id": device_id}, {"_id": 1}):
            return None
        command_id = secrets.token_urlsafe(18)
        expires_at = utc_now() + timedelta(minutes=5)
        self.db.commands.insert_one({"id": command_id, "deviceId": device_id, "type": command_type, "payload": payload, "status": "pending", "createdAt": utc_now(), "expiresAt": expires_at})
        self.record_event(device_id, "command.queued", {"commandId": command_id, "type": command_type})
        return {"id": command_id, "expiresAt": expires_at.isoformat()}

    def update_heartbeat(self, device_id: str, location: dict[str, float] | None) -> bool:
        device = self.db.devices.find_one({"id": device_id}, {"status": 1, "locationProtection": 1})
        if not device:
            return False
        update: dict[str, Any] = {"lastSeenAt": utc_now()}
        if location and device.get("locationProtection") and device.get("status") == "lost":
            update["lastKnownLocation"] = location
        self.db.devices.update_one({"id": device_id}, {"$set": update})
        return True

    def restore_apps(self, device_id: str) -> list[dict[str, str]]:
        row = self.db.devices.find_one({"id": device_id}, {"restoreApps": 1})
        return row.get("restoreApps", []) if row else []

    def list_devices(self) -> list[dict[str, Any]]:
        rows = self.db.devices.find({}, {"_id": 0, "id": 1, "displayName": 1, "status": 1, "locationProtection": 1, "lastSeenAt": 1}).sort("lastSeenAt", -1)
        return [{**row, "lastSeenAt": row["lastSeenAt"].isoformat()} for row in rows]

    def record_event(self, device_id: str, topic: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"id": secrets.token_urlsafe(18), "deviceId": device_id, "topic": topic, "data": data, "createdAt": utc_now()}
        self.db.device_events.insert_one(event)
        return {**event, "createdAt": event["createdAt"].isoformat()}

    def events_after(self, device_id: str, after: str | None) -> list[dict[str, Any]]:
        criteria: dict[str, Any] = {"deviceId": device_id}
        if after:
            criteria["createdAt"] = {"$gt": parse_iso(after)}
        rows = self.db.device_events.find(criteria, {"_id": 0}).sort("createdAt", 1).limit(100)
        return [{**row, "createdAt": row["createdAt"].isoformat()} for row in rows]

    def maintain(self) -> dict[str, int]:
        now = utc_now()
        pairings = self.db.pairing_codes.delete_many({"$or": [{"usedAt": {"$ne": None}}, {"expiresAt": {"$lte": now}}]}).deleted_count
        commands = self.db.commands.delete_many({"expiresAt": {"$lte": now}}).deleted_count
        return {"expiredPairingCodes": pairings, "expiredCommands": commands}


def build_store(config: dict[str, Any]) -> DeviceStore:
    mongo_uri = config.get("MONGODB_URI")
    if mongo_uri:
        try:
            return MongoStore(mongo_uri, config["MONGO_DATABASE"])
        except Exception as error:  # fallback remains deliberate and visible in /healthz
            config["MONGO_FALLBACK_REASON"] = type(error).__name__
    return LocalStore(config["DATA_DIR"])


def catalog_snapshot() -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Foundstore-Flask-Render"}

    def github(path: str) -> Any:
        with urlopen(Request(f"https://api.github.com{path}", headers=headers), timeout=10) as response:  # nosec B310: fixed GitHub API origin
            return json.load(response)

    catalog_file = github(f"/repos/{CATALOG_OWNER}/{CATALOG_REPOSITORY}/contents/repo.list?ref=main")
    slugs = [item.strip() for item in base64.b64decode(catalog_file["content"]).decode("utf-8").split(",") if item.strip()]
    repositories = {item["name"].lower(): item for item in github(f"/users/{CATALOG_OWNER}/repos?per_page=100&sort=updated")}
    packages: list[dict[str, Any]] = []
    for slug in slugs:
        repository = repositories.get(slug.lower(), {})
        description = repository.get("description")
        topics = repository.get("topics", [])
        packages.append({"slug": slug, "name": title_for(slug), "author": CATALOG_OWNER, "description": description, "category": category_for(slug, description, topics), "tags": topics, "repositoryUrl": repository.get("html_url", f"https://github.com/{CATALOG_OWNER}/{slug}"), "updatedAt": repository.get("updated_at")})
    packages.sort(key=lambda item: item["name"].lower())
    return {"packages": packages, "fetchedAt": iso_now(), "source": "GitHub API"}


def owner_authorized(app: Flask) -> bool:
    required = app.config.get("OWNER_API_TOKEN")
    supplied = request.headers.get("X-Foundstore-Owner-Token", "")
    return bool(required and supplied and secrets.compare_digest(required, supplied))


def agent_token() -> str:
    return request.headers.get("X-Danenone-Agent-Token", "")


def long_poll_seconds() -> int | None:
    try:
        return min(max(int(request.args.get("wait", DEFAULT_LONG_POLL_SECONDS)), 0), MAX_LONG_POLL_SECONDS)
    except ValueError:
        return None


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("DATA_DIR", "/var/data" if os.environ.get("RENDER") else "./var"),
        MONGODB_URI=os.environ.get("MONGODB_URI"),
        MONGO_DATABASE=os.environ.get("MONGO_DATABASE", "foundstore"),
        OWNER_API_TOKEN=os.environ.get("OWNER_API_TOKEN", ""),
        COMMAND_SIGNING_KEY=os.environ.get("COMMAND_SIGNING_KEY", "development-command-signing-key"),
        MONGO_FALLBACK_REASON=None,
    )
    if test_config:
        app.config.update(test_config)
    app.extensions["device_store"] = build_store(app.config)

    @app.get("/")
    def index() -> str:
        return render_template("index.html", catalog_owner=CATALOG_OWNER)

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok", "storage": app.extensions["device_store"].backend_name, "mongoFallbackReason": app.config.get("MONGO_FALLBACK_REASON"), "serverTime": iso_now()})

    @app.get("/api/v1/catalog")
    def catalog() -> Response:
        try:
            return jsonify(catalog_snapshot())
        except Exception as error:
            return jsonify({"error": "No se pudo obtener el catálogo de GitHub", "detail": type(error).__name__}), 502

    @app.get("/api/v1/devices")
    def devices() -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "No autorizado"}), 401
        return jsonify({"devices": app.extensions["device_store"].list_devices()})

    @app.post("/api/v1/pairing-codes")
    def create_pairing() -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "No autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        display_name = str(payload.get("displayName", "DaneDesk")).strip()[:80] or "DaneDesk"
        restore_apps = payload.get("restoreApps", [])
        if not isinstance(restore_apps, list) or any(not isinstance(item, dict) for item in restore_apps):
            return jsonify({"error": "restoreApps debe ser una lista de aplicaciones aprobadas"}), 400
        pairing = app.extensions["device_store"].create_pairing_code(display_name, restore_apps)
        return jsonify({**pairing, "agentUri": f"foundstore://agent/pair?server={request.host_url.rstrip('/')}&code={pairing['code']}"}), 201

    @app.post("/api/v1/agent/bootstrap")
    def bootstrap() -> Response:
        payload = request.get_json(silent=True) or {}
        code = str(payload.get("code", "")).upper()
        display_name = str(payload.get("displayName", "DaneDesk")).strip()[:80]
        if not 6 <= len(code) <= 12 or not code.isalnum():
            return jsonify({"error": "El código de emparejamiento debe ser alfanumérico y tener entre 6 y 12 caracteres"}), 400
        device = app.extensions["device_store"].claim_device(code, display_name or "DaneDesk")
        if not device:
            return jsonify({"error": "El código es inválido, venció o ya fue utilizado"}), 401
        return jsonify({**device, "commandKey": device_command_key(app.config["COMMAND_SIGNING_KEY"], device["id"])}), 201

    @app.get("/api/v1/devices/<device_id>/commands/next")
    def next_command(device_id: str) -> Response:
        if not app.extensions["device_store"].authenticate_device(device_id, agent_token()):
            return jsonify({"error": "Agente no autorizado"}), 401
        wait_seconds = long_poll_seconds()
        if wait_seconds is None:
            return jsonify({"error": "wait debe ser un número entero"}), 400
        deadline = time.monotonic() + wait_seconds
        while True:
            commands = app.extensions["device_store"].pending_commands(device_id)
            if commands or time.monotonic() >= deadline:
                key = device_command_key(app.config["COMMAND_SIGNING_KEY"], device_id)
                signed_commands = [{**command, "deviceId": device_id, "signature": command_signature(key, {**command, "deviceId": device_id})} for command in commands]
                return jsonify({"commands": signed_commands, "retryAfterSeconds": 2 if commands else 15})
            time.sleep(1)

    @app.post("/api/v1/devices/<device_id>/commands")
    def queue_command(device_id: str) -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "No autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        command_type = str(payload.get("type", ""))
        if command_type not in {"ring", "lock", "show_message", "install_request"}:
            return jsonify({"error": "Tipo de orden no permitido"}), 400
        command = app.extensions["device_store"].enqueue_command(device_id, command_type, payload.get("payload", {}))
        if not command:
            return jsonify({"error": "Dispositivo no encontrado"}), 404
        return jsonify(command), 202

    @app.post("/api/v1/devices/<device_id>/installation-requests")
    def queue_installation(device_id: str) -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "No autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        package = str(payload.get("package", ""))
        version = str(payload.get("version", "")).strip()[:80]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", package):
            return jsonify({"error": "La referencia debe usar el formato author/package"}), 400
        command = app.extensions["device_store"].enqueue_command(device_id, "install_request", {"package": package, "version": version or None, "localApprovalRequired": True})
        if not command:
            return jsonify({"error": "Dispositivo no encontrado"}), 404
        return jsonify({**command, "localApprovalRequired": True}), 202

    @app.get("/api/v1/devices/<device_id>/events/next")
    def next_event(device_id: str) -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "No autorizado"}), 401
        wait_seconds = long_poll_seconds()
        if wait_seconds is None:
            return jsonify({"error": "wait debe ser un número entero"}), 400
        after = request.args.get("after")
        deadline = time.monotonic() + wait_seconds
        while True:
            events = app.extensions["device_store"].events_after(device_id, after)
            if events or time.monotonic() >= deadline:
                return jsonify({"events": events, "retryAfterSeconds": 2 if events else 15})
            time.sleep(1)

    @app.post("/api/v1/devices/<device_id>/events")
    def agent_event(device_id: str) -> Response:
        if not app.extensions["device_store"].authenticate_device(device_id, agent_token()):
            return jsonify({"error": "Agente no autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        topic = str(payload.get("topic", ""))
        data = payload.get("data", {})
        allowed_topics = {"agent.connected", "command.rejected_signature", "install.awaiting_approval", "install.approved", "install.rejected", "install.completed", "install.failed", "device.locked"}
        if topic not in allowed_topics or not isinstance(data, dict):
            return jsonify({"error": "Evento no permitido"}), 400
        return jsonify(app.extensions["device_store"].record_event(device_id, topic, data)), 202

    @app.post("/api/v1/devices/<device_id>/heartbeat")
    def heartbeat(device_id: str) -> Response:
        if not app.extensions["device_store"].authenticate_device(device_id, agent_token()):
            return jsonify({"error": "Agente no autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        location = payload.get("location")
        if location is not None and (not isinstance(location, dict) or not all(key in location for key in ("latitude", "longitude", "accuracy"))):
            return jsonify({"error": "Ubicación inválida"}), 400
        app.extensions["device_store"].update_heartbeat(device_id, location)
        return jsonify({"success": True, "locationStoredOnlyWhenLost": True})

    @app.get("/api/v1/devices/<device_id>/state")
    def device_state(device_id: str) -> Response:
        device = app.extensions["device_store"].authenticate_device(device_id, agent_token())
        if not device:
            return jsonify({"error": "Agente no autorizado"}), 401
        last_seen = device.get("last_seen_at") or device.get("lastSeenAt")
        if isinstance(last_seen, datetime):
            last_seen = last_seen.isoformat()
        return jsonify({
            "device": {
                "id": device["id"],
                "displayName": device.get("display_name") or device.get("displayName"),
                "status": device.get("status", "active"),
                "locationProtection": bool(device.get("location_protection", device.get("locationProtection", False))),
                "lastSeenAt": last_seen,
            },
        })

    @app.get("/api/v1/devices/<device_id>/restore-apps")
    def restore_apps(device_id: str) -> Response:
        if not app.extensions["device_store"].authenticate_device(device_id, agent_token()):
            return jsonify({"error": "Agente no autorizado"}), 401
        return jsonify({"approvedApps": app.extensions["device_store"].restore_apps(device_id)})

    return app


app = create_app()
