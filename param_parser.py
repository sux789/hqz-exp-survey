# -*- coding: utf-8 -*-
"""「程序参数」sheet 解析器。

一块 Excel 既能当调查基础数据，也能当行为配置：在第一个 sheet 之外增加一张
「程序参数」sheet（兼容旧名「参数」），用 key|value 描述 App 该显示什么、照片怎么压、
照片存到手机相册的哪一层、文件名叫什么。

约定（与 hqz-supervision 的参数表同构，便于两份 Excel 互相迁移）：
- 表头固定 6 列：key | value | 类型 | 默认值 | 说明 | 示例
- 多值用半角 ';'；**拒绝全角分隔符**（全角分号会把一个值静默切成两个，是坏数据）
- 未知 key / 非法取值 / 越界数值 / 未知占位符 → ParamError，消息带 Excel 行号
- 没有这张 sheet → 全部取默认值（v1.3 起默认只拍照、不含轨迹，见 C17）

v1.5 起新增四个 key —— 照片不再上传服务器，改为写入手机相册：
- 项目名称（文本）：相册顶层目录、水印、文件名里的项目名，留空由 App 端取 App 名兜底
- 说明（文本）：水印里的一行说明文字，留空不显示
- 目录（模板）：相册子目录 Pictures/{目录}/，默认 `{{项目名称}}/{{小班号}}`
- 相片文件名（模板）：不含扩展名，默认 `{{项目名称}}_{{小班号}}_样地{{样地号}}_{{时间}}`

模板占位符只有五个：{{项目名称}} {{说明}} {{小班号}} {{样地号}} {{时间}}（时间=YYYYMMDD_HHMMSS），
**未知占位符一律报错**——写错的占位符会静默变空，文件名只剩时间戳，事后无法按小班追溯。

sheet 名不参与「第一个 sheet 是基础数据」的判定：基础数据永远取第一个 sheet（C12），
若用户把「程序参数」放到了第一位，这里会给出可读的报错而不是让小班解析莫名失败。
"""

import re

from openpyxl.utils import get_column_letter

SHEET_NAMES = ("程序参数", "参数")
HEADER = ("key", "value", "类型", "默认值", "说明", "示例")
FULLWIDTH = {"；": ";", "｜": "|", "，": ","}

FEATURES = ("拍照", "视频", "轨迹", "打卡")
WATERMARKS = ("项目名称", "小班", "时间", "坐标")
TEMPLATE_VARS = ("项目名称", "说明", "小班号", "样地号", "时间")
TEXT_LIMITS = {"项目名称": 40, "说明": 80}

# key -> (类型, 可选值或取值区间, 默认值, 说明)
KEYS = {
    "功能": ("列表", FEATURES, "拍照",
             "App 详情页显示哪些工具；默认只拍照，需要轨迹就加上「轨迹」"),
    "项目名称": ("文本", None, "",
                 "照片相册顶层目录、水印与文件名里的项目名；留空用 App 名「抚育调查」"),
    "说明": ("文本", None, "",
             "照片水印里的一行说明文字；留空不显示"),
    "目录": ("模板", None, "{{项目名称}}/{{小班号}}",
             "照片在本机相册的子目录：Pictures/{目录}/；用半角 / 分层"),
    "相片文件名": ("模板", None, "{{项目名称}}_{{小班号}}_样地{{样地号}}_{{时间}}",
                   "照片文件名（不含扩展名）；{{时间}}=YYYYMMDD_HHMMSS"),
    "水印内容": ("列表", WATERMARKS, "项目名称;小班;时间;坐标",
                 "照片水印逐行内容；去掉「坐标」即不写定位"),
    "压缩最长边": ("数值", (320, 4096), 1440,
                   "照片压缩后最长边像素，仅影响新拍照片"),
    "压缩质量": ("数值", (0.3, 1.0), 0.8,
                 "JPEG 质量 0.3-1.0，越小文件越小"),
    "不显示列": ("列表", None, "",
                 "小班列表要隐藏的列名，必须是基础数据表头"),
    "调查树种": ("树种", None, "",
                 "调查页固定显示的树种；留空按「树种组成」拆分。多个用空格或顿号隔开"),
    "轨迹采样间隔": ("数值", (1, 60), 5,
                     "记录轨迹时取点间隔（秒），越大越省电"),
}

# 「调查树种」是给外业非技术人员的，分隔符按人怎么写都认：空格、顿号、逗号、分号、斜杠。
# 其余列表型 key 仍走 _split（只认半角分号，全角报错），避免一个宽松口径扩散到全表。
SPECIES_SPLIT = re.compile(r"[\s、,，;；/／|｜]+")

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


