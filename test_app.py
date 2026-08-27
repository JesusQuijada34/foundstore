import os
import base64
import hashlib
import re
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from app import MongoStore, base64url_encode, canonical_e2e_aad, canonical_e2e_report_aad, catalog_references, create_app, github_public_profile, github_public_repositories, github_public_star_count, package_revision, raw_github_text, utc_now


class FlaskRenderAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "OWNER_API_TOKEN": "owner-test-token", "ALLOW_LEGACY_PAIRING": True})
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def owner_headers(self) -> dict[str, str]:
        return {"X-Foundstore-Owner-Token": "owner-test-token"}

    def test_web_root_shows_public_landing_but_health_remains_public(self) -> None:
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        landing = root.get_data(as_text=True)
        self.assertIn("Encuentra software que", landing)
        self.assertIn("Explorar con GitHub", landing)
        self.assertIn("Secuencia simulada de instalación de Foundstore", landing)
        self.assertIn("la aprobación sigue siendo local", landing)
        self.assertIn("Detección local · no se guarda ni se transmite", landing)
        self.assertNotIn("repositoryUrl", landing)
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["storage"], "sqlite-fallback")
        favicon = self.client.get("/favicon.ico")
        self.assertEqual(favicon.status_code, 200)
        self.assertEqual(favicon.content_type, "image/svg+xml")

    def test_developer_search_route_returns_public_users_before_dynamic_profile_route(self) -> None:
        users = [{"githubLogin": "JesusQuijada34", "githubName": "JesusQuijada34", "avatarUrl": "https://example.test/avatar.png", "githubUrl": "https://github.com/JesusQuijada34"}]
        with patch("app.github_user_search", return_value=users) as search:
            response = self.client.get("/api/v1/developers/search?q=%40JesusQuijada34")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["users"], users)
        search.assert_called_once_with("@JesusQuijada34")

    def test_github_public_profile_reads_real_social_fields_from_public_endpoints(self) -> None:
        class ApiResponse:
            ok = True

            def __init__(self, payload: object) -> None:
                self._payload = payload

            def json(self) -> object:
                return self._payload

        def fake_get(url: str, **_: object) -> ApiResponse:
            if url.endswith("/users/octocat"):
                return ApiResponse({"login": "octocat", "name": "The Octocat", "bio": "GitHub mascot", "company": "@github", "location": "San Francisco", "followers": 4, "following": 2, "public_repos": 8, "created_at": "2011-01-25T18:44:36Z", "avatar_url": "https://github.example/octocat.png", "html_url": "https://github.com/octocat"})
            if url.endswith("/followers"):
                return ApiResponse([{"login": "follower-one", "avatar_url": "https://github.example/follower.png", "html_url": "https://github.com/follower-one"}])
            if url.endswith("/following"):
                return ApiResponse([{"login": "following-one", "avatar_url": "https://github.example/following.png", "html_url": "https://github.com/following-one"}])
            raise AssertionError(url)

        with patch("app.GITHUB_PROFILE_CACHE", {}), patch("app.requests.get", side_effect=fake_get):
            profile = github_public_profile("octocat")
        self.assertEqual(profile["githubBio"], "GitHub mascot")
        self.assertEqual(profile["githubFollowersCount"], 4)
        self.assertEqual(profile["githubFollowingCount"], 2)
        self.assertEqual(profile["githubPublicReposCount"], 8)
        self.assertEqual(profile["githubFollowers"][0]["githubLogin"], "follower-one")
        self.assertEqual(profile["githubFollowing"][0]["githubLogin"], "following-one")

    def test_social_preview_crawler_can_read_public_metadata_without_browser_session(self) -> None:
        response = self.client.get("/", headers={"User-Agent": "TelegramBot (like TwitterBot)"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('property="og:title"', response.get_data(as_text=True))

    def test_github_avatar_proxy_returns_only_safe_image_content(self) -> None:
        class AvatarResponse:
            ok = True
            content = b"png-bytes"
            headers = {"Content-Type": "image/png"}

        with patch("app.requests.get", return_value=AvatarResponse()):
            avatar = self.client.get("/assets/github-avatar/JesusQuijada34.png")
        self.assertEqual(avatar.status_code, 200)
        self.assertEqual(avatar.content_type, "image/png")
        self.assertEqual(avatar.get_data(), b"png-bytes")
        self.assertEqual(self.client.get("/assets/github-avatar/no/invalid.png").status_code, 404)

    def test_package_favicon_requires_a_valid_catalog_package(self) -> None:
        package = {"slug": "camera", "author": "JesusQuijada34", "branch": "main", "packageIcon": "https://raw.example.test/camera.ico"}
        identity = {"githubLogin": "JesusQuijada34", "githubName": "JQ", "avatarUrl": "", "githubUrl": "https://github.com/JesusQuijada34"}

        class IconResponse:
            ok = True
            content = b"icon-bytes"
            headers = {"Content-Type": "image/vnd.microsoft.icon"}

        with patch("app.github_public_profile", return_value=identity), patch("app.catalog_snapshot", return_value={"packages": [package]}), patch("app.package_metadata", return_value={}), patch("app.requests.get", return_value=IconResponse()):
            icon = self.client.get("/assets/package-favicon/JesusQuijada34/camera.ico")
            missing = self.client.get("/assets/package-favicon/JesusQuijada34/missing.ico")
        self.assertEqual(icon.status_code, 200)
        self.assertEqual(icon.get_data(), b"icon-bytes")
        self.assertTrue(icon.content_type.startswith("image/"))
        self.assertEqual(missing.status_code, 404)

    def test_github_star_requires_separate_consent_and_explicit_confirmation(self) -> None:
        package = {"slug": "camera", "author": "JesusQuijada34", "branch": "main"}
        identity = {"githubLogin": "JesusQuijada34", "githubName": "JQ", "avatarUrl": "", "githubUrl": "https://github.com/JesusQuijada34"}
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "reader"
        with patch("app.github_public_profile", return_value=identity), patch("app.catalog_snapshot", return_value={"packages": [package]}), patch("app.package_metadata", return_value={}):
            required = self.client.get("/api/v1/me/starred/JesusQuijada34/camera")
            self.app.extensions["github_star_grants"]["grant-test"] = {"accessToken": "not-a-real-token", "login": "reader", "author": "JesusQuijada34", "slug": "camera", "confirmation": "confirm-test", "expiresAt": 4_102_444_800}
            with self.client.session_transaction() as browser_session:
                browser_session["github_star_grant_id"] = "grant-test"
            with patch("app.requests.put") as blocked_put:
                blocked = self.client.put("/api/v1/me/starred/JesusQuijada34/camera")
            class StarResponse:
                status_code = 204
            with patch("app.requests.put", return_value=StarResponse()) as confirmed_put:
                changed = self.client.put("/api/v1/me/starred/JesusQuijada34/camera", headers={"X-Foundstore-Star-Confirm": "confirm-test"})
        self.assertEqual(required.status_code, 200)
        self.assertEqual(required.json["state"], "consent_required")
        self.assertEqual(blocked.status_code, 428)
        blocked_put.assert_not_called()
        confirmed_put.assert_called_once()
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(changed.json["starred"])

    def test_raw_github_text_uses_the_requests_client_and_reads_utf8(self) -> None:
        class TextResponse:
            ok = True
            content = b"<details><author>JesusQuijada34</author></details>"

        with patch("app.requests.get", return_value=TextResponse()) as get:
            content = raw_github_text("JesusQuijada34", "camera", "main", "details.xml")
        self.assertIn("JesusQuijada34", content)
        self.assertIn("raw.githubusercontent.com", get.call_args.args[0])

    def test_public_repository_discovery_falls_back_to_the_public_profile_listing(self) -> None:
        class ApiResponse:
            ok = False

        class ProfileResponse:
            ok = True
            text = '<a href="/JesusQuijada34/camera">Camera</a><a href="/JesusQuijada34/matchmeter">MatchMeter</a>'

        def fake_get(url: str, **_: object) -> object:
            return ApiResponse() if url.startswith("https://api.github.com/") else ProfileResponse()

        with patch("app.requests.get", side_effect=fake_get):
            repositories = github_public_repositories("JesusQuijada34")
        self.assertEqual([item["name"] for item in repositories], ["camera", "matchmeter"])
        self.assertEqual(repositories[0]["stars"], None)

    def test_public_star_count_reads_the_visible_github_label_without_defaulting_to_zero(self) -> None:
        class RepositoryPage:
            ok = True
            text = '<span aria-label="2 users starred this repository"></span>'

        with patch("app.requests.get", return_value=RepositoryPage()):
            stars = github_public_star_count("JesusQuijada34", "camera")
        self.assertEqual(stars, 2)

    def test_catalog_revision_changes_when_verified_github_stars_change(self) -> None:
        package = {"author": "JesusQuijada34", "slug": "camera", "branch": "main", "updatedAt": "2026-08-22", "stars": 2}
        self.assertNotEqual(package_revision(package), package_revision({**package, "stars": 3}))

    def test_pwa_manifest_and_service_worker_are_available_from_root_scope(self) -> None:
        manifest = self.client.get("/manifest.webmanifest")
        worker = self.client.get("/service-worker.js")
        components = self.client.get("/static/js/foundstore-components.js")
        mark = self.client.get("/static/foundstore-mark.svg")
        login = self.client.get("/").get_data(as_text=True)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "reader"
        catalog_response = self.client.get("/")
        catalog = catalog_response.get_data(as_text=True)
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json["display"], "standalone")
        self.assertEqual(manifest.json["start_url"], "/")
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers["Service-Worker-Allowed"], "/")
        self.assertEqual(components.status_code, 200)
        self.assertEqual(mark.status_code, 200)
        self.assertIn("foundstore-discovery-mark-solid_515e468d.png", login)
        worker_source = worker.get_data(as_text=True)
        self.assertIn("foundstore-shell-v3", worker_source)
        self.assertIn("foundstore-data-v3", worker_source)
        self.assertIn('request.cache === "no-store"', worker_source)
        self.assertIn('request.mode === "navigate"', worker_source)
        self.assertNotIn('STATIC_SHELL = ["/",', worker_source)
        self.assertEqual(catalog_response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(catalog_response.headers["Pragma"], "no-cache")
        self.assertIn("Cookie", catalog_response.headers["Vary"])
        self.assertIn("followedDevelopers", catalog)
        self.assertIn("/api/v1/me/following", catalog)
        self.assertIn("foundstore-components.js", catalog)
        self.assertIn("foundstore-public-upgrade.css", login)
        self.assertIn("foundstore-public-upgrade.css", catalog)
        self.assertIn("foundstore-discovery-mark-solid_515e468d.png", login)
        self.assertIn("Explorar con GitHub", login)
        self.assertIn('id="main-content"', catalog)
        public_styles = self.client.get("/static/css/foundstore-public-upgrade.css")
        motion_styles = self.client.get("/static/css/foundstore-motion.css")
        motion_script = self.client.get("/static/js/foundstore-motion.js")
        account_styles = self.client.get("/static/css/foundstore-account.css")
        account_script = self.client.get("/static/js/foundstore-account.js")
        self.assertEqual(public_styles.status_code, 200)
        self.assertEqual(motion_styles.status_code, 200)
        self.assertEqual(motion_script.status_code, 200)
        self.assertEqual(account_styles.status_code, 200)
        self.assertEqual(account_script.status_code, 200)
        self.assertIn("foundstore-ambient-drift", public_styles.get_data(as_text=True))
        self.assertIn("prefers-reduced-motion", public_styles.get_data(as_text=True))
        self.assertIn("foundstore-stage-four", public_styles.get_data(as_text=True))
        self.assertIn("foundstore-account-trigger", account_styles.get_data(as_text=True))
        self.assertIn("FoundstoreAccount", account_script.get_data(as_text=True))
        account_menu = account_script.get_data(as_text=True)
        for path in ("/account/profile", "/account/licenses", "/account/devices", "/account/privacy", "/account/packages/invalid"):
            self.assertIn(path, account_menu)
        self.assertIn("prefers-reduced-motion", motion_styles.get_data(as_text=True))
        motion_source = motion_script.get_data(as_text=True)
        self.assertIn("navigator.userAgent", motion_source)
        self.assertNotIn("fetch(", motion_source)
        self.assertIn("data-fallback", components.get_data(as_text=True))
        self.assertIn("foundstore-package-main", components.get_data(as_text=True))
        self.assertIn("creatorPackageRow", components.get_data(as_text=True))
        self.assertIn("foundstore-account.js", catalog)

    def test_github_login_starts_authorization_with_configured_callback(self) -> None:
        oauth_app = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "GITHUB_CLIENT_ID": "client-id", "GITHUB_CLIENT_SECRET": "client-secret", "SECRET_KEY": "test-session"})
        response = oauth_app.test_client().get("/auth/github/login", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("https://github.com/login/oauth/authorize?", response.location)
        self.assertIn("redirect_uri=https%3A%2F%2Fmyfoundstore.onrender.com%2Fauth%2Fgithub%2Fcallback", response.location)
        legacy = oauth_app.test_client().get("/login", follow_redirects=False)
        self.assertEqual(legacy.status_code, 200)
        self.assertIn("Continuar con GitHub", legacy.get_data(as_text=True))

    def test_regular_oauth_callback_ignores_abandoned_star_state_and_persists_session(self) -> None:
        oauth_app = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "GITHUB_CLIENT_ID": "client-id", "GITHUB_CLIENT_SECRET": "client-secret", "SECRET_KEY": "test-session"})
        client = oauth_app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["github_oauth_state"] = "regular-state"
            browser_session["github_star_oauth_state"] = "old-star-state"
            browser_session["github_star_target"] = {"author": "JesusQuijada34", "slug": "camera"}
        class TokenResponse:
            def json(self) -> dict[str, str]: return {"access_token": "test-token"}
        class ProfileResponse:
            def json(self) -> dict[str, str]: return {"login": "reader", "name": "Reader", "blog": ""}
        with patch("app.requests.post", return_value=TokenResponse()), patch("app.requests.get", return_value=ProfileResponse()), patch("app.catalog_snapshot", return_value={"packages": []}):
            callback = client.get("/auth/github/callback?code=test-code&state=regular-state", follow_redirects=False)
        self.assertEqual(callback.status_code, 302)
        with client.session_transaction() as browser_session:
            self.assertEqual(browser_session["github_login"], "reader")
            self.assertTrue(browser_session.permanent)

    def test_catalog_references_reject_invalid_entries_and_deduplicates_repositories(self) -> None:
        references = catalog_references("camera, JesusQuijada34/packagemaker\n# comentario\nno válido, camera, OtherDev/app", "JesusQuijada34")
        self.assertEqual(references, [("JesusQuijada34", "camera"), ("JesusQuijada34", "packagemaker"), ("OtherDev", "app")])

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

    def test_panel_secret_names_are_used_for_render_configuration(self) -> None:
        with patch.dict(os.environ, {"GITHUB_OAUTH_CLIENT_ID": "panel-id", "GITHUB_OAUTH_CLIENT_SECRET": "panel-secret", "NULL_HV": "panel-internal-secret", "MONGO_URI": ""}, clear=False):
            migrated = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "MONGODB_URI": None, "OWNER_API_TOKEN": "owner-test-token"})
        self.assertEqual(migrated.config["GITHUB_CLIENT_ID"], "panel-id")
        self.assertEqual(migrated.config["GITHUB_CLIENT_SECRET"], "panel-secret")
        self.assertEqual(migrated.config["SECRET_KEY"], "panel-internal-secret")
        self.assertEqual(migrated.config["COMMAND_SIGNING_KEY"], "panel-internal-secret")

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
        self.assertTrue(link.json["verificationUri"].startswith("https://myfoundstore.onrender.com/link/"))
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

    def test_access_serial_and_onboarding_require_github_session(self) -> None:
        self.assertEqual(self.client.post("/api/v1/me/access-serials", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/me/onboarding").status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        serial = self.client.post("/api/v1/me/access-serials", json={"platform": "Knosthalij"})
        onboarding = self.client.get("/api/v1/me/onboarding")
        self.assertEqual(serial.status_code, 201)
        self.assertEqual(serial.json["kind"], "license_link")
        self.assertTrue(serial.json["serial"])
        self.assertEqual(serial.json["platform"], "Knosthalij")
        self.assertEqual(onboarding.status_code, 200)
        self.assertTrue(onboarding.json["githubAuthenticated"])
        self.assertTrue(onboarding.json["localApprovalRequired"])
        self.assertNotIn("agentToken", onboarding.json)
        self.assertEqual(onboarding.json["serialEndpoint"], "/api/v1/me/access-serials")

    def test_flet_console_authorization_uses_pkce_github_confirmation_and_revocable_session(self) -> None:
        verifier = "flet-console-verifier-0123456789012345678901234567890123456789"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        started = self.client.post("/api/v1/console-auth", json={"pkceChallenge": challenge})
        self.assertEqual(started.status_code, 201)
        request_id, user_code = started.json["requestId"], started.json["userCode"]
        self.assertEqual(self.client.get(f"/api/v1/console-auth/{request_id}", headers={"X-Foundstore-Console-Code": user_code}).json["status"], "awaiting_owner")
        verify_path = f"/console/authorize/{request_id}?code={user_code}"
        self.assertEqual(self.client.get(verify_path).status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        approval_page = self.client.get(verify_path)
        self.assertEqual(approval_page.status_code, 200)
        csrf = re.search(r'name="csrf" value="([^"]+)"', approval_page.get_data(as_text=True))
        self.assertIsNotNone(csrf)
        approved = self.client.post(verify_path, data={"code": user_code, "csrf": csrf.group(1) if csrf else ""})
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/console-auth/{request_id}", headers={"X-Foundstore-Console-Code": user_code}).json["status"], "approved")
        self.assertEqual(self.client.post(f"/api/v1/console-auth/{request_id}/token", json={"pkceVerifier": verifier + "-wrong"}).status_code, 401)
        claimed = self.client.post(f"/api/v1/console-auth/{request_id}/token", json={"pkceVerifier": verifier})
        self.assertEqual(claimed.status_code, 201)
        self.assertEqual(claimed.json["account"], "jq34")
        self.assertNotIn("github", claimed.json["consoleToken"].lower())
        self.assertEqual(self.client.post(f"/api/v1/console-auth/{request_id}/token", json={"pkceVerifier": verifier}).status_code, 401)
        console_headers = {"X-Foundstore-Console-Token": claimed.json["consoleToken"]}
        console_client = self.app.test_client()
        self.assertEqual(console_client.get("/api/v1/me/devices", headers=console_headers).status_code, 200)
        self.assertEqual(console_client.post("/api/v1/me/licenses", headers=console_headers, json={}).status_code, 201)
        self.assertEqual(console_client.delete("/api/v1/console-session", headers=console_headers).status_code, 204)
        self.assertEqual(console_client.get("/api/v1/me/licenses", headers=console_headers).status_code, 401)

    def test_settings_requires_github_and_exposes_safe_account_sections(self) -> None:
        self.assertEqual(self.client.get("/settings").status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        settings = self.client.get("/settings")
        self.assertEqual(settings.status_code, 200)
        body = settings.get_data(as_text=True)
        self.assertIn("Preferencias del navegador", body)
        self.assertIn("/account/licenses", body)
        self.assertIn("/account/packages/invalid", body)

    def test_logout_clears_github_session_and_redirects_to_public_landing(self) -> None:
        grant_id = "temporary-star-grant"
        self.app.extensions["github_star_grants"][grant_id] = {"login": "jq34", "expiresAt": 4102444800}
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
            browser_session["github_star_grant_id"] = grant_id
            browser_session["github_oauth_state"] = "oauth-state"
            browser_session["github_oauth_next"] = "/account/profile"
        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(grant_id, self.app.extensions["github_star_grants"])
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("github_login", browser_session)
            self.assertNotIn("github_oauth_state", browser_session)
        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn("Tu catálogo", landing.get_data(as_text=True))

    def test_account_owner_can_revoke_only_own_license_and_view_minimized_device_detail(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        created = self.client.post("/api/v1/me/licenses", json={})
        self.assertEqual(created.status_code, 201)
        license_code = created.json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk privado", "platform": "Danenone"}).json
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]})
        self.assertEqual(claimed.status_code, 201)
        device_id = claimed.json["id"]
        detail = self.client.get(f"/api/v1/me/devices/{device_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json["device"]["id"], device_id)
        self.assertEqual(detail.json["security"]["endToEndPayloads"], "pending_agent_update")
        device_page = self.client.get(f"/account/devices/{device_id}")
        self.assertEqual(device_page.status_code, 200)
        self.assertIn('id="device-console"', device_page.get_data(as_text=True))
        self.assertIn("Instalaciones verificadas", device_page.get_data(as_text=True))
        self.assertIn("Canal cifrado de extremo a extremo", device_page.get_data(as_text=True))
        self.assertIn("clave no exportable", device_page.get_data(as_text=True))
        self.assertNotIn("Dirección MAC", device_page.get_data(as_text=True))
        public_numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
        public_jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": base64.urlsafe_b64encode(public_numbers.x.to_bytes(32, "big")).decode("ascii").rstrip("="),
            "y": base64.urlsafe_b64encode(public_numbers.y.to_bytes(32, "big")).decode("ascii").rstrip("="),
        }
        agent_headers = {"X-Danenone-Agent-Token": claimed.json["agentToken"]}
        registered = self.client.post(f"/api/v1/devices/{device_id}/e2e-key", headers=agent_headers, json={"publicJwk": public_jwk, "keyEpoch": 1})
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json["publicJwk"], public_jwk)
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-key", headers=agent_headers, json={"publicJwk": public_jwk, "keyEpoch": 1}).status_code, 409)
        owner_key = self.client.get(f"/api/v1/me/devices/{device_id}/e2e-key")
        self.assertEqual(owner_key.status_code, 200)
        self.assertEqual(owner_key.json["fingerprint"], registered.json["fingerprint"])
        requested = self.client.post(f"/api/v1/me/devices/{device_id}/network-inventory-request")
        self.assertEqual(requested.status_code, 202)
        self.assertTrue(requested.json["localApprovalRequired"])
        revoked = self.client.post("/api/v1/me/licenses/revoke", json={"license": license_code, "reason": "Revocación de prueba"})
        self.assertEqual(revoked.status_code, 200)
        self.assertTrue(revoked.json["success"])
        intruder = self.app.test_client()
        with intruder.session_transaction() as browser_session:
            browser_session["github_login"] = "otro"
        self.assertEqual(intruder.post("/api/v1/me/licenses/revoke", json={"license": license_code}).status_code, 404)

    def test_e2e_envelope_is_opaque_one_time_and_key_epoch_bound(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk E2E", "platform": "Danenone"}).json
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        device_id, agent_headers = claimed["id"], {"X-Danenone-Agent-Token": claimed["agentToken"]}
        numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
        public_jwk = {"kty": "EC", "crv": "P-256", "x": base64.urlsafe_b64encode(numbers.x.to_bytes(32, "big")).decode("ascii").rstrip("="), "y": base64.urlsafe_b64encode(numbers.y.to_bytes(32, "big")).decode("ascii").rstrip("=")}
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-key", headers=agent_headers, json={"publicJwk": public_jwk, "keyEpoch": 1}).status_code, 201)

        def envelope(envelope_id: str, epoch: int = 1) -> dict[str, object]:
            expires_at = (utc_now() + timedelta(minutes=5)).isoformat()
            aad = canonical_e2e_aad(1, device_id, epoch, envelope_id, expires_at, "owner-to-device")
            return {"version": 1, "deviceId": device_id, "keyEpoch": epoch, "envelopeId": envelope_id, "type": "network_inventory_request", "expiresAt": expires_at, "senderEphemeralPublicJwk": public_jwk, "nonce": base64url_encode(b"N" * 12), "ciphertext": base64url_encode(b"opaque-ciphertext-without-plaintext"), "aad": base64url_encode(aad)}

        first = envelope("e2e_envelope_first")
        invalid = {**first, "aad": base64url_encode(b"not-the-canonical-aad")}
        self.assertEqual(self.client.post(f"/api/v1/me/devices/{device_id}/e2e-envelopes", json=invalid).status_code, 400)
        queued = self.client.post(f"/api/v1/me/devices/{device_id}/e2e-envelopes", json=first)
        self.assertEqual(queued.status_code, 202)
        commands = self.client.get(f"/api/v1/devices/{device_id}/commands/next?wait=0", headers=agent_headers)
        self.assertTrue(any(item["type"] == "e2e_envelope" and item["payload"]["envelopeId"] == first["envelopeId"] for item in commands.json["commands"]))
        fetched = self.client.get(f"/api/v1/devices/{device_id}/e2e-envelopes/{first['envelopeId']}", headers=agent_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json["ciphertext"], first["ciphertext"])
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-envelopes/{first['envelopeId']}/receipt", headers=agent_headers, json={"receipt": "accepted"}).status_code, 202)
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-envelopes/{first['envelopeId']}/receipt", headers=agent_headers, json={"receipt": "accepted"}).status_code, 409)
        self.assertEqual(self.client.get(f"/api/v1/devices/{device_id}/e2e-envelopes/{first['envelopeId']}", headers=agent_headers).status_code, 404)
        second = envelope("e2e_envelope_second")
        self.assertEqual(self.client.post(f"/api/v1/me/devices/{device_id}/e2e-envelopes", json=second).status_code, 202)
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-key", headers=agent_headers, json={"publicJwk": public_jwk, "keyEpoch": 2}).status_code, 201)
        self.assertEqual(self.client.get(f"/api/v1/devices/{device_id}/e2e-envelopes/{second['envelopeId']}", headers=agent_headers).status_code, 404)

    def test_e2e_device_report_requires_owner_key_and_stays_opaque(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk informe E2E", "platform": "Danenone"}).json
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        device_id, agent_headers = claimed["id"], {"X-Danenone-Agent-Token": claimed["agentToken"]}

        def public_jwk() -> dict[str, str]:
            numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
            return {"kty": "EC", "crv": "P-256", "x": base64.urlsafe_b64encode(numbers.x.to_bytes(32, "big")).decode("ascii").rstrip("="), "y": base64.urlsafe_b64encode(numbers.y.to_bytes(32, "big")).decode("ascii").rstrip("=")}

        device_public, owner_public, sender_public = public_jwk(), public_jwk(), public_jwk()
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-key", headers=agent_headers, json={"publicJwk": device_public, "keyEpoch": 1}).status_code, 201)
        self.assertEqual(self.client.post("/api/v1/me/e2e-key", json={"publicJwk": owner_public, "keyEpoch": 1}).status_code, 201)
        owner_key = self.client.get(f"/api/v1/devices/{device_id}/e2e-owner-key", headers=agent_headers)
        self.assertEqual(owner_key.status_code, 200)
        self.assertEqual(owner_key.json["publicJwk"], owner_public)
        report_id, expires_at = "e2e_report_first", (utc_now() + timedelta(minutes=5)).isoformat()
        aad = canonical_e2e_report_aad(1, device_id, 1, 1, report_id, expires_at)
        report = {"version": 1, "deviceId": device_id, "deviceKeyEpoch": 1, "ownerKeyEpoch": 1, "reportId": report_id, "type": "device_inventory", "expiresAt": expires_at, "senderEphemeralPublicJwk": sender_public, "nonce": base64url_encode(b"R" * 12), "ciphertext": base64url_encode(b"opaque-device-inventory-ciphertext"), "aad": base64url_encode(aad)}
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-reports", headers=agent_headers, json=report).status_code, 202)
        reports = self.client.get(f"/api/v1/me/devices/{device_id}/e2e-reports")
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(reports.json["reports"][0]["ciphertext"], report["ciphertext"])
        self.assertNotIn("plaintext", reports.json["reports"][0])
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-reports", headers=agent_headers, json=report).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/me/e2e-key", json={"publicJwk": public_jwk(), "keyEpoch": 2}).status_code, 201)
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/e2e-reports", headers=agent_headers, json=report).status_code, 400)

    def test_account_sections_are_independent_and_require_github(self) -> None:
        paths = ["/account/profile", "/account/licenses", "/account/devices", "/account/privacy", "/account/packages/invalid"]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        expected = {
            "/account/profile": "Perfil público",
            "/account/licenses": "Licencias",
            "/account/devices": "Dispositivos vinculados",
            "/account/privacy": "Privacidad",
            "/account/packages/invalid": "Paquetes inválidos",
        }
        for path, heading in expected.items():
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(heading, page.get_data(as_text=True))
        mobile_markup = self.client.get("/account/profile").get_data(as_text=True)
        self.assertIn(".nav-card{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible}", mobile_markup)
        self.assertIn("@media(prefers-reduced-motion:reduce)", mobile_markup)
        legacy = self.client.get("/profile")
        self.assertEqual(legacy.status_code, 302)
        self.assertIn("/account/profile", legacy.headers["Location"])

    def test_device_detail_page_stays_owner_only(self) -> None:
        self.assertEqual(self.client.get("/account/devices/not-owned").status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        self.assertEqual(self.client.get("/account/devices/not-owned").status_code, 404)

    def test_installation_progress_and_catalog_count_require_real_agent_events(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk de progreso", "platform": "Danenone"}).json
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        device_id = claimed["id"]
        requested = self.client.post(
            f"/api/v1/devices/{device_id}/installation-requests",
            headers=self.owner_headers(),
            json={"package": "JesusQuijada34/packagemaker"},
        )
        self.assertEqual(requested.status_code, 202)
        request_id = requested.json["id"]
        agent_headers = {"X-Danenone-Agent-Token": claimed["agentToken"]}
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/events", headers=agent_headers, json={"topic": "install.approved", "data": {"requestId": request_id}}).status_code, 202)
        active = self.client.get(f"/api/v1/me/devices/{device_id}/installations")
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json["installations"][0]["status"], "installing")
        self.assertEqual(self.client.post(f"/api/v1/devices/{device_id}/events", headers=agent_headers, json={"topic": "install.completed", "data": {"requestId": request_id}}).status_code, 202)
        count = self.client.get("/api/v1/packages/JesusQuijada34/packagemaker/installations")
        self.assertEqual(count.status_code, 200)
        self.assertEqual(count.json["installedDevices"], 1)

    def test_mongo_license_link_status_accepts_serialized_expiration(self) -> None:
        class Links:
            def find_one(self, *_: object, **__: object) -> dict[str, object]:
                return {"status": "approved", "expiresAt": "2099-01-01T00:00:00+00:00", "usedAt": None}

        class Database:
            license_links = Links()

        store = object.__new__(MongoStore)
        store.db = Database()
        status = store.license_link_status("link-1", "token-1")
        self.assertEqual(status, {"status": "approved", "expiresAt": "2099-01-01T00:00:00+00:00", "claimed": False})

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
        self.assertIn("Ver ficha", root)
        self.assertNotIn("repositoryUrl", root)

    def test_public_package_detail_and_catalog_item_hide_download_urls(self) -> None:
        package = {"slug": "packagemaker", "name": "PackageMaker", "author": "JesusQuijada34", "description": "Creador de paquetes Fluthin", "category": "Desarrollo", "tags": [], "visuals": {"icon": "https://example.test/icon.png", "splash": "https://example.test/splash.png", "portrait": "https://example.test/portrait.png"}}
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "reader"
        with patch("app.catalog_snapshot", return_value={"packages": [package]}), patch("app.package_metadata", return_value={"platform": "AlphaCube", "platformTargets": ["Danenone", "Knosthalij"], "readme": "# README oficial", "version": "v1", "publisher": "Influent"}):
            page = self.client.get("/JesusQuijada34/packagemaker")
            api = self.client.get("/api/v1/catalog/packagemaker")
            missing = self.client.get("/JesusQuijada34/no-existe")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Instalar en DaneDesk", page.get_data(as_text=True))
        self.assertNotIn("downloadUrl", page.get_data(as_text=True))
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json["package"]["slug"], "packagemaker")
        self.assertEqual(api.json["package"]["visuals"]["portrait"], "https://example.test/portrait.png")
        self.assertEqual(api.json["package"]["platformTargets"], ["Danenone", "Knosthalij"])
        self.assertEqual(api.json["package"]["publisher"], "Influent")
        self.assertIn("README oficial", page.get_data(as_text=True))
        self.assertIn('id="splash"', page.get_data(as_text=True))
        self.assertIn("/developer/", page.get_data(as_text=True))
        self.assertEqual(missing.status_code, 404)

    def test_static_repository_scan_is_exposed_without_executing_a_package(self) -> None:
        package = {"slug": "packagemaker", "name": "PackageMaker", "author": "ExternalDev", "branch": "main"}
        report = {"status": "review_required", "highestSeverity": "medium", "findings": [{"path": "updater.py", "severity": "medium"}], "method": "static_public_text_only"}
        with patch("app.github_public_profile", return_value={"githubLogin": "ExternalDev", "githubName": "External Dev", "avatarUrl": "", "githubUrl": "https://github.com/ExternalDev"}), patch("app.catalog_snapshot", return_value={"packages": [package]}), patch("app.package_metadata", return_value={}), patch("app.static_repository_scan", return_value=report) as scan:
            response = self.client.get("/api/v1/packages/ExternalDev/packagemaker/security")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["scan"]["method"], "static_public_text_only")
        scan.assert_called_once()

    def test_catalog_changes_returns_only_revised_packages_and_removed_keys(self) -> None:
        package = {"slug": "camera", "name": "Camera", "author": "JesusQuijada34", "branch": "main", "revision": "current-revision"}
        snapshot = {"packages": [package], "catalogVersion": "version-2", "fetchedAt": "2026-01-01T00:00:00+00:00"}
        with patch("app.catalog_snapshot", return_value=snapshot), patch("app.package_metadata", return_value={"platformTargets": ["Danenone"]}):
            unchanged = self.client.post("/api/v1/catalog/changes", json={"known": {"JesusQuijada34/camera": "current-revision", "old/app": "legacy"}})
            changed = self.client.post("/api/v1/catalog/changes", json={"known": {"JesusQuijada34/camera": "older-revision"}})
        self.assertEqual(unchanged.status_code, 200)
        self.assertEqual(unchanged.json["packages"], [])
        self.assertEqual(unchanged.json["removed"], ["old/app"])
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json["packages"][0]["slug"], "camera")
        self.assertEqual(changed.json["catalogVersion"], "version-2")

    def test_public_catalog_is_visible_with_or_without_a_github_session(self) -> None:
        package = {"slug": "camera", "name": "Camera", "author": "JesusQuijada34", "branch": "main", "revision": "published-revision"}
        snapshot = {"packages": [package], "catalogVersion": "public-version", "fetchedAt": "2026-01-01T00:00:00+00:00", "source": "GitHub public repositories", "excluded": [{"repository": "owner/incomplete", "reasons": ["Recurso requerido ausente"]}]}
        with patch("app.catalog_snapshot", return_value=snapshot), patch("app.package_metadata", return_value={"platformTargets": ["Danenone"]}):
            anonymous = self.client.get("/api/v1/catalog")
            with self.client.session_transaction() as browser_session:
                browser_session["github_login"] = "JesusQuijada34"
            authenticated = self.client.get("/api/v1/catalog")
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(anonymous.json["packages"], authenticated.json["packages"])
        self.assertEqual(anonymous.json["packages"][0]["slug"], "camera")
        self.assertNotIn("excluded", anonymous.json)

    def test_profile_keeps_owner_license_and_links_a_knosthalij_device(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        self.assertEqual(self.client.get("/account/licenses").status_code, 200)
        created = self.client.post("/api/v1/me/licenses", json={})
        self.assertEqual(created.status_code, 201)
        license_code = created.json["license"]
        listed = self.client.get("/api/v1/me/licenses")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json["licenses"][0]["license"], license_code)

        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "Foundstore para Knosthalij", "platform": "Knosthalij"}).json
        intruder = self.app.test_client()
        with intruder.session_transaction() as browser_session:
            browser_session["github_login"] = "otro-usuario"
        self.assertEqual(intruder.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 400)
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        claimed = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]})
        self.assertEqual(claimed.status_code, 201)
        self.assertEqual(claimed.json["platform"], "Knosthalij")

    def test_github_profile_can_be_edited_and_exposes_a_public_developer_page(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        github_identity = {"githubLogin": "jq34", "githubName": "JQ 34", "avatarUrl": "https://example.test/avatar.png", "githubUrl": "https://github.com/jq34"}
        empty_catalog = {"packages": [], "fetchedAt": "2026-01-01T00:00:00+00:00", "source": "GitHub API"}
        with patch("app.github_public_profile", return_value=github_identity), patch("app.catalog_snapshot", return_value=empty_catalog):
            initial = self.client.get("/api/v1/me/profile")
            updated = self.client.patch("/api/v1/me/profile", json={"displayName": "JQ Studio", "bio": "Paquetes Fluthin", "website": "https://example.test", "catalogRepository": "catalog"})
            public = self.client.get("/api/v1/developers/jq34")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["profile"]["displayName"], "JQ Studio")
        self.assertEqual(updated.json["profile"]["catalogRepository"], "catalog")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json["profile"]["githubLogin"], "jq34")
        self.assertEqual(self.client.get("/developer/jq34").status_code, 200)

    def test_authenticated_profile_discovers_only_public_repositories_and_marks_own_profile(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        identity = {"githubLogin": "jq34", "githubName": "JQ 34", "avatarUrl": "", "githubUrl": "https://github.com/jq34"}
        snapshot = {"packages": [], "fetchedAt": "2026-01-01T00:00:00+00:00", "source": "GitHub API"}
        public_repositories = [{"name": "catalog", "url": "https://github.com/jq34/catalog", "description": "Público", "updatedAt": "2026-01-01T00:00:00Z"}]
        with patch("app.github_public_profile", return_value=identity), patch("app.catalog_snapshot", return_value=snapshot), patch("app.github_public_repositories", return_value=public_repositories):
            repositories = self.client.get("/api/v1/me/repositories")
            profile = self.client.get("/api/v1/developers/jq34")
            page = self.client.get("/developer/jq34")
        self.assertEqual(repositories.status_code, 200)
        self.assertEqual(repositories.json["scope"], "public_only")
        self.assertTrue(repositories.json["privateRepositoriesRequireConsent"])
        self.assertEqual(repositories.json["repositories"], public_repositories)
        self.assertTrue(profile.json["isOwnProfile"])
        self.assertIn('id="profileOwn"', page.get_data(as_text=True))
        self.assertIn('id="profileFollow" type="button" hidden aria-hidden="true"', page.get_data(as_text=True))
        self.assertIn('id="profileTitle"', page.get_data(as_text=True))
        invalid_packages = self.client.get("/account/packages/invalid").get_data(as_text=True)
        self.assertIn("Paquetes inválidos", invalid_packages)
        self.assertIn("invalid-packages", invalid_packages)
        self.assertNotIn('id="catalogRepository"', invalid_packages)

    def test_profile_privacy_is_public_by_default_and_filters_third_party_view(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "owner"
        identity = {"githubLogin": "owner", "githubName": "Owner", "avatarUrl": "https://example.test/avatar.png", "githubUrl": "https://github.com/owner"}
        snapshot = {"packages": [{"slug": "valid-app", "author": "owner", "branch": "main"}], "fetchedAt": "2026-01-01T00:00:00+00:00", "catalogVersion": "test"}
        with patch("app.github_public_profile", return_value=identity), patch("app.catalog_snapshot", return_value=snapshot), patch("app.package_metadata", return_value={}):
            owner = self.client.patch("/api/v1/me/profile", json={"displayName": "Owner", "bio": "Visible sólo al dueño", "website": "https://example.test", "privacy": {"avatar": "private", "bio": "private", "repositories": "private", "followers": "private", "following": "private"}})
            outsider = self.app.test_client()
            public = outsider.get("/api/v1/developers/owner")
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json["profile"]["avatarUrl"], "")
        self.assertEqual(public.json["profile"]["bio"], "")
        self.assertEqual(public.json["catalog"]["packages"], [])
        self.assertIsNone(public.json["followerCount"])
        self.assertIsNone(public.json["followingCount"])

    def test_authenticated_user_can_follow_and_unfollow_a_developer(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "reader"
        identity = {"githubLogin": "ExternalDev", "githubName": "External Dev", "avatarUrl": "https://github.com/ExternalDev.png?size=176", "githubUrl": "https://github.com/ExternalDev"}
        snapshot = {"packages": [], "fetchedAt": "2026-01-01T00:00:00+00:00", "source": "GitHub API"}
        with patch("app.github_public_profile", return_value=identity), patch("app.catalog_snapshot", return_value=snapshot):
            before = self.client.get("/api/v1/developers/ExternalDev")
            followed = self.client.post("/api/v1/me/following/ExternalDev")
            listed = self.client.get("/api/v1/me/following")
            after = self.client.get("/api/v1/developers/ExternalDev")
            removed = self.client.delete("/api/v1/me/following/ExternalDev")
            page = self.client.get("/developer/ExternalDev")
        self.assertFalse(before.json["following"])
        self.assertEqual(followed.status_code, 200)
        self.assertTrue(followed.json["following"])
        self.assertEqual(listed.json["developers"], ["ExternalDev"])
        self.assertTrue(after.json["following"])
        self.assertEqual(after.json["followerCount"], 1)
        self.assertFalse(removed.json["following"])
        self.assertIn('id="profileAvatarFallback"', page.get_data(as_text=True))
        self.assertIn('id="profileFollow"', page.get_data(as_text=True))
        self.assertIn("githubFollowersCount", page.get_data(as_text=True))
        self.assertIn("profile-layout", page.get_data(as_text=True))
        self.assertIn("foundstore-profile.css", page.get_data(as_text=True))
        self.assertIn("profile-stats", page.get_data(as_text=True))
        self.assertIn("profile-package-list", page.get_data(as_text=True))

    def test_catalog_install_rejects_platform_incompatible_device(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "Knosthalij", "platform": "Knosthalij"}).json
        self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]})
        device = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        package = {"slug": "solo-danenone", "name": "Sólo Danenone", "description": "Prueba", "category": "Sistema", "branch": "main"}
        with patch("app.catalog_snapshot", return_value={"packages": [package]}), patch("app.package_metadata", return_value={"platformTargets": ["Danenone"]}):
            response = self.client.post(f"/api/v1/me/devices/{device['id']}/installations", json={"slug": "solo-danenone"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["platformTargets"], ["Danenone"])

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

    def test_revoked_license_is_not_returned_by_owner_license_listing(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        created = self.client.post("/api/v1/me/licenses", json={})
        self.assertEqual(created.status_code, 201)
        license_code = created.json["license"]
        self.assertEqual(self.client.get("/api/v1/me/licenses").json["licenses"][0]["license"], license_code)
        revoked = self.client.post("/api/v1/me/licenses/revoke", json={"license": license_code, "reason": "Prueba"})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me/licenses").json["licenses"], [])

    def test_authenticated_notifications_long_poll_reads_owned_device_events(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        link = self.client.post("/api/v1/license-links", json={"license": license_code, "displayName": "DaneDesk avisos"}).json
        self.assertEqual(self.client.post(f"/link/{link['linkId']}", data={"code": link["userCode"]}).status_code, 200)
        device = self.client.post(f"/api/v1/license-links/{link['linkId']}/claim", headers={"X-Foundstore-Link-Token": link["linkToken"]}).json
        agent_headers = {"X-Danenone-Agent-Token": device["agentToken"]}
        self.client.post(f"/api/v1/devices/{device['id']}/events", headers=agent_headers, json={"topic": "device.ring.started", "data": {}})
        response = self.client.get("/api/v1/me/notifications?wait=0")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["topic"] == "device.ring.started" for item in response.json["notifications"]))

    def test_profile_share_code_is_eight_characters_and_redirects_without_plain_payload(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        response = self.client.post("/api/v1/share/profile/JesusQuijada34")
        self.assertEqual(response.status_code, 200)
        code = response.json["code"]
        self.assertRegex(code, r"^[A-Za-z0-9]{8}$")
        self.assertNotIn("JesusQuijada34", response.json["url"])
        redirected = self.client.get(f"/me/qr/{code}", follow_redirects=False)
        self.assertEqual(redirected.status_code, 302)
        self.assertEqual(redirected.location, "/developer/JesusQuijada34")

    def test_package_share_requires_session_and_redirects_only_to_valid_package(self) -> None:
        anonymous = self.client.post("/api/v1/share/package/JesusQuijada34/camera")
        self.assertEqual(anonymous.status_code, 401)
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        package = {"author": "JesusQuijada34", "slug": "camera", "branch": "main", "revision": "r1"}
        with patch("app.catalog_snapshot", return_value={"packages": [package], "catalogVersion": "v1", "fetchedAt": "2026-01-01T00:00:00+00:00"}), patch("app.package_metadata", return_value={}):
            response = self.client.post("/api/v1/share/package/JesusQuijada34/camera")
            self.assertEqual(response.status_code, 200)
            code = response.json["code"]
            redirected = self.client.get(f"/linkdo/{code}", follow_redirects=False)
        self.assertRegex(code, r"^[A-Za-z0-9]{8}$")
        self.assertNotIn("JesusQuijada34", response.json["url"])
        self.assertEqual(redirected.status_code, 302)
        self.assertEqual(redirected.location, "/JesusQuijada34/camera")
        self.assertEqual(self.client.post("/api/v1/share/package/JesusQuijada34/missing").status_code, 404)

    def test_developer_catalog_diff_requires_active_license_header_and_never_echoes_it(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "jq34"
        missing = self.client.post("/api/v1/developer/catalog/diff", json={"known": {}})
        self.assertEqual(missing.status_code, 401)
        license_code = self.client.post("/api/v1/me/licenses", json={}).json["license"]
        snapshot = {"packages": [{"author": "jq34", "slug": "camera", "revision": "new-revision", "branch": "main"}], "catalogVersion": "v3", "fetchedAt": "2026-01-01T00:00:00+00:00"}
        with patch("app.catalog_snapshot", return_value=snapshot), patch("app.package_metadata", return_value={}):
            active = self.client.post("/api/v1/developer/catalog/diff", headers={"X-Foundstore-License": license_code}, json={"known": {"jq34/camera": "old-revision"}})
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json["packages"][0]["slug"], "camera")
        self.assertNotIn(license_code, active.get_data(as_text=True))
        self.assertEqual(self.client.post("/api/v1/me/licenses/revoke", json={"license": license_code}).status_code, 200)
        revoked = self.client.post("/api/v1/developer/catalog/diff", headers={"X-Foundstore-License": license_code}, json={"known": {}})
        self.assertEqual(revoked.status_code, 401)

    def test_flat_ui_and_share_controls_are_loaded_by_active_pages(self) -> None:
        landing = self.client.get("/")
        self.assertIn("foundstore-flat.css?v=flat1", landing.get_data(as_text=True))
        with self.client.session_transaction() as browser_session:
            browser_session["github_login"] = "ExternalDev"
        with patch("app.github_public_profile", return_value={"githubLogin": "ExternalDev", "githubName": "External Dev", "avatarUrl": "", "githubUrl": "https://github.com/ExternalDev"}), patch("app.catalog_snapshot", return_value={"packages": [], "fetchedAt": "2026-01-01T00:00:00+00:00"}):
            profile = self.client.get("/developer/ExternalDev")
        body = profile.get_data(as_text=True)
        self.assertIn("foundstore-flat.css?v=flat1", body)
        self.assertIn("data-share-endpoint=\"/api/v1/share/profile/ExternalDev\"", body)
