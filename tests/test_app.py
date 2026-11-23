import io
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from app import ASSET_VERSION, create_app
from calculations import calculate_summary, unit_volume
from export_xlsx import build_project_workbook
from param_parser import public_params
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

    def test_workbook_without_param_sheet_defaults_to_photo_only(self):
        params = parse_workbook(SAMPLE)["params"]
        self.assertEqual(params["功能"], ["拍照"])          # v1.3：默认不显示轨迹（C17）
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

    def test_track_interval_is_ignored_while_track_is_off(self):
        """不开轨迹时「轨迹采样间隔」不生效：填 0 不能拖垮整份工作簿。

        真实总表（tpl/中幼林抚育…总表.xlsx）就用 0 表示「不要轨迹」，
        历史上因此整份上传被拒（ParamError 越界），这里锁住该口径。
        """
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "关闭轨迹.xlsx"
            path.write_bytes(workbook_with_params([
                ["功能", "拍照", "列表", "拍照;轨迹", "只拍照", ""],
                ["轨迹采样间隔", "0", "数值", "5", "不开轨迹时填 0", ""],
            ]))
            params = parse_workbook(path)["params"]
        self.assertEqual(params["功能"], ["拍照"])
        self.assertEqual(params["轨迹采样间隔"], 5)          # 回落默认值，不采用非法的 0
        self.assertFalse(public_params(params)["has_track"])

    def test_track_interval_still_validated_when_track_is_on(self):
        """开了轨迹就必须是 1-60；错误在这时才暴露，不被静默吃掉（C17 单开关）。"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "开轨迹但间隔非法.xlsx"
            path.write_bytes(workbook_with_params([
                ["功能", "拍照;轨迹", "列表", "拍照", "打开轨迹", ""],
                ["轨迹采样间隔", "0", "数值", "5", "", ""],
            ]))
            with self.assertRaises(WorkbookError) as ctx:
                parse_workbook(path)
        self.assertIn("轨迹采样间隔", str(ctx.exception))
        self.assertIn("超出范围", str(ctx.exception))


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

    def test_legacy_login_endpoints_stay_json(self):
        """旧 WebView 缓存的 app.js 还会打这两个接口：必须回 JSON，不能回 404 HTML。"""
        response = self.client.post("/api/login", json={"username": "a", "password": "b"})
        self.assertEqual(response.status_code, 410)
        self.assertTrue(response.is_json)
        self.assertIn("/forest/login", response.get_json()["login_url"])
        users = self.client.get("/admin/api/users")
        self.assertEqual(users.status_code, 410)
        self.assertTrue(users.is_json)

    def test_export_requires_login_and_returns_one_sheet_per_plot(self):
        url = f"/api/projects/{self.project['id']}/export.xlsx"
        self.logout()
        self.assertEqual(self.client.get(url).status_code, 401)
        self.login(1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response.headers["Content-Type"])
        self.assertIn(".xlsx", response.headers["Content-Disposition"])
        wb = load_workbook(io.BytesIO(response.data))
        self.assertEqual(len(wb.sheetnames), 684)      # 每个小班默认一块样地 → 684 张 sheet
        self.assertEqual(wb.sheetnames[0], "XP-01-1")  # sheet 名 = 小班号-样地号
        response.close()

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
        self.assertFalse(detail["params"]["has_track"])     # 默认不带轨迹

    def test_survey_autosave_calculates_and_rejects_invalid_counts(self):
        sub_id = self.first_sub()
        payload = {
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
        self.assertEqual(len(saved["plots"]), 1)                 # 上传即自带一块样地
        self.assertEqual(saved["plots"][0]["plot_no"], "1")      # 默认样地号 1
        self.assertEqual(saved["plots"][0]["summary"]["plot_count"], 4)
        self.assertTrue(saved["plots"][0]["has_survey"])
        payload["trees"]["云南松"]["6"]["count"] = 1.5
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是整数", response.get_json()["error"])

    def test_track_save_and_gpx_export(self):
        # 轨迹是可选功能：显式在参数 sheet 里打开，才允许记录与导出
        project = self.upload("含轨迹.xlsx", workbook_with_params([
            ["功能", "拍照;轨迹", "列表", "拍照", "打开轨迹", ""],
        ]))
        detail = self.client.get(f"/api/projects/{project['id']}").get_json()
        self.assertTrue(detail["params"]["has_track"])
        sub_id = detail["subcompartments"][0]["id"]
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

    def test_track_is_rejected_when_param_disables_it(self):
        response = self.client.put(f"/api/subcompartments/{self.first_sub()}/track",
                                   json={"points": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("轨迹", response.get_json()["error"])

    def test_rejects_unknown_species(self):
        sub_id = self.first_sub()
        response = self.client.put(f"/api/subcompartments/{sub_id}/survey", json={
            "trees": {"不存在树种": {}}, "cut": {},
        })
        self.assertEqual(response.status_code, 400)

    # ── 覆盖更新 ────────────────────────────────────────────
    def test_update_keeps_survey_and_requires_name_confirm(self):
        sub_id = self.first_sub()
        detail = self.client.get(f"/api/subcompartments/{sub_id}").get_json()
        plot_id = detail["plots"][0]["id"]
        # 样地号改成 7：v1.4 起号在样地行上，走 PATCH，不再塞在调查数据里
        renamed = self.client.patch(f"/api/subcompartments/{sub_id}/plots/{plot_id}",
                                    json={"plot_no": "7"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.get_json()["plot"]["plot_no"], "7")
        payload = {
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
        self.assertEqual(after["plots"][0]["plot_no"], "7")   # 覆盖前改的样地号被保住
        self.assertEqual(after["plots"][0]["survey"]["trees"]["云南松"]["6"]["count"], 3)

    # ── 多块样地（v1.4）────────────────────────────────────
    def test_multiple_plots_are_independent(self):
        """一个小班多块样地：新增 → 各填各的 → 互不影响 → 改名 → 删除。"""
        sub_id = self.first_sub()
        first = self.client.get(f"/api/subcompartments/{sub_id}").get_json()["plots"][0]
        self.assertEqual(first["plot_no"], "1")

        added = self.client.post(f"/api/subcompartments/{sub_id}/plots", json={})
        self.assertEqual(added.status_code, 201)
        second = added.get_json()["plot"]
        self.assertEqual(second["plot_no"], "2")           # 自动递增

        self.client.put(f"/api/subcompartments/{sub_id}/plots/{first['id']}/survey", json={
            "trees": {"云南松": {"6": {"height": 8, "count": 2}}}, "cut": {},
        })
        self.client.put(f"/api/subcompartments/{sub_id}/plots/{second['id']}/survey", json={
            "trees": {"云南松": {"6": {"height": 9, "count": 3}}}, "cut": {"6": 1},
        })

        plots = self.client.get(f"/api/subcompartments/{sub_id}").get_json()["plots"]
        self.assertEqual([plot["plot_no"] for plot in plots], ["1", "2"])
        self.assertEqual(plots[0]["summary"]["plot_count"], 2)
        self.assertEqual(plots[1]["summary"]["plot_count"], 3)
        self.assertEqual(plots[1]["summary"]["cut_count"], 1)
        self.assertTrue(all(plot["has_survey"] for plot in plots))

        # 列表页要能直接看到每块样地号，才知道点哪个进
        project = self.client.get(f"/api/projects/{self.project['id']}").get_json()
        row = next(item for item in project["subcompartments"] if item["id"] == sub_id)
        self.assertEqual([plot["plot_no"] for plot in row["plots"]], ["1", "2"])
        self.assertTrue(row["has_survey"])

        renamed = self.client.patch(f"/api/subcompartments/{sub_id}/plots/{second['id']}",
                                    json={"plot_no": "2-1"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.get_json()["plot"]["plot_no"], "2-1")

        removed = self.client.delete(f"/api/subcompartments/{sub_id}/plots/{second['id']}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual([plot["plot_no"] for plot in removed.get_json()["plots"]], ["1"])

    def test_plot_number_is_unique_and_last_plot_is_protected(self):
        sub_id = self.first_sub()
        plot_id = self.client.get(f"/api/subcompartments/{sub_id}").get_json()["plots"][0]["id"]
        self.client.post(f"/api/subcompartments/{sub_id}/plots", json={})

        duplicate = self.client.patch(f"/api/subcompartments/{sub_id}/plots/{plot_id}",
                                      json={"plot_no": "2"})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("已有样地号", duplicate.get_json()["error"])

        empty = self.client.patch(f"/api/subcompartments/{sub_id}/plots/{plot_id}",
                                  json={"plot_no": "   "})
        self.assertEqual(empty.status_code, 400)
        self.assertIn("不能为空", empty.get_json()["error"])

        second = self.client.post(f"/api/subcompartments/{sub_id}/plots", json={}).get_json()["plot"]
        self.assertEqual(second["plot_no"], "3")           # 中间插号也不撞
        self.client.delete(f"/api/subcompartments/{sub_id}/plots/{second['id']}")

        first_gone = self.client.delete(f"/api/subcompartments/{sub_id}/plots/{plot_id}")
        self.assertEqual(first_gone.status_code, 200)
        self.assertEqual([plot["plot_no"] for plot in first_gone.get_json()["plots"]], ["2"])
        kept_id = first_gone.get_json()["plots"][0]["id"]

        last = self.client.delete(f"/api/subcompartments/{sub_id}/plots/{kept_id}")
        self.assertEqual(last.status_code, 400)
        self.assertIn("至少要保留一个样地", last.get_json()["error"])

    def test_plot_track_and_photos_are_per_plot(self):
        project = self.upload("含轨迹.xlsx", workbook_with_params([
            ["功能", "拍照;轨迹", "列表", "拍照", "打开轨迹", ""],
        ]))
        sub_id = self.client.get(f"/api/projects/{project['id']}").get_json()["subcompartments"][0]["id"]
        detail = self.client.get(f"/api/subcompartments/{sub_id}").get_json()
        first = detail["plots"][0]
        second = self.client.post(f"/api/subcompartments/{sub_id}/plots", json={}).get_json()["plot"]

        points = [
            {"lat": 24.1, "lng": 102.1, "timestamp": 1700000000000, "accuracy": 5},
            {"lat": 24.1001, "lng": 102.1001, "timestamp": 1700000001000, "accuracy": 4},
        ]
        saved = self.client.put(f"/api/subcompartments/{sub_id}/plots/{second['id']}/track",
                                json={"points": points})
        self.assertEqual(saved.status_code, 200)

        plots = {plot["id"]: plot for plot in
                 self.client.get(f"/api/subcompartments/{sub_id}").get_json()["plots"]}
        self.assertEqual(plots[first["id"]]["track"], [])
        self.assertEqual(len(plots[second["id"]]["track"]), 2)
        self.assertGreater(plots[second["id"]]["track_distance"], 10)
        self.assertEqual(
            self.client.get(f"/api/subcompartments/{sub_id}/plots/{first['id']}/track.gpx").status_code,
            400)   # 第一块没轨迹
        gpx = self.client.get(f"/api/subcompartments/{sub_id}/plots/{second['id']}/track.gpx")
        self.assertEqual(gpx.status_code, 200)
        self.assertIn(b"XP-01-2", gpx.data)

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

    def test_assets_are_versioned_for_webview_cache(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        html = self.client.get("/", environ_overrides={"SCRIPT_NAME": "/exp-survey"}).get_data(as_text=True)
        self.assertIn("/exp-survey/static/app.js?v=", html)
        self.assertNotIn('app.js"', html)   # 不能再有无版本号的引用
        js = self.client.get(f"/static/app.js?v={ASSET_VERSION}")
        self.assertEqual(js.headers["Cache-Control"], "public, max-age=604800")
        js.close()   # 释放静态文件句柄，避免 ResourceWarning 噪音


class ExportTests(unittest.TestCase):
    """全量导出：一个项目一个 xlsx，每个小班一张 sheet（C18）。"""

    def setUp(self):
        parsed = parse_workbook(SAMPLE)
        self.schema = parsed["schema"]
        self.subs = [{
            "source_row": 1,
            "fields": {"number": "XP-01", "village": "弥勒村", "area": 220.72,
                       "composition": "9云南松1其他阔叶", "canopy": 0.8,
                       "avg_dbh": 17.2, "avg_height": 10, "cut_method": "生长伐"},
            "species": [{"name": "云南松", "coefficient": 9.0},
                        {"name": "其他阔叶", "coefficient": 1.0}],
            "plot_no": "1",
            "survey": {"trees": {"云南松": {"6": {"height": 8, "count": 2}},
                                 "其他阔叶": {"6": {"height": 8, "count": 2}}},
                       "cut": {"6": 2}},
            "track": [{"lat": 24.1, "lng": 102.1}, {"lat": 24.2, "lng": 102.2}],
            "photo_count": 3,
        }, {
            "source_row": 2,
            "fields": {"number": "XP-01"},      # 重名小班 + 同样地号 → sheet 名必须去重
            "species": [{"name": "云南松", "coefficient": 10.0}],
            "plot_no": "1",
            "survey": {}, "track": [], "photo_count": 0,
        }]

    def test_one_sheet_per_plot_with_readable_numbers(self):
        buffer, count = build_project_workbook("设计总表.xlsx", self.schema, self.subs)
        self.assertEqual(count, 2)
        wb = load_workbook(buffer)
        self.assertEqual(wb.sheetnames, ["XP-01-1", "XP-01-1(2)"])
        ws = wb["XP-01-1"]
        values = [cell for row in ws.iter_rows(values_only=True) for cell in row if cell is not None]
        self.assertIn("小班号", values)
        self.assertIn("弥勒村", values)
        # 明细行：6 径阶 2 株 × 2 树种
        self.assertEqual(values.count("云南松"), 1)
        # 汇总：样地 4 株、蓄积 0.05（与 App 同一套口径）
        self.assertIn(4, values)
        self.assertIn(0.05, values)
        self.assertIn(3, values)          # 照片数
        self.assertIn(2, values)          # 轨迹点数

    def test_plots_are_sorted_by_natural_order(self):
        """sheet 顺序按已填的小班号 → 样地号自然序：XP-2 在 XP-10 前，样地 2 在样地 10 前。"""
        subs = []
        for number, plot_no in (("XP-10", "1"), ("XP-2", "10"), ("XP-2", "2")):
            subs.append({
                "source_row": len(subs) + 1,
                "fields": {"number": number},
                "species": [{"name": "云南松", "coefficient": 10.0}],
                "plot_no": plot_no,
                "survey": {}, "track": [], "photo_count": 0,
            })
        buffer, count = build_project_workbook("设计总表.xlsx", self.schema, subs)
        self.assertEqual(count, 3)
        self.assertEqual(load_workbook(buffer).sheetnames, ["XP-2-2", "XP-2-10", "XP-10-1"])

    def test_two_plots_of_one_subcompartment_get_two_sheets(self):
        """同一个小班两块样地 = 两张 sheet，各写各的样地号与数据。"""
        base = dict(self.subs[0])
        second = dict(base)
        second["plot_no"] = "2"
        second["survey"] = {"trees": {"云南松": {"6": {"height": 9, "count": 5}}}, "cut": {}}
        second["track"] = []
        buffer, count = build_project_workbook("设计总表.xlsx", self.schema, [base, second])
        self.assertEqual(count, 2)
        wb = load_workbook(buffer)
        self.assertEqual(wb.sheetnames, ["XP-01-1", "XP-01-2"])
        values = [cell for row in wb["XP-01-2"].iter_rows(values_only=True) for cell in row if cell is not None]
        self.assertIn("2", values)
        self.assertIn(5, values)        # 第二块样地 5 株，不串第一块的 4 株

    def test_unsurveyed_plot_is_explicit(self):
        buffer, _ = build_project_workbook("设计总表.xlsx", self.schema, self.subs)
        ws = load_workbook(buffer)["XP-01-1(2)"]
        texts = [cell for row in ws.iter_rows(values_only=True) for cell in row if isinstance(cell, str)]
        self.assertIn("本样地尚未录入调查数据", texts)


class ExifTests(unittest.TestCase):
    """前端 EXIF 纯逻辑（static/photo_exif.js）用 node 直跑，Python 侧只做看门。"""

    @unittest.skipUnless(shutil.which("node"), "需要 node 才能跑 EXIF 用例")
    def test_photo_exif_roundtrip(self):
        script = ROOT / "tests" / "test_exif.js"
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         (result.stdout or "")[-1000:] + (result.stderr or "")[-500:])


if __name__ == "__main__":
    unittest.main()
