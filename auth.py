# -*- coding: utf-8 -*-
"""统一账号：复用 forest-data 的用户体系（共享 secret_key + forest_web.db）。

森林门户 https://forest.bibook.top/forest/login 是唯一的登录入口；本应用不再自建账号。

三条只读原则（hqz-survey / hqz-supervision 踩坑固化，改前必读）：

1. **不写 session**。本应用任何一次 session 写入都会按 SESSION_COOKIE_PATH 落一条同名
   cookie。旧版本写的是 Path=/exp-survey，登出时 forest-data 只清 Path=/ 那条，
   /exp-survey 那条仍在，浏览器"最长路径优先"→ 登出不掉、换账号仍是前一个人
   （hqz-survey 2026-08-24 修复，见其 CONSTRAINTS H9）。所以这里只读不写，并清历史残留。
2. **身份只认 session["user_id"]**，其余字段每次现查库：改角色、停用、账号过期立即生效。
3. **跳转只用 request.script_root**：网关已剥前缀并设 SCRIPT_NAME，硬编码 "/" 会跳回
   gateway 首页（/exp-survey 内所有页面都会丢）。

配置由 create_app 注入（测试可直接覆盖）：
    FOREST_DB          forest_web.db 路径
    FOREST_SECRET_KEY  forest-data 的 .secret_key 内容（同域共享 cookie 的前提）
    LOCAL_DEV_USER     非空则本地免登录（等同 admin），仅限本机开发调试
"""

import os
import sqlite3
from datetime import date
from functools import wraps
from pathlib import Path

from flask import current_app, jsonify, redirect, request, session

LOGIN_PATH = "/forest/login"
LOGOUT_PATH = "/forest/logout"

# 服务器与本地开发的查找顺序；环境变量优先级最高
_SECRET_CANDIDATES = (
    "/home/www/bibook_deploy/apps/forest-data/web/.secret_key",
    "/Users/sux/Desktop/forest-data/web/.secret_key",
)
_DB_CANDIDATES = (
    "/home/www/bibook_deploy/apps/forest-data/web/forest_web.db",
    "/Users/sux/Desktop/forest-data/web/forest_web.db",
)


def _first_existing(env_key, candidates):
    env = (os.environ.get(env_key) or "").strip()
    if env and Path(env).exists():
        return Path(env)
    for item in candidates:
        path = Path(item)
        if path.exists():
            return path
    return None


def forest_settings(instance_path):
    """→ (secret_key, forest_db_path 或 "")。找不到 secret_key 时退回本实例的文件。

    退回只在本地无 forest-data 的场景成立；线上若走到这条分支，所有登录态都会失效，
    所以 create_app 会把结果写日志，deploy.sh 也会先做预检。
    """
    key_path = _first_existing("EXP_FOREST_SECRET", _SECRET_CANDIDATES)
    if key_path is not None:
        secret = key_path.read_text(encoding="utf-8").strip()
    else:
        secret = os.environ.get("EXP_SECRET_KEY") or ""
        if not secret:
            fallback = Path(instance_path) / ".local_secret_key"
            if fallback.exists():
                secret = fallback.read_text(encoding="utf-8").strip()
            else:
                import uuid
                secret = uuid.uuid4().hex
                fallback.write_text(secret, encoding="utf-8")
    db_path = _first_existing("EXP_FOREST_DB", _DB_CANDIDATES)
    return secret, (str(db_path) if db_path else "")


def _forest_db():
    return (current_app.config.get("FOREST_DB") or "").strip()


def _local_dev_user():
    name = (current_app.config.get("LOCAL_DEV_USER") or "").strip()
    if not name:
        return None
    return {
        "id": 0, "username": name, "display_name": name,
        "is_admin": 1, "role": "admin", "is_owner": True,
    }


def _row_to_user(row):
    """forest_web.db 的 users 行 → 本应用口径。

    role/is_owner 是给旧前端与旧的覆盖口径用的兼容字段：
    forest-data 只有 is_admin，管理员即原「超级管理员」，可覆盖任何人。
    """
    keys = set(row.keys())
    admin = bool(row["is_admin"]) if "is_admin" in keys else False
    username = row["username"]
    return {
        "id": row["id"],
        "username": username,
        "display_name": (row["display_name"] if "display_name" in keys else "") or username,
        "is_admin": 1 if admin else 0,
        "role": "admin" if admin else "user",
        "is_owner": admin,
    }


def current_user():
    """→ dict 或 None。未登录 / 账号停用 / 账号过期 / 用户库不可用，一律 None。"""
    dev = _local_dev_user()
    if dev is not None:
        return dev
    uid = session.get("user_id")
    if not uid:
        return None
    db_path = _forest_db()
    if not db_path:
        current_app.logger.error("FOREST_DB 未配置，无法校验登录态")
        return None
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE id=? AND is_active=1", (uid,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as error:
        current_app.logger.error("读取 forest_web.db 失败：%s", error)
        return None
    if row is None:
        return None
    expires = row["expires_at"] if "expires_at" in set(row.keys()) else None
    if expires and str(expires)[:10] < date.today().isoformat():
        return None
    return _row_to_user(row)


def is_admin(user):
    return bool(user) and bool(user["is_admin"])


def can_overwrite(user, uploader):
    """覆盖口径：管理员可覆盖任何人；普通用户只能覆盖自己上传的项目。"""
    if user is None:
        return False
    if user["is_admin"]:
        return True
    return (uploader or "").strip() == user["username"]


def login_url(next_path=""):
    """→ /forest/login?next=…。next 必须是站内绝对路径（含 SCRIPT_NAME）。"""
    target = next_path or (request.script_root or "") + "/"
    return f"{LOGIN_PATH}?next={target}"


def logout_url():
    return LOGOUT_PATH


def _wants_json():
    """接口统一回 JSON：/api/* 与 /admin/api/*（后者也是 fetch 调用，回 302 会让前端拿到 HTML）。"""
    path = request.path or ""
    return path.startswith("/api/") or path.startswith("/admin/api/")


def _current_path():
    """站内绝对路径（含 SCRIPT_NAME），用作登录后的回跳目标。"""
    return (request.script_root or "") + (request.path or "/")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if _wants_json():
                return jsonify(error="请先登录", login_url=login_url()), 401
            return redirect(login_url(_current_path()))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            if _wants_json():
                return jsonify(error="请先登录", login_url=login_url()), 401
            return redirect(login_url(_current_path()))
        if not user["is_admin"]:
            if _wants_json():
                return jsonify(error="需要管理员权限"), 403
            return redirect((request.script_root or "") + "/")
        return view(*args, **kwargs)

    return wrapper
