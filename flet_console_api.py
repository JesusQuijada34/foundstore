"""Cliente HTTP de Foundstore Console.

El módulo no guarda credenciales: la interfaz Flet delega la persistencia del token
de consola al almacenamiento seguro nativo de cada plataforma.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_ORIGIN = os.environ.get("FOUNDSTORE_API_ORIGIN", "https://imfoundstore.onrender.com").rstrip("/")
USER_AGENT = "Foundstore-Flet-Console/0.1"


class ConsoleApiError(RuntimeError):
    """Una respuesta esperada de red o autorización no pudo completarse."""


def pkce_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise ConsoleApiError("El verificador PKCE no tiene un formato válido")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class ConsoleAuthorization:
    request_id: str
    user_code: str
    verification_uri: str
    expires_at: str


class FoundstoreConsoleApi:
    def __init__(self, origin: str = DEFAULT_ORIGIN, console_token: str | None = None, session: requests.Session | None = None) -> None:
        if not re.fullmatch(r"https://[^\s/]+(?:/[^\s]*)?", origin):
            raise ConsoleApiError("El origen de Foundstore debe usar HTTPS")
        self.origin = origin.rstrip("/")
        self.console_token = console_token or ""
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.console_token:
            request_headers["X-Foundstore-Console-Token"] = self.console_token
        request_headers.update(headers or {})
        try:
            response = self.session.request(method, f"{self.origin}{path}", json=payload, headers=request_headers, timeout=20)
            data = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as error:
            raise ConsoleApiError("No se pudo comunicar con Foundstore") from error
        if not response.ok:
            message = data.get("error") if isinstance(data, dict) else None
            if response.status_code == 401:
                raise ConsoleApiError("La sesión de Foundstore Console venció o fue revocada")
            raise ConsoleApiError(str(message or "Foundstore rechazó la operación"))
        return data if isinstance(data, dict) else {}

    def begin_authorization(self, verifier: str) -> ConsoleAuthorization:
        data = self._request("POST", "/api/v1/console-auth", {"pkceChallenge": pkce_challenge(verifier)})
        required = ("requestId", "userCode", "verificationUri", "expiresAt")
        if not all(isinstance(data.get(key), str) and data[key] for key in required):
            raise ConsoleApiError("Foundstore devolvió una autorización incompleta")
        return ConsoleAuthorization(data["requestId"], data["userCode"], data["verificationUri"], data["expiresAt"])

    def authorization_status(self, authorization: ConsoleAuthorization) -> str:
        data = self._request("GET", f"/api/v1/console-auth/{authorization.request_id}", headers={"X-Foundstore-Console-Code": authorization.user_code})
        return str(data.get("status") or "")

    def claim_authorization(self, authorization: ConsoleAuthorization, verifier: str) -> dict[str, str]:
        data = self._request("POST", f"/api/v1/console-auth/{authorization.request_id}/token", {"pkceVerifier": verifier})
        if not isinstance(data.get("consoleToken"), str) or not isinstance(data.get("account"), str):
            raise ConsoleApiError("Foundstore no emitió una sesión de consola válida")
        self.console_token = data["consoleToken"]
        return {"account": data["account"], "expiresAt": str(data.get("expiresAt") or "")}

    def logout(self) -> None:
        self._request("DELETE", "/api/v1/console-session")
        self.console_token = ""

    def devices(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/me/devices")
        return [item for item in data.get("devices", []) if isinstance(item, dict)]

    def licenses(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/me/licenses")
        return [item for item in data.get("licenses", []) if isinstance(item, dict)]

    def create_license(self) -> dict[str, Any]:
        return self._request("POST", "/api/v1/me/licenses", {})

    def revoke_license(self, license_code: str, reason: str) -> None:
        self._request("POST", "/api/v1/me/licenses/revoke", {"license": license_code, "reason": reason})

    def catalog(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/catalog")
        return [item for item in data.get("packages", []) if isinstance(item, dict)]

    def request_installation(self, device_id: str, slug: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/me/devices/{device_id}/installations", {"slug": slug})

    def device_installations(self, device_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/api/v1/me/devices/{device_id}/installations")
        return [item for item in data.get("installations", []) if isinstance(item, dict)]
