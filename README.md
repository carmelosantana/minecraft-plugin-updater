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

Add the updater service to the same Compose project and make Minecraft depend on its successful completion. The published image supports `linux/amd64` and `linux/arm64`.

```bash
docker compose up -d --pull always
```

The `plugin-updater` init service finishes before `minecraft` starts. A Dokploy redeployment recreates the one-shot service and checks for releases before starting Minecraft.

Use `latest` to receive updater improvements on redeploy, or pin a published version such as `1.0.0` for a fixed updater image. Plugin release checks work the same either way.

```bash
docker compose up -d --pull always --force-recreate
```

Compose `restart` alone does not rerun completed dependency services. Recreate or redeploy the project to guarantee an update check.

```bash
docker compose up -d --pull always --force-recreate
```

### Dokploy service fragment

```yaml
services:
  plugin-updater:
    image: ghcr.io/carmelosantana/minecraft-plugin-updater:latest
    pull_policy: always
    restart: "no"
    volumes:
      - minecraft:/minecraft

  minecraft:
    image: 05jchambers/legendary-minecraft-geyser-floodgate:latest
    depends_on:
      plugin-updater:
        condition: service_completed_successfully
    volumes:
      - minecraft:/minecraft

volumes:
  minecraft:
    driver: local
```

No GitHub token is needed for the ten public plugin repositories. If a token is configured, use a read-only fine-grained token rather than a general account token.

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

Public repositories work without credentials. Set `PLUGIN_UPDATER_GITHUB_TOKEN` for private repositories or higher API limits. Use a read-only fine-grained token with access only to repository contents.

That name works whether you run `updater.py` directly or run the container: `compose.updater.yaml` reads `PLUGIN_UPDATER_GITHUB_TOKEN` from the host environment and passes it into the container as `GITHUB_TOKEN`. The updater accepts either name and prefers `PLUGIN_UPDATER_GITHUB_TOKEN`, so a direct run and a composed run authenticate identically. A missing token is never an error.

By default, update failures are warnings so an unavailable GitHub endpoint cannot prevent Minecraft from starting. Pass `--strict` only if server startup must stop when any plugin cannot be checked.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 updater.py --manifest plugins.json --plugins-dir /path/to/plugins --dry-run
```
