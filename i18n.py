"""Internationalization helpers for Foundstore.

The catalog is intentionally dependency-free so the Flask service remains easy to
run on Render. Unknown locales are normalized and safely fall back to Spanish.
"""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from typing import Any

import requests
from flask import Request

DEFAULT_LOCALE = "es"
COOKIE_NAME = "foundstore_locale"
SUPPORTED_LOCALES = {
    "es": "Español", "en": "English", "fr": "Français", "de": "Deutsch",
    "pt": "Português", "it": "Italiano", "nl": "Nederlands", "ca": "Català",
    "ja": "日本語", "ko": "한국어", "zh-CN": "简体中文", "ru": "Русский",
    "ar": "العربية", "hi": "हिन्दी", "tr": "Türkçe", "pl": "Polski", "uk": "Українська",
}
COUNTRY_TO_LOCALE = {
    "ES":"es","MX":"es","AR":"es","BO":"es","CL":"es","CO":"es","CR":"es","CU":"es","DO":"es","EC":"es","GT":"es","HN":"es","NI":"es","PA":"es","PE":"es","PR":"es","PY":"es","SV":"es","UY":"es","VE":"es",
    "US":"en","GB":"en","IE":"en","CA":"en","AU":"en","NZ":"en","IN":"hi","SG":"en","PH":"en","ZA":"en",
    "FR":"fr","BE":"fr","LU":"fr","MC":"fr","CH":"fr",
    "DE":"de","AT":"de","LI":"de",
    "PT":"pt","BR":"pt","IT":"it","NL":"nl","ID":"en","JP":"ja","KR":"ko","CN":"zh-CN","TW":"zh-CN","HK":"zh-CN",
    "RU":"ru","BY":"ru","KZ":"ru","KG":"ru","TJ":"ru","TM":"ru","UZ":"ru","UA":"uk","TR":"tr","PL":"pl",
    "SA":"ar","AE":"ar","EG":"ar","MA":"ar","DZ":"ar","TN":"ar","JO":"ar","LB":"ar","IQ":"ar","IL":"ar",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        "Language": "Idioma", "Choose language": "Elegir idioma", "Home": "Inicio", "Packages": "Paquetes", "Developers": "Desarrolladores", "Settings": "Configuración", "Help": "Ayuda", "Sign in": "Iniciar sesión", "Sign out": "Cerrar sesión", "Back": "Volver", "Search": "Buscar", "Download": "Descargar", "Loading…": "Cargando…", "Try again later.": "Vuelve a intentarlo más tarde.", "Not available": "No disponible", "Public catalog": "Catálogo público", "Your profile": "Tu perfil", "Follow": "Seguir", "Following": "Siguiendo", "followers": "seguidores", "following": "seguidos", "packages": "paquetes", "Developer": "Desarrollador", "Author": "Autor", "Platform": "Plataforma", "Version": "Versión", "Category": "Categoría", "Package name": "Nombre del paquete", "Information": "Información", "Privacy": "Privacidad", "Error": "Error",
    },
    "en": {
        "Language": "Language", "Choose language": "Choose language", "Home": "Home", "Packages": "Packages", "Developers": "Developers", "Settings": "Settings", "Help": "Help", "Sign in": "Sign in", "Sign out": "Sign out", "Back": "Back", "Search": "Search", "Download": "Download", "Loading…": "Loading…", "Try again later.": "Try again later.", "Not available": "Not available", "Public catalog": "Public catalog", "Your profile": "Your profile", "Follow": "Follow", "Following": "Following", "followers": "followers", "following": "following", "packages": "packages", "Developer": "Developer", "Author": "Author", "Platform": "Platform", "Version": "Version", "Category": "Category", "Package name": "Package name", "Information": "Information", "Privacy": "Privacy", "Error": "Error",
    },
}

# High-value UI strings are translated explicitly; every other key safely falls
# back to Spanish so a missing translation never breaks rendering.
TRANSLATIONS.update({locale: dict(TRANSLATIONS["en"]) for locale in SUPPORTED_LOCALES if locale not in TRANSLATIONS})


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    value = value.replace("_", "-").strip()
    if value in SUPPORTED_LOCALES:
        return value
    base = value.split("-", 1)[0].lower()
    aliases = {"zh": "zh-CN", "cmn": "zh-CN", "iw": "ar", "in": "hi"}
    return aliases.get(base, base if base in SUPPORTED_LOCALES else None)


def language_from_accept_language(header: str | None) -> str | None:
    candidates: list[tuple[float, str]] = []
    for item in (header or "").split(","):
        bits = item.strip().split(";q=")
        locale = normalize_locale(bits[0])
        if not locale:
            continue
        try:
            quality = float(bits[1]) if len(bits) > 1 else 1.0
        except ValueError:
            quality = 0.0
        candidates.append((quality, locale))
    return max(candidates, default=(0.0, None))[1]


@lru_cache(maxsize=256)
def locale_from_ip(ip: str | None, country_hint: str | None = None) -> str | None:
    country = (country_hint or "").upper()
    if country in COUNTRY_TO_LOCALE:
        return COUNTRY_TO_LOCALE[country]
    if not ip or ip in {"127.0.0.1", "::1"} or ip.startswith(("10.", "192.168.", "172.")):
        return None
    try:
        response = requests.get(f"https://ipwho.is/{ip}", timeout=1.5)
        data: dict[str, Any] = response.json() if response.ok else {}
        return COUNTRY_TO_LOCALE.get(str(data.get("country_code", "")).upper())
    except (requests.RequestException, ValueError, TypeError):
        return None


def resolve_locale(request: Request) -> str:
    explicit = normalize_locale(request.args.get("lang"))
    if explicit:
        return explicit
    cookie = normalize_locale(request.cookies.get(COOKIE_NAME))
    if cookie:
        return cookie
    detected = locale_from_ip(request.headers.get("X-Forwarded-For", request.remote_addr), request.headers.get("CF-IPCountry"))
    return detected or language_from_accept_language(request.headers.get("Accept-Language")) or DEFAULT_LOCALE


def translate(key: str, locale: str = DEFAULT_LOCALE, **values: Any) -> str:
    locale = normalize_locale(locale) or DEFAULT_LOCALE
    text = TRANSLATIONS.get(locale, {}).get(key) or TRANSLATIONS["es"].get(key) or key
    return text.format(**values) if values else text


def catalog() -> str:
    return json.dumps(SUPPORTED_LOCALES, ensure_ascii=False)
