import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from app import create_app
from calculations import calculate_summary, unit_volume
from workbook import WorkbookError, parse_workbook


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "中幼林抚育林木采伐调查设计总表.xlsx"

FOREST_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    created_at TEXT
);
"""


def make_forest_db(path, users):
    """建一个最小 forest_web.db：只保留鉴权要用的 users 表。"""
    conn = sqlite3.connect(path)
    conn.executescript(FOREST_SCHEMA)
    conn.executemany(
        "INSERT INTO users(id, username, display_name, is_admin, is_active, expires_at)"
        " VALUES(?,?,?,?,?,?)", users,
    )
    conn.commit()
    conn.close()


def workbook_with_params(rows, name="带参数.xlsx"):
    """复制真实工作簿并追加「程序参数」sheet，返回 bytes。"""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / name
        shutil.copy(SAMPLE, path)
        wb = load_workbook(path)
        ws = wb.create_sheet("程序参数")
        ws.append(["key", "value", "类型", "默认值", "说明", "示例"])
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path.read_bytes()


class WorkbookTests(unittest.TestCase):
    def test_parse_base_data_and_plot_schema(self):
        parsed = parse_workbook(SAMPLE)
        self.assertEqual(len(parsed["records"]), 684)
        self.assertEqual(parsed["records"][0]["fields"]["number"], "XP-01")
        self.assertEqual([item["name"] for item in parsed["records"][0]["species"]], ["云南松", "其他阔叶"])
        self.assertEqual(parsed["schema"]["diameters"], list(range(6, 51, 2)))
        self.assertEqual(set(parsed["schema"]["species"]), {"云南松", "油杉", "其他阔叶", "栎类"})
        self.assertEqual(parsed["schema"]["area_factor"], 15)

    def test_workbook_without_param_sheet_keeps_v1_defaults(self):
        params = parse_workbook(SAMPLE)["params"]
        self.assertEqual(params["功能"], ["拍照", "轨迹"])
        self.assertEqual(params["压缩最长边"], 1440)
        self.assertEqual(params["压缩质量"], 0.8)
        self.assertEqual(params["source_sheet"], "")

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

    def test_param_sheet_drives_features_and_compression(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "参数.xlsx"
            path.write_bytes(workbook_with_params([
                ["功能", "拍照", "列表", "拍照;轨迹", "关闭轨迹", ""],
                ["压缩最长边", "1024", "数值", "1440", "", ""],
                ["压缩质量", "0.7", "数值", "0.8", "", ""],
                ["不显示列", "郁闭度", "列表", "", "", ""],
                ["水印内容", "时间;小班", "列表", "", "", ""],
            ]))
            params = parse_workbook(path)["params"]
        self.assertEqual(params["功能"], ["拍照"])
        self.assertEqual(params["压缩最长边"], 1024)
        self.assertEqual(params["压缩质量"], 0.7)
        self.assertEqual(params["不显示列"], ["郁闭度"])
        self.assertEqual(params["水印内容"], ["时间", "小班"])
        self.assertEqual(params["source_sheet"], "程序参数")

    def test_param_sheet_rejects_bad_values_with_row_number(self):
        cases = [
            ([["功能", "拍照;飞行"]], "未知取值"),
            ([["功能", "拍照；轨迹"]], "全角分隔符"),
            ([["压缩最长边", "100"]], "超出范围"),
            ([["未知键", "1"]], "未知 key"),
            ([["不显示列", "不存在的列"]], "不在基础数据表头中"),
        ]
        for rows, expected in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "坏参数.xlsx"
                    path.write_bytes(workbook_with_params(rows))
                    with self.assertRaises(WorkbookError) as ctx:
                        parse_workbook(path)
                self.assertIn(expected, str(ctx.exception))
                self.assertIn("第2行", str(ctx.exception))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        forest_db = root / "forest_web.db"
        make_forest_db(forest_db, [
            (1, "admin", "管理员甲", 1, 1, None),
            (2, "worker", "调查员", 0, 1, None),
            (3, "admin2", "管理员乙", 1, 1, None),
            (4, "expired", "过期账号", 1, 1, "2020-01-01"),
            (5, "disabled", "停用账号", 1, 0, None),
        ])
        self.app = create_app(test_config={
            "TESTING": True,
            "DATABASE": str(root / "test.sqlite3"),
            "UPLOAD_DIR": str(root / "uploads"),
            "PHOTO_DIR": str(root / "photos"),
            "BACKUP_DIR": str(root / "backups"),
            "SECRET_KEY": "test-secret",
            "FOREST_DB": str(forest_db),
            "LOCAL_DEV_USER": "",
        })
        self.client = self.app.test_client()
        self.login(1)
        self.project = self.upload(SAMPLE.name, SAMPLE.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def login(self, user_id):
        """模拟 forest-data 登录成功后写入的 session（本应用只读不改）。"""
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

    def logout(self):
        with self.client.session_transaction() as session:
            session.clear()

    def upload(self, filename, blob):
        response = self.client.post("/admin/api/projects", data={
            "file": (io.BytesIO(blob), filename),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["project"]

    def first_sub(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        return project["subcompartments"][0]["id"]

    # ── 鉴权（账号在 forest-data）────────────────────────────
    def test_anonymous_is_sent_to_unified_login(self):
        self.logout()
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 401)
        self.assertIn("/forest/login", response.get_json()["login_url"])
        page = self.client.get("/")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/forest/login?next=/", page.headers["Location"])

    def test_me_exposes_login_and_logout_url(self):
        me = self.client.get("/api/me").get_json()
        self.assertEqual(me["user"], "admin")
        self.assertEqual(me["role"], "admin")
        self.assertIn("/forest/login", me["login_url"])
        self.assertEqual(me["logout_url"], "/forest/logout")

    def test_disabled_and_expired_accounts_are_rejected(self):
        self.logout()
        for user_id in (4, 5):
            with self.subTest(user_id=user_id):
                self.login(user_id)
                self.assertEqual(self.client.get("/api/projects").status_code, 401)
        # 不存在的 user_id 同样拒绝（账号被删）
        self.login(999)
        self.assertEqual(self.client.get("/api/projects").status_code, 401)

    def test_plain_user_cannot_enter_admin(self):
        self.logout()
        self.login(2)
        self.assertEqual(self.client.get("/admin/api/projects").status_code, 403)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        # 调查接口仍然可用
        self.assertEqual(self.client.get("/api/projects").status_code, 200)

    def test_admin_role_comes_from_forest_users_table(self):
        self.logout()
        self.login(3)
        response = self.client.get("/admin/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["projects"][0]["can_overwrite"])

    def test_admin_can_overwrite_other_uploader(self):
        self.logout()
        self.login(3)
        response = self.client.post(
            f"/admin/api/projects/{self.project['id']}/update?dry=1",
            data={"file": (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["preview"]["matched"], 684)

    # ── 数据 ────────────────────────────────────────────────
    def test_upload_is_moved_to_admin(self):
        response = self.client.post("/api/projects", data={
            "file": (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 403)
        self.assertIn("/admin/", response.get_json()["error"])

    def test_project_uses_original_filename(self):
        response = self.client.get("/api/projects")
        self.assertEqual(response.get_json()["projects"][0]["filename"], SAMPLE.name)
        self.assertEqual(self.project["subcompartment_count"], 684)
        self.assertEqual(self.project["uploader"], "admin")

    def test_subcompartment_detail_uses_species_composition(self):
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        first = project["subcompartments"][0]
        detail = self.client.get(f"/api/subcompartments/{first['id']}").get_json()
        self.assertEqual(detail["fields"]["number"], "XP-01")
        self.assertEqual([item["name"] for item in detail["species"]], ["云南松", "其他阔叶"])
        self.assertEqual(detail["schema"]["diameters"][0], 6)
        self.assertTrue(detail["params"]["has_photo"])
        self.assertTrue(detail["params"]["has_track"])

    def test_survey_autosave_calculates_and_rejects_invalid_counts(self):
        sub_id = self.first_sub()
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
        sub_id = self.first_sub()
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
        sub_id = self.first_sub()
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json={
            "trees": {"不存在树种": {}}, "cut": {},
        })
        self.assertEqual(response.status_code, 400)

    # ── 覆盖更新 ────────────────────────────────────────────
    def test_update_keeps_survey_and_requires_name_confirm(self):
        sub_id = self.first_sub()
        payload = {
            "plot_no": "7",
            "trees": {"云南松": {"6": {"height": 9, "count": 3}}, "其他阔叶": {}},
            "cut": {"6": 1},
        }
        self.assertEqual(self.client.put(
            f"/api/subcompartments/{sub_id}/survey", json=payload).status_code, 200)

        preview = self.client.post(
            f"/admin/api/projects/{self.project['id']}/update?dry=1",
            data={"file": (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name)},
            content_type="multipart/form-data",
        ).get_json()["preview"]
        self.assertEqual(preview["matched"], 684)
        self.assertEqual(preview["added"], 0)

        wrong = self.client.post(
            f"/admin/api/projects/{self.project['id']}/update",
            data={"file": (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name), "confirm": "错的.xlsx"},
            content_type="multipart/form-data",
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertIn("确认名称不一致", wrong.get_json()["error"])

        done = self.client.post(
            f"/admin/api/projects/{self.project['id']}/update",
            data={"file": (io.BytesIO(SAMPLE.read_bytes()), SAMPLE.name), "confirm": SAMPLE.name},
            content_type="multipart/form-data",
        )
        self.assertEqual(done.status_code, 200)
        self.assertTrue(done.get_json()["backup"].endswith(".json"))
        after = self.client.get(f"/api/subcompartments/{sub_id}").get_json()
        self.assertEqual(after["survey"]["plot_no"], "7")
        self.assertEqual(after["survey"]["trees"]["云南松"]["6"]["count"], 3)

    def test_param_sheet_upload_hides_track(self):
        project = self.upload("关闭轨迹.xlsx", workbook_with_params([
            ["功能", "拍照", "列表", "拍照;轨迹", "", ""],
            ["压缩最长边", "1024", "数值", "1440", "", ""],
        ]))
        detail = self.client.get(
            f"/api/projects/{project['id']}"
        ).get_json()
        self.assertFalse(detail["params"]["has_track"])
        self.assertEqual(detail["params"]["压缩最长边"], 1024)
        sub_id = detail["subcompartments"][0]["id"]
        response = self.client.put(f"/api/subcompartments/{sub_id}/track", json={"points": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("关闭轨迹", response.get_json()["error"])


class GatewayMountTests(unittest.TestCase):
    """网关前缀挂载的回归：H9（cookie 路径）与"跳转丢前缀"两条都只会在线上炸。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        forest_db = root / "forest_web.db"
        make_forest_db(forest_db, [(1, "admin", "管理员甲", 1, 1, None)])
        self.root = root
        self.forest_db = forest_db
        self.app = create_app(prefix="/exp-survey", test_config={
            "TESTING": True,
            "DATABASE": str(root / "test.sqlite3"),
            "UPLOAD_DIR": str(root / "uploads"),
            "PHOTO_DIR": str(root / "photos"),
            "BACKUP_DIR": str(root / "backups"),
            "SECRET_KEY": "test-secret",
            "FOREST_DB": str(forest_db),
            "LOCAL_DEV_USER": "",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_session_cookie_is_never_scoped_to_prefix(self):
        self.assertEqual(self.app.config["SESSION_COOKIE_PATH"], "/")
        response = self.client.get("/api/me")
        for cookie in response.headers.getlist("Set-Cookie"):
            # 只允许删除历史残留，不允许写一条带值的 /exp-survey cookie
            if "Path=/exp-survey" in cookie:
                self.assertIn("Expires=Thu, 01 Jan 1970", cookie)

    def test_login_redirect_keeps_gateway_prefix(self):
        response = self.client.get("/", environ_overrides={"SCRIPT_NAME": "/exp-survey"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"],
                         "/forest/login?next=/exp-survey/")

    def test_login_user_is_read_from_forest_db(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        me = self.client.get("/api/me", environ_overrides={"SCRIPT_NAME": "/exp-survey"}).get_json()
        self.assertEqual(me["user"], "admin")
        self.assertEqual(me["login_url"], "/forest/login?next=/exp-survey/")


if __name__ == "__main__":
    unittest.main()
