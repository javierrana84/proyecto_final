import unittest
import re
from unittest.mock import Mock, patch

from app import app


class AppTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_homepage_renders_flight_search(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tu vuelo, en ruta", response.data)
        self.assertIn(b"flight-number", response.data)
        self.assertIn(b'href="http://localhost:3000"', response.data)
        self.assertIn(b"Abrir dashboard", response.data)

    def test_security_headers_and_script_nonce_are_set(self):
        response = self.client.get("/")
        nonce = re.search(rb'<script nonce="([^"]+)"', response.data).group(1).decode()
        policy = response.headers["Content-Security-Policy"]

        self.assertIn(f"'nonce-{nonce}'", policy)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(
            response.headers["Cache-Control"],
            "private, no-cache, max-age=0, must-revalidate",
        )
        self.assertEqual(response.headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")

    def test_static_assets_have_public_cache(self):
        response = self.client.get("/static/style.css")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")

    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")

    def test_invalid_flight_number_is_rejected(self):
        response = self.client.get("/api/flights?flight_iata=not-a-flight")

        self.assertEqual(response.status_code, 400)

    @patch.dict("os.environ", {"AIRLABS_API_KEY": "test-key"})
    @patch("app.requests.get")
    def test_flight_lookup_returns_provider_data(self, get):
        upstream = Mock()
        upstream.json.return_value = {
            "response": [{
                "flight_iata": "IB6842",
                "dep_iata": "MAD",
                "arr_iata": "EZE",
                "status": "en-route",
                "lat": -34.6,
                "internal_field": "not exposed",
            }]
        }
        get.return_value = upstream

        response = self.client.get("/api/flights?flight_iata=ib6842")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["flights"][0]["dep_iata"], "MAD")
        self.assertNotIn("internal_field", response.json["flights"][0])
        self.assertEqual(get.call_args.kwargs["params"]["api_key"], "test-key")

    @patch.dict("os.environ", {"AIRLABS_API_KEY": ""})
    def test_flight_lookup_requires_api_key(self):
        response = self.client.get("/api/flights?flight_iata=IB6842")

        self.assertEqual(response.status_code, 503)

    def test_metrics_endpoint_exposes_prometheus_metrics(self):
        self.client.get("/health")
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"http_requests_total", response.data)
        self.assertIn(b'route="/health"', response.data)
        self.assertIn(b"process_resident_memory_bytes", response.data)
        self.assertIn(b"app_uptime_seconds", response.data)


if __name__ == "__main__":
    unittest.main()