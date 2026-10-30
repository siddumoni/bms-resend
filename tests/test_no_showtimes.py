import unittest
from unittest.mock import patch

import main


class NoShowtimeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.watch = {
            "name": "Test Movie",
            "url": "https://in.bookmyshow.com/movies/chennai/test-movie/buytickets/ET00123456",
            "dates": "20261107",
            "theatre": "",
            "time_period": "",
            "format": "",
        }

    @patch("main.load_state", return_value={"shows": {}, "dates": {}})
    @patch("main.get_fail_tracker", return_value={})
    @patch("main.fetch_bms", return_value={
        "data": {"topStickyWidgets": [], "showtimeWidgets": []}
    })
    def test_successful_response_without_showtimes_is_not_an_error(
        self, _fetch, _tracker, _state
    ):
        result = main.process_watch(self.watch, {}, legacy_mode=False)
        self.assertIsNone(result["error"])
        self.assertEqual(result["fetch_errors"], [])
        self.assertEqual(result["failed_dates"], [])
        self.assertEqual(result["filtered"], [])
        self.assertEqual(result["changes"], [])

    @patch("main.load_state", return_value={"shows": {}, "dates": {}})
    @patch("main.get_fail_tracker", return_value={})
    @patch("main.fetch_bms", return_value=None)
    def test_failed_request_remains_an_error(self, _fetch, _tracker, _state):
        result = main.process_watch(self.watch, {}, legacy_mode=False)
        self.assertIsNotNone(result["error"])
        self.assertTrue(result["fetch_errors"])
        self.assertEqual(result["failed_dates"], ["20261107"])


if __name__ == "__main__":
    unittest.main()
