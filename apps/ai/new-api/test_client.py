"""Verify session renewal and bounded retries without real credentials or cluster access."""

import io
import json
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from reconcile import APIError, Client


def response(data, cookie=None):
    result = io.BytesIO(json.dumps({"success": True, "data": data}).encode())
    result.headers = Message()
    if cookie:
        result.headers.add_header("Set-Cookie", "new_api_refresh=" + cookie + "; Secure; HttpOnly; Path=/api/user/auth")
    return result


def failure(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://127.0.0.1:3000", code, "error", headers, None)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Client("http://127.0.0.1:3000", "test-password", origin="https://inference.orleans.io")

    def test_login_captures_secure_refresh_cookie(self):
        with patch("reconcile.urllib.request.urlopen", side_effect=[
            response({"status": True}), response({"access_token": "access"}, "refresh"),
        ]):
            self.client.initialize()
        self.assertEqual(self.client.token, "access")
        self.assertEqual(self.client.refresh_token, "refresh")

    def test_expiry_renews_same_session_and_retries_original_request(self):
        self.client.token = "expired"
        self.client.refresh_token = "refresh"
        with patch("reconcile.urllib.request.urlopen", side_effect=[
            failure(401), response({"status": True}),
            response({"access_token": "renewed"}, "rotated"), response(["options"]),
        ]) as send:
            self.assertEqual(self.client.request("GET", "/api/option/"), ["options"])
        requests = [call.args[0] for call in send.call_args_list]
        self.assertEqual([r.full_url.removeprefix(self.client.base_url) for r in requests],
                         ["/api/option/", "/api/setup", "/api/user/auth/refresh", "/api/option/"])
        self.assertEqual(requests[2].get_header("Cookie"), "new_api_refresh=refresh")
        self.assertEqual(requests[2].get_header("Origin"), "https://inference.orleans.io")
        self.assertEqual(requests[3].get_header("Authorization"), "Bearer renewed")
        self.assertTrue(all(r.get_header("Cookie") is None for r in [requests[0], requests[1], requests[3]]))
        self.assertTrue(all(r.get_header("Origin") is None for r in [requests[0], requests[1], requests[3]]))
        self.assertEqual(self.client.refresh_token, "rotated")

    def test_revoked_refresh_falls_back_to_login(self):
        self.client.refresh_token = "revoked"
        with patch("reconcile.urllib.request.urlopen", side_effect=[
            response({"status": True}), failure(401), response({"access_token": "new"}, "new-refresh"),
        ]):
            self.client.initialize()
        self.assertEqual(self.client.token, "new")
        self.assertEqual(self.client.refresh_token, "new-refresh")

    def test_second_unauthorized_response_does_not_loop(self):
        self.client.token = "expired"
        self.client.refresh_token = "refresh"
        with patch("reconcile.urllib.request.urlopen", side_effect=[
            failure(401), response({"status": True}), response({"access_token": "renewed"}, "rotated"), failure(401),
        ]) as send:
            with self.assertRaises(APIError):
                self.client.request("GET", "/api/option/")
        self.assertEqual(send.call_count, 4)

    def test_rate_limit_preserves_session_and_retry_after(self):
        self.client.refresh_token = "refresh"
        with patch("reconcile.urllib.request.urlopen", side_effect=[response({"status": True}), failure(429, "1200")]) as send:
            with self.assertRaises(APIError) as caught:
                self.client.initialize()
        self.assertEqual(caught.exception.retry_after, 1200)
        self.assertEqual(self.client.refresh_token, "refresh")
        self.assertEqual(send.call_count, 2)

    def test_rate_limit_without_valid_hint_uses_conservative_backoff(self):
        for hint in [None, "invalid"]:
            with self.subTest(hint=hint), patch("reconcile.urllib.request.urlopen", side_effect=failure(429, hint)):
                with self.assertRaises(APIError) as caught:
                    self.client.request("GET", "/api/setup")
                self.assertEqual(caught.exception.retry_after, 1200)


if __name__ == "__main__":
    unittest.main()
