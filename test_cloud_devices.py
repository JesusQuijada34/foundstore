import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_devices import CloudDevicesClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode("utf-8"))

    def __exit__(self, exc_type, exc, traceback):
        return False


class CloudDevicesClientTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tempdir.name) / "cloud-devices.json"
        self.client = CloudDevicesClient(self.state_path)

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("cloud_devices.urlopen")
    def test_pair_persists_token_restrictively_but_status_hides_it(self, urlopen):
        urlopen.return_value = FakeResponse({"id": "device-1", "agentToken": "secret-agent-token", "platform": "Danenone"})
        paired = self.client.pair("https://foundstore.example", "A2BC34DE", "DaneDesk")

        self.assertEqual(paired["deviceId"], "device-1")
        self.assertEqual(stat.S_IMODE(self.state_path.stat().st_mode), 0o600)
        self.assertNotIn("agentToken", self.client.status())

    @patch("cloud_devices.manager.install")
    @patch("cloud_devices.urlopen")
    def test_poll_keeps_install_request_pending_for_local_approval(self, urlopen, install):
        self.client._save({"server": "https://foundstore.example", "deviceId": "device-1", "agentToken": "secret-agent-token", "pendingActions": []})
        urlopen.side_effect = [
            FakeResponse({"commands": [{"id": "cmd-1", "type": "install_request", "payload": {"package": "Influent/packagemaker", "localApprovalRequired": True}}], "retryAfterSeconds": 2}),
            FakeResponse({"id": "event-pending"}),
        ]

        result = self.client.poll(wait=0)

        self.assertEqual(result["localApprovalRequired"], ["cmd-1"])
        install.assert_not_called()
        self.assertEqual(self.client.status()["pendingActions"], 1)


if __name__ == "__main__":
    unittest.main()
