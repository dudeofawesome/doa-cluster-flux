#!/usr/bin/env python3
"""Smoke-test a built Keycloak image using a disposable local container."""

import argparse
import json
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href"))


def interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Local Docker image reference to test")
    parser.add_argument("--timeout", type=int, default=180, help="Startup timeout in seconds")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)

    with tempfile.TemporaryDirectory(prefix="keycloak-smoke-") as folder:
        realm = Path(folder) / "sequoia-realm.json"
        realm.write_text(json.dumps({"realm": "sequoia", "enabled": True, "sslRequired": "none"}))
        # docker cp preserves permissions; Keycloak runs as an unprivileged user.
        Path(folder).chmod(0o755)
        realm.chmod(0o644)
        container = docker(
            "create",
            "--publish", "127.0.0.1::8080",
            "--env", "KC_DB=dev-file",
            "--env", "KC_BOOTSTRAP_ADMIN_USERNAME=smoke-test",
            "--env", "KC_BOOTSTRAP_ADMIN_PASSWORD=local-test-only",
            args.image, "start-dev", "--import-realm", "--http-relative-path=/auth",
        )
        try:
            docker("cp", f"{folder}/.", f"{container}:/opt/keycloak/data/import")
            docker("start", container)
            port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
            root = f"http://127.0.0.1:{port}/auth/"
            deadline = time.monotonic() + args.timeout
            print(f"Waiting up to {args.timeout}s for Keycloak...", flush=True)
            while True:
                try:
                    response = urllib.request.urlopen(root, timeout=3)
                    break
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    if docker("inspect", "--format", "{{.State.Running}}", container) != "true":
                        raise RuntimeError("Keycloak exited before becoming ready") from None
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Keycloak did not become ready before the timeout") from None
                    time.sleep(1)

            with response:
                if response.status != 200 or response.url != root:
                    raise RuntimeError(f"Expected HTTP 200 without a redirect; got {response.status} at {response.url}")
                html = response.read().decode()
            if "Welcome to Orleans" not in html or "Initial server setup is required" in html:
                raise RuntimeError("Expected the custom welcome page after administrator bootstrap")
            links = Links()
            links.feed(html)
            expected = [root + path for path in (
                "realms/sequoia/account/", "admin/sequoia/console/", "admin/master/console/",
            )]
            if links.hrefs != expected:
                raise RuntimeError(f"Unexpected welcome links: {links.hrefs!r}")
            print("PASS: welcome page renders without redirecting, with all three prefixed links", flush=True)
            for name in ("sequoia", "master"):
                issuer = f"{root}realms/{name}"
                with urllib.request.urlopen(f"{issuer}/.well-known/openid-configuration", timeout=10) as discovery:
                    if json.load(discovery).get("issuer") != issuer:
                        raise RuntimeError(f"Unexpected issuer for the {name} realm")
                print(f"PASS: {name} realm discovery returns the expected issuer", flush=True)
            for url in expected:
                with urllib.request.urlopen(url, timeout=10) as destination:
                    if destination.status != 200:
                        raise RuntimeError(f"Unexpected HTTP {destination.status} at {url}")
                print(f"PASS: {url.removeprefix(root)} returns HTTP 200", flush=True)
        except (Exception, KeyboardInterrupt):
            subprocess.run(["docker", "logs", "--tail", "100", container], check=False)
            raise
        finally:
            subprocess.run(
                ["docker", "rm", "--force", container],
                check=True, stdout=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
