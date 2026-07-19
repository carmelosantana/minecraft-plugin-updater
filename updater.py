#!/usr/bin/env python3
"""Install checksum-verified Minecraft plugin releases from GitHub."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "carmelosantana-minecraft-plugin-updater/1.0"


class UpdateError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[plugin-updater] {message}", flush=True)


def request(url: str, token: str | None = None) -> bytes:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"request failed for {url}: {exc}") from exc


def release_for(plugin: dict[str, Any], token: str | None) -> dict[str, Any]:
    repo = plugin["repo"]
    pin = plugin.get("pin")
    suffix = f"tags/{pin}" if pin else "latest"
    url = f"https://api.github.com/repos/{repo}/releases/{suffix}"
    try:
        release = json.loads(request(url, token))
    except json.JSONDecodeError as exc:
        raise UpdateError(f"GitHub returned invalid JSON for {repo}") from exc
    if release.get("draft") or (release.get("prerelease") and not plugin.get("allow_prerelease", False)):
        raise UpdateError(f"release {release.get('tag_name', '?')} is not an allowed stable release")
    return release


def select_assets(plugin: dict[str, Any], release: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pattern = re.compile(plugin.get("asset_regex", r"\.jar$"))
    assets = release.get("assets", [])
    jars = [asset for asset in assets if pattern.search(asset.get("name", ""))]
    sums = [asset for asset in assets if asset.get("name") == "SHA256SUMS.txt"]
    if len(jars) != 1:
        raise UpdateError(f"expected one matching JAR asset, found {len(jars)}")
    if len(sums) != 1:
        raise UpdateError(f"expected one SHA256SUMS.txt asset, found {len(sums)}")
    return jars[0], sums[0]


def expected_checksum(checksums: bytes, asset_name: str) -> str:
    for raw_line in checksums.decode("utf-8", errors="strict").splitlines():
        parts = raw_line.strip().split()
        if len(parts) >= 2 and Path(parts[-1].lstrip("*")).name == asset_name:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    raise UpdateError(f"no valid SHA-256 entry found for {asset_name}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"cannot read {path}: {exc}") from exc


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, path)


def prune_backups(directory: Path, destination: str, keep: int) -> None:
    backups = sorted(directory.glob(f"{destination}.*.bak"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[max(keep, 0):]:
        old.unlink()


def archive_legacy_jars(plugin: dict[str, Any], plugins_dir: Path, backup_dir: Path) -> list[str]:
    archived: list[str] = []
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = plugin["destination"]
    for pattern in plugin.get("legacy_globs", []):
        for legacy in plugins_dir.glob(pattern):
            if not legacy.is_file() or legacy.name == destination:
                continue
            target = backup_dir / f"{legacy.name}.{stamp}.legacy.bak"
            counter = 1
            while target.exists():
                target = backup_dir / f"{legacy.name}.{stamp}.{counter}.legacy.bak"
                counter += 1
            shutil.move(legacy, target)
            archived.append(legacy.name)
    return archived


def install_one(
    plugin: dict[str, Any], plugins_dir: Path, backup_dir: Path, state: dict[str, Any], token: str | None,
    dry_run: bool, keep_backups: int,
) -> str:
    name = plugin["name"]
    destination = plugins_dir / plugin["destination"]
    release = release_for(plugin, token)
    tag = release.get("tag_name")
    if not tag:
        raise UpdateError("release has no tag_name")
    jar_asset, sums_asset = select_assets(plugin, release)
    checksums = request(sums_asset["browser_download_url"], token)
    expected = expected_checksum(checksums, jar_asset["name"])

    current = state.get(name, {})
    if destination.exists() and current.get("tag") == tag and sha256(destination.read_bytes()) == expected:
        return f"{name}: already current ({tag})"

    jar = request(jar_asset["browser_download_url"], token)
    actual = sha256(jar)
    if actual != expected:
        raise UpdateError(f"checksum mismatch for {jar_asset['name']}: expected {expected}, got {actual}")
    if dry_run:
        return f"{name}: would install {tag}"

    plugins_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(destination, backup_dir / f"{destination.name}.{stamp}.bak")
    with tempfile.NamedTemporaryFile("wb", dir=plugins_dir, delete=False) as handle:
        handle.write(jar)
        temp = Path(handle.name)
    temp.chmod(0o644)
    os.replace(temp, destination)
    archived = archive_legacy_jars(plugin, plugins_dir, backup_dir)
    state[name] = {"tag": tag, "sha256": actual, "asset": jar_asset["name"], "installed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    prune_backups(backup_dir, destination.name, keep_backups)
    suffix = f"; archived legacy JARs: {', '.join(archived)}" if archived else ""
    return f"{name}: installed {tag}{suffix}"


def resolve_token() -> str | None:
    """Read the GitHub token, preferring the specific name over the generic one.

    `PLUGIN_UPDATER_GITHUB_TOKEN` is what README.md tells operators to set and what
    runs directly on a host. `GITHUB_TOKEN` is what compose.updater.yaml maps that
    value to inside the container. Both are accepted so a direct invocation and a
    composed one behave identically. A missing token is not an error: public
    repositories work unauthenticated.
    """
    return (
        os.environ.get("PLUGIN_UPDATER_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or None
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("/config/plugins.json"))
    parser.add_argument("--plugins-dir", type=Path, default=Path("/minecraft/plugins"))
    parser.add_argument("--state-file", type=Path, default=Path("/minecraft/plugin-updater/state.json"))
    parser.add_argument("--backup-dir", type=Path, default=Path("/minecraft/plugin-updater/backups"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail startup when any update fails")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_json(args.manifest, None)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("plugins"), list):
        log("ERROR: manifest must contain a plugins array")
        return 2
    state = load_json(args.state_file, {})
    token = resolve_token()
    keep_backups = int(manifest.get("keep_backups", 3))
    failures = 0
    for plugin in manifest["plugins"]:
        if not plugin.get("enabled", True):
            log(f"{plugin.get('name', '?')}: disabled")
            continue
        try:
            log(install_one(plugin, args.plugins_dir, args.backup_dir, state, token, args.dry_run, keep_backups))
            if not args.dry_run:
                atomic_json(args.state_file, state)
        except (UpdateError, OSError, UnicodeError, KeyError, ValueError) as exc:
            failures += 1
            log(f"WARNING: {plugin.get('name', '?')}: {exc}; keeping installed JAR")
    if failures:
        log(f"completed with {failures} warning(s)")
        return 1 if args.strict else 0
    log("all managed plugins are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
