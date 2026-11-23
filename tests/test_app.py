import io
import json
import tempfile
import unittest
from pathlib import Path

from app import create_app
from calculations import calculate_summary, unit_volume
from workbook import parse_workbook


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "中幼林抚育林木采伐调查设计总表.xlsx"


class WorkbookTests(unittest.TestCase):
    def test_parse_base_data_and_plot_schema(self):
        parsed = parse_workbook(SAMPLE)
        self.assertEqual(len(parsed["records"]), 684)
        self.assertEqual(parsed["records"][0]["fields"]["number"], "XP-01")
        self.assertEqual([item["name"] for item in parsed["records"][0]["species"]], ["云南松", "其他阔叶"])
        self.assertEqual(parsed["schema"]["diameters"], list(range(6, 51, 2)))
        self.assertEqual(set(parsed["schema"]["species"]), {"云南松", "油杉", "其他阔叶", "栎类"})
        self.assertEqual(parsed["schema"]["area_factor"], 15)

    def test_grouped_volume_matches_sample_formula(self):
        parsed = parse_workbook(SAMPLE)
        params = parsed["schema"]["species"]["云南松"]
        self.assertEqual(unit_volume(params, 6, 8), 0.013)
        survey = {
            "plot_no": "1",
            "trees": {
                "云南松": {"6": {"height": 8, "count": 2}},
                "其他阔叶": {"6": {"height": 8, "count": 2}},
            },
            "cut": {"6": 2},
        }
        summary = calculate_summary(survey, parsed["schema"], ["云南松", "其他阔叶"])
        self.assertEqual(summary["plot_count"], 4)
        self.assertEqual(summary["total_volume"], 0.05)
        self.assertEqual(summary["per_hectare_count"], 60)
        self.assertEqual(summary["per_hectare_volume"], 0.75)
        self.assertEqual(summary["cut_count"], 2)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(root / "test.sqlite3"),
            "UPLOAD_DIR": str(root / "uploads"),
            "PHOTO_DIR": str(root / "photos"),
        })
        self.client = self.app.test_client()
        with SAMPLE.open("rb") as source:
            response = self.client.post("/api/projects", data={
                "file": (io.BytesIO(source.read()), SAMPLE.name),
            }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.project = response.get_json()["project"]

    def tearDown(self):
        self.temp.cleanup()

    def test_project_uses_original_filename(self):
        response = self.client.get("/api/projects")
        self.assertEqual(response.get_json()["projects"][0]["filename"], SAMPLE.name)
        self.assertEqual(self.project["subcompartment_count"], 684)

    def test_subcompartment_detail_uses_species_composition(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        first = project["subcompartments"][0]
        detail = self.client.get(f"/api/subcompartments/{first['id']}").get_json()
        self.assertEqual(detail["fields"]["number"], "XP-01")
        self.assertEqual([item["name"] for item in detail["species"]], ["云南松", "其他阔叶"])
        self.assertEqual(detail["schema"]["diameters"][0], 6)

    def test_survey_autosave_calculates_and_rejects_invalid_counts(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        sub_id = project["subcompartments"][0]["id"]
        payload = {
            "plot_no": "1",
            "trees": {
                "云南松": {"6": {"height": 8, "count": 2}},
                "其他阔叶": {"6": {"height": 8, "count": 2}},
            },
            "cut": {"6": 2},
        }
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["summary"]["total_volume"], 0.05)
        saved = self.client.get(f"/api/subcompartments/{sub_id}").get_json()
        self.assertEqual(saved["survey"]["plot_no"], "1")
        payload["trees"]["云南松"]["6"]["count"] = 1.5
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是整数", response.get_json()["error"])

    def test_track_save_and_gpx_export(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        sub_id = project["subcompartments"][0]["id"]
        points = [
            {"lat": 24.1, "lng": 102.1, "timestamp": 1700000000000, "accuracy": 5},
            {"lat": 24.1001, "lng": 102.1001, "timestamp": 1700000001000, "accuracy": 4},
        ]
        response = self.client.put(f"/api/subcompartments/{sub_id}/track", json={"points": points})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.get_json()["distance"], 10)
        gpx = self.client.get(f"/api/subcompartments/{sub_id}/track.gpx")
        self.assertEqual(gpx.status_code, 200)
        self.assertIn(b'<name>', gpx.data)
        self.assertIn(b'XP-01', gpx.data)

    def test_rejects_unknown_species(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        sub_id = project["subcompartments"][0]["id"]
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json={
            "trees": {"不存在树种": {}}, "cut": {},
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
