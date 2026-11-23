import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Flask, Response, g, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from calculations import calculate_summary, haversine_distance
from workbook import WorkbookError, parse_workbook


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "survey.sqlite3"),
        UPLOAD_DIR=str(Path(app.instance_path) / "uploads"),
        PHOTO_DIR=str(Path(app.instance_path) / "photos"),
        MAX_CONTENT_LENGTH=36 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    for key in ("UPLOAD_DIR", "PHOTO_DIR"):
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
        get_db().executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
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
        """)
        get_db().commit()

    with app.app_context():
        init_db()

    def project_json(row):
        sub_count = get_db().execute(
            "SELECT COUNT(*) FROM subcompartments WHERE project_id = ?", (row["id"],)
        ).fetchone()[0]
        return {
            "id": row["id"],
            "filename": row["filename"],
            "uploaded_at": row["uploaded_at"],
            "subcompartment_count": sub_count,
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
            SELECT s.*, p.filename AS project_filename, p.schema_json
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
            "survey": survey,
            "summary": calculate_summary(survey, schema, [item["name"] for item in species]),
            "track": track,
            "track_distance": haversine_distance(track),
            "photos": [{
                "id": photo["id"],
                "url": f"/photos/{photo['id']}",
                "original_size": photo["original_size"],
                "compressed_size": photo["compressed_size"],
                "created_at": photo["created_at"],
            } for photo in photos],
        }

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/projects")
    def projects():
        rows = get_db().execute("SELECT * FROM projects ORDER BY uploaded_at DESC").fetchall()
        return jsonify({"projects": [project_json(row) for row in rows]})

    @app.post("/api/projects")
    def upload_project():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise WorkbookError("请选择要上传的 Excel 文件")
        filename = Path(upload.filename).name
        if Path(filename).suffix.lower() not in (".xlsx", ".xlsm"):
            raise WorkbookError("仅支持 .xlsx 或 .xlsm 文件")
        stored_name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        stored_path = Path(app.config["UPLOAD_DIR"]) / stored_name
        upload.save(stored_path)
        try:
            parsed = parse_workbook(stored_path)
            project_id = uuid.uuid4().hex
            db = get_db()
            with db:
                db.execute(
                    "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
                    (project_id, filename, stored_name, json.dumps(parsed["schema"], ensure_ascii=False),
                     datetime.now(timezone.utc).isoformat()),
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
        except Exception:
            stored_path.unlink(missing_ok=True)
            raise
        row = get_db().execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return jsonify({"project": project_json(row)}), 201

    @app.get("/api/projects/<project_id>")
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

    @app.get("/api/subcompartments/<int:sub_id>")
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

    @app.put("/api/subcompartments/<int:sub_id>/survey")
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

    @app.post("/api/subcompartments/<int:sub_id>/photos")
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
                "url": f"/photos/{cursor.lastrowid}",
                "original_size": original_size,
                "compressed_size": len(content),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }), 201

    @app.get("/photos/<int:photo_id>")
    def photo_file(photo_id):
        photo = get_db().execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if photo is None:
            raise WorkbookError("照片不存在")
        return send_file(Path(app.config["PHOTO_DIR"]) / photo["filename"], mimetype="image/jpeg")

    @app.put("/api/subcompartments/<int:sub_id>/track")
    def save_track(sub_id):
        get_subcompartment(sub_id)
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

    @app.get("/api/subcompartments/<int:sub_id>/track.gpx")
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

    @app.errorhandler(WorkbookError)
    def workbook_error(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify({"error": "上传文件不能超过 36MB"}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
