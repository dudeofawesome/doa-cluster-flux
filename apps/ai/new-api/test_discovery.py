"""Exercise API snapshots and failure isolation without Kubernetes access."""

import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

from reconcile import DiscoveryError, ModelDiscovery, reconcile_discovered


def model(name, features=None, deleting=False):
    metadata = {"name": name}
    if deleting:
        metadata["deletionTimestamp"] = "2026-10-14T00:00:00Z"
    return {"metadata": metadata, "spec": {"features": features or ["TextGeneration"]}, "status": {"replicas": 0}}


def page(items, cursor=""):
    return io.BytesIO(json.dumps({"items": items, "metadata": {"continue": cursor}}).encode())


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.credentials = Path(self.folder.name)
        (self.credentials / "token").write_text("first-token")
        self.discovery = ModelDiscovery(credentials=self.credentials)
        self.settings = {"namespace": "inference", "label_selector": "inference.orleans.io/expose=true"}
        self.context = patch("reconcile.ssl.create_default_context", return_value=object())
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_complete_snapshot_filters_deleted_and_non_text_models_and_reads_rotated_token(self):
        requests = []

        def respond(request, **kwargs):
            requests.append(request)
            if len(requests) == 1:
                (self.credentials / "token").write_text("rotated-token")
                return page([model("zeta"), model("embedding", ["Embedding"]), model("deleted", deleting=True)], "next/page")
            return page([model("alpha"), model("zeta")])

        with patch("reconcile.urllib.request.urlopen", side_effect=respond):
            self.assertEqual(self.discovery.models(self.settings), ["alpha", "zeta"])
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer first-token")
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer rotated-token")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[1].full_url).query)
        self.assertEqual(query["labelSelector"], [self.settings["label_selector"]])
        self.assertEqual(query["continue"], ["next/page"])
        self.assertEqual(urllib.parse.urlsplit(requests[0].full_url).path, "/apis/kubeai.org/v1/namespaces/inference/models")

    def test_successful_empty_snapshot(self):
        with patch("reconcile.urllib.request.urlopen", return_value=page([])):
            self.assertEqual(self.discovery.models(self.settings), [])

    def test_failed_later_page_never_reconciles_partial_catalog(self):
        error = urllib.error.HTTPError("https://kubernetes.default.svc", 410, "expired snapshot", {}, None)
        client = Mock()
        with patch("reconcile.urllib.request.urlopen", side_effect=[page([model("partial")], "next"), error]):
            with self.assertRaises(DiscoveryError):
                reconcile_discovered(client, {"model_discovery": self.settings}, "secret", self.discovery)
        self.assertEqual(client.mock_calls, [])

    def test_malformed_response_is_not_an_empty_catalog(self):
        with patch("reconcile.urllib.request.urlopen", return_value=io.BytesIO(b'{"kind":"Status"}')):
            with self.assertRaises(DiscoveryError):
                self.discovery.models(self.settings)


if __name__ == "__main__":
    unittest.main()
