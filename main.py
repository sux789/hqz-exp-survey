import argparse
import json
from pathlib import Path

from calculations import calculate_summary
from workbook import parse_workbook


def export_validation(data_path, out_dir):
    data_path = Path(data_path)
    if data_path.is_file():
        paths = [data_path]
    else:
        paths = sorted([*data_path.glob("*.xlsx"), *data_path.glob("*.xlsm")])
    paths = [path for path in paths if not path.name.startswith("~$")]
    if not paths:
        raise SystemExit(f"没有找到 Excel 输入：{data_path}")
    results = []
    for path in paths:
        parsed = parse_workbook(path)
        first = parsed["records"][0]
        visible = [item["name"] for item in first["species"]]
        first_dbh = str(parsed["schema"]["diameters"][0])
        survey = {"plot_no": "校验", "trees": {}, "cut": {first_dbh: 2}}
        for name in visible:
            survey["trees"][name] = {first_dbh: {"height": 8, "count": 2}}
        results.append({
            "filename": path.name,
            "record_count": len(parsed["records"]),
            "first_subcompartment": first["fields"]["number"],
            "diameters": parsed["schema"]["diameters"],
            "area_factor": parsed["schema"]["area_factor"],
            "formula_parameters": parsed["schema"]["species"],
            "cut_parameters": parsed["schema"]["cut"],
            "probe_summary": calculate_summary(survey, parsed["schema"], visible),
        })
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "validation-summary.json"
    output.write_text(json.dumps({"projects": results}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"已校验 {len(results)} 个工作簿，结果：{output}")


def main():
    parser = argparse.ArgumentParser(description="中幼林抚育调查")
    parser.add_argument("--data", help="用于批量校验的 Excel 文件或目录")
    parser.add_argument("--out", help="校验结果输出目录")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if args.data or args.out:
        if not args.data or not args.out:
            parser.error("--data 与 --out 必须同时使用")
        export_validation(args.data, args.out)
        return
    from app import app
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
