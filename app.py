import io
import json
import math
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import (
    Blueprint, Flask, Response, g, jsonify, render_template, request,
    send_file,
)
from werkzeug.exceptions import RequestEntityTooLarge

# ── gateway 共存：依赖模块命名空间隔离 ──────────────────────
# gateway 用 importlib 按绝对路径加载各 app，纯裸 `import auth` 会注册到公共
# sys.modules["auth"]，与 forest-data 的同名模块冲突（它要 init_auth 等接口）。
# 这里把本 app 的 4 个本地依赖以唯一前缀注册，避免污染公共命名空间。
import sys as _sys
import importlib.util as _ilu
_LOCAL_DIR = Path(__file__).resolve().parent
_PREFIX = "expsurvey_"

def _local_module(_name):
    _full = _PREFIX + _name
    if _full not in _sys.modules:
        _spec = _ilu.spec_from_file_location(_full, str(_LOCAL_DIR / f"{_name}.py"))
        _mod = _ilu.module_from_spec(_spec)
        _sys.modules[_full] = _mod
        _spec.loader.exec_module(_mod)
    return _sys.modules[_full]

auth = _local_module("auth")
_calc = _local_module("calculations")
_pp = _local_module("param_parser")
_workbook = _local_module("workbook")
_export = _local_module("export_xlsx")
calculate_summary = _calc.calculate_summary
haversine_distance = _calc.haversine_distance
default_params = _pp.default_params
public_params = _pp.public_params
WorkbookError = _workbook.WorkbookError
parse_workbook = _workbook.parse_workbook
build_project_workbook = _export.build_project_workbook

