import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# gateway 共存：避免裸 import 污染公共 sys.modules["param_parser"]
# （supervision 等同族 app 也用同名模块，谁先占位会让对方 ImportError）
import sys as _sys
_param_parser = _sys.modules.get("expsurvey_param_parser")
if _param_parser is None:
    from param_parser import ParamError, find_param_sheet, parse_program_params
else:
    ParamError = _param_parser.ParamError
    find_param_sheet = _param_parser.find_param_sheet
    parse_program_params = _param_parser.parse_program_params


class WorkbookError(ValueError):
    pass


ALIASES = {
    "section": ["标段"],
    "township": ["乡镇（林场）", "乡镇(林场)", "乡镇", "林场"],
    "village": ["村委会", "村"],
    "number": ["小班号"],
    "area": ["小班面积"],
    "composition": ["树种组成"],
    "canopy": ["郁闭度"],
    "avg_dbh": ["平均胸径"],
    "avg_height": ["平均树高"],
    "tree_count": ["小班株数"],
    "volume": ["小班蓄积"],
    "cut_method": ["采伐方式"],
    "count_intensity": ["株数强度"],
    "volume_intensity": ["蓄积强度"],
    "cut_count": ["采伐株数"],
    "cut_volume": ["采伐蓄积"],
}


def normalize(value):
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).strip()


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def merged_value(ws, row, column):
    cell = ws.cell(row, column)
    if cell.value is not None:
        return cell.value
    for merged in ws.merged_cells.ranges:
        if merged.min_row <= row <= merged.max_row and merged.min_col <= column <= merged.max_col:
            return ws.cell(merged.min_row, merged.min_col).value
    return None


def find_base_headers(ws):
    header_row = None
    for row in range(1, min(ws.max_row, 15) + 1):
        for column in range(1, ws.max_column + 1):
            if normalize(merged_value(ws, row, column)) == "小班号":
                header_row = row
                break
        if header_row:
            break
    if not header_row:
        raise WorkbookError("第一个 sheet 未找到“小班号”表头")

    data_start = header_row + 1
    for merged in ws.merged_cells.ranges:
        if merged.min_row <= header_row <= merged.max_row:
            data_start = max(data_start, merged.max_row + 1)

    headers = []
    for column in range(1, ws.max_column + 1):
        value = normalize(merged_value(ws, header_row, column))
        if value:
            headers.append((column, value))
    names = [name for _, name in headers]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise WorkbookError(f"第一个 sheet 表头重复：{', '.join(duplicates)}")

    fields = {}
    for key, aliases in ALIASES.items():
        for alias in aliases:
            normalized = normalize(alias)
            if normalized in names:
                fields[key] = normalized
                break
    for required in ("number", "composition"):
        if required not in fields:
            raise WorkbookError(f"第一个 sheet 缺少必需字段：{required}")
    return header_row, data_start, headers, fields


def parse_composition(value, row_number):
    text = normalize(value)
    if not text:
        raise WorkbookError(f"第 {row_number} 行：树种组成为空")
    result = []
    position = 0
    pattern = re.compile(r"(\d+(?:\.\d+)?)([^\d]+)")
    for match in pattern.finditer(text):
        if text[position:match.start()]:
            raise WorkbookError(f"第 {row_number} 行：无法解析树种组成 {text!r}")
        name = match.group(2).strip()
        if not name:
            raise WorkbookError(f"第 {row_number} 行：树种组成为空名称")
        result.append({"name": name, "coefficient": float(match.group(1))})
        position = match.end()
    if not result or text[position:]:
        raise WorkbookError(f"第 {row_number} 行：无法解析树种组成 {text!r}")
    return result


def parse_base_rows(ws):
    _, data_start, headers, fields = find_base_headers(ws)
    records = []
    for row_number in range(data_start, ws.max_row + 1):
        values = [ws.cell(row_number, column).value for column, _ in headers]
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        data = {name: json_value(value) for (_, name), value in zip(headers, values)}
        number = data.get(fields["number"])
        if number is None or str(number).strip() == "":
            raise WorkbookError(f"第 {row_number} 行：小班号为空")
        species = parse_composition(data.get(fields["composition"]), row_number)
        field_values = {key: data.get(column) for key, column in fields.items()}
        records.append({
            "source_row": row_number,
            "data": data,
            "fields": field_values,
            "species": species,
        })
    if not records:
        raise WorkbookError("第一个 sheet 没有调查基础数据")
    return records, fields, [name for _, name in headers]


NUMBER = r"(?:\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?|\.\d+)"


def formula_parameters(formula, dbh_coord, height_coord):
    pattern = re.compile(
        rf"^=ROUND\((?P<a>{NUMBER})\*{re.escape(dbh_coord)}\^(?P<b>{NUMBER})\*"
        rf"{re.escape(height_coord)}\^(?P<c>{NUMBER})\*1,(?P<digits>\d+)\)$",
        re.IGNORECASE,
    )
    match = pattern.match(formula.replace(" ", ""))
    if not match:
        return None
    return {
        "a": float(match.group("a")),
        "b": float(match.group("b")),
        "c": float(match.group("c")),
        "digits": int(match.group("digits")),
        "formula": formula,
    }


