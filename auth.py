# -*- coding: utf-8 -*-
"""用户、会话与权限（模式对齐 hqz-supervision）。

- users.role：`admin` 才能进 /admin；`user` 只能做调查
- users.is_owner：超管，可覆盖别人上传的项目；普通 admin 只能覆盖自己的
- 首次启动无用户时按环境变量播种一个超管：
    EXP_ADMIN_USER（默认 admin）/ EXP_ADMIN_PASSWORD（默认 admin123）
  生产部署必须显式设置，否则日志里会提示默认密码。
"""

import os
from datetime import datetime
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_owner INTEGER NOT NULL DEFAULT 0,
    pwd_ver INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256")


def password_error(password):
    if not password or len(password) < MIN_PASSWORD:
        return f"密码至少 {MIN_PASSWORD} 位"
    return ""


def ensure_users(db):
    """建表 + 首次播种超管。返回 (用户名, 是否用了默认密码, 是否新建)。"""
    db.executescript(SCHEMA)
    existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing:
        db.commit()
        return None, False, False
    username = (os.environ.get("EXP_ADMIN_USER") or "admin").strip()
    password = os.environ.get("EXP_ADMIN_PASSWORD") or "admin123"
    db.execute(
        "INSERT INTO users(username, password_hash, role, is_owner, created_at)"
        " VALUES(?,?,?,?,?)",
        (username, hash_password(password), "admin", 1,
         datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    db.commit()
    return username, password == "admin123", True


def current_user(db):
    """→ sqlite3.Row 或 None。每次从库里取，保证改密码/改角色立即生效。"""
    username = session.get("user")
    if not username:
        return None
    return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def is_admin(user):
    return bool(user) and user["role"] == "admin"


def login_required(db_getter):
    """接口守卫：未登录返回 JSON 401（页面路由自己判断并跳转）。"""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user(db_getter())
            if user is None:
                return jsonify(error="请先登录"), 401
            return view(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(db_getter):
    """接口守卫：必须 role=admin。"""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user(db_getter())
            if user is None:
                return jsonify(error="请先登录"), 401
            if not is_admin(user):
                return jsonify(error="需要管理员权限"), 403
            return view(*args, **kwargs)

        return wrapper

    return decorator


def can_overwrite(user, uploader):
    """覆盖口径：超管可覆盖任何人；普通 admin 只能覆盖自己上传的项目。"""
    if user is None:
        return False
    if user["is_owner"]:
        return True
    return (uploader or "").strip() == user["username"]


def verify_password(user, password):
    return bool(user) and check_password_hash(user["password_hash"], password or "")
