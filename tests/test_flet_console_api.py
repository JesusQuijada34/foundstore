from __future__ import annotations

import base64
import hashlib
import unittest

from flet_console_api import FoundstoreConsoleApi, pkce_challenge


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class FletConsoleApiTests(unittest.TestCase):
    def test_pkce_and_console_token_are_scoped_to_console_header(self) -> None:
        verifier = "flet-console-verifier-0123456789012345678901234567890123456789"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        session = FakeSession([
            FakeResponse(201, {"requestId": "request_123", "userCode": "ABCD1234", "verificationUri": "https://example.test/console/authorize/request_123?code=ABCD1234", "expiresAt": "2099-01-01T00:00:00+00:00"}),
            FakeResponse(201, {"consoleToken": "console-token-value", "account": "jq34", "expiresAt": "2099-01-01T12:00:00+00:00"}),
            FakeResponse(200, {"devices": []}),
        ])
        api = FoundstoreConsoleApi("https://example.test", session=session)
        authorization = api.begin_authorization(verifier)
        self.assertEqual(session.calls[0]["json"], {"pkceChallenge": challenge})
        self.assertEqual(pkce_challenge(verifier), challenge)
        self.assertEqual(api.claim_authorization(authorization, verifier)["account"], "jq34")
        self.assertNotIn("Authorization", session.calls[1]["headers"])
        self.assertEqual(api.devices(), [])
        self.assertEqual(session.calls[2]["headers"]["X-Foundstore-Console-Token"], "console-token-value")


if __name__ == "__main__":
    unittest.main()
