import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main


class CaseInsensitiveHeaders(dict):
    def get(self, key, default=None):
        key = key.lower()
        for existing, value in self.items():
            if existing.lower() == key:
                return value
        return default


class FakeResponse:
    def __init__(self, status_code, headers=None, text="", payload=None):
        self.status_code = status_code
        self.reason = "OK" if status_code == 200 else "Service Unavailable"
        self.headers = CaseInsensitiveHeaders(headers or {})
        self.text = text
        self.url = main.API_URL
        self.request = SimpleNamespace(method="GET", headers={})
        self._payload = {} if payload is None else payload

    def json(self):
        if self.status_code != 200:
            raise ValueError("not JSON")
        return self._payload


def fetch_args(**overrides):
    args = {
        "event_code": "ET00123456",
        "date_code": "20261101",
        "region_code": "CHEN",
        "region_slug": "chennai",
        "lat": "13.056",
        "lon": "80.206",
        "geohash": "tf3",
    }
    args.update(overrides)
    return args


class RetryPolicyTests(unittest.TestCase):
    def test_retry_after_seconds_is_honored(self):
        response = FakeResponse(429, headers={"Retry-After": "37"})
        self.assertEqual(main.retry_delay_seconds(response, attempt=1), 37)

    def test_exponential_backoff_is_bounded(self):
        self.assertEqual(main.retry_delay_seconds(attempt=1), 5)
        self.assertEqual(main.retry_delay_seconds(attempt=2), 10)
        self.assertEqual(main.retry_delay_seconds(attempt=3), 20)
        self.assertEqual(main.retry_delay_seconds(attempt=20), 60)

    @patch("main.time.sleep")
    @patch("main.requests.get")
    def test_transient_5xx_retries_then_succeeds(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            FakeResponse(503, headers={"server": "origin"}),
            FakeResponse(200, payload={"showtimes": []}),
        ]
        result = main.fetch_bms(**fetch_args())
        self.assertEqual(result, {"showtimes": []})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(5)

    @patch("main.time.sleep")
    @patch("main.requests.get")
    def test_429_obeys_retry_after(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            FakeResponse(429, headers={"Retry-After": "37"}),
            FakeResponse(200, payload={"showtimes": []}),
        ]
        result = main.fetch_bms(**fetch_args())
        self.assertEqual(result, {"showtimes": []})
        mock_sleep.assert_called_once_with(37)

    @patch("main.time.sleep")
    @patch("main.requests.get")
    def test_cloudflare_403_gets_one_delayed_recheck(self, mock_get, mock_sleep):
        blocked = FakeResponse(
            403,
            headers={
                "server": "cloudflare",
                "cf-ray": "abc123-SJC",
                "content-type": "text/html; charset=UTF-8",
            },
            text="Attention Required! Cloudflare",
        )
        mock_get.side_effect = [blocked, blocked]
        failure = {}
        result = main.fetch_bms(**fetch_args(), failure_details=failure)
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(120)
        self.assertEqual(failure["status_code"], 403)
        self.assertIn("delayed recheck completed", failure["recovery_recheck"])

    @patch("main.time.sleep")
    @patch("main.requests.get")
    def test_non_cloudflare_403_is_not_retried(self, mock_get, mock_sleep):
        mock_get.return_value = FakeResponse(
            403, headers={"server": "origin"}, text="Forbidden"
        )
        result = main.fetch_bms(**fetch_args())
        self.assertIsNone(result)
        mock_get.assert_called_once()
        mock_sleep.assert_not_called()

    def test_empty_success_payload_is_still_success(self):
        with patch("main.requests.get", return_value=FakeResponse(200, payload={})):
            self.assertEqual(main.fetch_bms(**fetch_args()), {})


if __name__ == "__main__":
    unittest.main()
