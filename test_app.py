import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app


class FlaskRenderAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "OWNER_API_TOKEN": "owner-test-token", "ALLOW_LEGACY_PAIRING": True})
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def owner_headers(self) -> dict[str, str]:
        return {"X-Foundstore-Owner-Token": "owner-test-token"}

    def test_direct_root_and_health_do_not_redirect(self) -> None:
        self.assertEqual(self.client.get("/").status_code, 200)
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["storage"], "sqlite-fallback")

    def test_render_without_explicit_volume_uses_local_ephemeral_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as workdir, patch.dict(os.environ, {"RENDER": "true"}, clear=True):
            previous = os.getcwd()
            try:
                os.chdir(workdir)
                app = create_app({"TESTING": True, "MONGODB_URI": None, "OWNER_API_TOKEN": "owner-test-token"})
                self.assertEqual(app.config["DATA_DIR"], "./var")
                self.assertEqual(app.test_client().get("/healthz").json["storage"], "sqlite-fallback")
            finally:
                os.chdir(previous)

    def test_pairing_is_single_use_and_returns_no_token_in_uri(self) -> None:
        self.app.config["ALLOW_LEGACY_PAIRING"] = True
        pairing = self.client.post("/api/v1/pairing-codes", headers=self.owner_headers(), json={"displayName": "DaneDesk Azul", "restoreApps": [{"publisher": "Influent", "slug": "packagemaker", "version": "0.1"}]})
        self.assertEqual(pairing.status_code, 201)
        code = pairing.json["code"]
        self.assertTrue(6 <= len(code) <= 12 and code.isalnum())
        self.assertNotIn("agentToken", pairing.json["agentUri"])

        claimed = self.client.post("/api/v1/agent/bootstrap", json={"code": code, "displayName": "DaneDesk Azul"})
        self.assertEqual(claimed.status_code, 201)
        self.assertIn("agentToken", claimed.json)
        duplicate = self.client.post("/api/v1/agent/bootstrap", json={"code": code, "displayName": "Otro"})
        self.assertEqual(duplicate.status_code, 401)

    def test_license_link_requires_owner_session_then_can_be_claimed_once_and_revoked(self) -> None:
        license_response = self.client.post("/api/v1/licenses", headers=self.owner_headers(), json={"restoreApps": [{"publisher": "Influent", "slug": "packagemaker", "version": "0.1"}]})
        self.assertEqual(license_response.status_code, 201)
        license_code = license_response.json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk de prueba"})
        self.assertEqual(link.status_code, 201)
        link_id, link_token, user_code = link.json["linkId"], link.json["linkToken"], link.json["userCode"]
        link_headers = {"X-Foundstore-Link-Token": link_token}
        self.assertEqual(self.client.get(f"/api/v1/license-links/{link_id}", headers=link_headers).json["status"], "awaiting_owner")
        self.assertEqual(self.client.post(f"/api/v1/license-links/{link_id}/claim", headers=link_headers).status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        self.assertEqual(self.client.post(f"/link/{link_id}", data={"code": user_code}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link_id}/claim", headers=link_headers)
        self.assertEqual(claimed.status_code, 201)
        self.assertIn("agentToken", claimed.json)
        self.assertEqual(self.client.post(f"/api/v1/license-links/{link_id}/claim", headers=link_headers).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/licenses/revoke", headers=self.owner_headers(), json={"license": license_code, "reason": "Equipo reportado como robado"}).status_code, 200)
        agent_headers = {"X-Danenone-Agent-Token": claimed.json["agentToken"]}
        revoked = self.client.get(f"/api/v1/devices/{claimed.json['id']}/state", headers=agent_headers)
        self.assertEqual(revoked.status_code, 403)
        self.assertTrue(revoked.json["relinkRequired"])

    def test_catalog_install_requires_session_owned_device_and_never_returns_download_url(self) -> None:
        license_code = self.client.post("/api/v1/licenses", headers=self.owner_headers(), json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk catálogo"}).json
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]})
        device = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        self.assertEqual(self.client.get("/api/v1/me/devices").json["devices"][0]["id"], device["id"])
        with patch("app.catalog_snapshot", return_value={"packages": [{"slug": "packagemaker", "name": "PackageMaker", "description": "Creador", "category": "Desarrollo"}]}):
            response = self.client.post(f"/api/v1/me/devices/{device['id']}/installations", json={"slug": "packagemaker"})
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json["localApprovalRequired"])
        self.assertNotIn("downloadUrl", response.json)
        root = self.client.get("/").get_data(as_text=True)
        self.assertIn("Solicitar instalación", root)
        self.assertNotIn("repositoryUrl", root)

    def test_command_long_poll_and_restore_require_agent_token(self) -> None:
        pairing = self.client.post("/api/v1/pairing-codes", headers=self.owner_headers(), json={"restoreApps": [{"publisher": "Influent", "slug": "packagemaker", "version": "0.1"}]}).json
        device = self.client.post("/api/v1/agent/bootstrap", json={"code": pairing["code"], "displayName": "DaneDesk"}).json
        agent_headers = {"X-Danenone-Agent-Token": device["agentToken"]}

        unauthorized = self.client.get(f"/api/v1/devices/{device['id']}/restore-apps")
        self.assertEqual(unauthorized.status_code, 401)
        queued = self.client.post(f"/api/v1/devices/{device['id']}/commands", headers=self.owner_headers(), json={"type": "ring", "payload": {}})
        self.assertEqual(queued.status_code, 202)
        pending = self.client.get(f"/api/v1/devices/{device['id']}/commands/next?wait=0", headers=agent_headers)
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json["commands"][0]["type"], "ring")
        self.assertIn("signature", pending.json["commands"][0])
        self.assertIn("expiresAt", pending.json["commands"][0])
        restored = self.client.get(f"/api/v1/devices/{device['id']}/restore-apps", headers=agent_headers)
        self.assertEqual(restored.json["approvedApps"][0]["slug"], "packagemaker")

    def test_location_is_stored_only_while_lost_and_is_cleared_after_recovery(self) -> None:
        pairing = self.client.post("/api/v1/pairing-codes", headers=self.owner_headers(), json={}).json
        device = self.client.post("/api/v1/agent/bootstrap", json={"code": pairing["code"], "displayName": "DaneDesk privado"}).json
        agent_headers = {"X-Danenone-Agent-Token": device["agentToken"]}
        location = {"latitude": 18.4861, "longitude": -69.9312, "accuracy": 25}
        store = self.app.extensions["device_store"]

        self.assertEqual(self.client.post(f"/api/v1/devices/{device['id']}/heartbeat", headers=agent_headers, json={"location": location}).status_code, 200)
        with store._connect() as conn:
            self.assertIsNone(conn.execute("SELECT location_json FROM devices WHERE id = ?", (device["id"],)).fetchone()["location_json"])
            conn.execute("UPDATE devices SET status = 'lost' WHERE id = ?", (device["id"],))

        self.client.post(f"/api/v1/devices/{device['id']}/heartbeat", headers=agent_headers, json={"location": location})
        with store._connect() as conn:
            self.assertIn("latitude", conn.execute("SELECT location_json FROM devices WHERE id = ?", (device["id"],)).fetchone()["location_json"])
            conn.execute("UPDATE devices SET status = 'active' WHERE id = ?", (device["id"],))

        self.client.post(f"/api/v1/devices/{device['id']}/heartbeat", headers=agent_headers, json={})
        with store._connect() as conn:
            self.assertIsNone(conn.execute("SELECT location_json FROM devices WHERE id = ?", (device["id"],)).fetchone()["location_json"])

    def test_protected_location_requires_owner_and_lost_state(self) -> None:
        pairing = self.client.post("/api/v1/pairing-codes", headers=self.owner_headers(), json={}).json
        device = self.client.post("/api/v1/agent/bootstrap", json={"code": pairing["code"], "displayName": "DaneDesk privado"}).json
        agent_headers = {"X-Danenone-Agent-Token": device["agentToken"]}
        location = {"latitude": 18.4861, "longitude": -69.9312, "accuracy": 25}
        store = self.app.extensions["device_store"]
        with store._connect() as conn:
            conn.execute("UPDATE devices SET status = 'lost' WHERE id = ?", (device["id"],))
        self.client.post(f"/api/v1/devices/{device['id']}/heartbeat", headers=agent_headers, json={"location": location})

        self.assertEqual(self.client.get(f"/api/v1/devices/{device['id']}/location").status_code, 401)
        response = self.client.get(f"/api/v1/devices/{device['id']}/location", headers=self.owner_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["location"], location)

    def test_foundstore_app_and_agent_share_device_events_and_install_requests(self) -> None:
        pairing = self.client.post("/api/v1/pairing-codes", headers=self.owner_headers(), json={"displayName": "Equipo compartido"}).json
        device = self.client.post("/api/v1/agent/bootstrap", json={"code": pairing["code"], "displayName": "Equipo compartido"}).json
        agent_headers = {"X-Danenone-Agent-Token": device["agentToken"]}

        devices = self.client.get("/api/v1/devices", headers=self.owner_headers())
        self.assertEqual(devices.status_code, 200)
        self.assertEqual(devices.json["devices"][0]["id"], device["id"])

        queued = self.client.post(
            f"/api/v1/devices/{device['id']}/installation-requests",
            headers=self.owner_headers(),
            json={"package": "Influent/packagemaker", "version": "0.1"},
        )
        self.assertEqual(queued.status_code, 202)
        self.assertTrue(queued.json["localApprovalRequired"])
        command = self.client.get(f"/api/v1/devices/{device['id']}/commands/next?wait=0", headers=agent_headers)
        self.assertEqual(command.json["commands"][0]["type"], "install_request")
        self.assertTrue(command.json["commands"][0]["payload"]["localApprovalRequired"])

        event = self.client.post(
            f"/api/v1/devices/{device['id']}/events",
            headers=agent_headers,
            json={"topic": "install.awaiting_approval", "data": {"package": "Influent/packagemaker"}},
        )
        self.assertEqual(event.status_code, 202)
        observed = self.client.get(f"/api/v1/devices/{device['id']}/events/next?wait=0", headers=self.owner_headers())
        self.assertEqual(observed.status_code, 200)
        self.assertTrue(any(item["topic"] == "install.awaiting_approval" for item in observed.json["events"]))
