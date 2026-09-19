import argparse
import copy
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import catalog


def fixture():
    return {
        "version": "2026.09.17",
        "generated_at": "2026-09-17T00:00:00Z",
        "brands": [{"id": "brand", "name": "Example"}],
        "materials": [{"id": "material", "material": "PLA", "material_class": "FFF"}],
        "filaments": [{"id": "product", "brand_id": "brand", "material_id": "material",
                       "name": "Basic PLA", "density": 1.24,
                       "min_print_temperature": 200, "max_print_temperature": 221,
                       "min_bed_temperature": 0, "max_bed_temperature": 60}],
        "variants": [{"id": "variant", "filament_id": "product", "name": "Red / Blue",
                      "color_hex": ["#FF0000", "#0000FF"],
                      "traits": {"coextruded": True, "glitter": True, "transparent": True}}],
        "sizes": [
            {"id": "size-1", "uuid": "59f9eb40-da3b-4573-bcb6-5ba87459bee7",
             "variant_id": "variant", "filament_weight": 1000, "diameter": 1.75,
             "empty_spool_weight": 200},
            {"id": "size-2", "uuid": "bb53ccc0-b889-428b-8fed-6b66996490d7",
             "variant_id": "variant", "filament_weight": 500, "diameter": 1.75,
             "spool_refill": True},
        ],
    }


class ConversionTests(unittest.TestCase):
    def test_mapping_and_temperature_policy(self):
        rows, materials, skipped = catalog.convert(fixture())
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 0)
        self.assertEqual(materials, [{"material": "PLA", "density": 1.24}])
        self.assertEqual(rows[0]["spool_weight"], 200)
        self.assertEqual(rows[0]["extruder_temp"], 211)
        self.assertEqual(rows[0]["bed_temp"], 30)
        self.assertEqual(rows[0]["color_hexes"], ["ff0000", "0000ff"])
        self.assertEqual(rows[0]["multi_color_direction"], "coaxial")
        self.assertEqual(rows[0]["pattern"], "sparkle")
        self.assertTrue(rows[0]["translucent"])
        self.assertTrue(rows[1]["name"].endswith("(refill)"))
        self.assertNotIn("spool_weight", rows[1])

    def test_canonical_identity_survives_renames_and_reordering(self):
        data = fixture()
        expected = [row["id"] for row in catalog.convert(data)[0]]
        data["brands"][0]["name"] = "Renamed brand"
        data["filaments"][0]["name"] = "Renamed product"
        data["variants"][0]["name"] = "Renamed color"
        data["sizes"].reverse()
        for size in data["sizes"]:
            size["id"] += "-regenerated"
        self.assertEqual([row["id"] for row in catalog.convert(data)[0]], expected)

    def test_missing_optional_fields_and_single_color(self):
        data = fixture()
        product = data["filaments"][0]
        del product["min_print_temperature"]
        del product["max_print_temperature"]
        data["variants"][0]["color_hex"] = "#ABCDEF"
        rows, _, _ = catalog.convert(data)
        self.assertNotIn("extruder_temp", rows[0])
        self.assertEqual(rows[0]["color_hex"], "abcdef")
        self.assertNotIn("color_hexes", rows[0])

    def test_invalid_required_data_rejected(self):
        changes = [
            ("sizes", "uuid", None),
            ("sizes", "diameter", 0),
            ("sizes", "filament_weight", float("nan")),
            ("filaments", "density", None),
            ("filaments", "density", True),
            ("filaments", "min_print_temperature", 250),
            ("variants", "color_hex", "not-a-color"),
            ("variants", "filament_id", "missing"),
        ]
        for group, field, value in changes:
            with self.subTest(field=field, value=value):
                data = fixture()
                data[group][0][field] = value
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    catalog.convert(data)

    def test_duplicates_rejected(self):
        for field in ("id", "uuid"):
            with self.subTest(field=field):
                data = fixture()
                data["sizes"][1][field] = data["sizes"][0][field]
                with self.assertRaises(ValueError):
                    catalog.convert(data)

    def test_resin_is_not_published_as_filament(self):
        data = fixture()
        data["materials"][0]["material_class"] = "SLA"
        self.assertEqual(catalog.convert(data), ([], [], 2))

    def test_material_density_not_weighted_by_number_of_colors(self):
        data = fixture()
        product = copy.deepcopy(data["filaments"][0])
        product.update(id="product-2", density=1.4)
        data["filaments"].append(product)
        variant = copy.deepcopy(data["variants"][0])
        variant.update(id="variant-2", filament_id="product-2")
        data["variants"].append(variant)
        size = copy.deepcopy(data["sizes"][0])
        size.update(id="size-3", variant_id="variant-2", uuid="0a98b6ca-4c53-4916-85c9-f426e309a046")
        data["sizes"].append(size)
        self.assertAlmostEqual(catalog.convert(data)[1][0]["density"], 1.32)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = fixture()
        self.publish()

    def publish(self, data=None, **kwargs):
        return catalog.publish(self.root, catalog.json_bytes(data or self.data),
                               catalog.SOURCE_URL, min_records=1, **kwargs)

    def test_failed_refresh_preserves_catalog(self):
        previous = (self.root / "current").resolve()
        data = copy.deepcopy(self.data)
        data["sizes"].pop()
        with self.assertRaisesRegex(ValueError, "removal"):
            self.publish(data)
        with self.assertRaises(ValueError):
            catalog.publish(self.root, b"invalid json", catalog.SOURCE_URL, min_records=1)
        data = copy.deepcopy(self.data)
        data["generated_at"] = "2026-09-16T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "older"):
            self.publish(data)
        with self.assertRaisesRegex(ValueError, "minimum"):
            catalog.publish(self.root, catalog.json_bytes(self.data), catalog.SOURCE_URL, min_records=1000)
        self.assertEqual(catalog.load_current(self.root)[0], previous)

    def test_replacement_ids_are_guarded_even_if_count_unchanged(self):
        data = copy.deepcopy(self.data)
        data["sizes"][0]["uuid"] = "0a98b6ca-4c53-4916-85c9-f426e309a046"
        with self.assertRaisesRegex(ValueError, "removal"):
            self.publish(data)

    def test_retains_current_and_previous_and_detects_corruption(self):
        first = (self.root / "current").resolve()
        self.publish()
        second = (self.root / "current").resolve()
        self.publish()
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(len(list(self.root.glob("generation-*"))), 2)
        (self.root / "current" / "filaments.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "Corrupt"):
            catalog.load_current(self.root)

    def test_bootstrap_reuses_valid_catalog_without_network(self):
        args = argparse.Namespace(data_dir=self.root, if_missing=True)
        with patch.object(catalog, "download", side_effect=AssertionError("unexpected fetch")):
            catalog.refresh(args)

    def test_concurrent_bootstraps_download_once(self):
        root = self.root / "concurrent"
        args = argparse.Namespace(data_dir=root, if_missing=True, input=None,
                                  source_url=catalog.SOURCE_URL, min_records=1, max_drop=0.2)
        failures = []

        def refresh():
            try:
                catalog.refresh(args)
            except Exception as error:
                failures.append(error)

        with patch.object(catalog, "download", return_value=catalog.json_bytes(self.data)) as fetch:
            threads = [threading.Thread(target=refresh) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            fetch.assert_called_once()
        catalog.load_current(root)

class DownloadTests(unittest.TestCase):
    def test_oversized_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            catalog.read_limited(io.BytesIO(b"12345"), 4)

    def test_plain_http_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            catalog.download("http://example.com/all.json")


if __name__ == "__main__":
    unittest.main()
