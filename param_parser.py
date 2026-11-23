# -*- coding: utf-8 -*-
"""「程序参数」sheet 解析器。

一块 Excel 既能当调查基础数据，也能当行为配置：在第一个 sheet 之外增加一张
「程序参数」sheet（兼容旧名「参数」），用 key|value 描述 App 该显示什么、照片怎么压。

约定（与 hqz-supervision 的参数表同构，便于两份 Excel 互相迁移）：
- 表头固定 6 列：key | value | 类型 | 默认值 | 说明 | 示例
- 多值用半角 ';'；**拒绝全角分隔符**（全角分号会把一个值静默切成两个，是坏数据）
- 未知 key / 非法取值 / 越界数值 → ParamError，消息带 Excel 行号
- 没有这张 sheet → 全部取默认值（v1.3 起默认只拍照、不含轨迹，见 C17）

sheet 名不参与「第一个 sheet 是基础数据」的判定：基础数据永远取第一个 sheet（C12），
若用户把「程序参数」放到了第一位，这里会给出可读的报错而不是让小班解析莫名失败。
"""

from openpyxl.utils import get_column_letter

SHEET_NAMES = ("程序参数", "参数")
HEADER = ("key", "value", "类型", "默认值", "说明", "示例")
FULLWIDTH = {"；": ";", "｜": "|", "，": ","}

FEATURES = ("拍照", "视频", "轨迹", "打卡")
WATERMARKS = ("时间", "坐标", "小班")

# key -> (类型, 可选值或取值区间, 默认值, 说明)
KEYS = {
    "功能": ("列表", FEATURES, "拍照",
             "App 详情页显示哪些工具；默认只拍照，需要轨迹就加上「轨迹」"),
    "压缩最长边": ("数值", (320, 4096), 1440,
                   "照片压缩后最长边像素，仅影响新拍照片"),
    "压缩质量": ("数值", (0.3, 1.0), 0.8,
                 "JPEG 质量 0.3-1.0，越小文件越小"),
    "不显示列": ("列表", None, "",
                 "小班列表要隐藏的列名，必须是基础数据表头"),
    "水印内容": ("列表", WATERMARKS, "时间;坐标;小班",
                 "照片水印逐行内容；去掉「坐标」即不写定位"),
    "轨迹采样间隔": ("数值", (1, 60), 5,
                     "记录轨迹时取点间隔（秒），越大越省电"),
}

DEFAULT_SOURCE = ""


class ParamError(ValueError):
    """程序参数违规；message 已带 Excel 行号。"""


def _text(value):
    return "" if value is None else str(value).strip()


def normalize_name(value):
    return "".join(_text(value).split())


def find_param_sheet(wb):
    """返回参数 sheet；没有则 None。同名多个 → 报错。"""
    found = [ws for ws in wb.worksheets if normalize_name(ws.title) in SHEET_NAMES]
    if len(found) > 1:
        raise ParamError(
            "工作簿里有多张参数表：%s；只允许一张" % "、".join(ws.title for ws in found)
        )
    return found[0] if found else None


def _split(value, row_no, key):
    for bad, good in FULLWIDTH.items():
        if bad in value:
            raise ParamError(
                f"程序参数第{row_no}行 key「{key}」：使用了全角分隔符「{bad}」，"
                f"请改成半角「{good}」"
            )
    return [item.strip() for item in value.split(";") if item.strip()]


def _number(value, row_no, key, low, high, integer):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ParamError(f"程序参数第{row_no}行 key「{key}」：必须是数字，实际 {value!r}") from exc
    if not (low <= result <= high):
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：{result} 超出范围 {low}-{high}"
        )
    if integer:
        if not result.is_integer():
            raise ParamError(f"程序参数第{row_no}行 key「{key}」：必须是整数，实际 {result}")
        return int(result)
    return round(result, 3)


def _list_items(key, value, row_no, headers):
    """列表型 key（功能 / 水印内容 / 不显示列）的取值校验。"""
    items = _split(value, row_no, key)
    if key == "功能":
        unknown = [item for item in items if item not in FEATURES]
        if unknown:
            raise ParamError(
                f"程序参数第{row_no}行「功能」：未知取值 {('、'.join(unknown))}；"
                f"可选 {'、'.join(FEATURES)}"
            )
    elif key == "水印内容":
        unknown = [item for item in items if item not in WATERMARKS]
        if unknown:
            raise ParamError(
                f"程序参数第{row_no}行「水印内容」：未知取值 {('、'.join(unknown))}；"
                f"可选 {'、'.join(WATERMARKS)}"
            )
    elif key == "不显示列":
        unknown = [item for item in items if item not in headers]
        if unknown:
            raise ParamError(
                f"程序参数第{row_no}行「不显示列」：{('、'.join(unknown))} 不在基础数据表头中；"
                f"现有表头：{'、'.join(sorted(headers))}"
            )
    return items


