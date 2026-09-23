import csv
import tempfile
import unittest
from pathlib import Path
from catalog import load_catalog

HEADER = ["id", "anon_name", "categories", "city", "city_imputed", "synthetic", "price_from_kzt", "price_imputed", "event_formats", "languages", "max_hours", "busy_dates", "description"]

class CatalogImportTests(unittest.TestCase):
    def test_loads_real_catalog_and_unique_ids(self):
        path = Path(__file__).resolve().parents[1] / "contractors.csv"
        profiles = load_catalog(path)
        self.assertEqual(66, len(profiles))
        self.assertEqual(len(profiles), len({p["id"] for p in profiles}))
        self.assertIsInstance(profiles[0]["synthetic"], bool)
        self.assertTrue(all(isinstance(p["categories"], list) for p in profiles))

    def test_utf8_bom_empty_hours_and_false_boolean(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f); w.writerow(HEADER); w.writerow(["a", "Name", "x|y", "City", "False", "False", 10, "True", "format", "ru", "", "2026-09-25", "desc"])
            p = load_catalog(path)[0]
            self.assertIsNone(p["max_hours"])
            self.assertFalse(p["synthetic"])
            self.assertFalse(p["city_imputed"])
            self.assertEqual(["x", "y"], p["categories"])

if __name__ == "__main__": unittest.main()
