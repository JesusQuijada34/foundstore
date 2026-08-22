from __future__ import annotations

import unittest
import os
import tempfile
from unittest.mock import Mock, patch

import foundstore_api


class FoundstoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_home = tempfile.TemporaryDirectory()
        self.cache_patch = patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache_home.name})
        self.cache_patch.start()

    def tearDown(self) -> None:
        self.cache_patch.stop()
        self.cache_home.cleanup()

    @patch("foundstore_api.requests.get")
    def test_catalog_normalizes_verified_stars_and_visuals(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "packages": [{"slug": "camera", "app": "camera", "author": "JesusQuijada34", "name": "Camera Selfie", "stars": 2, "visuals": {"icon": "https://example.test/icon.png"}}]
        }
        request.return_value = response
        package = foundstore_api.catalog()[0]
        self.assertEqual(package["slug"], "camera")
        self.assertEqual(package["stars"], 2)
        self.assertEqual(package["packageIcon"], "https://example.test/icon.png")

    @patch("foundstore_api.requests.get")
    def test_detail_preserves_readme_and_splash(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "package": {"app": "camera", "author": "JesusQuijada34", "readme": "# Camera", "stars": 2, "visuals": {"splash": "https://example.test/splash.png"}}
        }
        request.return_value = response
        package = foundstore_api.package_detail("camera")
        self.assertEqual(package["readme"], "# Camera")
        self.assertEqual(package["visuals"]["splash"], "https://example.test/splash.png")
        request.assert_called_once()

    @patch("foundstore_api.requests.get")
    def test_catalog_reuses_local_cache_before_fifteen_minute_ttl(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"packages": [{"app": "camera", "author": "JesusQuijada34", "stars": 2}]}
        request.return_value = response
        foundstore_api.catalog(force=True)
        second = foundstore_api.catalog()
        self.assertEqual(second[0]["app"], "camera")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