def parse_program_params(wb, base_headers):
    """解析参数表。

    wb: openpyxl Workbook；base_headers: 第一个 sheet 的表头列名（用于校验「不显示列」）。
    返回 dict；无参数表时返回默认值（source_sheet 为空串）。

    分两遍：「功能」先落地，再按「轨迹是否开启」决定「轨迹采样间隔」是否要校验。
    表内说明本来就写着「不开轨迹时该项不生效」，所以不开轨迹时填 0 或其他越界值
    都不该拖垮整份工作簿——历史总表用 0 表示「不要轨迹」，曾导致上传被整份拒绝。
    反过来，**开了轨迹**就必须是合法值，错误在这时才暴露，不会被悄悄吃掉。
    """
    ws = find_param_sheet(wb)
    if ws is None:
        return default_params()

    if ws.max_row < 2:
        raise ParamError("程序参数 sheet 只有表头，没有配置行")

    headers = set(base_headers)
    columns = 6
    header_checked = False
    rows = []
    seen = set()

    for row_no in range(1, ws.max_row + 1):
        cells = [_text(ws.cell(row_no, index).value) for index in range(1, columns + 1)]
        key, value = cells[0], cells[1]

        if not key and not any(cells):
            continue
        if not header_checked:
            if [cells[0].lower(), cells[1].lower()] != ["key", "value"]:
                raise ParamError(
                    f"程序参数第{row_no}行不是标准表头（应为 key|value|类型|默认值|说明|示例），"
                    f"实际 A={key!r} B={value!r}"
                )
            header_checked = True
            continue
        if key == "key":
            continue  # 表头重复行

        if key not in KEYS:
            raise ParamError(
                f"程序参数第{row_no}行：未知 key「{key}」；合法 key：{'、'.join(KEYS)}"
            )
        if key in seen:
            raise ParamError(f"程序参数第{row_no}行：key「{key}」重复配置")
        seen.add(key)
        rows.append((row_no, key, value))

    if not header_checked:
        raise ParamError("程序参数 sheet 未找到 key|value 表头")

    values = {}
    for row_no, key, value in rows:
        if key == "功能":
            values[key] = _list_items(key, value, row_no, headers)
    track_on = "轨迹" in values.get("功能", default_params()["功能"])

    for row_no, key, value in rows:
        if key == "功能":
            continue
        kind, allowed, _default, _desc = KEYS[key]
        if kind == "列表":
            values[key] = _list_items(key, value, row_no, headers)
            continue
        if key == "轨迹采样间隔" and not track_on:
            continue  # 不开轨迹 → 该项不生效，保持默认值，不因 0 之类的值拒收整份工作簿
        low, high = allowed
        values[key] = _number(value, row_no, key, low, high, integer=key != "压缩质量")

    params = default_params()
    params.update(values)
    params["source_sheet"] = ws.title
    return params


def default_params():
    """无参数表时的默认行为：只拍照（不含轨迹），1440px / 0.8。

    v1.3 起默认**不显示轨迹**：外业手机定位耗电且多数小班不需要留轨迹，
    需要时在参数 sheet 的「功能」里加「轨迹」即可，其余默认值不变。
    """
    return {
        "功能": _split(KEYS["功能"][2], 0, "功能"),
        "压缩最长边": KEYS["压缩最长边"][2],
        "压缩质量": KEYS["压缩质量"][2],
        "不显示列": [],
        "水印内容": _split(KEYS["水印内容"][2], 0, "水印内容"),
        "轨迹采样间隔": KEYS["轨迹采样间隔"][2],
        "source_sheet": DEFAULT_SOURCE,
    }


def public_params(params):
    """给前端的稳定结构（不暴露 source_sheet 之类内部字段）。"""
    clean = {key: params[key] for key in KEYS}
    clean["has_track"] = "轨迹" in clean["功能"]
    clean["has_photo"] = "拍照" in clean["功能"] or "视频" in clean["功能"]
    return clean
