"""不变量检查：把业务勾稽关系写成断言，每次生成输出后必跑。
用法: python tools/checks/check_invariants.py 输出目录/
入口：bash tools/run.sh --out out/ 会自动调用本脚本。

与 compare.py 分工：
- compare.py 证明「没改坏旧行为」（新旧双跑 diff，重构时用）
- 本脚本证明「输出满足业务勾稽」（如 合计=明细和、A列=B列-C列，改口径时两者都要）

按项目填 CHECKS：每项 = (名称, 函数(ctx) -> (ok: bool, 详情: str))。
退出码：0 全通过 / 1 有违反 / 2 CHECKS 为空（尚未填业务勾稽）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from calculations import round_half_up

TOL = 1e-4  # 数值容差，与 compare.py 一致

class Ctx:
    """惰性加载输出文件 + 常用断言助手。按输出格式扩展。"""
    def __init__(self, out_dir: Path):
        self.dir = out_dir
        self._wb = {}

    def cell(self, file, sheet, coord):
        """读 Excel 单元格值。"""
        from openpyxl import load_workbook
        if file not in self._wb:
            self._wb[file] = load_workbook(self.dir / file, data_only=True)
        return self._wb[file][sheet][coord].value

    def near(self, a, b, tol=TOL):
        """数值近似相等。"""
        try:
            return abs(float(a) - float(b)) <= tol
        except (TypeError, ValueError):
            return False

    def lines(self, file):
        """读文本/Markdown 输出的行（原样，不 strip）。"""
        return (self.dir / file).read_text(encoding="utf-8").splitlines()

    def csv(self, file):
        """读 CSV 输出 → 行列表，每行是字段列表。首行为表头。"""
        import csv as _csv
        with (self.dir / file).open(encoding="utf-8", newline="") as fh:
            return list(_csv.reader(fh))

def _projects(c: Ctx):
    return json.loads((c.dir / "validation-summary.json").read_text(encoding="utf-8"))["projects"]


def _diameters_are_fixed_and_ordered(c: Ctx):
    projects = _projects(c)
    valid = bool(projects) and all(
        project["record_count"] > 0 and project["diameters"] == sorted(set(project["diameters"]))
        and all(value > 0 for value in project["diameters"])
        for project in projects
    )
    return valid, f"{len(projects)} 个工作簿的固定胸径项及记录数"


def _volume_totals_reconcile(c: Ctx):
    details = []
    for project in _projects(c):
        summary = project["probe_summary"]
        species_total = round_half_up(sum(item["volume"] for item in summary["species"].values()), 3)
        if not c.near(summary["total_volume"], species_total):
            return False, f"{project['filename']} 总蓄积不等于树种蓄积和"
        expected_per_ha = round_half_up(species_total * project["area_factor"], 3)
        if not c.near(summary["per_hectare_volume"], expected_per_ha):
            return False, f"{project['filename']} 每公顷蓄积勾稽失败"
        details.append(f"{project['filename']}={species_total}")
    return True, "; ".join(details)


def _formula_probe_matches_source_parameters(c: Ctx):
    for project in _projects(c):
        dbh = project["diameters"][0]
        for name, params in project["formula_parameters"].items():
            if name not in project["probe_summary"]["species"]:
                continue
            unit = round_half_up(params["a"] * dbh ** params["b"] * 8 ** params["c"], params["digits"])
            expected = round_half_up(unit * 2, 3)
            actual = project["probe_summary"]["species"][name]["volume"]
            if not c.near(actual, expected):
                return False, f"{project['filename']} {name}：{actual} ≠ {expected}"
    return True, "样地表 a/b/c 参数、单株材积和株数乘积一致"


CHECKS = [
    ("固定胸径项严格递增且基础数据非空", _diameters_are_fixed_and_ordered),
    ("总蓄积与每公顷蓄积勾稽", _volume_totals_reconcile),
    ("材积公式探针与源表参数一致", _formula_probe_matches_source_parameters),
]
# ────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    if not CHECKS:
        print("CHECKS 为空：先把业务勾稽填进 CHECKS（文件内有示例）")
        sys.exit(2)
    ctx = Ctx(Path(sys.argv[1]))
    fails = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn(ctx)
        except Exception as e:  # 断言本身执行失败也计为违反，带出上下文
            ok, detail = False, f"断言执行异常: {e}"
        print(f"[{'PASS' if ok else 'FAIL'}] {name} | {detail}")
        fails += 0 if ok else 1
    print(f"\n不变量: {len(CHECKS)} 项 | 违反: {fails}")
    sys.exit(1 if fails else 0)
