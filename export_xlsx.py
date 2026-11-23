# -*- coding: utf-8 -*-
"""全量导出：一个项目 → 一个 xlsx，每个小班一张 sheet。

为什么这么切（C18）：
- 外业交回来是「一张小班一张表」的签字习惯，按小班分 sheet 能直接打印归档；
- 所有小班在一个文件里，管理员只需下载一次，不用逐个点。

单元格口径与 App 内完全一致（复用 calculations），不在导出里另算一套：
单株材积 = ROUND(a × D^b × H^c, digits)，每公顷按样地表系数换算。
未调查的小班也要有一张 sheet，写明「尚未录入」，否则会以为是漏导。
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# gateway 共存：与 workbook.py 同一套前缀导入，避免裸 import 污染 sys.modules
import sys as _sys
_calc = _sys.modules.get("expsurvey_calculations")
if _calc is None:
    from calculations import calculate_summary, cutting_volume, diameter_volume
else:
    calculate_summary = _calc.calculate_summary
    cutting_volume = _calc.cutting_volume
    diameter_volume = _calc.diameter_volume

TITLE = "中幼林抚育调查 · 小班调查表"
BAD_SHEET_CHARS = set('[]:*?/\\')
GREEN = "2D5A3D"
LIGHT = "D9EAD3"
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _sheet_name(fields, source_row, used):
    """sheet 名：小班号优先；非法字符去掉，31 字截断，重名加序号。"""
    raw = str(fields.get("number") or "").strip() or f"小班{source_row}"
    clean = "".join("_" if ch in BAD_SHEET_CHARS else ch for ch in raw)[:31].strip() or f"小班{source_row}"
    name = clean
    index = 2
    while name in used:
        suffix = f"({index})"
        name = (clean[: 31 - len(suffix)]) + suffix
        index += 1
    used.add(name)
    return name


def _write_title(ws, filename, span=6):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    cell = ws.cell(row=1, column=1, value=TITLE)
    cell.font = Font(bold=True, size=14, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=GREEN)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
    note = ws.cell(row=2, column=1, value=f"项目文件：{filename}")
    note.font = Font(size=10, color="555555")
    note.alignment = Alignment(horizontal="left")


def _write_pairs(ws, start_row, pairs):
    """label/value 三对一行，返回下一可用行号。"""
    row = start_row
    for index in range(0, len(pairs), 3):
        chunk = pairs[index:index + 3]
        for offset, (label, value) in enumerate(chunk):
            label_cell = ws.cell(row=row, column=offset * 2 + 1, value=label)
            label_cell.font = Font(bold=True, size=10)
            value_cell = ws.cell(row=row, column=offset * 2 + 2, value=value)
            value_cell.alignment = Alignment(horizontal="left")
        row += 1
    return row


def _write_header(ws, row, headers):
    for index, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=index, value=text)
        cell.font = Font(bold=True, size=10)
        cell.fill = PatternFill("solid", fgColor=LIGHT)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
    return row + 1


def _write_row(ws, row, values, decimals=()):
    for index, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=index, value=value)
        cell.border = BORDER
        if index in decimals and isinstance(value, (int, float)):
            cell.number_format = "0." + "0" * decimals[index]
        elif index > 1:
            cell.alignment = Alignment(horizontal="center")
    return row + 1


def _sheet_for(wb, sub, schema, filename, used):
    fields = sub.get("fields") or {}
    species = sub.get("species") or []
    survey = sub.get("survey") or {}
    diameters = schema.get("diameters") or []
    visible = [item["name"] for item in species]
    summary = calculate_summary(survey, schema, visible)
    ws = wb.create_sheet(_sheet_name(fields, sub.get("source_row"), used))

    _write_title(ws, filename)
    row = _write_pairs(ws, 4, [
        ("小班号", fields.get("number") or ""),
        ("村委会", fields.get("village") or ""),
        ("小班面积(亩)", fields.get("area") or ""),
        ("树种组成", fields.get("composition") or ""),
        ("郁闭度", fields.get("canopy") or ""),
        ("平均胸径", fields.get("avg_dbh") or ""),
        ("平均树高", fields.get("avg_height") or ""),
        ("采伐方式", fields.get("cut_method") or ""),
        ("样地号", survey.get("plot_no") or ""),
    ])
    row += 1

    # 调查明细：只写有数据的行，避免每张 sheet 都是 23 个径阶的空表
    trees = survey.get("trees") or {}
    detail_rows = []
    for item in species:
        name = item["name"]
        params = schema["species"].get(name) or {}
        rows = trees.get(name) or {}
        for dbh in diameters:
            values = rows.get(str(dbh)) or {}
            count = int(values.get("count") or 0)
            height = values.get("height")
            if not count and not height:
                continue
            detail_rows.append([
                name, dbh, count, height if height is not None else "",
                diameter_volume(params, dbh, height, 1) if height else "",
                diameter_volume(params, dbh, height, count),
            ])

    row = _write_header(ws, row, ["树种", "径阶(cm)", "株数", "树高(m)", "单株材积(m³)", "蓄积(m³)"])
    if detail_rows:
        for values in detail_rows:
            row = _write_row(ws, row, values, decimals={5: 3, 6: 3})
    else:
        cell = ws.cell(row=row, column=1, value="本小班尚未录入调查数据" if not survey else "已录入，但没有株数/树高")
        cell.font = Font(italic=True, color="888888", size=10)
        row += 1
    row += 1

    # 采伐
    cut = survey.get("cut") or {}
    cut_params = schema.get("cut") or {}
    cut_rows = [[dbh, int(cut.get(str(dbh)) or 0),
                 cutting_volume(cut_params, int(cut.get(str(dbh)) or 0))]
                for dbh in diameters if int(cut.get(str(dbh)) or 0)]
    row = _write_header(ws, row, ["采伐径阶(cm)", "采伐株数", "采伐蓄积(m³)"])
    if cut_rows:
        for values in cut_rows:
            row = _write_row(ws, row, values, decimals={3: 3})
    else:
        ws.cell(row=row, column=1, value="无采伐").font = Font(italic=True, color="888888", size=10)
        row += 1
    row += 1

    # 汇总
    row = _write_header(ws, row, ["汇总项", "数值", "单位"])
    summary_rows = [
        ("样地株数", summary["plot_count"], "株"),
        ("样地蓄积", summary["total_volume"], "m³"),
        ("平均胸径", round(summary["average_dbh"], 2), "cm"),
        ("每公顷株数", summary["per_hectare_count"], "株/hm²"),
        ("每公顷蓄积", summary["per_hectare_volume"], "m³/hm²"),
        ("采伐株数", summary["cut_count"], "株"),
        ("采伐蓄积", summary["cut_volume"], "m³"),
        ("照片", sub.get("photo_count", 0), "张"),
        ("轨迹点", len(sub.get("track") or []), "个"),
    ]
    for label, value, unit in summary_rows:
        row = _write_row(ws, row, [label, value, unit])

    widths = (14, 10, 9, 10, 15, 13)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.sheet_view.showGridLines = False


def build_project_workbook(filename, schema, subs):
    """→ (BytesIO, sheet_count)。subs 每项含 fields/species/survey/track/photo_count/source_row。"""
    wb = Workbook()
    wb.remove(wb.active)          # 只用真实的 sheet，不留下空白的 Sheet
    used = set()
    for sub in subs:
        _sheet_for(wb, sub, schema, filename, used)
    if not subs:
        ws = wb.create_sheet("无小班")
        ws["A1"] = "该项目还没有小班数据"
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer, len(wb.sheetnames)
