#!/usr/bin/env bash
# 部署到 gateway（与 hqz-survey / cam / supervision 同一套 appspec 模型）
# - 代码同步：只推运行必需文件，数据目录（instance/）不覆盖
# - appspec 落到 gateway/apps_root：新应用接入 = 一份 appspec，不改 gateway 代码
# - 首页 apps 表登记（幂等）
# - 重启 gateway 会影响所有 app（与同族部署同风险等级）
#
# 首次部署需在服务器安装依赖：
#   INSTALL=1 bash deploy.sh
set -euo pipefail

REMOTE=${REMOTE:-www@forest.bibook.top}
DEST=${DEST:-/home/www/bibook_deploy/apps/exp-survey}
APPSPEC=${APPSPEC:-./deploy/exp-survey.appspec}
GATEWAY=${GATEWAY:-/home/www/bibook_deploy/apps/gateway}
DB=${DB:-/home/www/bibook_deploy/apps/forest-data/web/forest_web.db}

if [ ! -f "$APPSPEC" ]; then
  echo "缺少 appspec：$APPSPEC" >&2
  exit 2
fi

echo "0/5 预检 forest-data 凭证（统一账号靠它，缺一个全员登录失效）"
if ! ssh "$REMOTE" "test -r /home/www/bibook_deploy/apps/forest-data/web/.secret_key && test -r '$DB'"; then
  echo "预检失败：gateway 进程读不到 forest-data 的 .secret_key 或 forest_web.db" >&2
  echo "  期望：/home/www/bibook_deploy/apps/forest-data/web/{.secret_key,forest_web.db} 对 www 可读" >&2
  exit 3
fi

echo "1/5 建目录并同步代码 → $REMOTE:$DEST"
ssh "$REMOTE" "mkdir -p '$DEST/instance' '$GATEWAY/apps_root'"
# 注意：--exclude 用 '/' 锚定，避免误伤同名子目录（supervision 踩坑固化）
rsync -avz --exclude '__pycache__/' --exclude '*.pyc' --exclude '.DS_Store' \
  ./app.py ./auth.py ./workbook.py ./param_parser.py ./calculations.py ./export_xlsx.py \
  ./main.py ./requirements.txt \
  "$REMOTE:$DEST/"
rsync -avz --exclude '__pycache__/' --exclude '.DS_Store' ./templates/ "$REMOTE:$DEST/templates/"
rsync -avz --exclude '__pycache__/' --exclude '.DS_Store' ./static/ "$REMOTE:$DEST/static/"

echo "2/5 同步 appspec → $GATEWAY/apps_root/exp-survey.appspec"
scp -q "$APPSPEC" "$REMOTE:$GATEWAY/apps_root/exp-survey.appspec"

echo "3/5 首页 apps 表登记（幂等）"
ssh "$REMOTE" "sqlite3 '$DB' \"INSERT OR IGNORE INTO apps(code,name,description,base_path,is_active,created_at) \
  VALUES('exp-survey','抚育调查','中幼林抚育样地调查','/exp-survey',1,datetime('now','localtime'))\""

if [ "${INSTALL:-0}" = "1" ]; then
  echo "4/5 安装 Python 依赖"
  ssh "$REMOTE" "cd '$DEST' && python3 -m pip install --user -r requirements.txt"
else
  echo "4/5 跳过依赖安装（首次部署请加 INSTALL=1）"
fi

echo "5/5 优雅重载 gateway 并验证"
# 用 HUP 让 gunicorn 重载 worker：restart 会中断所有同网关 app（既有踩坑记录）
ssh "$REMOTE" "pid=\$(systemctl --user show -p MainPID --value gateway.service); \
  if [ -n \"\$pid\" ] && [ \"\$pid\" != 0 ]; then kill -HUP \"\$pid\"; else systemctl --user restart gateway.service; fi"
sleep 3
code=$(curl -s -o /dev/null -w "%{http_code}" https://forest.bibook.top/exp-survey/)
loc=$(curl -s -o /dev/null -w "%{redirect_url}" https://forest.bibook.top/exp-survey/)
echo "deploy: 已同步；GET /exp-survey/ → $code ${loc:+→ $loc}"
case "$loc" in
  *forest/login*) echo "  登录跳转正常（统一账号）" ;;
  *) echo "  警告：未跳到 /forest/login，检查 secret_key / FOREST_DB" >&2 ;;
esac
