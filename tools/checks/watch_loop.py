"""无人工位巡检：文件一改就跑闸门，失败立即产出分诊单。

用法:
  bash tools/ai.sh watch                       # 常驻（Ctrl-C 停止）
  bash tools/ai.sh watch --once                # 跑一次就退出（CI / cron 用）
  bash tools/ai.sh watch --out out/            # 带上业务门（勾稽 + 双跑）
  bash tools/ai.sh watch --interval 3 --cycles 2

设计意图:
  ① **事件驱动，不轮询进程状态**：只在文件真正变化时干活，空闲时零开销（1 次/interval 的 stat）。
  ② **不为常驻而常驻**：--once 就是 cron/launchd/pre-push 的同一条路径，避免"本机能跑、CI 不能跑"。
  ③ **失败才叫醒人**：全绿只写一行日志；FAIL 才生成 TRIAGE.md —— 人只在需要判断时被打断。
  ④ **本机无需装 fswatch**：macOS 自带 python3 即可跑；装了 fswatch 也不依赖它（少一个环境变量）。
  ⑤ 巡检产物（日志 / TRIAGE）**不改代码、不重建基线**——只准备证据（C09）。
退出码: --once 模式下与 run.sh 一致（0 全绿 / 1 有 FAIL）；常驻模式 Ctrl-C 返回 0。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WATCH_EXT = {".py", ".sh", ".md", ".json", ".csv", ".toml", ".yaml", ".yml",
             ".js", ".ts", ".html", ".css", ".sql"}
SKIP_DIRS = {".git", "out", "baseline", "node_modules", "__pycache__", ".venv", "venv",
             "dist", "build", ".workbuddy", ".pytest_cache", ".mypy_cache",
             ".idea", ".vscode", "__MACOSX", ".trae-html-share-packages"}
# 自身产物不参与触发，否则「写日志 → 触发 → 再写日志」无限自激
SKIP_FILES = {"doc/brief.md", "doc/review.md", "doc/align.html", ".gate_state",
              "doc/health/last_gates.json", "doc/health/TRIAGE.md",
              "doc/health/last_watch.json"}


def snapshot(root: Path):
    sig = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            if p.suffix.lower() not in WATCH_EXT:
                continue
            rel = p.relative_to(root).as_posix()
            if rel in SKIP_FILES or rel.startswith("doc/health/"):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            sig[rel] = (st.st_mtime_ns, st.st_size)
    return sig


def diff_sig(old, new, limit=8):
    changed = [k for k in new if old.get(k) != new[k]]
    removed = [k for k in old if k not in new]
    items = changed + [f"-{k}" for k in removed]
    head = "、".join(items[:limit])
    if len(items) > limit:
        head += f" 等 {len(items)} 项"
    return items, head


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(root: Path, text: str):
    d = root / "doc/health"
    d.mkdir(parents=True, exist_ok=True)
    log = d / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(text)
    return log


def run_gates(root: Path, py: str, extra):
    cmd = ["bash", str(root / "tools/run.sh"), "--json"] + extra
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    body = (r.stdout or "") + (r.stderr or "")
    append_log(root, f"\n{'=' * 60}\n[{stamp()}] run.sh → rc={r.returncode}\n{body}")
    if r.returncode != 0:
        subprocess.run([py, str(root / "tools/checks/triage.py"), str(root)],
                       cwd=root, capture_output=True, text=True)
    return r.returncode, body


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = Path(argv[1]).resolve()
    py = sys.executable or "python3"
    interval = 5.0
    cycles = 0
    once = False
    extra = []
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--once":
            once = True
        elif a == "--interval" and i + 1 < len(argv):
            interval = float(argv[i + 1]); i += 1
        elif a == "--cycles" and i + 1 < len(argv):
            cycles = int(argv[i + 1]); i += 1
        elif a == "--out" and i + 1 < len(argv):
            extra += ["--out", argv[i + 1]]; i += 1
        elif a == "--data" and i + 1 < len(argv):
            extra += ["--data", argv[i + 1]]; i += 1
        else:
            print(f"未知参数: {a}（看 bash tools/ai.sh -h）")
            return 2
        i += 1

    if once:
        rc, _ = run_gates(root, py, extra)
        print(("巡检: FAIL → 见 doc/health/TRIAGE.md" if rc else "巡检: 全绿") + f"（日志 doc/health/）")
        return rc

    print(f"巡检中：{root} ｜ 间隔 {interval}s ｜ 业务门 {' '.join(extra) or '（仅静态门）'} ｜ Ctrl-C 停止")
    last = snapshot(root)
    print(f"[{stamp()}] 已建立快照（{len(last)} 个文件），等待改动…")
    runs = 0
    try:
        while True:
            time.sleep(interval)
            cur = snapshot(root)
            if cur == last:
                continue
            items, head = diff_sig(last, cur)
            last = cur
            print(f"[{stamp()}] 检测到改动：{head}")
            rc, body = run_gates(root, py, extra)
            runs += 1
            (root / "doc/health").mkdir(parents=True, exist_ok=True)
            (root / "doc/health/last_watch.json").write_text(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "changed": items, "rc": rc, "runs": runs,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            if rc:
                print(f"[{stamp()}] FAIL → doc/health/TRIAGE.md（{len(items)} 个文件改动）")
            else:
                print(f"[{stamp()}] 全绿")
            last = snapshot(root)          # 重新取快照，吞掉本轮自己写的产物
            if cycles and runs >= cycles:
                return 0
    except KeyboardInterrupt:
        print("\n巡检已停止")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
