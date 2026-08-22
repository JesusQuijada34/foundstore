from __future__ import annotations

import unittest
from threading import Event
from unittest.mock import patch

import fluthin_manager as manager


class FluthinManagerTests(unittest.TestCase):
    def test_cancelled_install_stops_before_network_access(self) -> None:
        cancel_event = Event()
        cancel_event.set()
        with self.assertRaises(manager.InstallationCancelled):
            manager.install("JesusQuijada34/camera", cancel_event=cancel_event)

    @patch("fluthin_manager.latest_release")
    @patch("fluthin_manager.installed_record")
    def test_update_is_reported_only_when_latest_release_tag_changes(self, installed_record, latest_release) -> None:
        installed_record.return_value = {
            "metadata": {"name": "Camera", "version": "v1.0", "author": "JesusQuijada34", "app": "camera"},
            "manifest": {"release": "v1.0"},
        }
        latest_release.return_value = {"tag_name": "v1.1"}
        update = manager.update_available("JesusQuijada34/camera")
        self.assertEqual(update["available"], "v1.1")

    @patch("fluthin_manager.latest_release")
    @patch("fluthin_manager.installed_record")
    def test_current_release_does_not_expose_update_action(self, installed_record, latest_release) -> None:
        installed_record.return_value = {
            "metadata": {"name": "Camera", "version": "v1.0", "author": "JesusQuijada34", "app": "camera"},
            "manifest": {"release": "v1.0"},
        }
        latest_release.return_value = {"tag_name": "v1.0"}
        self.assertIsNone(manager.update_available("JesusQuijada34/camera"))


if __name__ == "__main__":
    unittest.main()
