"""把 run.sh 的七门结果转成唯一机器事实（schema v2）。

用法:
  python tools/checks/emit_json.py <gates.tsv> <项目根> [--print|--out PATH]

契约：七个门各一条；overall = PASS | FAIL | INCOMPLETE。
SKIP/WARN 表示未完整验证，不再被描述成“全绿”。结果包含源码摘要与 Git HEAD，
下游可识别陈旧报告。本脚本只负责序列化，FAIL 是数据，不是序列化失败。
"""
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.project import (GATE_ORDER, atomic_write_text, git_head,  # noqa: E402
                         source_fingerprint)

DEFAULT_OUT = "doc/health/last_gates.json"
SEVERITY = {"PASS": 1, "SKIP": 2, "WARN": 3, "FAIL": 4}


def parse(tsv):
    records = {}
    for line in Path(tsv).read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        gid, name, status, detail = (p.strip() for p in parts[:4])
        if not gid:
            continue
        if gid not in GATE_ORDER or status not in SEVERITY:
            raise ValueError(f"非法门结果: {gid}/{status}")
        item = {"id": gid, "name": name, "status": status, "detail": detail}
        if gid not in records:
            records[gid] = item
        else:
            old = records[gid]
            if SEVERITY[status] >= SEVERITY[old["status"]]:
                item["detail"] = "；".join(x for x in (old["detail"], detail) if x)
                records[gid] = item
    missing = [gid for gid in GATE_ORDER if gid not in records]
    if missing:
        raise ValueError("缺门结果: " + ", ".join(missing))
    return [records[gid] for gid in GATE_ORDER]


def option(argv, name, default=""):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    try:
        tsv, root = Path(argv[1]), Path(argv[2]).resolve()
        gates = parse(tsv)
        counts = {k: sum(1 for g in gates if g["status"] == k)
                  for k in ("PASS", "FAIL", "WARN", "SKIP")}
        overall = ("FAIL" if counts["FAIL"] else
                   "INCOMPLETE" if counts["WARN"] or counts["SKIP"] else "PASS")
        payload = {
            "schema_version": 2,
            "project": root.name,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "run_id": uuid.uuid4().hex,
            "command": os.environ.get("GATE_COMMAND", "bash tools/run.sh --json"),
            "template": (root / ".template").exists(),
            "overall": overall,
            "complete": overall == "PASS",
            "counts": counts,
            "git_head": git_head(root),
            "source_hash": source_fingerprint(root),
            "invocation": {"out": option(argv, "--run-out"),
                           "data": option(argv, "--run-data")},
            "gates": gates,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        if "--print" in argv or "--out" not in argv:
            print(text, end="")
            return 0
        out = Path(option(argv, "--out", DEFAULT_OUT))
        if not out.is_absolute():
            out = root / out
        atomic_write_text(out, text)
        try:
            shown = out.relative_to(root)
        except ValueError:
            shown = out
        print(f"机器可读结果: {shown} ｜ overall={overall}")
        return 0
    except (OSError, ValueError, IndexError) as exc:
        print(f"生成机器结果失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
