"""Cliente local para Cloud Danenone Devices.

Foundstore y este agente usan la misma identidad DaneDesk. El agente no ejecuta
instalaciones en segundo plano: recibe solicitudes de la nube, las guarda como
pendientes y sólo ejecuta `flut cloud approve <id>` cuando una persona local las
aprueba explícitamente.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import fluthin_manager as manager

DEFAULT_STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "foundstore" / "cloud-devices.json"
PAIRING_CODE = re.compile(r"^[A-Za-z0-9]{6,12}$")
PACKAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class CloudDevicesError(RuntimeError):
    pass


class CloudDevicesClient:
    def __init__(self, state_path: Path | None = None, allow_insecure_local: bool = False):
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.allow_insecure_local = allow_insecure_local

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CloudDevicesError("El estado local de Cloud Danenone Devices no es válido") from error

    def _save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".cloud-devices-", dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False, sort_keys=True)
                file.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _connected(self) -> dict[str, Any]:
        state = self._load()
        if not all(state.get(key) for key in ("server", "deviceId", "agentToken")):
            raise CloudDevicesError("Este DaneDesk aún no está conectado a Cloud Danenone Devices")
        return state

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self._connected()
        url = f"{state['server'].rstrip('/')}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", "X-Danenone-Agent-Token": state["agentToken"]}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(url, data=body, headers=headers, method=method), timeout=35) as response:  # nosec B310: endpoint saved only after explicit pairing
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:240]
            raise CloudDevicesError(f"Cloud Danenone Devices respondió {error.code}: {detail}") from error
        except URLError as error:
            raise CloudDevicesError("No se pudo conectar con Cloud Danenone Devices") from error

    def pair(self, server: str, code: str, display_name: str) -> dict[str, Any]:
        is_local_test_server = self.allow_insecure_local and (server.startswith("http://127.0.0.1:") or server.startswith("http://localhost:"))
        if not server.startswith("https://") and not is_local_test_server:
            raise CloudDevicesError("El servidor debe usar HTTPS")
        if not PAIRING_CODE.fullmatch(code):
            raise CloudDevicesError("El código de pairing debe tener entre 6 y 12 caracteres alfanuméricos")
        payload = json.dumps({"code": code.upper(), "displayName": display_name.strip()[:80] or "DaneDesk"}).encode("utf-8")
        try:
            with urlopen(Request(f"{server.rstrip('/')}/api/v1/agent/bootstrap", data=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST"), timeout=20) as response:  # nosec B310: explicit server supplied by the local owner
                result = json.load(response)
        except (HTTPError, URLError) as error:
            raise CloudDevicesError("No se pudo completar el pairing con Cloud Danenone Devices") from error
        if not all(result.get(key) for key in ("id", "agentToken")):
            raise CloudDevicesError("La respuesta de pairing no contiene una identidad válida")
        state = {"server": server.rstrip("/"), "deviceId": result["id"], "agentToken": result["agentToken"], "displayName": display_name.strip()[:80] or "DaneDesk", "pendingActions": []}
        self._save(state)
        return {"deviceId": state["deviceId"], "server": state["server"], "platform": result.get("platform", "Danenone")}

    def status(self) -> dict[str, Any]:
        state = self._connected()
        return {"connected": True, "deviceId": state["deviceId"], "displayName": state.get("displayName", "DaneDesk"), "server": state["server"], "pendingActions": len(state.get("pendingActions", []))}

    def cloud_state(self) -> dict[str, Any]:
        state = self._connected()
        remote = self._request("GET", f"/api/v1/devices/{state['deviceId']}/state").get("device")
        if not isinstance(remote, dict) or remote.get("id") != state["deviceId"]:
            raise CloudDevicesError("Cloud Danenone Devices no devolvió el estado de este DaneDesk")
        return {**self.status(), "remote": remote}

    def poll(self, wait: int = 25) -> dict[str, Any]:
        state = self._connected()
        wait = min(max(wait, 0), 25)
        result = self._request("GET", f"/api/v1/devices/{state['deviceId']}/commands/next?wait={wait}")
        pending = state.setdefault("pendingActions", [])
        known = {item["id"] for item in pending}
        for command in result.get("commands", []):
            if command.get("id") not in known:
                pending.append(command)
                if command.get("type") == "install_request":
                    self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "install.awaiting_approval", "data": {"commandId": command["id"], "package": command.get("payload", {}).get("package")}})
        self._save(state)
        return {"commands": result.get("commands", []), "retryAfterSeconds": result.get("retryAfterSeconds", 15), "localApprovalRequired": [command["id"] for command in result.get("commands", []) if command.get("type") == "install_request"]}

    def announce_presence(self) -> dict[str, Any]:
        state = self._connected()
        return self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "agent.connected", "data": {"client": "flut", "nonce": secrets.token_hex(8)}})

    def daemon(self) -> None:
        """Mantiene un único long-poll, con retroceso progresivo al fallar la red."""
        self.announce_presence()
        delay = 1
        while True:
            try:
                result = self.poll(wait=25)
                delay = max(1, int(result.get("retryAfterSeconds", 15)))
            except CloudDevicesError:
                delay = min(delay * 2, 120)
            time.sleep(delay)

    def approve(self, command_id: str) -> dict[str, Any]:
        state = self._connected()
        command = next((item for item in state.get("pendingActions", []) if item.get("id") == command_id), None)
        if not command:
            raise CloudDevicesError("La solicitud no existe en las acciones pendientes de este DaneDesk")
        if command.get("type") != "install_request":
            raise CloudDevicesError("Esta acción no admite instalación mediante Foundstore")
        payload = command.get("payload", {})
        reference = str(payload.get("package", ""))
        if not PACKAGE_REFERENCE.fullmatch(reference):
            raise CloudDevicesError("La solicitud contiene una referencia de paquete no válida")
        self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "install.approved", "data": {"commandId": command_id, "package": reference}})
        try:
            result = manager.install(reference, version=payload.get("version") or None)
        except Exception as error:
            self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "install.failed", "data": {"commandId": command_id, "package": reference, "reason": str(error)[:240]}})
            raise
        state["pendingActions"] = [item for item in state["pendingActions"] if item.get("id") != command_id]
        self._save(state)
        self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "install.completed", "data": {"commandId": command_id, "package": reference}})
        return result

    def reject(self, command_id: str) -> dict[str, Any]:
        state = self._connected()
        command = next((item for item in state.get("pendingActions", []) if item.get("id") == command_id), None)
        if not command:
            raise CloudDevicesError("La solicitud no existe en las acciones pendientes de este DaneDesk")
        state["pendingActions"] = [item for item in state["pendingActions"] if item.get("id") != command_id]
        self._save(state)
        return self._request("POST", f"/api/v1/devices/{state['deviceId']}/events", {"topic": "install.rejected", "data": {"commandId": command_id, "package": command.get("payload", {}).get("package")}})

    def restore_apps(self) -> list[dict[str, str]]:
        state = self._connected()
        return self._request("GET", f"/api/v1/devices/{state['deviceId']}/restore-apps").get("approvedApps", [])
