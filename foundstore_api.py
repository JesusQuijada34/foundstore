from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import requests


API_ORIGIN = os.environ.get("FOUNDSTORE_API_ORIGIN", "https://imfoundstore.onrender.com").rstrip("/")
USER_AGENT = "Foundstore-Qt6/1.1"


class FoundstoreApiError(RuntimeError):
    pass


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


def catalog() -> list[dict[str, Any]]:
    data = _get("/api/v1/catalog")
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise FoundstoreApiError("La respuesta de catálogo no incluye paquetes")
    return [_normalize(item) for item in packages if isinstance(item, dict)]


def package_detail(slug: str) -> dict[str, Any]:
    safe_slug = quote(slug.strip(), safe="")
    if not safe_slug:
        raise FoundstoreApiError("La ficha requiere un identificador de paquete")
    data = _get(f"/api/v1/catalog/{safe_slug}")
    package = data.get("package")
    if not isinstance(package, dict):
        raise FoundstoreApiError("La ficha pública no incluye datos de paquete")
    return _normalize(package)
