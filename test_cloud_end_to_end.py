import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("DATA_DIR", str(Path(tempfile.gettempdir()) / "foundstore-import-state"))
sys.path.insert(0, str(ROOT / "render-flask"))

from app import create_app
from cloud_devices import CloudDevicesClient


class DaneDeskEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "OWNER_API_TOKEN": "owner-e2e-token"})
        self.server = make_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.cloud = CloudDevicesClient(Path(self.tempdir.name) / "agent-state.json", allow_insecure_local=True)
        self.owner_headers = {"X-Foundstore-Owner-Token": "owner-e2e-token"}

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def test_same_danedesk_links_pairing_store_request_agent_and_event_feed(self):
        pairing = self.app.test_client().post(
            "/api/v1/pairing-codes",
            headers=self.owner_headers,
            json={"displayName": "DaneDesk E2E", "restoreApps": [{"publisher": "Influent", "slug": "packagemaker", "version": "0.1"}]},
        ).json

        paired = self.cloud.pair(self.base_url, pairing["code"], "DaneDesk E2E")
        device_id = paired["deviceId"]
        cloud_state = self.cloud.cloud_state()
        self.assertEqual(cloud_state["remote"]["id"], device_id)
        self.assertEqual(cloud_state["remote"]["status"], "active")
        listed = self.app.test_client().get("/api/v1/devices", headers=self.owner_headers).json["devices"]
        self.assertEqual(listed[0]["id"], device_id)

        request = self.app.test_client().post(
            f"/api/v1/devices/{device_id}/installation-requests",
            headers=self.owner_headers,
            json={"package": "Influent/packagemaker", "version": "0.1"},
        )
        self.assertEqual(request.status_code, 202)

        pending = self.cloud.poll(wait=0)
        self.assertEqual(pending["localApprovalRequired"], [pending["commands"][0]["id"]])
        self.assertEqual(self.cloud.status()["deviceId"], device_id)
        self.assertEqual(self.cloud.status()["pendingActions"], 1)

        events = self.app.test_client().get(f"/api/v1/devices/{device_id}/events/next?wait=0", headers=self.owner_headers).json["events"]
        topics = {event["topic"] for event in events}
        self.assertIn("device.paired", topics)
        self.assertIn("install.awaiting_approval", topics)


if __name__ == "__main__":
    unittest.main()
