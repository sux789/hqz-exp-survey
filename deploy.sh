#!/bin/bash
# 通过 DEST 指定目标；RESTART_CMD 留空则不自动重启。
# 多 worker 部署必须共享同一份 .secret_key，否则 session 互踢。
set -e

DEST="${DEST:-}"
RESTART_CMD="${RESTART_CMD:-}"

if [ -z "$DEST" ]; then
  echo "用法: DEST=user@server:/path/to/app/ bash deploy.sh；如需重启，同时设置 RESTART_CMD。" >&2
  exit 2
fi

rsync -avz \
  --exclude "*.db" \
  --exclude ".secret_key" \
  --exclude "__pycache__/" \
  --exclude ".git/" \
  --exclude ".workbuddy/" \
  --exclude "instance/" \
  --exclude "data/" \
  --exclude "doc/" \
  --exclude "baseline/" \
  --exclude "out/" \
  ./ "$DEST"

if [ -n "$RESTART_CMD" ]; then
  eval "$RESTART_CMD"
fi

echo "部署完成 $(date '+%F %T')"

# 首次部署前安装依赖：python3 -m pip install -r requirements.txt
