from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


API_ORIGIN = os.environ.get("FOUNDSTORE_API_ORIGIN", "https://imfoundstore.onrender.com").rstrip("/")
USER_AGENT = "Foundstore-Qt6/1.1"
CACHE_TTL_SECONDS = 15 * 60
CACHE_SCHEMA_VERSION = 2


class FoundstoreApiError(RuntimeError):
    pass


def _cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    directory = base / "influent-danenone" / "foundstore"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cache_path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        raise FoundstoreApiError("La clave de caché no es segura")
    return _cache_dir() / f"{name}.json"


def _read_cache(name: str) -> tuple[Any, float] | None:
    path = _cache_path(name)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != CACHE_SCHEMA_VERSION or record.get("origin") != API_ORIGIN:
            return None
        cached_at = float(record["cached_at"])
        payload = record["payload"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload, cached_at


def _write_cache(name: str, payload: Any) -> None:
    path = _cache_path(name)
    temporary = path.with_suffix(".tmp")
    record = {"schema": CACHE_SCHEMA_VERSION, "cached_at": time.time(), "origin": API_ORIGIN, "payload": payload}
    temporary.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def _is_fresh(cached_at: float) -> bool:
    return time.time() - cached_at < CACHE_TTL_SECONDS


def _get(path: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{API_ORIGIN}{path}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise FoundstoreApiError("No se pudo consultar la API pública de Foundstore") from error
    if not isinstance(data, dict):
        raise FoundstoreApiError("La API pública devolvió un formato inesperado")
    return data


def _normalize(package: dict[str, Any]) -> dict[str, Any]:
    visuals = package.get("visuals") if isinstance(package.get("visuals"), dict) else {}
    stars = package.get("stars")
    return {
        **package,
        "author": str(package.get("author") or ""),
        "app": str(package.get("app") or package.get("slug") or ""),
        "slug": str(package.get("slug") or package.get("app") or ""),
        "name": str(package.get("name") or package.get("app") or "Paquete Fluthin"),
        "publisher": str(package.get("publisher") or "Influent"),
        "description": str(package.get("description") or ""),
        "platform": str(package.get("platform") or ""),
        "platformTargets": package.get("platformTargets") if isinstance(package.get("platformTargets"), list) else [],
        "stars": int(stars) if isinstance(stars, int) else None,
        "visuals": visuals,
        "packageIcon": str(package.get("packageIcon") or visuals.get("icon") or ""),
        "readme": str(package.get("readme") or ""),
    }


def cached_catalog() -> tuple[list[dict[str, Any]], bool] | None:
    cached = _read_cache("catalog")
    if cached is None:
        return None
    payload, cached_at = cached
    if not isinstance(payload, list):
        return None
    return [_normalize(item) for item in payload if isinstance(item, dict)], _is_fresh(cached_at)


def catalog(force: bool = False) -> list[dict[str, Any]]:
    cached = cached_catalog()
    if cached is not None and cached[1] and not force:
        return cached[0]
    data = _get("/api/v1/catalog")
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise FoundstoreApiError("La respuesta de catálogo no incluye paquetes")
    normalized = [_normalize(item) for item in packages if isinstance(item, dict)]
    _write_cache("catalog", normalized)
    return normalized


def package_detail(slug: str, force: bool = False) -> dict[str, Any]:
    safe_slug = quote(slug.strip(), safe="")
    if not safe_slug:
        raise FoundstoreApiError("La ficha requiere un identificador de paquete")
    cache_name = f"detail-{safe_slug.lower()}"
    cached = _read_cache(cache_name)
    if cached is not None and _is_fresh(cached[1]) and not force and isinstance(cached[0], dict):
        return _normalize(cached[0])
    data = _get(f"/api/v1/catalog/{safe_slug}")
    package = data.get("package")
    if not isinstance(package, dict):
        raise FoundstoreApiError("La ficha pública no incluye datos de paquete")
    normalized = _normalize(package)
    _write_cache(cache_name, normalized)
    return normalized