def _text_param(key, value, row_no):
    """文本型 key（项目名称 / 说明）：去空白、拒绝控制字符与破坏路径的字符。"""
    text = _text(value)
    if any(ord(ch) < 32 for ch in text):
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：不能包含换行或控制字符"
        )
    limit = TEXT_LIMITS.get(key)
    if limit and len(text) > limit:
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：长度 {len(text)} 超过 {limit} 字"
        )
    if key == "项目名称":
        for bad in ("/", "\\", ".."):
            if bad in text:
                raise ParamError(
                    f"程序参数第{row_no}行 key「项目名称」：不能包含 {bad!r}；"
                    f"分层目录请写在「目录」里"
                )
    return text


def _template_param(key, value, row_no):
    """模板型 key（目录 / 相片文件名）：占位符必须成对且只允许已知变量。

    写错的占位符（如 {{小班}}、{{样地}}）会被静默替换成空串，照片就只剩时间戳，
    事后无法按小班追溯——所以这里按坏数据拒收，并把可用占位符列在消息里。
    """
    text = _text(value)
    if not text:
        raise ParamError(f"程序参数第{row_no}行 key「{key}」：模板不能为空")

    leftover = re.sub(r"\{\{[^{}]*\}\}", "", text)
    if "{" in leftover or "}" in leftover:
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：占位符必须写成 {{{{列名}}}}（双花括号完整配对），"
            f"实际 {text!r}"
        )
    used = [item.strip() for item in re.findall(r"\{\{([^{}]*)\}\}", text)]
    unknown = [item for item in used if item not in TEMPLATE_VARS]
    if unknown:
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：未知占位符 {'、'.join(unknown)}；"
            f"可用 {'、'.join(TEMPLATE_VARS)}"
        )
    if key == "相片文件名" and ("/" in text or "\\" in text):
        raise ParamError(
            f"程序参数第{row_no}行 key「相片文件名」：不能包含 / 或 \\；分层目录请写在「目录」里"
        )
    if key == "目录":
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            raise ParamError(
                f"程序参数第{row_no}行 key「目录」：必须是相册内的相对路径，不能以 / 或盘符开头"
            )
        if any(seg.strip() in (".", "..") for seg in text.split("/")):
            raise ParamError(
                f"程序参数第{row_no}行 key「目录」：不允许 . 或 .. 路径段"
            )
    return text


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


def _species_items(key, value, row_no, choices=None):
    """「调查树种」取值：允许空格 / 顿号 / 逗号 / 分号 / 斜杠混用，重复与未知树种当场报错。

    为什么这里放宽分隔符而不沿用 _split：写这张表的是外业技术员，不是程序员。
    「云南松 油杉 其他阔叶 栎类」这种空格写法最自然，报「全角分隔符」只会让人放弃配置。
    但**不能放宽到自动纠错**：树种名与样地表对不上时按 C13 原样报错，绝不猜近似名。
    """
    text = _text(value)
    if not text:
        return []  # 留空 = 不固定，回到「按树种组成拆分」
    items = [item for item in SPECIES_SPLIT.split(text) if item]
    seen, duplicated = set(), []
    for item in items:
        if item in seen and item not in duplicated:
            duplicated.append(item)
        seen.add(item)
    if duplicated:
        raise ParamError(
            f"程序参数第{row_no}行 key「{key}」：树种重复 {('、'.join(duplicated))}；每个树种只写一次"
        )
    if choices is not None:
        unknown = [item for item in items if item not in choices]
        if unknown:
            raise ParamError(
                f"程序参数第{row_no}行 key「{key}」：{('、'.join(unknown))} 在样地表里没有材积公式；"
                f"样地表现有树种：{'、'.join(choices)}"
            )
    return items


def parse_program_params(wb, base_headers, species_choices=None):
    """解析参数表。

    wb: openpyxl Workbook；base_headers: 第一个 sheet 的表头列名（用于校验「不显示列」）；
    species_choices: 样地表里带材积公式的树种（用于校验「调查树种」，None 表示不校验）。
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
        if kind == "树种":
            values[key] = _species_items(key, value, row_no, species_choices)
            continue
        if kind == "列表":
            values[key] = _list_items(key, value, row_no, headers)
            continue
        if kind == "文本":
            values[key] = _text_param(key, value, row_no)
            continue
        if kind == "模板":
            values[key] = _template_param(key, value, row_no)
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
    v1.5 起从 KEYS 直接派生，新增 key 不会漏掉默认值（漏掉的 key 会让前端拿到
    undefined，照片目录退化成兜底值）。
    """
    params = {}
    for key, (kind, _allowed, default, _desc) in KEYS.items():
        if kind == "列表":
            params[key] = _split(default, 0, key)
        elif kind == "树种":
            params[key] = [] if not _text(default) else _species_items(key, default, 0)
        else:
            params[key] = default
    params["source_sheet"] = DEFAULT_SOURCE
    return params


def public_params(params):
    """给前端的稳定结构（不暴露 source_sheet 之类内部字段）。"""
    clean = {key: params[key] for key in KEYS}
    clean["has_track"] = "轨迹" in clean["功能"]
    clean["has_photo"] = "拍照" in clean["功能"] or "视频" in clean["功能"]
    return clean
