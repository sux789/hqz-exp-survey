"""校验调查工作簿：python tools/checks/validate.py data/xxx.xlsx"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPT_DIR]
sys.path.insert(0, str(ROOT))

from workbook import WorkbookError, parse_workbook


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        print("[FATAL] 仅支持 .xlsx 或 .xlsm 文件")
        return 1
    try:
        parsed = parse_workbook(path)
    except WorkbookError as error:
        print(f"[FATAL] {error}")
        return 1
    except Exception as error:
        print(f"[FATAL] 文件 {path.name} 结构校验失败：{error}")
        return 1
    species = sorted({item["name"] for row in parsed["records"] for item in row["species"]})
    print(f"[PASS] {path.name} | {len(parsed['records'])} 个小班 | {len(parsed['schema']['diameters'])} 个固定胸径项")
    print(f"[PASS] 树种公式覆盖：{', '.join(species)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
