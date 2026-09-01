import unittest

from marketing_diagnosis.data import normalize_dataset


class BasicTests(unittest.TestCase):
    def test_normalize_daily(self):
        raw = {"hotel_daily": [{"business_date": "2026-07-01", "room_count": 31, "room_nights": 26}]}
        result = normalize_dataset(raw)
        self.assertEqual(result["sections"]["hotel_daily"][0]["room_count"], 31.0)


if __name__ == "__main__":
    unittest.main()
