# Minecraft Plugin Updater

This startup helper installs the latest stable GitHub releases of Carmelo Santana's Minecraft plugins before the Legendary Paper/Geyser/Floodgate server starts.

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).

## Safety behavior

- Downloads only published, non-prerelease GitHub releases by default.
- Requires exactly one matching JAR and a `SHA256SUMS.txt` release asset.
- Verifies SHA-256 before replacing anything.
- Uses atomic file replacement and retains three previous JARs in `/minecraft/plugin-updater/backups`.
- Archives matching versioned JARs after a successful first install, preventing duplicate plugin loading during migration.
- Runs as the init container's root user so it can initialize a fresh named volume; the Legendary startup script subsequently normalizes `/minecraft` ownership.
- Keeps the installed JAR if GitHub is unavailable, a release is malformed, or verification fails.
- Does not hot-reload plugins. Updates take effect on container startup.

## Install with the Legendary stack

Place this directory inside the directory containing the Legendary `docker-compose.yml`, then start Compose with both files:

```bash
docker compose \
  -f docker-compose.yml \
  -f minecraft-plugin-updater/compose.updater.yaml \
  up -d --build
```

The `plugin-updater` init service finishes before `minecraftbe` starts. Restarting the stack checks for updates:

```bash
docker compose \
  -f docker-compose.yml \
  -f minecraft-plugin-updater/compose.updater.yaml \
  restart
```

Compose `restart` does not rerun completed dependency services. To guarantee an update check, recreate the services:

```bash
docker compose \
  -f docker-compose.yml \
  -f minecraft-plugin-updater/compose.updater.yaml \
  up -d --build --force-recreate
```

## Configuration

Edit `plugins.json` to disable or pin a plugin:

```json
{
  "name": "Ollama",
  "repo": "carmelosantana/minecraft-ollama",
  "destination": "ollama.jar",
  "asset_regex": "^ollama-[0-9].*\\.jar$",
  "legacy_globs": ["ollama-[0-9]*.jar"],
  "enabled": true,
  "pin": "v0.2.0"
}
```

Remove `pin` to follow the latest stable release. Set `enabled` to `false` to leave an installed plugin untouched.

Public repositories work without credentials. Set `PLUGIN_UPDATER_GITHUB_TOKEN` in the host environment for private repositories or higher API limits. Use a read-only fine-grained token with access only to repository contents.

By default, update failures are warnings so an unavailable GitHub endpoint cannot prevent Minecraft from starting. Pass `--strict` only if server startup must stop when any plugin cannot be checked.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 updater.py --manifest plugins.json --plugins-dir /path/to/plugins --dry-run
```
