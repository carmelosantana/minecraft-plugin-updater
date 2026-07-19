import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.plugins = root / "plugins"
        self.backups = root / "backups"
        self.state = {}
        self.jar = b"verified plugin jar"
        self.digest = hashlib.sha256(self.jar).hexdigest()
        self.plugin = {
            "name": "Example",
            "repo": "owner/example",
            "destination": "example.jar",
            "asset_regex": r"^example-[0-9].*\.jar$",
            "legacy_globs": ["example-[0-9]*.jar"],
        }
        self.release = {
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "example-1.2.3.jar", "browser_download_url": "https://assets.test/plugin"},
                {"name": "SHA256SUMS.txt", "browser_download_url": "https://assets.test/sums"},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def response(self, url, _token=None):
        if url.endswith("/releases/latest"):
            return json.dumps(self.release).encode()
        if url.endswith("/sums"):
            return f"{self.digest}  example-1.2.3.jar\n".encode()
        if url.endswith("/plugin"):
            return self.jar
        raise AssertionError(url)

    @patch("updater.request")
    def test_install_and_noop(self, mocked_request):
        mocked_request.side_effect = self.response
        message = updater.install_one(self.plugin, self.plugins, self.backups, self.state, None, False, 3)
        self.assertEqual("Example: installed v1.2.3", message)
        self.assertEqual(self.jar, (self.plugins / "example.jar").read_bytes())
        self.assertEqual("v1.2.3", self.state["Example"]["tag"])

        message = updater.install_one(self.plugin, self.plugins, self.backups, self.state, None, False, 3)
        self.assertEqual("Example: already current (v1.2.3)", message)

    @patch("updater.request")
    def test_bad_checksum_preserves_installed_jar(self, mocked_request):
        existing = b"known good"
        self.plugins.mkdir()
        destination = self.plugins / "example.jar"
        destination.write_bytes(existing)

        def bad_response(url, token=None):
            if url.endswith("/sums"):
                return f"{'0' * 64}  example-1.2.3.jar\n".encode()
            return self.response(url, token)

        mocked_request.side_effect = bad_response
        with self.assertRaises(updater.UpdateError):
            updater.install_one(self.plugin, self.plugins, self.backups, self.state, None, False, 3)
        self.assertEqual(existing, destination.read_bytes())

    @patch("updater.request")
    def test_replacement_creates_backup(self, mocked_request):
        self.plugins.mkdir()
        (self.plugins / "example.jar").write_bytes(b"old jar")
        mocked_request.side_effect = self.response
        updater.install_one(self.plugin, self.plugins, self.backups, self.state, None, False, 3)
        backups = list(self.backups.glob("example.jar.*.bak"))
        self.assertEqual(1, len(backups))
        self.assertEqual(b"old jar", backups[0].read_bytes())

    @patch("updater.request")
    def test_successful_install_archives_versioned_legacy_jar(self, mocked_request):
        self.plugins.mkdir()
        legacy = self.plugins / "example-1.0.0.jar"
        legacy.write_bytes(b"legacy")
        mocked_request.side_effect = self.response
        updater.install_one(self.plugin, self.plugins, self.backups, self.state, None, False, 3)
        self.assertFalse(legacy.exists())
        archived = list(self.backups.glob("example-1.0.0.jar.*.legacy.bak"))
        self.assertEqual(1, len(archived))
        self.assertEqual(b"legacy", archived[0].read_bytes())

    def test_checksum_parser_rejects_missing_asset(self):
        with self.assertRaises(updater.UpdateError):
            updater.expected_checksum(f"{'0' * 64}  other.jar\n".encode(), "example.jar")


class ResolveTokenTests(unittest.TestCase):
    """The specific name is what README.md documents and what a direct host run
    uses; the generic name is what compose.updater.yaml sets inside the container.
    Both must work, and a missing token must stay a non-error."""

    def env(self, **values):
        return patch.dict(updater.os.environ, values, clear=True)

    def test_prefers_the_specific_name(self):
        with self.env(PLUGIN_UPDATER_GITHUB_TOKEN="specific", GITHUB_TOKEN="generic"):
            self.assertEqual("specific", updater.resolve_token())

    def test_accepts_the_specific_name_alone(self):
        with self.env(PLUGIN_UPDATER_GITHUB_TOKEN="specific"):
            self.assertEqual("specific", updater.resolve_token())

    def test_accepts_the_generic_name_alone(self):
        with self.env(GITHUB_TOKEN="generic"):
            self.assertEqual("generic", updater.resolve_token())

    def test_missing_token_is_not_an_error(self):
        with self.env():
            self.assertIsNone(updater.resolve_token())

    def test_empty_value_is_treated_as_absent(self):
        with self.env(PLUGIN_UPDATER_GITHUB_TOKEN="", GITHUB_TOKEN=""):
            self.assertIsNone(updater.resolve_token())

    def test_empty_specific_falls_back_to_generic(self):
        with self.env(PLUGIN_UPDATER_GITHUB_TOKEN="", GITHUB_TOKEN="generic"):
            self.assertEqual("generic", updater.resolve_token())


if __name__ == "__main__":
    unittest.main()
