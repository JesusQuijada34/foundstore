"""Foundstore Flask service for the `render` branch.

This service is intentionally separate from the React/tRPC application on `main`.
It exposes a direct public catalog route plus a small, authenticated DaneDesk agent
API. Device commands are delivered through one long-poll request at a time, not
through a busy loop.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for

CATALOG_OWNER = os.environ.get("CATALOG_OWNER", "JesusQuijada34")
CATALOG_REPOSITORY = os.environ.get("CATALOG_REPOSITORY", "catalog")
DEFAULT_LONG_POLL_SECONDS = 25
MAX_LONG_POLL_SECONDS = 25
PACKAGE_METADATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CATALOG_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
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


def license_cipher(secret: str) -> Fernet:
    """Derive a stable Fernet key without persisting raw license codes in storage."""
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


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


def valid_repository_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value))


def catalog_references(source_text: str, default_owner: str) -> list[tuple[str, str]]:
    """Parse public repo.list entries without trusting stale or malformed references."""
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_entry in re.split(r"[,\n]", source_text):
        entry = raw_entry.strip()
        if not entry or entry.startswith("#"):
            continue
        parts = entry.split("/", 1)
        owner, slug = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (default_owner, parts[0].strip())
        if not valid_github_login(owner) or not valid_repository_name(slug):
            continue
        key = (owner.lower(), slug.lower())
        if key not in seen:
            seen.add(key)
            references.append((owner, slug))
    return references


def package_revision(package: dict[str, Any]) -> str:
    stable = {key: package.get(key) for key in ("author", "slug", "branch", "updatedAt", "description", "repositoryUrl")}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def canonical_platform(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "danenone":
        return "Danenone"
    if normalized in {"knosthalij", "windows"}:
        return "Knosthalij"
    return value.strip()


def platforms_for(value: str) -> list[str]:
    normalized = value.strip().lower()
    if normalized == "alphacube":
        return ["Danenone", "Knosthalij"]
    if normalized == "knosthalij":
        return ["Knosthalij"]
    if normalized == "danenone":
        return ["Danenone"]
    return [canonical_platform(value)] if value.strip() else []


def raw_github_text(author: str, slug: str, branch: str, path: str) -> str:
    raw_url = f"https://raw.githubusercontent.com/{author}/{slug}/{branch}/{path}"
    with urlopen(Request(raw_url, headers={"User-Agent": "Foundstore-Flask-Render"}), timeout=8) as response:  # nosec B310: fixed GitHub raw origin
        return response.read().decode("utf-8")


def package_metadata(slug: str, branch: str = "main", author: str = CATALOG_OWNER) -> dict[str, Any]:
    cache_key = f"{author}:{slug}:{branch}"
    cached = PACKAGE_METADATA_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    metadata: dict[str, Any] = {"platform": "", "platformTargets": [], "readme": "", "version": "", "publisher": "", "manifestValid": False}
    try:
        root = ET.fromstring(raw_github_text(author, slug, branch, "details.xml"))
        metadata["manifestValid"] = bool(root.tag)
        for key in ("platform", "version", "publisher", "name", "description"):
            element = root.find(key)
            if element is not None and element.text:
                metadata[key] = element.text.strip()
        if str(metadata.get("publisher", "")).lower() == "influent":
            metadata["publisher"] = "Influent"
        metadata["platformTargets"] = platforms_for(str(metadata.get("platform", "")))
    except (ET.ParseError, OSError, ValueError):
        pass
    try:
        metadata["readme"] = raw_github_text(author, slug, branch, "README.md")[:50000]
    except OSError:
        pass
    PACKAGE_METADATA_CACHE[cache_key] = (time.time() + 300, metadata)
    return metadata


class DeviceStore(Protocol):
    backend_name: str

    def create_pairing_code(self, display_name: str, restore_apps: list[dict[str, str]]) -> dict[str, Any]: ...
    def claim_device(self, code: str, display_name: str) -> dict[str, Any] | None: ...
    def create_license(self, restore_apps: list[dict[str, str]], owner_login: str = "") -> dict[str, Any]: ...
    def begin_license_link(self, license_code: str, display_name: str, platform: str = "Danenone") -> dict[str, Any] | None: ...
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
    def list_licenses_for_owner(self, github_login: str) -> list[dict[str, Any]]: ...
    def get_developer_profile(self, github_login: str) -> dict[str, Any] | None: ...
    def update_developer_profile(self, github_login: str, updates: dict[str, str]) -> dict[str, Any]: ...
    def follow_developer(self, follower_login: str, developer_login: str) -> bool: ...
    def unfollow_developer(self, follower_login: str, developer_login: str) -> bool: ...
    def is_following_developer(self, follower_login: str, developer_login: str) -> bool: ...
    def list_followed_developers(self, follower_login: str) -> list[str]: ...
    def developer_follower_count(self, developer_login: str) -> int: ...
    def get_repository_scan(self, author: str, slug: str, branch: str) -> dict[str, Any] | None: ...
    def save_repository_scan(self, author: str, slug: str, branch: str, report: dict[str, Any]) -> None: ...
    def record_event(self, device_id: str, topic: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def events_after(self, device_id: str, after: str | None) -> list[dict[str, Any]]: ...
    def maintain(self) -> dict[str, int]: ...


class LocalStore:
    """SQLite fallback. Attach Render's paid persistent disk to DATA_DIR for durability."""

    backend_name = "sqlite-fallback"

    def __init__(self, data_dir: str, license_secret: str):
        self.path = Path(data_dir) / "foundstore-render.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.license_fernet = license_cipher(license_secret)
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
                CREATE TABLE IF NOT EXISTS developer_profiles (
                  github_login TEXT PRIMARY KEY,
                  display_name TEXT,
                  bio TEXT,
                  website TEXT,
                  catalog_repository TEXT NOT NULL DEFAULT 'catalog',
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repository_scans (
                  author TEXT NOT NULL,
                  slug TEXT NOT NULL,
                  branch TEXT NOT NULL,
                  report_json TEXT NOT NULL,
                  scanned_at TEXT NOT NULL,
                  PRIMARY KEY(author, slug, branch)
                );
                CREATE TABLE IF NOT EXISTS developer_follows (
                  follower_login TEXT NOT NULL,
                  developer_login TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY(follower_login, developer_login)
                );
                CREATE INDEX IF NOT EXISTS idx_developer_follows_target ON developer_follows(developer_login);
                CREATE INDEX IF NOT EXISTS idx_license_links_license ON license_links(license_hash);
                CREATE INDEX IF NOT EXISTS idx_device_events_device_time
                  ON device_events(device_id, created_at);
                """
            )
            for migration in (
                "ALTER TABLE devices ADD COLUMN platform TEXT NOT NULL DEFAULT 'Danenone'",
                "ALTER TABLE device_licenses ADD COLUMN license_ciphertext TEXT",
                "ALTER TABLE license_links ADD COLUMN platform TEXT NOT NULL DEFAULT 'Danenone'",
            ):
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass
            conn.execute("UPDATE devices SET platform = 'Knosthalij' WHERE lower(platform) = 'windows'")
            conn.execute("UPDATE license_links SET platform = 'Knosthalij' WHERE lower(platform) = 'windows'")

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

    def create_license(self, restore_apps: list[dict[str, str]], owner_login: str = "") -> dict[str, Any]:
        code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(20))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO device_licenses(code_hash, owner_login, restore_apps_json, issued_at, license_ciphertext) VALUES (?, ?, ?, ?, ?)",
                (token_hash(code), owner_login or None, json.dumps(restore_apps), iso_now(), self.license_fernet.encrypt(code.encode("utf-8")).decode("ascii")),
            )
        return {"license": display_license(code), "status": "active"}

    def begin_license_link(self, license_code: str, display_name: str, platform: str = "Danenone") -> dict[str, Any] | None:
        platform = canonical_platform(platform)
        if platform not in {"Danenone", "Knosthalij"}:
            return None
        license_hash = token_hash(normalize_license(license_code))
        with self._connect() as conn:
            license_row = conn.execute("SELECT status, device_id FROM device_licenses WHERE code_hash = ?", (license_hash,)).fetchone()
            if not license_row or license_row["status"] != "active" or license_row["device_id"]:
                return None
            link_id, link_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
            user_code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(8))
            expires_at = utc_now() + timedelta(minutes=10)
            conn.execute("INSERT INTO license_links(id, license_hash, link_token_hash, user_code_hash, display_name, platform, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (link_id, license_hash, token_hash(link_token), token_hash(user_code), display_name, platform, expires_at.isoformat()))
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
            link = conn.execute("SELECT l.*, d.owner_login AS license_owner FROM license_links l JOIN device_licenses d ON d.code_hash = l.license_hash WHERE l.id = ?", (link_id,)).fetchone()
            if not link or link["status"] != "awaiting_owner" or parse_iso(link["expires_at"]) <= utc_now() or not secrets.compare_digest(link["user_code_hash"], token_hash(user_code.upper())):
                return False
            if link["license_owner"] and link["license_owner"] != github_login:
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
            conn.execute("INSERT INTO devices(id, display_name, agent_token_hash, last_seen_at, restore_apps_json, platform) VALUES (?, ?, ?, ?, ?, ?)", (device_id, link["display_name"], token_hash(agent_token), now, license_row["restore_apps_json"], link["platform"]))
            conn.execute("UPDATE device_licenses SET device_id = ?, owner_login = COALESCE(owner_login, ?) WHERE code_hash = ?", (device_id, link["owner_login"], link["license_hash"]))
            conn.execute("UPDATE license_links SET status = 'claimed', used_at = ? WHERE id = ?", (now, link_id))
        self.record_event(device_id, "device.paired", {"displayName": link["display_name"], "ownerLogin": link["owner_login"], "platform": link["platform"]})
        return {"id": device_id, "agentToken": agent_token, "platform": link["platform"]}

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
            rows = conn.execute("SELECT id, display_name, status, location_protection, last_seen_at, platform FROM devices ORDER BY last_seen_at DESC").fetchall()
        return [{"id": row["id"], "displayName": row["display_name"], "status": row["status"], "locationProtection": bool(row["location_protection"]), "lastSeenAt": row["last_seen_at"], "platform": row["platform"]} for row in rows]

    def list_devices_for_owner(self, github_login: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT d.id, d.display_name, d.status, d.location_protection, d.last_seen_at, d.platform
                   FROM devices d JOIN device_licenses l ON l.device_id = d.id
                   WHERE l.owner_login = ? AND l.status = 'active' ORDER BY d.last_seen_at DESC""",
                (github_login,),
            ).fetchall()
        return [{"id": row["id"], "displayName": row["display_name"], "status": row["status"], "locationProtection": bool(row["location_protection"]), "lastSeenAt": row["last_seen_at"], "platform": row["platform"]} for row in rows]

    def list_licenses_for_owner(self, github_login: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT l.status, l.issued_at, l.license_ciphertext, d.display_name, d.platform
                   FROM device_licenses l LEFT JOIN devices d ON d.id = l.device_id
                   WHERE l.owner_login = ? ORDER BY l.issued_at DESC""",
                (github_login,),
            ).fetchall()
        licenses = []
        for row in rows:
            try:
                code = display_license(self.license_fernet.decrypt(row["license_ciphertext"].encode("ascii")).decode("utf-8")) if row["license_ciphertext"] else None
            except (InvalidToken, AttributeError):
                code = None
            licenses.append({"license": code, "status": row["status"], "issuedAt": row["issued_at"], "deviceName": row["display_name"], "platform": row["platform"]})
        return licenses

    def get_developer_profile(self, github_login: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT github_login, display_name, bio, website, catalog_repository, updated_at FROM developer_profiles WHERE github_login = ?",
                (github_login,),
            ).fetchone()
        return dict(row) if row else None

    def update_developer_profile(self, github_login: str, updates: dict[str, str]) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO developer_profiles(github_login, display_name, bio, website, catalog_repository, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(github_login) DO UPDATE SET display_name = excluded.display_name, bio = excluded.bio,
                     website = excluded.website, catalog_repository = excluded.catalog_repository, updated_at = excluded.updated_at""",
                (github_login, updates.get("displayName", ""), updates.get("bio", ""), updates.get("website", ""), updates.get("catalogRepository", "catalog"), iso_now()),
            )
        return self.get_developer_profile(github_login) or {}

    def follow_developer(self, follower_login: str, developer_login: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO developer_follows(follower_login, developer_login, created_at) VALUES (?, ?, ?)",
                (follower_login, developer_login, iso_now()),
            )
        return self.is_following_developer(follower_login, developer_login)

    def unfollow_developer(self, follower_login: str, developer_login: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM developer_follows WHERE follower_login = ? AND developer_login = ?", (follower_login, developer_login))
        return not self.is_following_developer(follower_login, developer_login)

    def is_following_developer(self, follower_login: str, developer_login: str) -> bool:
        with self._connect() as conn:
            return bool(conn.execute("SELECT 1 FROM developer_follows WHERE follower_login = ? AND developer_login = ?", (follower_login, developer_login)).fetchone())

    def list_followed_developers(self, follower_login: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT developer_login FROM developer_follows WHERE follower_login = ? ORDER BY created_at DESC", (follower_login,)).fetchall()
        return [str(row["developer_login"]) for row in rows]

    def developer_follower_count(self, developer_login: str) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM developer_follows WHERE developer_login = ?", (developer_login,)).fetchone()["count"])

    def get_repository_scan(self, author: str, slug: str, branch: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM repository_scans WHERE author = ? AND slug = ? AND branch = ?",
                (author, slug, branch),
            ).fetchone()
        return json.loads(row["report_json"]) if row else None

    def save_repository_scan(self, author: str, slug: str, branch: str, report: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO repository_scans(author, slug, branch, report_json, scanned_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(author, slug, branch) DO UPDATE SET report_json = excluded.report_json, scanned_at = excluded.scanned_at""",
                (author, slug, branch, json.dumps(report), iso_now()),
            )

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

    def __init__(self, uri: str, database_name: str, license_secret: str):
        from pymongo import MongoClient

        self.client = MongoClient(uri, connectTimeoutMS=5_000, serverSelectionTimeoutMS=5_000)
        self.client.admin.command("ping")
        self.db = self.client[database_name]
        self.license_fernet = license_cipher(license_secret)
        self.db.pairing_codes.create_index("expiresAt", expireAfterSeconds=0)
        self.db.license_links.create_index("expiresAt", expireAfterSeconds=0)
        self.db.commands.create_index("expiresAt", expireAfterSeconds=0)
        self.db.device_events.create_index([("deviceId", 1), ("createdAt", 1)])
        self.db.developer_profiles.create_index("githubLogin", unique=True)
        self.db.developer_follows.create_index([("followerLogin", 1), ("developerLogin", 1)], unique=True)
        self.db.developer_follows.create_index("developerLogin")
        self.db.repository_scans.create_index([("author", 1), ("slug", 1), ("branch", 1)], unique=True)
        self.db.devices.update_many({"platform": "Windows"}, {"$set": {"platform": "Knosthalij"}})
        self.db.license_links.update_many({"platform": "Windows"}, {"$set": {"platform": "Knosthalij"}})

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

    def create_license(self, restore_apps: list[dict[str, str]], owner_login: str = "") -> dict[str, Any]:
        code = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(20))
        self.db.device_licenses.insert_one({"codeHash": token_hash(code), "status": "active", "ownerLogin": owner_login or None, "restoreApps": restore_apps, "issuedAt": utc_now(), "deviceId": None, "licenseCiphertext": self.license_fernet.encrypt(code.encode("utf-8")).decode("ascii")})
        return {"license": display_license(code), "status": "active"}

    def begin_license_link(self, license_code: str, display_name: str, platform: str = "Danenone") -> dict[str, Any] | None:
        platform = canonical_platform(platform)
        if platform not in {"Danenone", "Knosthalij"}:
            return None
        license_hash = token_hash(normalize_license(license_code))
        license_row = self.db.device_licenses.find_one({"codeHash": license_hash, "status": "active", "deviceId": None})
        if not license_row:
            return None
        link_id, link_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        user_code, expires_at = "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(8)), utc_now() + timedelta(minutes=10)
        self.db.license_links.insert_one({"id": link_id, "licenseHash": license_hash, "linkTokenHash": token_hash(link_token), "userCodeHash": token_hash(user_code), "displayName": display_name, "platform": platform, "status": "awaiting_owner", "expiresAt": expires_at, "usedAt": None})
        return {"linkId": link_id, "linkToken": link_token, "userCode": user_code, "expiresAt": expires_at.isoformat()}

    def license_link_status(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        link = self.db.license_links.find_one({"id": link_id, "linkTokenHash": token_hash(link_token)}, {"_id": 0})
        if not link:
            return None
        status = "expired" if link["expiresAt"] <= utc_now() and link["status"] == "awaiting_owner" else link["status"]
        return {"status": status, "expiresAt": link["expiresAt"].isoformat(), "claimed": bool(link.get("usedAt"))}

    def approve_license_link(self, link_id: str, user_code: str, github_login: str) -> bool:
        link = self.db.license_links.find_one({"id": link_id, "status": "awaiting_owner", "userCodeHash": token_hash(user_code.upper()), "expiresAt": {"$gt": utc_now()}})
        if not link:
            return False
        license_row = self.db.device_licenses.find_one({"codeHash": link["licenseHash"]}, {"ownerLogin": 1})
        if license_row and license_row.get("ownerLogin") and license_row["ownerLogin"] != github_login:
            return False
        result = self.db.license_links.update_one({"id": link_id, "status": "awaiting_owner"}, {"$set": {"status": "approved", "ownerLogin": github_login}})
        return bool(result.modified_count)

    def claim_license_link(self, link_id: str, link_token: str) -> dict[str, Any] | None:
        link = self.db.license_links.find_one({"id": link_id, "linkTokenHash": token_hash(link_token), "status": "approved", "usedAt": None, "expiresAt": {"$gt": utc_now()}})
        if not link:
            return None
        license_row = self.db.device_licenses.find_one_and_update({"codeHash": link["licenseHash"], "status": "active", "deviceId": None}, {"$set": {"ownerLogin": link["ownerLogin"], "deviceId": "pending"}})
        if not license_row:
            return None
        device_id, agent_token = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        self.db.devices.insert_one({"id": device_id, "displayName": link["displayName"], "agentTokenHash": token_hash(agent_token), "status": "active", "locationProtection": True, "lastSeenAt": utc_now(), "restoreApps": license_row.get("restoreApps", []), "platform": link.get("platform", "Danenone")})
        self.db.device_licenses.update_one({"codeHash": link["licenseHash"]}, {"$set": {"deviceId": device_id, "ownerLogin": license_row.get("ownerLogin") or link["ownerLogin"]}})
        self.db.license_links.update_one({"id": link_id}, {"$set": {"status": "claimed", "usedAt": utc_now()}})
        self.record_event(device_id, "device.paired", {"displayName": link["displayName"], "ownerLogin": link["ownerLogin"], "platform": link.get("platform", "Danenone")})
        return {"id": device_id, "agentToken": agent_token, "platform": link.get("platform", "Danenone")}

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
        rows = self.db.devices.find({"id": {"$in": device_ids}}, {"_id": 0, "id": 1, "displayName": 1, "status": 1, "locationProtection": 1, "lastSeenAt": 1, "platform": 1}).sort("lastSeenAt", -1)
        return [{**row, "lastSeenAt": row["lastSeenAt"].isoformat()} for row in rows]

    def list_licenses_for_owner(self, github_login: str) -> list[dict[str, Any]]:
        rows = self.db.device_licenses.find({"ownerLogin": github_login}, {"_id": 0}).sort("issuedAt", -1)
        licenses = []
        for row in rows:
            try:
                code = display_license(self.license_fernet.decrypt(row.get("licenseCiphertext", "").encode("ascii")).decode("utf-8")) if row.get("licenseCiphertext") else None
            except (InvalidToken, AttributeError):
                code = None
            device = self.db.devices.find_one({"id": row.get("deviceId")}, {"_id": 0, "displayName": 1, "platform": 1}) if row.get("deviceId") else None
            licenses.append({"license": code, "status": row["status"], "issuedAt": row["issuedAt"].isoformat(), "deviceName": device.get("displayName") if device else None, "platform": device.get("platform") if device else None})
        return licenses

    def get_developer_profile(self, github_login: str) -> dict[str, Any] | None:
        return self.db.developer_profiles.find_one({"githubLogin": github_login}, {"_id": 0})

    def update_developer_profile(self, github_login: str, updates: dict[str, str]) -> dict[str, Any]:
        self.db.developer_profiles.update_one(
            {"githubLogin": github_login},
            {"$set": {"githubLogin": github_login, "displayName": updates.get("displayName", ""), "bio": updates.get("bio", ""), "website": updates.get("website", ""), "catalogRepository": updates.get("catalogRepository", "catalog"), "updatedAt": utc_now()}},
            upsert=True,
        )
        return self.get_developer_profile(github_login) or {}

    def follow_developer(self, follower_login: str, developer_login: str) -> bool:
        self.db.developer_follows.update_one(
            {"followerLogin": follower_login, "developerLogin": developer_login},
            {"$setOnInsert": {"followerLogin": follower_login, "developerLogin": developer_login, "createdAt": utc_now()}},
            upsert=True,
        )
        return True

    def unfollow_developer(self, follower_login: str, developer_login: str) -> bool:
        self.db.developer_follows.delete_one({"followerLogin": follower_login, "developerLogin": developer_login})
        return True

    def is_following_developer(self, follower_login: str, developer_login: str) -> bool:
        return bool(self.db.developer_follows.find_one({"followerLogin": follower_login, "developerLogin": developer_login}, {"_id": 1}))

    def list_followed_developers(self, follower_login: str) -> list[str]:
        rows = self.db.developer_follows.find({"followerLogin": follower_login}, {"_id": 0, "developerLogin": 1}).sort("createdAt", -1)
        return [str(row["developerLogin"]) for row in rows]

    def developer_follower_count(self, developer_login: str) -> int:
        return int(self.db.developer_follows.count_documents({"developerLogin": developer_login}))

    def get_repository_scan(self, author: str, slug: str, branch: str) -> dict[str, Any] | None:
        return self.db.repository_scans.find_one({"author": author, "slug": slug, "branch": branch}, {"_id": 0})

    def save_repository_scan(self, author: str, slug: str, branch: str, report: dict[str, Any]) -> None:
        self.db.repository_scans.update_one(
            {"author": author, "slug": slug, "branch": branch},
            {"$set": {**report, "author": author, "slug": slug, "branch": branch, "persistedAt": utc_now()}},
            upsert=True,
        )

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
            return MongoStore(mongo_uri, config["MONGO_DATABASE"], config["COMMAND_SIGNING_KEY"])
        except Exception as error:  # fallback remains deliberate and visible in /healthz
            config["MONGO_FALLBACK_REASON"] = type(error).__name__
    return LocalStore(config["DATA_DIR"], config["COMMAND_SIGNING_KEY"])


def catalog_snapshot(catalog_owner: str = CATALOG_OWNER, catalog_repository: str = CATALOG_REPOSITORY) -> dict[str, Any]:
    cache_key = f"{catalog_owner.lower()}:{catalog_repository.lower()}"
    cached = CATALOG_SNAPSHOT_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Foundstore-Flask-Render"}

    def github(path: str) -> Any:
        with urlopen(Request(f"https://api.github.com{path}", headers=headers), timeout=10) as response:  # nosec B310: fixed GitHub API origin
            return json.load(response)

    try:
        catalog_file = github(f"/repos/{quote(catalog_owner)}/{quote(catalog_repository)}/contents/repo.list?ref=main")
        source_text = base64.b64decode(catalog_file["content"]).decode("utf-8")
    except Exception:
        raw_url = f"https://raw.githubusercontent.com/{catalog_owner}/{catalog_repository}/main/repo.list"
        with urlopen(Request(raw_url, headers={"User-Agent": "Foundstore-Flask-Render"}), timeout=10) as response:  # nosec B310: fixed GitHub raw origin
            source_text = response.read().decode("utf-8")
    references = catalog_references(source_text, catalog_owner)
    owners = sorted({author.lower(): author for author, _ in references}.values(), key=str.lower)
    repositories: dict[tuple[str, str], dict[str, Any]] = {}
    for author in owners:
        try:
            for item in github(f"/users/{quote(author)}/repos?per_page=100&sort=updated&type=owner"):
                name = str(item.get("name", ""))
                if valid_repository_name(name):
                    repositories[(author.lower(), name.lower())] = item
        except Exception:
            continue
    def build_package(reference: tuple[str, str]) -> dict[str, Any] | None:
        author, slug = reference
        repository = repositories.get((author.lower(), slug.lower()))
        if not repository:
            return None
        description = repository.get("description")
        topics = repository.get("topics", [])
        branch = repository.get("default_branch", "main")
        metadata = package_metadata(slug, branch, author)
        if not metadata.get("manifestValid"):
            return None
        asset_base = f"https://raw.githubusercontent.com/{author}/{slug}/{branch}/assets"
        package = {
            "slug": slug,
            "name": title_for(slug),
            "author": author,
            "description": metadata.get("description") or description,
            "category": category_for(slug, description, topics),
            "tags": topics,
            "repositoryUrl": repository.get("html_url", f"https://github.com/{catalog_owner}/{slug}"),
            "updatedAt": repository.get("updated_at"),
            "branch": branch,
            "visuals": {
                "icon": f"{asset_base}/product_logo.png",
                "splash": f"{asset_base}/splash.png",
                "portrait": f"{asset_base}/splash_setup.png",
            },
        }
        package["revision"] = package_revision(package)
        return package

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(references)))) as executor:
        packages = [package for package in executor.map(build_package, references) if package]
    packages.sort(key=lambda item: item["name"].lower())
    catalog_version = hashlib.sha256("|".join(f"{item['author']}/{item['slug']}:{item['revision']}" for item in packages).encode("utf-8")).hexdigest()[:20]
    snapshot = {"packages": packages, "catalogVersion": catalog_version, "fetchedAt": iso_now(), "source": "GitHub API"}
    CATALOG_SNAPSHOT_CACHE[cache_key] = (time.time() + 300, snapshot)
    return snapshot


def valid_github_login(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value))


def github_public_profile(github_login: str) -> dict[str, str]:
    """Read only GitHub's public identity fields; never keep an OAuth token."""
    if not valid_github_login(github_login):
        return {"githubLogin": github_login, "githubName": github_login, "avatarUrl": f"https://github.com/{quote(github_login)}.png?size=176", "githubUrl": ""}
    try:
        response = requests.get(
            f"https://api.github.com/users/{quote(github_login)}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Foundstore-Flask-Render"},
            timeout=6,
        )
        if response.ok:
            data = response.json()
            return {
                "githubLogin": str(data.get("login") or github_login),
                "githubName": str(data.get("name") or data.get("login") or github_login),
                "avatarUrl": str(data.get("avatar_url") or f"https://github.com/{quote(github_login)}.png?size=176"),
                "githubUrl": str(data.get("html_url") or f"https://github.com/{github_login}"),
            }
    except requests.RequestException:
        pass
    return {"githubLogin": github_login, "githubName": github_login, "avatarUrl": f"https://github.com/{quote(github_login)}.png?size=176", "githubUrl": f"https://github.com/{github_login}"}


def github_public_repositories(github_login: str) -> list[dict[str, str]]:
    """Discover only public repositories. Private repositories require a separate OAuth consent."""
    if not valid_github_login(github_login):
        return []
    repositories: list[dict[str, str]] = []
    for page in range(1, 6):
        try:
            response = requests.get(
                f"https://api.github.com/users/{quote(github_login)}/repos",
                params={"type": "owner", "sort": "updated", "per_page": 100, "page": page},
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Foundstore-Flask-Render"},
                timeout=8,
            )
            if not response.ok:
                break
            page_items = response.json()
            if not isinstance(page_items, list):
                break
            for item in page_items:
                name = str(item.get("name") or "")
                if valid_repository_name(name):
                    repositories.append({"name": name, "url": str(item.get("html_url") or f"https://github.com/{github_login}/{name}"), "description": str(item.get("description") or ""), "updatedAt": str(item.get("updated_at") or "")})
            if len(page_items) < 100:
                break
        except requests.RequestException:
            break
    return repositories


def developer_profile(store: DeviceStore, github_login: str) -> dict[str, str]:
    saved = store.get_developer_profile(github_login) or {}
    profile = github_public_profile(github_login)
    profile["displayName"] = str(saved.get("displayName") or saved.get("display_name") or profile["githubName"])
    profile["bio"] = str(saved.get("bio") or "")
    profile["website"] = str(saved.get("website") or "")
    profile["catalogRepository"] = str(saved.get("catalogRepository") or saved.get("catalog_repository") or "catalog")
    return profile


SCAN_TTL_SECONDS = 6 * 60 * 60
STATIC_SCAN_RULES = (
    ("high", "powershell_encoded", re.compile(r"powershell(?:\.exe)?\s+.*-(?:enc|encodedcommand)\b", re.I), "PowerShell codificado puede ocultar instrucciones."),
    ("high", "remote_pipe_shell", re.compile(r"(?:curl|wget)\b[^\n|]{0,240}\|\s*(?:ba)?sh\b", re.I), "Descarga remota enviada directamente a una shell."),
    ("high", "dynamic_exec", re.compile(r"\b(?:eval|exec)\s*\([^\n]{0,240}(?:base64|b64decode)", re.I), "Ejecución dinámica de contenido codificado."),
    ("medium", "shell_true", re.compile(r"subprocess\.[A-Za-z_]+\([^\n]{0,300}shell\s*=\s*True", re.I), "Subproceso con shell=True requiere revisión."),
    ("medium", "os_system", re.compile(r"\bos\.system\s*\(", re.I), "Ejecución de comandos mediante os.system requiere revisión."),
)


def static_repository_scan(store: DeviceStore, author: str, slug: str, branch: str) -> dict[str, Any]:
    """Evaluate a small public-text sample; this is not an executable malware sandbox."""
    cached = store.get_repository_scan(author, slug, branch)
    if cached and cached.get("scannedAt"):
        try:
            if (utc_now() - parse_iso(str(cached["scannedAt"]))).total_seconds() < SCAN_TTL_SECONDS:
                return cached
        except ValueError:
            pass
    files = ("details.xml", "README.md", "requirements.txt", "autorun", "autorun.bat", "updater.py", "config/settings.json")
    findings: list[dict[str, str]] = []
    inspected: list[str] = []
    for path in files:
        try:
            source = raw_github_text(author, slug, branch, path)[:200_000]
        except OSError:
            continue
        inspected.append(path)
        for severity, rule, pattern, message in STATIC_SCAN_RULES:
            if pattern.search(source):
                findings.append({"severity": severity, "rule": rule, "path": path, "message": message})
    highest = "high" if any(item["severity"] == "high" for item in findings) else "medium" if findings else "none"
    report = {
        "status": "review_required" if findings else "no_static_indicators",
        "highestSeverity": highest,
        "findings": findings,
        "inspectedFiles": inspected,
        "scannedAt": iso_now(),
        "method": "static_public_text_only",
        "disclaimer": "No se ejecutó código ni se analizó un archivo binario; revisa manualmente los hallazgos antes de confiar en un paquete.",
    }
    store.save_repository_scan(author, slug, branch, report)
    return report


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
        OWNER_API_TOKEN=os.environ.get("NULL_HV", ""),
        COMMAND_SIGNING_KEY=os.environ.get("NULL_HV", ""),
        SECRET_KEY=os.environ.get("NULL_HV", ""),
        GITHUB_CLIENT_ID=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""),
        GITHUB_CLIENT_SECRET=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
        PUBLIC_ORIGIN="https://imfoundstore.onrender.com",
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

    def developer_catalog(github_login: str) -> tuple[dict[str, str], dict[str, Any] | None]:
        profile_data = developer_profile(app.extensions["device_store"], github_login)
        try:
            snapshot = catalog_snapshot(github_login, profile_data["catalogRepository"])
        except Exception:
            return profile_data, None
        packages = [{**package, **package_metadata(package["slug"], package.get("branch", "main"), package["author"])} for package in snapshot["packages"]]
        return profile_data, {**snapshot, "packages": packages}

    @app.get("/")
    def index() -> str:
        return render_template("index.html", catalog_owner=CATALOG_OWNER, visitor_country=request.headers.get("CF-IPCountry", ""))

    @app.get("/<author>/<slug>")
    def package_detail(author: str, slug: str) -> Response | str:
        if not valid_github_login(author) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", slug):
            return jsonify({"error": "Aplicación no encontrada"}), 404
        profile_data, snapshot = developer_catalog(author)
        if not snapshot:
            return jsonify({"error": "El catálogo no está disponible"}), 503
        package = next((item for item in snapshot["packages"] if item["slug"].lower() == slug.lower()), None)
        if not package:
            return jsonify({"error": "Aplicación no encontrada"}), 404
        return render_template("package.html", package=package, developer=profile_data, catalog_owner=CATALOG_OWNER, visitor_country=request.headers.get("CF-IPCountry", ""))

    @app.get("/auth/github/login")
    def github_oauth_login() -> Response:
        if not oauth_ready():
            return jsonify({"error": "GitHub OAuth no está configurado"}), 503
        state = secrets.token_urlsafe(24)
        session["github_oauth_state"] = state
        link_id = request.args.get("link", "")
        if link_id:
            session["github_oauth_link"] = link_id
        callback = f"{app.config['PUBLIC_ORIGIN']}/auth/github/callback"
        query = urlencode({"client_id": app.config["GITHUB_CLIENT_ID"], "redirect_uri": callback, "state": state, "scope": "read:user"})
        return redirect(f"https://github.com/login/oauth/authorize?{query}")

    @app.get("/login")
    def legacy_login() -> Response:
        return redirect(url_for("github_oauth_login"))

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

    @app.get("/profile")
    def profile() -> Response | str:
        if not github_login():
            return redirect(url_for("github_oauth_login"))
        return render_template("profile.html", github_login=github_login(), visitor_country=request.headers.get("CF-IPCountry", ""))

    @app.get("/developer/<github_login>")
    def developer_page(github_login: str) -> Response | str:
        if not valid_github_login(github_login):
            return jsonify({"error": "Desarrollador no encontrado"}), 404
        return render_template("developer.html", github_login=github_login, visitor_country=request.headers.get("CF-IPCountry", ""))

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

    @app.get("/manifest.webmanifest")
    def manifest() -> Response:
        return Response(
            json.dumps({"name": "Foundstore for Influent Danenone", "short_name": "Foundstore", "start_url": "/", "display": "standalone", "background_color": "#0c101b", "theme_color": "#0c101b", "icons": [{"src": "/favicon.ico", "sizes": "64x64", "type": "image/svg+xml", "purpose": "any"}]}),
            content_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/service-worker.js")
    def service_worker() -> Response:
        response = send_from_directory(app.static_folder or "static", "service-worker.js", mimetype="application/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/favicon.ico")
    def favicon() -> Response:
        icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='16' fill='#0c3b29'/><path d='M16 20 32 11l16 9v20L32 53 16 40Z' fill='#72e2aa'/><path d='m32 11 16 9-16 10-16-10Z' fill='#c9ffe3'/></svg>"
        return Response(icon, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/assets/github-avatar/<github_login>.png")
    def github_avatar(github_login: str) -> Response:
        if not valid_github_login(github_login):
            return Response(status=404)
        try:
            avatar = requests.get(f"https://github.com/{quote(github_login)}.png?size=176", headers={"User-Agent": "Foundstore-Flask-Render"}, timeout=8)
            content_type = avatar.headers.get("Content-Type", "")
            if not avatar.ok or not content_type.startswith("image/") or len(avatar.content) > 2_000_000:
                return Response(status=404)
            return Response(avatar.content, content_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
        except requests.RequestException:
            return Response(status=502)

    @app.get("/api/v1/catalog")
    def catalog() -> Response:
        try:
            snapshot = catalog_snapshot()
            packages = [{**package, **package_metadata(package["slug"], package.get("branch", "main"), package["author"])} for package in snapshot["packages"]]
            return jsonify({**snapshot, "packages": packages})
        except Exception as error:
            return jsonify({"error": "No se pudo obtener el catálogo de GitHub", "detail": type(error).__name__}), 502

    @app.post("/api/v1/catalog/changes")
    def catalog_changes() -> Response:
        payload = request.get_json(silent=True) or {}
        known = payload.get("known", {})
        if not isinstance(known, dict) or len(known) > 500 or any(not isinstance(key, str) or not isinstance(value, str) or len(key) > 160 or len(value) > 64 for key, value in known.items()):
            return jsonify({"error": "El estado de catálogo no es válido"}), 400
        try:
            snapshot = catalog_snapshot()
            current = {f"{item['author']}/{item['slug']}": item for item in snapshot["packages"]}
            changed = [{**package, **package_metadata(package["slug"], package.get("branch", "main"), package["author"])} for key, package in current.items() if known.get(key) != package["revision"]]
            removed = sorted(key for key in known if key not in current)
            return jsonify({"packages": changed, "removed": removed, "catalogVersion": snapshot["catalogVersion"], "fetchedAt": snapshot["fetchedAt"]})
        except Exception as error:
            return jsonify({"error": "No se pudo actualizar el catálogo de GitHub", "detail": type(error).__name__}), 502

    @app.get("/api/v1/catalog/<slug>")
    def catalog_package(slug: str) -> Response:
        try:
            package = next((item for item in catalog_snapshot()["packages"] if item["slug"].lower() == slug.lower()), None)
        except Exception as error:
            return jsonify({"error": "No se pudo obtener el catálogo de GitHub", "detail": type(error).__name__}), 502
        if not package:
            return jsonify({"error": "Aplicación no encontrada"}), 404
        return jsonify({"package": {**package, **package_metadata(slug, package.get("branch", "main"), package["author"])}})

    @app.get("/api/v1/packages/<author>/<slug>/security")
    @app.get("/api/v1/catalog/<slug>/security", defaults={"author": CATALOG_OWNER})
    def catalog_package_security(author: str, slug: str) -> Response:
        if not valid_github_login(author):
            return jsonify({"error": "Desarrollador no encontrado"}), 404
        _, snapshot = developer_catalog(author)
        if not snapshot:
            return jsonify({"error": "El catálogo del desarrollador no está disponible"}), 503
        package = next((item for item in snapshot["packages"] if item["slug"].lower() == slug.lower()), None)
        if not package:
            return jsonify({"error": "Aplicación no encontrada"}), 404
        return jsonify({"scan": static_repository_scan(app.extensions["device_store"], package["author"], package["slug"], package.get("branch", "main"))})

    @app.get("/api/v1/developers/<github_login>")
    def developer_api(github_login: str) -> Response:
        if not valid_github_login(github_login):
            return jsonify({"error": "Desarrollador no encontrado"}), 404
        profile_data, snapshot = developer_catalog(github_login)
        viewer = session.get("github_login")
        store = app.extensions["device_store"]
        own_profile = bool(viewer and str(viewer).lower() == github_login.lower())
        return jsonify({"profile": profile_data, "catalog": snapshot, "catalogAvailable": bool(snapshot), "followerCount": store.developer_follower_count(github_login), "following": bool(viewer and store.is_following_developer(str(viewer), github_login)), "isOwnProfile": own_profile})

    @app.get("/api/v1/me/following")
    def my_following() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para seguir desarrolladores"}), 401
        return jsonify({"developers": app.extensions["device_store"].list_followed_developers(login)})

    @app.get("/api/v1/me/repositories")
    def my_public_repositories() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para descubrir repositorios públicos"}), 401
        return jsonify({"repositories": github_public_repositories(login), "scope": "public_only", "privateRepositoriesRequireConsent": True})

    @app.route("/api/v1/me/following/<developer_login>", methods=["POST", "DELETE"])
    def following_developer(developer_login: str) -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para seguir desarrolladores"}), 401
        if not valid_github_login(developer_login) or developer_login.lower() == login.lower():
            return jsonify({"error": "El desarrollador elegido no es válido"}), 400
        store = app.extensions["device_store"]
        following = store.follow_developer(login, developer_login) if request.method == "POST" else not store.unfollow_developer(login, developer_login)
        return jsonify({"developer": developer_login, "following": following, "followerCount": store.developer_follower_count(developer_login)})

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

    @app.get("/api/v1/me/licenses")
    def my_licenses() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para ver tus licencias"}), 401
        return jsonify({"licenses": app.extensions["device_store"].list_licenses_for_owner(login)})

    @app.route("/api/v1/me/profile", methods=["GET", "PATCH"])
    def my_profile() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub para administrar tu perfil"}), 401
        store = app.extensions["device_store"]
        if request.method == "PATCH":
            payload = request.get_json(silent=True) or {}
            display_name = str(payload.get("displayName", "")).strip()[:80]
            bio = str(payload.get("bio", "")).strip()[:500]
            website = str(payload.get("website", "")).strip()[:240]
            repository = str(payload.get("catalogRepository", "catalog")).strip()
            if website and not re.fullmatch(r"https://[^\s<>{}|\\^`\[\]]+", website):
                return jsonify({"error": "El sitio web debe usar HTTPS"}), 400
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", repository):
                return jsonify({"error": "El repositorio de catálogo no es válido"}), 400
            store.update_developer_profile(login, {"displayName": display_name, "bio": bio, "website": website, "catalogRepository": repository})
        profile_data, snapshot = developer_catalog(login)
        return jsonify({"profile": profile_data, "catalog": snapshot, "catalogAvailable": bool(snapshot)})

    @app.post("/api/v1/me/licenses")
    def create_my_license() -> Response:
        login = github_login()
        if not login:
            return jsonify({"error": "Inicia sesión con GitHub antes de crear una licencia"}), 401
        payload = request.get_json(silent=True) or {}
        restore_apps = payload.get("restoreApps", [])
        if not isinstance(restore_apps, list) or any(not isinstance(item, dict) for item in restore_apps):
            return jsonify({"error": "restoreApps debe ser una lista de aplicaciones aprobadas"}), 400
        return jsonify(app.extensions["device_store"].create_license(restore_apps, login)), 201

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
        metadata = package_metadata(slug, package.get("branch", "main"))
        if metadata["platformTargets"] and device.get("platform", "Danenone") not in metadata["platformTargets"]:
            return jsonify({"error": "La aplicación no es compatible con la plataforma del dispositivo elegido", "platformTargets": metadata["platformTargets"], "devicePlatform": device.get("platform", "Danenone")}), 409
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
        platform = canonical_platform(str(payload.get("platform", "Danenone")))
        link = app.extensions["device_store"].begin_license_link(license_code, display_name, platform)
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
    from waitress import serve

    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threads=8)