# gateway 约定：create_app(prefix='/exp-survey')，DispatcherMiddleware 已剥前缀并设 SCRIPT_NAME，
# 所以路由**不挂** url_prefix（否则双重前缀 404）；prefix 只用于页面 base 与 cookie 限定。

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    uploader TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS subcompartments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_row INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    species_json TEXT NOT NULL,
    survey_json TEXT NOT NULL DEFAULT '{}',
    track_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(project_id, source_row)
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subcompartment_id INTEGER NOT NULL REFERENCES subcompartments(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_size INTEGER NOT NULL,
    compressed_size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

MIGRATIONS = (
    ("projects", "uploader", "TEXT NOT NULL DEFAULT ''"),
    ("projects", "params_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("projects", "is_active", "INTEGER NOT NULL DEFAULT 1"),
)

# 静态资源版本：每次发版递增，模板把它拼到 ?v= 上。
# 原因：Capacitor WebView 会把 app.js 缓存到本地，HTML 改了但 JS 还是旧的 →
# 旧页面继续 POST 已删除的 /api/login，拿到 404 HTML 就报 "is not valid JSON"。
ASSET_VERSION = "v1.3.0"


def parse_blob(filename, blob):
    """内存解析：dry 预览不落盘、不产生垃圾文件。"""
    suffix = Path(filename).suffix.lower()
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(blob)
        handle.close()
        return parse_workbook(Path(handle.name))
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


class _EmptyPathFix:
    """网关剥前缀后 PATH_INFO 可能为空串（GET /exp-survey），werkzeug 会 308 补斜杠，
    Location 用 environ 的明文 scheme 拼成 http://… → Android WebView ERR_CLEARTEXT_NOT_PERMITTED。
    空路径归一为 /，直接命中首页（supervision 同款修复）。"""

    def __init__(self, app):
        self.app = app

    def __getattr__(self, name):
        return getattr(self.app, name)

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO", "") == "":
            environ["PATH_INFO"] = "/"
        return self.app(environ, start_response)


def create_app(prefix="", test_config=None):
    """Flask 工厂。gateway 调 create_app(prefix=apps spec['prefix'])；本地 prefix=''。"""
    app = Flask(__name__)
    bp = Blueprint("exp", __name__)
    instance = Path(app.instance_path)
    # 统一账号：secret_key 与 forest_web.db 都复用 forest-data，同域共享 session cookie
    forest_secret, forest_db = auth.forest_settings(instance)
    app.config.from_mapping(
        DATABASE=str(instance / "survey.sqlite3"),
        UPLOAD_DIR=str(instance / "uploads"),
        PHOTO_DIR=str(instance / "photos"),
        BACKUP_DIR=str(instance / "backups"),
        MAX_CONTENT_LENGTH=36 * 1024 * 1024,
        SECRET_KEY=forest_secret,
        FOREST_DB=forest_db,
        LOCAL_DEV_USER=os.environ.get("EXP_LOCAL_USER", ""),
        # 只读 forest-data 的登录态：cookie 必须落在根路径，并且不允许本应用续期/改写
        # session（否则会写出 Path=/exp-survey 的同名 cookie，遮蔽 forest-data 那条）
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_PATH="/",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=30 * 24 * 3600,
    )
    if test_config:
        app.config.update(test_config)
    if prefix:
        # 只限定 https；刻意不设 APPLICATION_ROOT —— 它会让 Flask 把 session cookie
        # 写到 Path=/exp-survey，与 forest-data 的 Path=/ 同名遮蔽（hqz-survey H9）
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PREFERRED_URL_SCHEME"] = "https"
    if not forest_db:
        app.logger.warning(
            "未找到 forest-data 的 forest_web.db；登录态无法校验（本地可用 EXP_LOCAL_USER 免登录）"
        )
    for key in ("UPLOAD_DIR", "PHOTO_DIR", "BACKUP_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()
        db.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        db.commit()

    with app.app_context():
        init_db()

    # ── 序列化 ────────────────────────────────────────────────
    def params_of(row):
        try:
            stored = json.loads(row["params_json"] or "{}")
        except (TypeError, ValueError):
            stored = {}
        return public_params({**default_params(), **stored})

    def project_json(row):
        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM subcompartments WHERE project_id = ?", (row["id"],)
        ).fetchone()[0]
        photos = db.execute(
            "SELECT COUNT(*) FROM subcompartments s JOIN photos p"
            " ON p.subcompartment_id = s.id WHERE s.project_id = ?", (row["id"],)
        ).fetchone()[0]
        return {
            "id": row["id"],
            "filename": row["filename"],
            "uploaded_at": row["uploaded_at"],
            "uploader": row["uploader"] or "",
            "subcompartment_count": count,
            "photo_count": photos,
            "params": params_of(row),
        }

    def sub_summary(row):
        survey = json.loads(row["survey_json"])
        has_survey = bool(survey.get("plot_no")) or any(
            values.get("count") or values.get("height")
            for species in survey.get("trees", {}).values()
            for values in species.values()
        )
        return {
            "id": row["id"],
            "source_row": row["source_row"],
            "fields": json.loads(row["fields_json"]),
            "species": json.loads(row["species_json"]),
            "has_survey": has_survey,
        }

    def get_subcompartment(sub_id):
        row = get_db().execute("""
            SELECT s.*, p.filename AS project_filename, p.schema_json, p.params_json
            FROM subcompartments s JOIN projects p ON p.id = s.project_id
            WHERE s.id = ?
        """, (sub_id,)).fetchone()
        if row is None:
            raise WorkbookError("小班不存在")
        return row

    def sub_detail(row):
        schema = json.loads(row["schema_json"])
        survey = json.loads(row["survey_json"])
        species = json.loads(row["species_json"])
        photos = get_db().execute(
            "SELECT * FROM photos WHERE subcompartment_id = ? ORDER BY id DESC", (row["id"],)
        ).fetchall()
        track = json.loads(row["track_json"])
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_filename": row["project_filename"],
            "source_row": row["source_row"],
            "data": json.loads(row["data_json"]),
            "fields": json.loads(row["fields_json"]),
            "species": species,
            "schema": schema,
            "params": params_of(row),
            "survey": survey,
            "summary": calculate_summary(survey, schema, [item["name"] for item in species]),
            "track": track,
            "track_distance": haversine_distance(track),
            "photos": [{
                "id": photo["id"],
                "url": f"photos/{photo['id']}",
                "original_size": photo["original_size"],
                "compressed_size": photo["compressed_size"],
                "created_at": photo["created_at"],
            } for photo in photos],
        }

    # ── 页面 ──────────────────────────────────────────────────
    @bp.get("/")
    @auth.login_required
    def index():
        return render_template("index.html", base=prefix, asset_version=ASSET_VERSION)

    @bp.get("/admin/")
    @auth.admin_required
    def admin_page():
        user = auth.current_user()
        return render_template("admin.html", base=prefix, user=user["username"],
                               is_admin=auth.is_admin(user), asset_version=ASSET_VERSION)

    # ── 认证（登录/改密都在 forest-data，这里只读登录态）──────
    @bp.get("/api/me")
    def api_me():
        user = auth.current_user()
        if user is None:
            return jsonify(user=None, login_url=auth.login_url())
        return jsonify(user=user["username"], display_name=user["display_name"],
                       role=user["role"], is_admin=bool(user["is_admin"]),
                       login_url=auth.login_url(), logout_url=auth.logout_url())

    @bp.post("/api/logout")
    def api_logout():
        # 不碰 session：清 cookie 由 forest-data 的 /forest/logout 统一做，
        # 本应用只回地址，避免写出 Path=/exp-survey 的同名 cookie
        return jsonify(ok=True, logout_url=auth.logout_url())

    @bp.post("/api/login")
    def api_login_gone():
        """v1.1 的登录接口已下线。

        旧 WebView 缓存里的 app.js 仍会打这里；以前没人接，返回 404 HTML，
        前端 response.json() 抛 "Unexpected token '<' … is not valid JSON"，
        用户只看到一句"不是有效 JSON"。这里给一份可读的 JSON，把跳转地址也带上。
        """
        return jsonify(
            error="登录已统一到森林门户，请重开应用或点「去登录」",
            login_url=auth.login_url(),
        ), 410

    @bp.get("/admin/api/users")
    @bp.post("/admin/api/users")
    def admin_users_gone():
        return jsonify(error="账号已统一到森林门户，请在门户后台管理"), 410

    @bp.post("/admin/api/users/<path:username>/password")
    def admin_reset_password_gone(username):
        return jsonify(error="账号已统一到森林门户，请在门户后台改密"), 410


    # ── App 接口 ──────────────────────────────────────────────
    @bp.get("/api/projects")
    @auth.login_required
    def projects():
        rows = get_db().execute(
            "SELECT * FROM projects WHERE COALESCE(is_active, 1)=1 ORDER BY uploaded_at DESC"
        ).fetchall()
        return jsonify({"projects": [project_json(row) for row in rows]})

    @bp.post("/api/projects")
    @auth.login_required
    def upload_gone():
        return jsonify(error="上传已迁移到管理员后台 /admin/，请让管理员操作"), 403

    @bp.get("/api/projects/<project_id>")
    @auth.login_required
    def project_detail(project_id):
        project = get_db().execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise WorkbookError("项目不存在")
        rows = get_db().execute(
            "SELECT * FROM subcompartments WHERE project_id = ? ORDER BY source_row", (project_id,)
        ).fetchall()
        result = project_json(project)
        result["subcompartments"] = [sub_summary(row) for row in rows]
        return jsonify(result)

    @bp.get("/api/projects/<project_id>/export.xlsx")
    @auth.login_required
    def project_export(project_id):
        """全部小班 → 一个 xlsx，每个小班一张 sheet（C18）。"""
        db = get_db()
        project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise WorkbookError("项目不存在")
        rows = db.execute(
            "SELECT * FROM subcompartments WHERE project_id = ? ORDER BY source_row", (project_id,)
        ).fetchall()
        counts = dict(db.execute(
            "SELECT s.id, COUNT(p.id) FROM subcompartments s"
            " JOIN photos p ON p.subcompartment_id = s.id"
            " WHERE s.project_id = ? GROUP BY s.id", (project_id,)
        ).fetchall())
        subs = [{
            "source_row": row["source_row"],
            "fields": json.loads(row["fields_json"]),
            "species": json.loads(row["species_json"]),
            "survey": json.loads(row["survey_json"]),
            "track": json.loads(row["track_json"]),
            "photo_count": counts.get(row["id"], 0),
        } for row in rows]
        buffer, sheet_count = build_project_workbook(
            project["filename"], json.loads(project["schema_json"]), subs)
        stem = Path(project["filename"]).stem or "样地"
        name = f"{stem}_样地明细_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        app.logger.info("导出项目 %s：%s 张 sheet", project_id, sheet_count)
        return send_file(
            buffer, as_attachment=True, download_name=name,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.get("/api/subcompartments/<int:sub_id>")
    @auth.login_required
    def subcompartment_detail(sub_id):
        return jsonify(sub_detail(get_subcompartment(sub_id)))

    def numeric(value, label, integer=False):
        if value is None or value == "":
            return 0 if integer else None
        if isinstance(value, bool):
            raise WorkbookError(f"{label}必须是数字")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise WorkbookError(f"{label}必须是数字") from exc
        if not math.isfinite(result) or result < 0 or result > 1000000:
            raise WorkbookError(f"{label}必须在 0 到 1000000 之间")
        if integer:
            if not result.is_integer():
                raise WorkbookError(f"{label}必须是整数")
            return int(result)
        return result

    @bp.put("/api/subcompartments/<int:sub_id>/survey")
    @auth.login_required
    def save_survey(sub_id):
        row = get_subcompartment(sub_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise WorkbookError("调查数据格式不正确")
        schema = json.loads(row["schema_json"])
        visible = [item["name"] for item in json.loads(row["species_json"])]
        raw_trees = payload.get("trees", {})
        raw_cut = payload.get("cut", {})
        if not isinstance(raw_trees, dict) or not isinstance(raw_cut, dict):
            raise WorkbookError("调查数据格式不正确")
        if set(raw_trees) - set(visible):
            raise WorkbookError("调查数据包含不属于该小班树种组成的树种")
        diameters = {str(value) for value in schema["diameters"]}
        trees = {}
        for name in visible:
            source = raw_trees.get(name, {})
            if not isinstance(source, dict) or set(source) - diameters:
                raise WorkbookError(f"{name} 的胸径项不在固定范围内")
            trees[name] = {}
            for dbh in diameters:
                values = source.get(dbh, {})
                if not isinstance(values, dict):
                    raise WorkbookError(f"{name} {dbh}cm 数据格式不正确")
                trees[name][dbh] = {
                    "height": numeric(values.get("height"), f"{name} {dbh}cm 树高"),
                    "count": numeric(values.get("count"), f"{name} {dbh}cm 株数", integer=True),
                }
        if set(raw_cut) - diameters:
            raise WorkbookError("采伐株数包含固定范围外的胸径项")
        cut = {dbh: numeric(raw_cut.get(dbh), f"采伐 {dbh}cm 株数", integer=True) for dbh in diameters}
        survey = {"plot_no": str(payload.get("plot_no", "")).strip()[:50], "trees": trees, "cut": cut}
        summary = calculate_summary(survey, schema, visible)
        db = get_db()
        with db:
            db.execute(
                "UPDATE subcompartments SET survey_json = ? WHERE id = ?",
                (json.dumps(survey, ensure_ascii=False), sub_id),
            )
        return jsonify({"survey": survey, "summary": summary})

    @bp.post("/api/subcompartments/<int:sub_id>/photos")
    @auth.login_required
    def upload_photo(sub_id):
        get_subcompartment(sub_id)
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise WorkbookError("请选择照片")
        content = upload.read()
        if not content.startswith(b"\xff\xd8\xff"):
            raise WorkbookError("请上传压缩后的 JPEG 照片")
        if len(content) > 12 * 1024 * 1024:
            raise WorkbookError("压缩后照片不能超过 12MB")
        try:
            original_size = max(0, int(request.form.get("original_size", len(content))))
        except ValueError as exc:
            raise WorkbookError("原始照片大小不正确") from exc
        filename = f"{uuid.uuid4().hex}.jpg"
        path = Path(app.config["PHOTO_DIR"]) / filename
        path.write_bytes(content)
        db = get_db()
        with db:
            cursor = db.execute(
                "INSERT INTO photos (subcompartment_id, filename, original_size, compressed_size, created_at) VALUES (?, ?, ?, ?, ?)",
                (sub_id, filename, original_size, len(content), datetime.now(timezone.utc).isoformat()),
            )
        return jsonify({
            "photo": {
                "id": cursor.lastrowid,
                "url": f"photos/{cursor.lastrowid}",
                "original_size": original_size,
                "compressed_size": len(content),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }), 201

    @bp.get("/photos/<int:photo_id>")
    @auth.login_required
    def photo_file(photo_id):
        photo = get_db().execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if photo is None:
            raise WorkbookError("照片不存在")
        return send_file(Path(app.config["PHOTO_DIR"]) / photo["filename"], mimetype="image/jpeg")

    @bp.put("/api/subcompartments/<int:sub_id>/track")
    @auth.login_required
    def save_track(sub_id):
        row = get_subcompartment(sub_id)
        if not params_of(row)["has_track"]:
            raise WorkbookError("该项目已在「程序参数」中关闭轨迹功能")
        payload = request.get_json(silent=True)
        points = payload.get("points") if isinstance(payload, dict) else None
        if not isinstance(points, list) or len(points) > 20000:
            raise WorkbookError("轨迹点格式不正确或超过 20000 点")
        cleaned = []
        for index, point in enumerate(points, start=1):
            if not isinstance(point, dict):
                raise WorkbookError(f"第 {index} 个轨迹点格式不正确")
            try:
                lat, lng = float(point["lat"]), float(point["lng"])
                timestamp = float(point["timestamp"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkbookError(f"第 {index} 个轨迹点缺少有效坐标或时间") from exc
            if not (-90 <= lat <= 90 and -180 <= lng <= 180) or not math.isfinite(timestamp):
                raise WorkbookError(f"第 {index} 个轨迹点坐标或时间超出范围")
            cleaned.append({
                "lat": lat,
                "lng": lng,
                "timestamp": timestamp,
                "accuracy": numeric(point.get("accuracy"), f"第 {index} 个轨迹点精度"),
            })
        db = get_db()
        with db:
            db.execute(
                "UPDATE subcompartments SET track_json = ? WHERE id = ?",
                (json.dumps(cleaned), sub_id),
            )
        return jsonify({"points": cleaned, "distance": haversine_distance(cleaned)})

    @bp.get("/api/subcompartments/<int:sub_id>/track.gpx")
    @auth.login_required
    def export_track(sub_id):
        row = get_subcompartment(sub_id)
        points = json.loads(row["track_json"])
        if not points:
            raise WorkbookError("暂无轨迹可导出")
        gpx = Element("gpx", {
            "version": "1.1", "creator": "中幼林抚育调查",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        })
        trk = SubElement(gpx, "trk")
        number = json.loads(row["fields_json"]).get("number", str(sub_id))
        SubElement(trk, "name").text = f"轨迹_{number}"
        segment = SubElement(trk, "trkseg")
        for point in points:
            node = SubElement(segment, "trkpt", {"lat": str(point["lat"]), "lon": str(point["lng"])})
            taken = datetime.fromtimestamp(point["timestamp"] / 1000, timezone.utc)
            SubElement(node, "time").text = taken.isoformat().replace("+00:00", "Z")
        xml = tostring(gpx, encoding="utf-8", xml_declaration=True)
        return Response(xml, mimetype="application/gpx+xml", headers={
            "Content-Disposition": f"attachment; filename=track_{sub_id}.gpx"
        })

    # ── 管理员后台 ────────────────────────────────────────────
    def parse_upload(upload):
        if upload is None or not upload.filename:
            raise WorkbookError("请选择要上传的 Excel 文件")
        filename = Path(upload.filename).name
        if Path(filename).suffix.lower() not in (".xlsx", ".xlsm"):
            raise WorkbookError("仅支持 .xlsx 或 .xlsm 文件")
        blob = upload.read()
        if not blob:
            raise WorkbookError("文件为空")
        return filename, blob

    def store_blob(filename, blob):
        ext = Path(filename).suffix.lower()
        stored_name = f"{uuid.uuid4().hex}{ext}"
        path = Path(app.config["UPLOAD_DIR"]) / stored_name
        path.write_bytes(blob)
        return stored_name, path

    def insert_project(filename, stored_name, parsed, uploader):
        project_id = uuid.uuid4().hex
        db = get_db()
        with db:
            db.execute(
                "INSERT INTO projects (id, filename, stored_path, schema_json, uploaded_at,"
                " uploader, params_json, is_active) VALUES (?,?,?,?,?,?,?,1)",
                (project_id, filename, stored_name,
                 json.dumps(parsed["schema"], ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(), uploader,
                 json.dumps(parsed["params"], ensure_ascii=False)),
            )
            db.executemany("""
                INSERT INTO subcompartments
                (project_id, source_row, data_json, fields_json, species_json)
                VALUES (?, ?, ?, ?, ?)
            """, [(
                project_id, record["source_row"], json.dumps(record["data"], ensure_ascii=False),
                json.dumps(record["fields"], ensure_ascii=False),
                json.dumps(record["species"], ensure_ascii=False),
            ) for record in parsed["records"]])
        return project_id

    @bp.get("/admin/api/projects")
    @auth.admin_required
    def admin_projects():
        user = auth.current_user()
        rows = get_db().execute("SELECT * FROM projects ORDER BY uploaded_at DESC").fetchall()
        return jsonify(projects=[{
            **project_json(row),
            "can_overwrite": auth.can_overwrite(user, row["uploader"]),
        } for row in rows])

    @bp.post("/admin/api/projects")
    @auth.admin_required
    def admin_upload():
        filename, blob = parse_upload(request.files.get("file"))
        parsed = parse_blob(filename, blob)
        stored_name, _path = store_blob(filename, blob)
        user = auth.current_user()
        project_id = insert_project(filename, stored_name, parsed, user["username"])
        row = get_db().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return jsonify(ok=True, project=project_json(row)), 201

    def numbers_of(records):
        return [str(record["fields"].get("number") or "").strip() for record in records]

    def merge_preview(project, parsed):
        """按小班号对齐：匹配上的更新基础数据、保留调查/轨迹/照片；新行追加；旧行不删。"""
        numbers = numbers_of(parsed["records"])
        empty = [index + 1 for index, number in enumerate(numbers) if not number]
        if empty:
            raise WorkbookError(f"新 Excel 第 {empty[0]} 条记录小班号为空")
        seen = set()
        duplicates = []
        for number in numbers:
            if number in seen and number not in duplicates:
                duplicates.append(number)
            seen.add(number)
        if duplicates:
            raise WorkbookError(f"新 Excel 小班号重复：{'、'.join(duplicates[:5])}")

        db = get_db()
        old_rows = db.execute(
            "SELECT * FROM subcompartments WHERE project_id=? ORDER BY source_row", (project["id"],)
        ).fetchall()
        old_numbers = {
            str(json.loads(row["fields_json"]).get("number") or "").strip()
            for row in old_rows
        }
        new_set = set(numbers)
        matched = [number for number in numbers if number in old_numbers]
        added = [number for number in numbers if number not in old_numbers]
        kept = [number for number in old_numbers if number not in new_set]
        return {
            "matched": len(matched),
            "added": len(added),
            "kept_old": len(kept),
            "old_total": len(old_rows),
            "new_total": len(numbers),
            "added_numbers": added[:10],
            "kept_numbers": sorted(kept)[:10],
        }

    def apply_merge(project, parsed, filename, stored_name):
        db = get_db()
        old_rows = db.execute(
            "SELECT * FROM subcompartments WHERE project_id=? ORDER BY source_row", (project["id"],)
        ).fetchall()
        old_numbers = {
            str(json.loads(row["fields_json"]).get("number") or "").strip(): row
            for row in old_rows
        }
        next_row = max([row["source_row"] for row in old_rows], default=0)
        with db:
            for record in parsed["records"]:
                number = str(record["fields"].get("number") or "").strip()
                payload = (
                    json.dumps(record["data"], ensure_ascii=False),
                    json.dumps(record["fields"], ensure_ascii=False),
                    json.dumps(record["species"], ensure_ascii=False),
                )
                old = old_numbers.get(number)
                if old is not None:
                    # 就地更新：id 不变 → 照片外键、调查数据、轨迹全部保住
                    db.execute(
                        "UPDATE subcompartments SET data_json=?, fields_json=?, species_json=?"
                        " WHERE id=?", (*payload, old["id"]),
                    )
                else:
                    next_row += 1
                    db.execute(
                        "INSERT INTO subcompartments (project_id, source_row, data_json,"
                        " fields_json, species_json) VALUES (?,?,?,?,?)",
                        (project["id"], next_row, *payload),
                    )
            db.execute(
                "UPDATE projects SET filename=?, stored_path=?, schema_json=?, uploaded_at=?,"
                " params_json=? WHERE id=?",
                (filename, stored_name,
                 json.dumps(parsed["schema"], ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(),
                 json.dumps(parsed["params"], ensure_ascii=False), project["id"]),
            )

    def backup_project(project, rows):
        """写库前留一份快照；不提供自动回滚，文件名回给管理员便于人工核对。"""
        name = f"{project['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        Path(app.config["BACKUP_DIR"], name).write_text(json.dumps({
            "project": {key: project[key] for key in project.keys()},
            "subcompartments": [{key: row[key] for key in row.keys()} for row in rows],
        }, ensure_ascii=False), encoding="utf-8")
        return name

    @bp.post("/admin/api/projects/<project_id>/update")
    @auth.admin_required
    def admin_update(project_id):
        db = get_db()
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise WorkbookError("项目不存在")
        user = auth.current_user()
        if not auth.can_overwrite(user, project["uploader"]):
            return jsonify(error=(
                f"该项目由「{project['uploader'] or '未知'}」上传，"
                "只有上传人本人或管理员可以覆盖"
            )), 403

        filename, blob = parse_upload(request.files.get("file"))
        parsed = parse_blob(filename, blob)
        preview = merge_preview(project, parsed)
        if request.args.get("dry") == "1":
            return jsonify(ok=True, preview=preview)

        confirm = (request.form.get("confirm") or "").strip()
        if confirm != project["filename"]:
            return jsonify(error="确认名称不一致：请照原样输入当前项目文件名"), 400

        stored_name, _path = store_blob(filename, blob)
        old_rows = db.execute(
            "SELECT * FROM subcompartments WHERE project_id=?", (project_id,)
        ).fetchall()
        backup = backup_project(project, old_rows)
        apply_merge(project, parsed, filename, stored_name)

        old_path = Path(app.config["UPLOAD_DIR"]) / (project["stored_path"] or "")
        if old_path.is_file() and old_path.name != stored_name:
            old_path.unlink(missing_ok=True)

        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return jsonify(ok=True, preview=preview, project=project_json(row), backup=backup)

    @bp.get("/admin/api/projects/<project_id>/source")
    @auth.admin_required
    def admin_source(project_id):
        db = get_db()
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise WorkbookError("项目不存在")
        path = Path(app.config["UPLOAD_DIR"]) / (project["stored_path"] or "")
        if not path.is_file():
            raise WorkbookError("源文件已丢失")
        return send_file(path, as_attachment=True, download_name=project["filename"])

    # ── 错误处理 ──────────────────────────────────────────────
    @app.errorhandler(WorkbookError)
    def workbook_error(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify({"error": "上传文件不能超过 36MB"}), 413

    @app.after_request
    def no_cache_html(response):
        # 发版后必须拿新页面；静态资源（带版本查询串）不受影响
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        if (request.path or "").startswith("/static/") and request.args.get("v"):
            # 带 ?v= 的资源内容随版本变，可长缓存：WebView 才不会拿旧 app.js
            response.headers["Cache-Control"] = "public, max-age=604800"
        # 清历史残留：v1.1 及以前把 session cookie 写在 Path=/exp-survey，与 forest-data
        # 的 Path=/ 同名。浏览器"最长路径优先"→ 登出不掉、换账号串号（hqz-survey H9）。
        if prefix:
            response.delete_cookie("session", path=prefix,
                                   secure=True, samesite="Lax")
        return response

    app.register_blueprint(bp)
    return _EmptyPathFix(app)


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
