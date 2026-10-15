"""Check reconciliation freshness, startup grace, and the independent scrape endpoint."""

import unittest
import urllib.request
from unittest.mock import Mock, patch

from reconcile import APIError, DiscoveryError, ReconciliationMetrics, main


class MetricsTests(unittest.TestCase):
    def test_initial_failures_age_from_startup_and_success_resets_age(self):
        with patch("reconcile.time.monotonic", return_value=100) as clock:
            metrics = ReconciliationMetrics()
            clock.return_value = 1001
            self.assertIn(b"new_api_config_success_age_seconds 901\n", metrics.render())
            metrics.succeeded()
            clock.return_value = 1002
            self.assertIn(b"new_api_config_success_age_seconds 1\n", metrics.render())

    def test_metrics_are_available_while_reconciliation_has_not_succeeded(self):
        metrics = ReconciliationMetrics()
        server = metrics.serve(("127.0.0.1", 0))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/metrics", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/plain")
            self.assertIn(b"new_api_config_success_age_seconds", response.read())

    def test_only_complete_reconciliation_resets_freshness(self):
        metrics = Mock()
        with patch("reconcile.ReconciliationMetrics", return_value=metrics), \
                patch("reconcile.Path.read_text", return_value="{}"), \
                patch.dict("reconcile.os.environ", {"NEW_API_ROOT_PASSWORD": "test", "NEW_API_CLIENT_SECRET": "test"}), \
                patch("reconcile.reconcile_discovered", side_effect=[DiscoveryError(), APIError("test"), None]), \
                patch("reconcile.time.sleep", side_effect=[None, None, KeyboardInterrupt]), \
                patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                main()
        metrics.succeeded.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
