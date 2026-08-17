#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import fluthin_manager as manager


def output(value, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                print(" | ".join(f"{key}={val}" for key, val in item.items()))
            else:
                print(item)
    elif isinstance(value, dict):
        for key, val in value.items():
            print(f"{key}: {val}")
    else:
        print(value)


def launch(reference: str) -> int:
    author, package = manager.parse_reference(reference)
    candidates = [
        record for record in manager.installed()
        if record["manifest"].get("reference", "").casefold() == f"{author}/{package}".casefold()
    ]
    if not candidates:
        raise RuntimeError(f"No está instalado: {reference}")
    directory = Path(candidates[0]["path"])
    preferred = [directory / package, directory / "bin" / package]
    binary = next((item for item in preferred if item.is_file() and os.access(item, os.X_OK)), None)
    if binary is None:
        search_dirs = [directory, directory / "bin"]
        binary = next((item for folder in search_dirs if folder.is_dir() for item in folder.iterdir() if item.is_file() and os.access(item, os.X_OK) and item.name not in {"autorun", "flut", "fluthin_manager"}), None)
    if binary is None:
        raise RuntimeError("El paquete no contiene un ejecutable registrado")
    subprocess.Popen([str(binary)], cwd=str(directory), start_new_session=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flut", description="Gestor de paquetes Fluthin para Influent Danenone")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--quiet", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Instalar author/package")
    install.add_argument("reference")
    install.add_argument("--version")
    install.add_argument("--file", dest="local_file")

    uninstall = sub.add_parser("uninstall", aliases=["remove"])
    uninstall.add_argument("reference")

    upgrade = sub.add_parser("upgrade", aliases=["update"])
    upgrade.add_argument("reference", nargs="?")

    downgrade = sub.add_parser("downgrade")
    downgrade.add_argument("reference")
    downgrade.add_argument("version")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--refresh", action="store_true")

    catalog = sub.add_parser("catalog", aliases=["refresh"])
    catalog.add_argument("--refresh", action="store_true")

    sub.add_parser("list", aliases=["installed"])
    check = sub.add_parser("check-updates")
    check.add_argument("--no-notify", action="store_true")

    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("reference")

    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            value = manager.install(args.reference, version=args.version, local_file=args.local_file)
        elif args.command in {"uninstall", "remove"}:
            value = {"removed": manager.uninstall(args.reference)}
        elif args.command in {"upgrade", "update"}:
            value = manager.upgrade(args.reference)
        elif args.command == "downgrade":
            value = manager.downgrade(args.reference, args.version)
        elif args.command == "search":
            value = manager.search(args.query, force=args.refresh)
        elif args.command in {"catalog", "refresh"}:
            value = manager.catalog(force=args.refresh)
        elif args.command in {"list", "installed"}:
            value = manager.installed()
        elif args.command == "check-updates":
            value = manager.check_updates(notify=not args.no_notify)
        elif args.command == "launch":
            return launch(args.reference)
        else:
            parser.error("comando desconocido")
        if not args.quiet:
            output(value, as_json=args.as_json)
        return 0
    except Exception as exc:
        if not args.quiet:
            print(f"flut: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
