"""新旧输出对比：改动后必跑。用法: python tools/checks/compare.py old_out/ new_out/
文本/CSV 按行对比；Excel 按 sheet!cell 对比（需 openpyxl）。退出码非 0 = 有差异。
入口：bash tools/run.sh --out out/ 会自动调用本脚本（需 baseline/latest 存在）。"""
import sys
from pathlib import Path

TOL = 1e-4  # 数值容差

def load_units(path: Path) -> dict:
    """输出 → {单元位置: 值}。按项目输出格式选实现。"""
    units = {}
    if path.suffix in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.value is not None:
                        units[f"{ws.title}!{c.coordinate}"] = c.value
    else:  # 文本/CSV/md/json 按行
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            units[f"L{i}"] = line
    return units

def diff(a: dict, b: dict) -> list:
    """差异列表: (位置, 旧值, 新值)。区分 缺失/None/类型/数值。"""
    diffs = []
    for key in sorted(set(a) | set(b)):
        va, vb = a.get(key, "<缺失>"), b.get(key, "<缺失>")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if abs(float(va) - float(vb)) > TOL:
                diffs.append((key, va, vb))
        elif va != vb or type(va) is not type(vb):
            diffs.append((key, va, vb))
    return diffs


def collect(dirpath: Path) -> dict:
    """输出目录 → {相对路径: 文件路径}。递归收集，跳过隐藏项与 __pycache__。

    只收集文件：目录本身不参与对比。否则两侧存在同名子目录时，
    load_units 会去 read_text 一个目录而抛 IsADirectoryError（见 CONSTRAINTS C05）。
    """
    files = {}
    for p in sorted(dirpath.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(dirpath)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        files[rel.as_posix()] = p
    return files


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    old_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
    for d in (old_dir, new_dir):
        if not d.is_dir():
            print(f"不是目录: {d}")
            sys.exit(2)
    old_files, new_files = collect(old_dir), collect(new_dir)
    total, all_diffs = 0, []
    for name in sorted(set(old_files) | set(new_files)):
        fo, fn = old_files.get(name), new_files.get(name)
        if fo is None or fn is None:
            all_diffs.append((name, "文件缺失", ""))
            continue
        ua, ub = load_units(fo), load_units(fn)
        total += len(set(ua) | set(ub))
        all_diffs += [(f"{name}:{k}", va, vb) for k, va, vb in diff(ua, ub)]
    rate = 1 - len(all_diffs) / max(total, 1)
    print(f"总单元: {total} | 差异: {len(all_diffs)} | 一致率: {rate:.2%}")
    for d in all_diffs[:50]:
        print(d)
    sys.exit(1 if all_diffs else 0)  # 非 0 退出码 → 可挂 pre-commit/CI