def parse_plot_schema(wb):
    ws = next((sheet for sheet in wb.worksheets if normalize(sheet.title) == "样地表"), None)
    if ws is None:
        raise WorkbookError("工作簿缺少“样地表”sheet")

    header_row = None
    dbh_column = None
    for row in range(1, min(ws.max_row, 12) + 1):
        for column in range(1, ws.max_column + 1):
            if normalize(ws.cell(row, column).value) == "胸径":
                header_row, dbh_column = row, column
                break
        if header_row:
            break
    if not header_row:
        raise WorkbookError("样地表未找到“胸径”表头")

    diameters = []
    diameter_rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        value = ws.cell(row, dbh_column).value
        if normalize(value) == "小计":
            break
        if isinstance(value, (int, float)) and value > 0:
            diameters.append(int(value) if float(value).is_integer() else float(value))
            diameter_rows.append(row)
    if not diameters:
        raise WorkbookError("样地表未找到固定胸径数值")

    species = {}
    first_row = diameter_rows[0]
    for column in range(1, ws.max_column):
        if normalize(ws.cell(header_row, column).value) != "树高":
            continue
        if normalize(ws.cell(header_row, column + 1).value) != "株数":
            continue
        name = normalize(merged_value(ws, header_row - 1, column))
        height_coord = ws.cell(first_row, column).coordinate
        dbh_coord = ws.cell(first_row, dbh_column).coordinate
        params = None
        for formula_cell in ws[first_row]:
            if isinstance(formula_cell.value, str) and formula_cell.value.startswith("="):
                params = formula_parameters(formula_cell.value, dbh_coord, height_coord)
                if params:
                    break
        if not name or not params:
            raise WorkbookError(f"样地表树种 {name or get_column_letter(column)} 缺少可识别的材积公式")
        species[name] = params

    cut = None
    for column in range(1, ws.max_column):
        if normalize(merged_value(ws, header_row - 1, column)) != "采伐":
            continue
        if normalize(ws.cell(header_row, column).value) != "株数":
            continue
        count_letter = get_column_letter(column)
        for row in diameter_rows:
            formula = ws.cell(row, column + 1).value
            if not isinstance(formula, str):
                continue
            match = re.match(
                rf"^=(?P<a>{NUMBER})\*{count_letter}{row}\^(?P<exponent>{NUMBER})$",
                formula.replace(" ", ""), re.IGNORECASE,
            )
            if match:
                cut = {
                    "a": float(match.group("a")),
                    "exponent": float(match.group("exponent")),
                    "formula": formula,
                }
                break
        if cut:
            break
    if not cut:
        raise WorkbookError("样地表未找到采伐蓄积公式")

    area_factor = 15.0
    for row in ws.iter_rows():
        if any(normalize(cell.value) == "保留公顷蓄积" for cell in row):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    factors = re.findall(rf"\*({NUMBER})(?:$|[^0-9.])", cell.value)
                    if factors:
                        area_factor = float(factors[-1])
    return {
        "diameters": diameters,
        "species": species,
        "cut": cut,
        "area_factor": area_factor,
        "source_sheet": ws.title,
    }


def survey_species(record_species, params):
    """调查页要显示的树种：参数「调查树种」非空就固定用它，否则按树种组成拆分。

    「不按树种组成拆分」的场景（同一小班混交、组成写不准、外业只按四大类点数）由参数兜底，
    而不是改数据：组成原文仍留在 fields.composition，导出/列表照旧可追溯。
    固定树种没有组成系数，coefficient 置 None —— 界面只显示树种名，不给外业看「9云南松」。
    """
    fixed = (params or {}).get("调查树种") or []
    if not fixed:
        return record_species
    return [{"name": name, "coefficient": None} for name in fixed]


def parse_workbook(path):
    path = Path(path)
    try:
        wb = load_workbook(path, data_only=False)
    except Exception as exc:
        raise WorkbookError(f"无法读取 Excel：{exc}") from exc
    if not wb.worksheets:
        raise WorkbookError("工作簿没有 sheet")
    first = wb.worksheets[0]
    if find_param_sheet(wb) is first:
        raise WorkbookError(
            "第一个 sheet 是「程序参数」；第一个 sheet 必须是调查基础数据（C12），"
            "请把程序参数放到后面的 sheet"
        )
    records, fields, headers = parse_base_rows(first)
    schema = parse_plot_schema(wb)
    try:
        params = parse_program_params(wb, headers, species_choices=list(schema["species"]))
    except ParamError as exc:
        raise WorkbookError(str(exc)) from exc
    available = set(schema["species"])
    missing = sorted({item["name"] for row in records for item in row["species"]} - available)
    if missing:
        raise WorkbookError(f"样地表缺少树种公式：{', '.join(missing)}")
    return {"records": records, "fields": fields, "schema": schema, "params": params}
