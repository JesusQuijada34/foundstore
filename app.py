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

import requests
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

CATALOG_OWNER = os.environ.get("CATALOG_OWNER", "JesusQuijada34")
CATALOG_REPOSITORY = os.environ.get("CATALOG_REPOSITORY", "catalog")
DEFAULT_LONG_POLL_SECONDS = 25
MAX_LONG_POLL_SECONDS = 25
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LICENSE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_license(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def display_license(value: str) -> str:
    return "-".join(value[index:index + 5] for index in range(0, len(value), 5))


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
    def create_license(self, restore_apps: list[dict[str, str]]) -> dict[str, Any]: ...
    def begin_license_link(self, license_code: str, display_name: str) -> dict[str, Any] | None: ...
    def license_link_status(self, link_id: str, link_token: str) -> dict[str, Any] | None: ...
    def approve_license_link(self, link_id: str, user_code: str, github_login: str) -> bool: ...
    def claim_license_link(self, link_id: str, link_token: str) -> dict[str, Any] | None: ...
    def revoke_license(self, license_code: str, reason: str) -> bool: ...
    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None: ...
    def pending_commands(self, device_id: str) -> list[dict[str, Any]]: ...
    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any], expires_in_seconds: int | None = None) -> dict[str, Any] | None: ...
    def update_heartbeat(self, device_id: str, location: dict[str, float] | None) -> bool: ...
    def get_protected_location(self, device_id: str) -> dict[str, float] | None: ...
    def restore_apps(self, device_id: str) -> list[dict[str, str]]: ...
    def list_devices(self) -> list[dict[str, Any]]: ...
    def list_devices_for_owner(self, github_login: str) -> list[dict[str, Any]]: ...
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
                CREATE TABLE IF NOT EXISTS device_licenses (
                  code_hash TEXT PRIMARY KEY,
                  status TEXT NOT NULL DEFAULT 'active',
                  owner_login TEXT,
                  device_id TEXT,
                  restore_apps_json TEXT NOT NULL,
                  issued_at TEXT NOT NULL,
                  revoked_at TEXT,
                  revoke_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS license_links (
                  id TEXT PRIMARY KEY,
                  license_hash TEXT NOT NULL,
                  link_token_hash TEXT NOT NULL,
                  user_code_hash TEXT NOT NULL,
                  display_name TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'awaiting_owner',
                  owner_login TEXT,
                  expires_at TEXT NOT NULL,
                  used_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_license_links_license ON license_links(license_hash);
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

    def create_license(self, restore_apps: list[dict[str, str]]) -> dict[str, Any]:
        code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(20))
        with self._connect() as conn:
            conn.execute("INSERT INTO device_licenses(code_hash, restore_apps_json, issued_at) VALUES (?, ?, ?)", (token_hash(code), json.dumps(restore_apps), iso_now()))
        return {"license": display_license(code), "status": "active"}

    def begin_license_link(self, license_code: str, display_name: str) -> dict[str, Any] | None:
        license_hash = token_hash(normalize_license(license_code))
        with self._connect() as conn:
            license_row = conn.execute("SELECT status, device_id FROM device_licenses WHERE code_hash = ?", (license_hash,)).fetchone()
            if not license_row or license_row["status"] != "active" or license_row["device_id"]:
                return None
            link_id, link_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
            user_code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(8))
            expires_at = utc_now() + timedelta(minutes=10)
            conn.execute("INSERT INTO license_links(id, license_hash, link_token_hash, user_code_hash, display_name, expires_at) VALUES (?, ?, ?, ?, ?, ?)", (link_id, license_hash, token_hash(link_token), token_hash(user_code), display_name, expires_at.isoformat()))
        return {"linkId": link_id, "linkToken": link_token, "userCode": user_code, "expiresAt": expires_at.isoformat()}

    def license_link_status(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            link = conn.execute("SELECT status, expires_at, used_at FROM license_links WHERE id = ? AND link_token_hash = ?", (link_id, token_hash(link_token))).fetchone()
        if not link:
            return None
        status = "expired" if parse_iso(link["expires_at"]) <= utc_now() and link["status"] == "awaiting_owner" else link["status"]
        return {"status": status, "expiresAt": link["expires_at"], "claimed": bool(link["used_at"])}

    def approve_license_link(self, link_id: str, user_code: str, github_login: str) -> bool:
        with self._connect() as conn:
            link = conn.execute("SELECT * FROM license_links WHERE id = ?", (link_id,)).fetchone()
            if not link or link["status"] != "awaiting_owner" or parse_iso(link["expires_at"]) <= utc_now() or not secrets.compare_digest(link["user_code_hash"], token_hash(user_code.upper())):
                return False
            return bool(conn.execute("UPDATE license_links SET status = 'approved', owner_login = ? WHERE id = ? AND status = 'awaiting_owner'", (github_login, link_id)).rowcount)

    def claim_license_link(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            link = conn.execute("SELECT * FROM license_links WHERE id = ? AND link_token_hash = ?", (link_id, token_hash(link_token))).fetchone()
            if not link or link["status"] != "approved" or link["used_at"] or parse_iso(link["expires_at"]) <= utc_now():
                return None
            license_row = conn.execute("SELECT * FROM device_licenses WHERE code_hash = ?", (link["license_hash"],)).fetchone()
            if not license_row or license_row["status"] != "active" or license_row["device_id"]:
                return None
            device_id, agent_token, now = secrets.token_urlsafe(18), secrets.token_urlsafe(32), iso_now()
            conn.execute("INSERT INTO devices(id, display_name, agent_token_hash, last_seen_at, restore_apps_json) VALUES (?, ?, ?, ?, ?)", (device_id, link["display_name"], token_hash(agent_token), now, license_row["restore_apps_json"]))
            conn.execute("UPDATE device_licenses SET device_id = ?, owner_login = ? WHERE code_hash = ?", (device_id, link["owner_login"], link["license_hash"]))
            conn.execute("UPDATE license_links SET status = 'claimed', used_at = ? WHERE id = ?", (now, link_id))
        self.record_event(device_id, "device.paired", {"displayName": link["display_name"], "ownerLogin": link["owner_login"]})
        return {"id": device_id, "agentToken": agent_token, "platform": "Danenone"}

    def revoke_license(self, license_code: str, reason: str) -> bool:
        license_hash = token_hash(normalize_license(license_code))
        with self._connect() as conn:
            license_row = conn.execute("SELECT device_id FROM device_licenses WHERE code_hash = ? AND status = 'active'", (license_hash,)).fetchone()
            if not license_row:
                return False
            conn.execute("UPDATE device_licenses SET status = 'revoked', revoked_at = ?, revoke_reason = ? WHERE code_hash = ?", (iso_now(), reason[:240], license_hash))
            if license_row["device_id"]:
                conn.execute("UPDATE devices SET status = 'revoked' WHERE id = ?", (license_row["device_id"],))
        if license_row["device_id"]:
            self.record_event(license_row["device_id"], "license.revoked", {"reason": reason[:240]})
        return True

    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            device = conn.execute(
                "SELECT * FROM devices WHERE id = ? AND agent_token_hash = ?",
                (device_id, token_hash(agent_token)),
            ).fetchone()
            if not device:
                return None
            if device["status"] != "revoked":
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

    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any], expires_in_seconds: int | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            device = conn.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not device:
                return None
            command_id = secrets.token_urlsafe(18)
            expires_at = utc_now() + timedelta(seconds=expires_in_seconds or 300)
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
            allow_location = bool(location and device["location_protection"] and device["status"] == "lost")
            stored_location = json.dumps(location) if allow_location else None
            conn.execute("UPDATE devices SET last_seen_at = ?, location_json = ? WHERE id = ?", (iso_now(), stored_location, device_id))
        return True

    def get_protected_location(self, device_id: str) -> dict[str, float] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT status, location_protection, location_json FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row or row["status"] != "lost" or not row["location_protection"] or not row["location_json"]:
            return None
        return json.loads(row["location_json"])

    def restore_apps(self, device_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            row = conn.execute("SELECT restore_apps_json FROM devices WHERE id = ?", (device_id,)).fetchone()
        return json.loads(row["restore_apps_json"]) if row else []

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, display_name, status, location_protection, last_seen_at FROM devices ORDER BY last_seen_at DESC").fetchall()
        return [{"id": row["id"], "displayName": row["display_name"], "status": row["status"], "locationProtection": bool(row["location_protection"]), "lastSeenAt": row["last_seen_at"]} for row in rows]

    def list_devices_for_owner(self, github_login: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT d.id, d.display_name, d.status, d.location_protection, d.last_seen_at
                   FROM devices d JOIN device_licenses l ON l.device_id = d.id
                   WHERE l.owner_login = ? AND l.status = 'active' ORDER BY d.last_seen_at DESC""",
                (github_login,),
            ).fetchall()
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
        self.db.license_links.create_index("expiresAt", expireAfterSeconds=0)
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

    def create_license(self, restore_apps: list[dict[str, str]]) -> dict[str, Any]:
        code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(20))
        self.db.device_licenses.insert_one({"codeHash": token_hash(code), "status": "active", "restoreApps": restore_apps, "issuedAt": utc_now(), "deviceId": None})
        return {"license": display_license(code), "status": "active"}

    def begin_license_link(self, license_code: str, display_name: str) -> dict[str, Any] | None:
        license_hash = token_hash(normalize_license(license_code))
        license_row = self.db.device_licenses.find_one({"codeHash": license_hash, "status": "active", "deviceId": None})
        if not license_row:
            return None
        link_id, link_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        user_code, expires_at = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(8)), utc_now() + timedelta(minutes=10)
        self.db.license_links.insert_one({"id": link_id, "licenseHash": license_hash, "linkTokenHash": token_hash(link_token), "userCodeHash": token_hash(user_code), "displayName": display_name, "status": "awaiting_owner", "expiresAt": expires_at, "usedAt": None})
        return {"linkId": link_id, "linkToken": link_token, "userCode": user_code, "expiresAt": expires_at.isoformat()}

    def license_link_status(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        link = self.db.license_links.find_one({"id": link_id, "linkTokenHash": token_hash(link_token)}, {"_id": 0})
        if not link:
            return None
        status = "expired" if link["expiresAt"] <= utc_now() and link["status"] == "awaiting_owner" else link["status"]
        return {"status": status, "expiresAt": link["expiresAt"].isoformat(), "claimed": bool(link.get("usedAt"))}

    def approve_license_link(self, link_id: str, user_code: str, github_login: str) -> bool:
        result = self.db.license_links.update_one({"id": link_id, "status": "awaiting_owner", "userCodeHash": token_hash(user_code.upper()), "expiresAt": {"$gt": utc_now()}}, {"$set": {"status": "approved", "ownerLogin": github_login}})
        return bool(result.modified_count)

    def claim_license_link(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        link = self.db.license_links.find_one({"id": link_id, "linkTokenHash": token_hash(link_token), "status": "approved", "usedAt": None, "expiresAt": {"$gt": utc_now()}})
        if not link:
            return None
        license_row = self.db.device_licenses.find_one_and_update({"codeHash": link["licenseHash"], "status": "active", "deviceId": None}, {"$set": {"ownerLogin": link["ownerLogin"], "deviceId": "pending"}})
        if not license_row:
            return None
        device_id, agent_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        self.db.devices.insert_one({"id": device_id, "displayName": link["displayName"], "agentTokenHash": token_hash(agent_token), "status": "active", "locationProtection": True, "lastSeenAt": utc_now(), "restoreApps": license_row.get("restoreApps", [])})
        self.db.device_licenses.update_one({"codeHash": link["licenseHash"]}, {"$set": {"deviceId": device_id}})
        self.db.license_links.update_one({"id": link_id}, {"$set": {"status": "claimed", "usedAt": utc_now()}})
        self.record_event(device_id, "device.paired", {"displayName": link["displayName"], "ownerLogin": link["ownerLogin"]})
        return {"id": device_id, "agentToken": agent_token, "platform": "Danenone"}

    def revoke_license(self, license_code: str, reason: str) -> bool:
        license_hash = token_hash(normalize_license(license_code))
        license_row = self.db.device_licenses.find_one_and_update({"codeHash": license_hash, "status": "active"}, {"$set": {"status": "revoked", "revokedAt": utc_now(), "revokeReason": reason[:240]}})
        if not license_row:
            return False
        if license_row.get("deviceId"):
            self.db.devices.update_one({"id": license_row["deviceId"]}, {"$set": {"status": "revoked"}})
            self.record_event(license_row["deviceId"], "license.revoked", {"reason": reason[:240]})
        return True

    def authenticate_device(self, device_id: str, agent_token: str) -> dict[str, Any] | None:
        device = self.db.devices.find_one({"id": device_id, "agentTokenHash": token_hash(agent_token)})
        if device and device.get("status") != "revoked":
            self.db.devices.update_one({"id": device_id}, {"$set": {"lastSeenAt": utc_now()}})
        return device

    def pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        now = utc_now()
        commands = list(self.db.commands.find({"deviceId": device_id, "status": "pending", "expiresAt": {"$gt": now}}).sort("createdAt", 1))
        identifiers = [command["id"] for command in commands]
        if identifiers:
            self.db.commands.update_many({"id": {"$in": identifiers}}, {"$set": {"status": "delivered", "deliveredAt": now}})
            self.db.device_events.insert_many([{"id": secrets.token_urlsafe(18), "deviceId": device_id, "topic": "command.delivered", "data": {"commandId": item}, "createdAt": now} for item in identifiers])
        return [{"id": command["id"], "type": command["type"], "payload": command["payload"], "expiresAt": command["expiresAt"].isoformat()} for command in commands]

    def enqueue_command(self, device_id: str, command_type: str, payload: dict[str, Any], expires_in_seconds: int | None = None) -> dict[str, Any] | None:
        if not self.db.devices.find_one({"id": device_id}, {"_id": 1}):
            return None
        command_id = secrets.token_urlsafe(18)
        expires_at = utc_now() + timedelta(seconds=expires_in_seconds or 300)
        self.db.commands.insert_one({"id": command_id, "deviceId": device_id, "type": command_type, "payload": payload, "status": "pending", "createdAt": utc_now(), "expiresAt": expires_at})
        self.record_event(device_id, "command.queued", {"commandId": command_id, "type": command_type})
        return {"id": command_id, "expiresAt": expires_at.isoformat()}

    def update_heartbeat(self, device_id: str, location: dict[str, float] | None) -> bool:
        device = self.db.devices.find_one({"id": device_id}, {"status": 1, "locationProtection": 1})
        if not device:
            return False
        update: dict[str, Any] = {"lastSeenAt": utc_now()}
        allow_location = bool(location and device.get("locationProtection") and device.get("status") == "lost")
        if allow_location:
            update["lastKnownLocation"] = location
            self.db.devices.update_one({"id": device_id}, {"$set": update})
        else:
            self.db.devices.update_one({"id": device_id}, {"$set": update, "$unset": {"lastKnownLocation": ""}})
        return True

    def get_protected_location(self, device_id: str) -> dict[str, float] | None:
        row = self.db.devices.find_one({"id": device_id, "status": "lost", "locationProtection": True}, {"_id": 0, "lastKnownLocation": 1})
        return row.get("lastKnownLocation") if row else None

    def restore_apps(self, device_id: str) -> list[dict[str, str]]:
        row = self.db.devices.find_one({"id": device_id}, {"restoreApps": 1})
        return row.get("restoreApps", []) if row else []

    def list_devices(self) -> list[dict[str, Any]]:
        rows = self.db.devices.find({}, {"_id": 0, "id": 1, "displayName": 1, "status": 1, "locationProtection": 1, "lastSeenAt": 1}).sort("lastSeenAt", -1)
        return [{**row, "lastSeenAt": row["lastSeenAt"].isoformat()} for row in rows]

    def list_devices_for_owner(self, github_login: str) -> list[dict[str, Any]]:
        licenses = list(self.db.device_licenses.find({"ownerLogin": github_login, "status": "active", "deviceId": {"$type": "string"}}, {"_id": 0, "deviceId": 1}))
        device_ids = [row["deviceId"] for row in licenses]
        if not device_ids:
            return []
        rows = self.db.devices.find({"id": {"$in": device_ids}}, {"_id": 0, "id": 1, "displayName": 1, "status": 1, "locationProtection": 1, "lastSeenAt": 1}).sort("lastSeenAt", -1)
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


def agent_device_or_error(app: Flask, device_id: str) -> tuple[dict[str, Any] | None, Response | None]:
    device = app.extensions["device_store"].authenticate_device(device_id, agent_token())
    if not device:
        return None, (jsonify({"error": "Agente no autorizado"}), 401)
    if device.get("status") == "revoked":
        return None, (jsonify({"error": "agent_revoked", "relinkRequired": True}), 403)
    return device, None


def long_poll_seconds() -> int | None:
    try:
        return min(max(int(request.args.get("wait", DEFAULT_LONG_POLL_SECONDS)), 0), MAX_LONG_POLL_SECONDS)
    except ValueError:
        return None


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, template_folder="render_templates")
    app.config.from_mapping(
        # Render Free no monta un disco en /var/data. Un volumen persistente debe
        # declararse explícitamente mediante DATA_DIR; el respaldo local es
        # deliberadamente efímero y se expone en /healthz como sqlite-fallback.
        DATA_DIR=os.environ.get("DATA_DIR", "./var"),
        MONGODB_URI=os.environ.get("MONGO_URI"),
        MONGO_DATABASE=os.environ.get("MONGO_DATABASE", "foundstore"),
        OWNER_API_TOKEN=os.environ.get("OWNER_API_TOKEN", ""),
        COMMAND_SIGNING_KEY=os.environ.get("NULL_HV", ""),
        SECRET_KEY=os.environ.get("NULL_HV", ""),
        GITHUB_CLIENT_ID=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""),
        GITHUB_CLIENT_SECRET=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
        ALLOW_LEGACY_PAIRING=os.environ.get("ALLOW_LEGACY_PAIRING", "").lower() == "true",
        MONGO_FALLBACK_REASON=None,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secrets.token_urlsafe(32)
        app.config["SESSION_EPHEMERAL"] = True
    if not app.config["COMMAND_SIGNING_KEY"]:
        app.config["COMMAND_SIGNING_KEY"] = app.config["SECRET_KEY"]
    app.extensions["device_store"] = build_store(app.config)

    def github_login() -> str | None:
        return session.get("github_login")

    def oauth_ready() -> bool:
        return bool(app.config["GITHUB_CLIENT_ID"] and app.config["GITHUB_CLIENT_SECRET"])

    @app.get("/")
    def index() -> str:
        return render_template("index.html", catalog_owner=CATALOG_OWNER)

    @app.get("/auth/github/login")
    def github_oauth_login() -> Response:
        if not oauth_ready():
            return jsonify({"error": "GitHub OAuth no está configurado"}), 503
        state = secrets.token_urlsafe(24)
        session["github_oauth_state"] = state
        link_id = request.args.get("link", "")
        if link_id:
            session["github_oauth_link"] = link_id
        callback = url_for("github_oauth_callback", _external=True)
        query = urllib.parse.urlencode({"client_id": app.config["GITHUB_CLIENT_ID"], "redirect_uri": callback, "state": state, "scope": "read:user"})
        return redirect(f"https://github.com/login/oauth/authorize?{query}")

    @app.get("/auth/github/callback")
    def github_oauth_callback() -> Response:
        if not oauth_ready() or not secrets.compare_digest(str(session.pop("github_oauth_state", "")), str(request.args.get("state", ""))):
            return jsonify({"error": "La confirmación de GitHub no es válida"}), 400
        code = request.args.get("code", "")
        try:
            token_response = requests.post("https://github.com/login/oauth/access_token", data={"client_id": app.config["GITHUB_CLIENT_ID"], "client_secret": app.config["GITHUB_CLIENT_SECRET"], "code": code}, headers={"Accept": "application/json"}, timeout=10).json()
            access_token = token_response.get("access_token", "")
            profile = requests.get("https://api.github.com/user", headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"}, timeout=10).json()
            login = str(profile.get("login", "")).strip()
        except requests.RequestException:
            return jsonify({"error": "No se pudo confirmar GitHub"}), 502
        if not login:
            return jsonify({"error": "GitHub no devolvió una identidad válida"}), 401
        session["github_login"] = login
        link_id = session.pop("github_oauth_link", "")
        return redirect(url_for("license_link_page", link_id=link_id) if link_id else url_for("index"))

    @app.route("/link/<link_id>", methods=["GET", "POST"])
    def license_link_page(link_id: str) -> Response | str:
        if not github_login():
            return redirect(url_for("github_oauth_login", link=link_id))
        if request.method == "POST":
            code = str(request.form.get("code", ""))
            if app.extensions["device_store"].approve_license_link(link_id, code, github_login() or ""):
                return "<h1>DaneDesk vinculado</h1><p>Ya puedes volver al dispositivo. Foundstore activará el agente con una credencial exclusiva.</p>"
            return "<h1>No se pudo vincular</h1><p>Verifica el código visible en el dispositivo o solicita una nueva operación.</p>", 400
        return f"<h1>Vincular DaneDesk</h1><p>Sesión de GitHub: <strong>{github_login()}</strong></p><form method='post'><label>Código mostrado por el dispositivo <input name='code' autocomplete='one-time-code' required></label><button type='submit'>Confirmar este dispositivo</button></form>"

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

    @app.get("/api/v1/me/devices")
    def my_devices() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para ver tus DaneDesk"}), 401
        return jsonify({"devices": app.extensions["device_store"].list_devices_for_owner(login)})

    @app.post("/api/v1/me/devices/<device_id>/installations")
    def install_from_catalog(device_id: str) -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub antes de solicitar una instalación"}), 401
        device = next((item for item in app.extensions["device_store"].list_devices_for_owner(login) if item["id"] == device_id and item["status"] == "active"), None)
        if not device:
            return jsonify({"error": "El dispositivo elegido no pertenece a tu cuenta o no está activo"}), 403
        payload = request.get_json(silent=True) or {}
        slug = str(payload.get("slug", "")).strip()
        try:
            catalog = catalog_snapshot()
        except Exception:
            return jsonify({"error": "El catálogo no está disponible para validar esta solicitud"}), 503
        package = next((item for item in catalog["packages"] if item["slug"] == slug), None)
        if not package:
            return jsonify({"error": "La aplicación no pertenece al catálogo Foundstore"}), 404
        command = app.extensions["device_store"].enqueue_command(device_id, "install_request", {"package": f"{CATALOG_OWNER}/{slug}", "version": None, "localApprovalRequired": True})
        if not command:
            return jsonify({"error": "No se pudo encolar la instalación"}), 409
        return jsonify({"requestId": command["id"], "deviceId": device_id, "package": {"slug": package["slug"], "name": package["name"]}, "localApprovalRequired": True}), 202

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

    @app.post("/api/v1/licenses")
    def create_license() -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "Propietario no autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        restore_apps = payload.get("restoreApps", [])
        if not isinstance(restore_apps, list) or any(not isinstance(item, dict) for item in restore_apps):
            return jsonify({"error": "restoreApps debe ser una lista de aplicaciones aprobadas"}), 400
        return jsonify(app.extensions["device_store"].create_license(restore_apps)), 201

    @app.post("/api/v1/license-links")
    def begin_license_link() -> Response:
        payload = request.get_json(silent=True) or {}
        license_code = str(payload.get("license", ""))
        display_name = str(payload.get("displayName", "DaneDesk")).strip()[:80] or "DaneDesk"
        link = app.extensions["device_store"].begin_license_link(license_code, display_name)
        if not link:
            return jsonify({"error": "La licencia no es válida, fue revocada o ya está vinculada"}), 401
        return jsonify({**link, "verificationUri": url_for("license_link_page", link_id=link["linkId"], _external=True)}), 201

    @app.get("/api/v1/license-links/<link_id>")
    def license_link_status(link_id: str) -> Response:
        link_token = request.headers.get("X-Foundstore-Link-Token", "")
        status = app.extensions["device_store"].license_link_status(link_id, link_token)
        if not status:
            return jsonify({"error": "Solicitud de vínculo no válida"}), 401
        return jsonify(status)

    @app.post("/api/v1/license-links/<link_id>/claim")
    def claim_license_link(link_id: str) -> Response:
        link_token = request.headers.get("X-Foundstore-Link-Token", "")
        device = app.extensions["device_store"].claim_license_link(link_id, link_token)
        if not device:
            return jsonify({"error": "El vínculo aún no está aprobado, venció o fue consumido"}), 401
        return jsonify({**device, "commandKey": device_command_key(app.config["COMMAND_SIGNING_KEY"], device["id"])}), 201

    @app.post("/api/v1/licenses/revoke")
    def revoke_license() -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "Propietario no autorizado"}), 401
        payload = request.get_json(silent=True) or {}
        reason = str(payload.get("reason", "Revocación solicitada por el propietario")).strip()[:240] or "Revocación solicitada por el propietario"
        if not app.extensions["device_store"].revoke_license(str(payload.get("license", "")), reason):
            return jsonify({"error": "La licencia no está activa o no existe"}), 404
        return jsonify({"success": True, "reason": reason})

    @app.post("/api/v1/agent/bootstrap")
    def bootstrap() -> Response:
        if not app.config["ALLOW_LEGACY_PAIRING"]:
            return jsonify({"error": "El emparejamiento directo está retirado; inicia un vínculo de licencia aprobado por el propietario"}), 410
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
        _, error = agent_device_or_error(app, device_id)
        if error:
            return error
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
        command_payload = payload.get("payload", {})
        if not isinstance(command_payload, dict):
            return jsonify({"error": "La carga de la orden debe ser un objeto"}), 400
        expires_in_seconds = None
        if command_type == "ring":
            duration = command_payload.get("durationSeconds", 5)
            if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 10:
                return jsonify({"error": "El timbre requiere durationSeconds entre 1 y 10"}), 400
            command_payload = {"durationSeconds": duration}
            expires_in_seconds = max(15, duration + 15)
        command = app.extensions["device_store"].enqueue_command(device_id, command_type, command_payload, expires_in_seconds)
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
        _, error = agent_device_or_error(app, device_id)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        topic = str(payload.get("topic", ""))
        data = payload.get("data", {})
        allowed_topics = {"agent.connected", "command.rejected_signature", "command.rejected_expired", "install.awaiting_approval", "install.approved", "install.rejected", "install.completed", "install.failed", "device.locked", "device.ring.started", "device.ring.failed"}
        if topic not in allowed_topics or not isinstance(data, dict):
            return jsonify({"error": "Evento no permitido"}), 400
        return jsonify(app.extensions["device_store"].record_event(device_id, topic, data)), 202

    @app.post("/api/v1/devices/<device_id>/heartbeat")
    def heartbeat(device_id: str) -> Response:
        _, error = agent_device_or_error(app, device_id)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        location = payload.get("location")
        if location is not None and (not isinstance(location, dict) or not all(key in location for key in ("latitude", "longitude", "accuracy"))):
            return jsonify({"error": "Ubicación inválida"}), 400
        app.extensions["device_store"].update_heartbeat(device_id, location)
        return jsonify({"success": True, "locationStoredOnlyWhenLost": True})

    @app.get("/api/v1/devices/<device_id>/state")
    def device_state(device_id: str) -> Response:
        device, error = agent_device_or_error(app, device_id)
        if error:
            return error
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

    @app.get("/api/v1/devices/<device_id>/location")
    def protected_location(device_id: str) -> Response:
        if not owner_authorized(app):
            return jsonify({"error": "Propietario no autorizado"}), 401
        location = app.extensions["device_store"].get_protected_location(device_id)
        if not location:
            return jsonify({"error": "No hay ubicación protegida disponible"}), 404
        return jsonify({"deviceId": device_id, "location": location})

    @app.get("/api/v1/devices/<device_id>/restore-apps")
    def restore_apps(device_id: str) -> Response:
        _, error = agent_device_or_error(app, device_id)
        if error:
            return error
        return jsonify({"approvedApps": app.extensions["device_store"].restore_apps(device_id)})

    return app


app = create_app()


if __name__ == "__main__":
    # Render debe usar Gunicorn según render.yaml. Esto permite que una
    # configuración manual que ejecute `python app.py` siga iniciando el
    # servicio en $PORT en lugar de salir inmediatamente.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
