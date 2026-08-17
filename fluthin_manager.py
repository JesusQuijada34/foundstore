from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
import time
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

CATALOG_URL = "https://raw.githubusercontent.com/JesusQuijada34/catalog/main/repo.list"
GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"


def _state_dir() -> Path:
    path = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "influent-danenone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_root() -> Path:
    requested = os.environ.get("FLUT_ROOT")
    if requested:
        root = Path(requested).expanduser()
    elif getattr(os, "geteuid", lambda: -1)() == 0:
        root = Path("/opt/fluthin")
    else:
        root = Path.home() / ".local/share/influent-danenone/fluthin"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_segment(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"{field} inseguro: {value!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(f"{field} contiene caracteres no permitidos: {value!r}")
    return value


def parse_reference(reference: str) -> tuple[str, str]:
    if "://" in reference:
        raise ValueError("La referencia debe usar author/package, no una URL")
    parts = reference.strip().split("/")
    if len(parts) != 2:
        raise ValueError("La referencia debe tener el formato author/package")
    return _safe_segment(parts[0], "author"), _safe_segment(parts[1], "package")


def _request(url: str, **kwargs: Any) -> requests.Response:
    headers = {"User-Agent": "Influent-Danenone-flut/1.0", "Accept": "application/vnd.github+json"}
    headers.update(kwargs.pop("headers", {}))
    response = requests.get(url, headers=headers, timeout=20, **kwargs)
    response.raise_for_status()
    return response


def _xml_text(root: ET.Element, tag: str, fallback: str = "") -> str:
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else fallback


def parse_details(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    if root.tag != "app":
        root = root.find(".//app")
    if root is None:
        raise ValueError("details.xml no contiene <app>")
    metadata = {
        "publisher": _xml_text(root, "publisher", _xml_text(root, "empresa")),
        "app": _xml_text(root, "app", _xml_text(root, "name")),
        "name": _xml_text(root, "name", _xml_text(root, "titulo")),
        "version": _xml_text(root, "version"),
        "author": _xml_text(root, "author", _xml_text(root, "autor")),
        "platform": _xml_text(root, "platform", _xml_text(root, "plataforma", "AlphaCube")),
        "description": _xml_text(root, "description"),
    }
    for field in ("publisher", "app", "name", "version", "author", "platform"):
        if not metadata[field]:
            raise ValueError(f"details.xml carece de {field}")
    _safe_segment(metadata["publisher"], "publisher")
    _safe_segment(metadata["app"], "app")
    return metadata


def catalog_repositories(force: bool = False) -> list[str]:
    cache = _state_dir() / "catalog.json"
    if cache.exists() and not force and time.time() - cache.stat().st_mtime < 300:
        return json.loads(cache.read_text(encoding="utf-8"))
    text = _request(CATALOG_URL).text
    repositories = [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]
    repositories = [_safe_segment(item, "catalog-repo") for item in repositories]
    cache.write_text(json.dumps(repositories, indent=2), encoding="utf-8")
    return repositories


def repository_details(author: str, package: str) -> dict[str, str]:
    author, package = parse_reference(f"{author}/{package}")
    for branch in ("main", "master"):
        url = f"{RAW_BASE}/{urllib.parse.quote(author)}/{urllib.parse.quote(package)}/{branch}/details.xml"
        try:
            return parse_details(_request(url).content)
        except (requests.RequestException, ValueError):
            continue
    raise FileNotFoundError(f"No se encontró details.xml en {author}/{package}")


def catalog(force: bool = False) -> list[dict[str, str]]:
    result = []
    for repo in catalog_repositories(force=force):
        try:
            details = repository_details(*repo.split("/", 1)) if "/" in repo else repository_details("JesusQuijada34", repo)
            details["repository"] = repo if "/" in repo else f"JesusQuijada34/{repo}"
            result.append(details)
        except (FileNotFoundError, requests.RequestException, ValueError):
            continue
    return result


def latest_release(author: str, package: str, version: str | None = None) -> dict[str, Any]:
    author, package = parse_reference(f"{author}/{package}")
    if version:
        tag = urllib.parse.quote(version, safe="")
        url = f"{GITHUB_API}/repos/{author}/{package}/releases/tags/{tag}"
    else:
        url = f"{GITHUB_API}/repos/{author}/{package}/releases/latest"
    return _request(url).json()


def current_platform_key() -> str:
    override = os.environ.get("FLUT_PLATFORM", "").strip().lower()
    if override in {"danenone", "linux"}:
        return "Danenone"
    if override in {"knosthalij", "windows"}:
        return "Knosthalij"
    if platform.system().lower().startswith("windows"):
        return "Knosthalij"
    return "Danenone"


def _asset_score(name: str, platform_key: str) -> int:
    lower = name.lower()
    if not lower.endswith((".iflapp", ".zip")):
        return -1
    score = 1
    if platform_key == "Danenone" and any(token in lower for token in ("danenone", "linux")):
        score += 10
    if platform_key == "Knosthalij" and any(token in lower for token in ("knosthalij", "windows", ".exe")):
        score += 10
    if "iflapp" in lower:
        score += 3
    return score


def select_asset(release: dict[str, Any], platform_key: str | None = None) -> dict[str, Any]:
    platform_key = platform_key or current_platform_key()
    assets = release.get("assets", [])
    ranked = sorted(assets, key=lambda asset: _asset_score(asset.get("name", ""), platform_key), reverse=True)
    if not ranked or _asset_score(ranked[0].get("name", ""), platform_key) < 0:
        raise FileNotFoundError(f"El release no contiene un `.iflapp` para {platform_key}")
    return ranked[0]


def _validate_zip(path: Path) -> dict[str, str]:
    if not zipfile.is_zipfile(path):
        raise ValueError("El artefacto no es un ZIP/.iflapp válido")
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            target = (Path("/tmp/flut-extract") / name).resolve()
            if not str(target).startswith("/tmp/flut-extract/"):
                raise ValueError(f"Path traversal detectado: {name}")
        try:
            xml = archive.read("details.xml")
        except KeyError as exc:
            raise ValueError("El paquete no contiene details.xml") from exc
    return parse_details(xml)


def _version_key(version: str) -> tuple[int, int, int]:
    match = re.search(r"v?(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    return tuple(int(item or 0) for item in match.groups()) if match else (0, 0, 0)


def _installed_records() -> list[dict[str, Any]]:
    records = []
    for details_file in install_root().glob("*/ */details.xml"):
        pass
    for details_file in install_root().glob("*/*/*/details.xml"):
        try:
            metadata = parse_details(details_file.read_bytes())
            manifest_path = details_file.parent / "install.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
            records.append({"metadata": metadata, "path": str(details_file.parent), "manifest": manifest})
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return records


def installed() -> list[dict[str, Any]]:
    return _installed_records()


def _notify(payload: dict[str, Any]) -> None:
    path = _state_dir() / "notifications.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    current.append({"created": int(time.time()), **payload})
    path.write_text(json.dumps(current[-100:], indent=2, ensure_ascii=False), encoding="utf-8")


def _desktop_path(metadata: dict[str, str]) -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications" / f"influent-{metadata['app']}.desktop"


def _find_executable(install_dir: Path, preferred_name: str | None = None) -> Path | None:
    if preferred_name:
        preferred = [install_dir / preferred_name, install_dir / "bin" / preferred_name]
        exact = next((item for item in preferred if item.is_file() and os.access(item, os.X_OK)), None)
        if exact:
            return exact
    search_dirs = [install_dir, install_dir / "bin"]
    return next((item for folder in search_dirs if folder.is_dir() for item in folder.iterdir() if item.is_file() and os.access(item, os.X_OK) and item.name not in {"autorun", "flut", "fluthin_manager"}), None)


def _register_desktop(install_dir: Path, metadata: dict[str, str], executable: Path | None) -> None:
    desktop = _desktop_path(metadata)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    exec_value = str(executable) if executable else f"flut launch {metadata['author']}/{metadata['app']}"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\n" +
        f"Name={metadata['name']}\nComment={metadata.get('description', '')}\n" +
        f"Exec={exec_value}\nCategories=System;Utility;\nTerminal={'true' if executable is None else 'false'}\n",
        encoding="utf-8",
    )


def install(reference: str, version: str | None = None, local_file: str | None = None) -> dict[str, Any]:
    author, package = parse_reference(reference)
    release = latest_release(author, package, version=version) if not local_file else None
    temp_dir = Path(tempfile.mkdtemp(prefix="flut-install-"))
    try:
        if local_file:
            artifact = Path(local_file).expanduser().resolve()
            metadata = _validate_zip(artifact)
            asset_name = artifact.name
            release_tag = metadata["version"]
            sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
        else:
            asset = select_asset(release)
            asset_url = asset["browser_download_url"]
            artifact = temp_dir / asset["name"]
            with _request(asset_url, stream=True) as response, artifact.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
            metadata = _validate_zip(artifact)
            asset_name = asset["name"]
            release_tag = release.get("tag_name", metadata["version"])
            sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
        destination = install_root() / metadata["publisher"] / metadata["app"] / metadata["version"]
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="flut-stage-", dir=str(destination.parent)))
        try:
            with zipfile.ZipFile(artifact) as archive:
                archive.extractall(staging)
            details = parse_details((staging / "details.xml").read_bytes())
            if details["app"] != metadata["app"] or details["publisher"] != metadata["publisher"]:
                raise ValueError("El metadata del paquete cambió durante la extracción")
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        executable = _find_executable(destination, metadata["app"])
        manifest = {"reference": f"{author}/{package}", "release": release_tag, "asset": asset_name, "sha256": sha256, "installed_at": int(time.time())}
        (destination / "install.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _register_desktop(destination, metadata, executable)
        autostart_files = _register_autostart(destination)
        if metadata["app"].casefold() == "foundstore":
            flut_binary = next((item for item in destination.iterdir() if item.name.casefold() == "flut" and item.is_file()), None)
            if flut_binary:
                local_bin = Path(os.environ.get("XDG_BIN_HOME", Path.home() / ".local/bin"))
                local_bin.mkdir(parents=True, exist_ok=True)
                link = local_bin / "flut"
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(flut_binary)
        manifest["autostart"] = autostart_files
        (destination / "install.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _notify({"type": "installed", "reference": reference, "version": metadata["version"], "name": metadata["name"]})
        return {"metadata": metadata, "path": str(destination), "manifest": manifest}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _register_autostart(install_dir: Path) -> list[str]:
    source = install_dir / "autostart"
    if not source.is_dir():
        return []
    target = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    target.mkdir(parents=True, exist_ok=True)
    registered = []
    for desktop in source.glob("*.desktop"):
        destination = target / desktop.name
        shutil.copy2(desktop, destination)
        registered.append(str(destination))
    return registered


def uninstall(reference: str) -> int:
    author, package = parse_reference(reference)
    removed = 0
    for record in installed():
        metadata = record["metadata"]
        if metadata["author"].lower() == author.lower() and metadata["app"].lower() == package.lower():
            for autostart_path in record["manifest"].get("autostart", []):
                Path(autostart_path).unlink(missing_ok=True)
            shutil.rmtree(record["path"], ignore_errors=True)
            removed += 1
    details_path = _desktop_path({"app": package})
    if details_path.exists():
        details_path.unlink()
    if removed:
        _notify({"type": "uninstalled", "reference": reference})
    return removed


def check_updates(notify: bool = True) -> list[dict[str, Any]]:
    updates = []
    for record in installed():
        metadata = record["metadata"]
        reference = record["manifest"].get("reference")
        if not reference:
            continue
        author, package = parse_reference(reference)
        try:
            remote = repository_details(author, package)
        except (OSError, ValueError, requests.RequestException):
            continue
        if _version_key(remote["version"]) > _version_key(metadata["version"]):
            update = {"reference": reference, "current": metadata["version"], "available": remote["version"], "name": remote["name"]}
            updates.append(update)
            if notify:
                _notify({"type": "update_available", **update})
    return updates


def upgrade(reference: str | None = None) -> list[dict[str, Any]]:
    targets = installed()
    if reference:
        author, package = parse_reference(reference)
        targets = [r for r in targets if r["metadata"]["author"].lower() == author.lower() and r["metadata"]["app"].lower() == package.lower()]
    results = []
    for record in targets:
        ref = record["manifest"].get("reference")
        if not ref:
            continue
        updates = [item for item in check_updates(notify=False) if item["reference"].lower() == ref.lower()]
        if updates:
            results.append(install(ref))
    return results


def downgrade(reference: str, version: str) -> dict[str, Any]:
    return install(reference, version=version)


def search(query: str, force: bool = False) -> list[dict[str, str]]:
    q = query.casefold().strip()
    return [item for item in catalog(force=force) if q in " ".join(item.get(key, "") for key in ("name", "app", "author", "description")).casefold()]
