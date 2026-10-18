"""Initialize and reconcile Git-owned New API settings over localhost only."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class ReconciliationMetrics:
    def __init__(self):
        self.last_success = None
        self.started = time.monotonic()

    def succeeded(self):
        self.last_success = time.monotonic()

    def render(self):
        last_success = self.last_success
        age = time.monotonic() - (self.started if last_success is None else last_success)
        return (
            "# HELP new_api_config_success_age_seconds Seconds since complete reconciliation, or startup if none succeeded.\n"
            "# TYPE new_api_config_success_age_seconds gauge\n"
            f"new_api_config_success_age_seconds {max(0, age)}\n"
        ).encode()

    def serve(self, address=("0.0.0.0", 9090)):
        metrics = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                body = metrics.render()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(address, Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        return server


class APIError(RuntimeError):
    def __init__(self, message, status=None, retry_after=30):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class DiscoveryError(RuntimeError):
    pass


class ModelDiscovery:
    def __init__(self, base_url="https://kubernetes.default.svc", credentials=None):
        self.base_url = base_url.rstrip("/")
        self.credentials = Path(credentials or "/var/run/secrets/kubernetes.io/serviceaccount")

    def models(self, settings):
        """Read a complete API snapshot before returning any catalog changes."""
        try:
            context = ssl.create_default_context(cafile=str(self.credentials / "ca.crt"))
            namespace = urllib.parse.quote(settings["namespace"], safe="")
            path = f"/apis/kubeai.org/v1/namespaces/{namespace}/models"
            names = set()
            cursor = ""
            while True:
                query = {
                    "labelSelector": settings["label_selector"],
                    "limit": "500",
                }
                if cursor:
                    query["continue"] = cursor
                # Projected tokens rotate; never retain a token between requests.
                token = (self.credentials / "token").read_text().strip()
                request = urllib.request.Request(
                    self.base_url + path + "?" + urllib.parse.urlencode(query),
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, context=context, timeout=30) as response:
                    result = json.load(response)
                for model in result["items"]:
                    metadata = model["metadata"]
                    features = model["spec"].get("features", [])
                    if not metadata.get("deletionTimestamp") and {"TextGeneration", "SpeechToText"}.intersection(features):
                        names.add(metadata["name"])
                cursor = result["metadata"].get("continue", "")
                if not cursor:
                    return sorted(names)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # An error, including an expired paginated snapshot, is never an empty list.
            raise DiscoveryError("Model discovery failed") from error


def reconcile_discovered(client, config, client_secret, discovery):
    models = discovery.models(config["model_discovery"])
    reconcile(client, {**config, "models": models}, client_secret)


class Client:
    def __init__(self, base_url, password, origin=None):
        self.base_url = base_url.rstrip("/")
        self.origin = (origin or self.base_url).rstrip("/")
        self.password = password
        self.token = None
        self.refresh_token = None

    def request(self, method, path, payload=None):
        authenticated = self.token is not None
        try:
            return self._request(method, path, payload)
        except APIError as error:
            if error.status != 401 or not authenticated or path.startswith("/api/user/auth/"):
                raise
        # Recover once within this reconciliation, without creating another session.
        self.initialize()
        return self._request(method, path, payload)

    def _request(self, method, path, payload=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if path == "/api/user/auth/refresh" and self.refresh_token:
            # Browser cookies remain Secure. This client talks only over localhost
            # and explicitly sends the refresh credential only to its auth route.
            headers["Cookie"] = "new_api_refresh=" + self.refresh_token
            # Cookie-authenticated refresh requires the trusted public origin,
            # even though the sidecar connects over localhost.
            headers["Origin"] = self.origin
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
                if path in ("/api/user/login", "/api/user/auth/refresh"):
                    for header in response.headers.get_all("Set-Cookie", []):
                        cookies = SimpleCookie(header)
                        if "new_api_refresh" in cookies:
                            self.refresh_token = cookies["new_api_refresh"].value or None
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.token = None
            retry_after = 30
            if error.code == 429:
                try:
                    retry_after = max(30, int(error.headers.get("Retry-After", "1200")))
                except ValueError:
                    retry_after = 1200
            # Do not include response bodies: they may contain credentials.
            raise APIError(f"{method} {path}: HTTP {error.code}", error.code, retry_after) from None
        if result.get("success") is not True:
            raise APIError(f"{method} {path}: operation rejected")
        return result.get("data")

    def initialize(self):
        setup = self.request("GET", "/api/setup")
        if not setup["status"]:
            if setup.get("root_init"):
                raise APIError("Unexpected existing root account in uninitialized database")
            self.request("POST", "/api/setup", {
                "username": "cluster-root",
                "password": self.password,
                "confirmPassword": self.password,
                "SelfUseModeEnabled": False,
                "DemoSiteEnabled": False,
            })
        if not self.token:
            if self.refresh_token:
                try:
                    refreshed = self._request("POST", "/api/user/auth/refresh", {})
                    self.token = refreshed["access_token"]
                    return
                except APIError as error:
                    if error.status != 401:
                        raise
                    self.refresh_token = None
            login = self.request("POST", "/api/user/login", {
                "username": "cluster-root", "password": self.password,
            })
            self.token = login["access_token"]

    def channels(self):
        page = 1
        while True:
            data = self.request("GET", f"/api/channel/?p={page}&page_size=100")
            yield from data["items"]
            if page * 100 >= data["total"]:
                break
            page += 1


def provider_config(config, client_secret):
    issuer = config["issuer"]
    return {
        "name": "Sequoia",
        "slug": "sequoia",
        "enabled": True,
        "client_id": config["client_id"],
        "client_secret": client_secret,
        "authorization_endpoint": issuer + "/protocol/openid-connect/auth",
        "token_endpoint": issuer + "/protocol/openid-connect/token",
        "user_info_endpoint": issuer + "/protocol/openid-connect/userinfo",
        "well_known": issuer + "/.well-known/openid-configuration",
        "scopes": "openid profile email",
        "user_id_field": "sub",
        "username_field": "preferred_username",
        "display_name_field": "name",
        "email_field": "email",
        "auth_style": 2,
        "access_policy": json.dumps({
            "logic": "and",
            "conditions": [
                {"field": "groups", "op": "contains", "value": config["allowed_group"]},
                {"field": "email_verified", "op": "eq", "value": True},
            ],
        }),
        "access_denied_message": "A verified Sequoia account in inference-users is required.",
    }


def reconcile(client, config, client_secret):
    client.initialize()
    options = {item["key"]: item["value"] for item in client.request("GET", "/api/option/")}
    desired_options = {
        "ServerAddress": config["public_url"],
        "SystemName": "Orleans Inference",
        "RegisterEnabled": "true",  # First OIDC login creates an account.
        "PasswordRegisterEnabled": "false",
        # Needed by the localhost reconciler; ingress blocks these sign-in routes.
        "PasswordLoginEnabled": "true",
        "GitHubOAuthEnabled": "false",
        "DiscordOAuthEnabled": "false",
        "LinuxDOOAuthEnabled": "false",
        "TelegramOAuthEnabled": "false",
        "WeChatAuthEnabled": "false",
        "OIDCEnabled": "false",
        "SelfUseModeEnabled": "false",
        "DemoSiteEnabled": "false",
        "QuotaForNewUser": "0",
        "QuotaForInviter": "0",
        "QuotaForInvitee": "0",
        "quota_setting.enable_free_model_pre_consume": "false",
        "RetryTimes": "0",
        "ModelRequestRateLimitEnabled": "true",
        "ModelRequestRateLimitDurationMinutes": "1",
        "ModelRequestRateLimitCount": "20",
        "ModelRequestRateLimitSuccessCount": "10",
    }
    # Local inference is free. Preserve pricing for unrelated manually added models.
    ratios = json.loads(options.get("ModelRatio", "{}"))
    ratios.update(dict.fromkeys(config["models"], 0))
    if json.loads(options.get("ModelRatio", "{}")) != ratios:
        desired_options["ModelRatio"] = json.dumps(ratios)
    for key, value in desired_options.items():
        if options.get(key) != value:
            client.request("PUT", "/api/option/", {"key": key, "value": value})

    providers = client.request("GET", "/api/custom-oauth-provider/")
    matches = [p for p in providers if p["slug"] == "sequoia"]
    if len(matches) > 1:
        raise APIError("Multiple Sequoia providers found")
    desired = provider_config(config, client_secret)
    if matches:
        # Secrets aren't returned by the API. Reapply it with the managed fields.
        client.request("PUT", f"/api/custom-oauth-provider/{matches[0]['id']}", desired)
    else:
        client.request("POST", "/api/custom-oauth-provider/", desired)

    channel = {
        "type": 1,  # OpenAI-compatible; adaptor appends /v1 to this base URL.
        "name": config["channel_name"],
        "base_url": config["upstream_base_url"],
        "models": ",".join(config["models"]),
        "group": "default",
        "key": "no-key-required",
        "auto_ban": 0,
    }
    matches = [c for c in client.channels() if c["name"] == channel["name"]]
    if len(matches) > 1:
        raise APIError("Multiple Git-owned KubeAI channels found")
    if not config["models"]:
        # Never submit an ambiguous empty model string to the upstream API.
        if matches and matches[0]["status"] != 2:
            client.request("POST", f"/api/channel/{matches[0]['id']}/status", {"status": 2})
        return
    if matches:
        current = matches[0]
        fields = {k: v for k, v in channel.items() if k != "key"}
        if any(current.get(k) != v for k, v in fields.items()):
            client.request("PUT", "/api/channel/", {"id": current["id"], **fields})
        if current["status"] != 1:
            client.request("POST", f"/api/channel/{current['id']}/status", {"status": 1})
    else:
        client.request("POST", "/api/channel/", {"mode": "single", "channel": channel})


def main():
    metrics = ReconciliationMetrics()
    metrics.serve()
    config = json.loads(Path("/config/gateway.json").read_text())
    client = Client("http://127.0.0.1:3000", os.environ["NEW_API_ROOT_PASSWORD"], origin=config["public_url"])
    discovery = ModelDiscovery()
    while True:
        try:
            reconcile_discovered(client, config, os.environ["NEW_API_CLIENT_SECRET"], discovery)
            metrics.succeeded()
            print("Managed gateway configuration ready", flush=True)
            time.sleep(300)
        except DiscoveryError:
            # Keep serving the last applied catalog after a discovery-only failure.
            print("Model discovery failed; retaining applied catalog and retrying in 30 seconds", flush=True)
            time.sleep(30)
        except (APIError, KeyError, ValueError, OSError) as error:
            # Avoid logging passwords, tokens, URLs with credentials, or API bodies.
            delay = error.retry_after if isinstance(error, APIError) else 30
            detail = str(error) if isinstance(error, APIError) else type(error).__name__
            print(f"Gateway configuration failed ({detail}); retrying in {delay} seconds", flush=True)
            time.sleep(delay)


if __name__ == "__main__":
    main()
