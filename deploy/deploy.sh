#!/usr/bin/env bash
#
# 软考刷题 · 应用侧一键部署（Debian / Ubuntu）
#
# 用法：
#   sudo ./deploy/deploy.sh                  # 首次完整部署
#   sudo ./deploy/deploy.sh --user 小明       # 首次部署并顺便建一个账号
#   sudo ./deploy/deploy.sh update           # 日常更新（复制文件 + 重启，保留数据）
#   sudo ./deploy/deploy.sh update --pull    # 先 git pull 再更新（线上更新题库用）
#   sudo ./deploy/deploy.sh user 小明         # 新建/重置账号，打印随机密码
#   sudo ./deploy/deploy.sh status           # 看服务状态和最近日志
#
# 前置条件：
#   - Python 3.8+（python3 -V 能输出版本）
#   - 系统使用 systemd
#
# 本脚本只负责「应用侧」：系统用户、复制文件、systemd 服务、自检。
# Nginx 与 HTTPS 证书见 deploy/nginx.conf 与 deploy/README 段落的说明。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ruankao}"
APP_USER="${APP_USER:-ruankao}"
SERVICE_NAME="ruankao"
PORT="${PORT:-8787}"

# 脚本所在目录的上一级 = 项目根目录
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ------------------------------ 参数解析 ------------------------------

MODE="install"
NEW_USER=""
DO_PULL=0

while [ $# -gt 0 ]; do
  case "$1" in
    install|update|status) MODE="$1"; shift ;;
    user) MODE="user"; NEW_USER="${2:-}"; [ -n "$NEW_USER" ] || die "用法：$0 user 名字"; shift 2 ;;
    --user) NEW_USER="${2:-}"; [ -n "$NEW_USER" ] || die "--user 需要名字"; shift 2 ;;
    --pull) DO_PULL=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "未知参数：$1（可用：install / update / user / status / --pull / --user）" ;;
  esac
done

# ------------------------------ 基础检查 ------------------------------

[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo $0"
command -v systemctl >/dev/null 2>&1 || die "未检测到 systemd，本脚本仅适用于使用 systemd 的发行版"

PY_BIN="$(command -v python3 || true)"
[ -n "$PY_BIN" ] || die "未找到 python3，请先安装 Python 3.8+"

PY_VER="$("$PY_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
PY_MAJOR="${PY_VER%%.*}"; PY_MINOR="${PY_VER#*.}"
{ [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 8 ]; } || die "Python 版本过低（当前 $PY_VER），需要 3.8+"

# 家目录下的 python（pyenv 等）在 ProtectHome=true 时服务读不到，换系统路径
PY_REAL="$(readlink -f "$PY_BIN")"
case "$PY_REAL" in
  /home/*|/root/*)
    if [ -x /usr/bin/python3 ]; then
      warn "python3 实际位于 $PY_REAL，服务无法访问家目录，改用 /usr/bin/python3"
      PY_BIN=/usr/bin/python3
    else
      die "python3 位于家目录且没有 /usr/bin/python3 可用，请先安装系统级 Python 3.8+"
    fi
    ;;
esac

log "Python：$PY_BIN（$PY_VER）"
log "源目录：$SRC_DIR"
log "安装到：$APP_DIR"

# ------------------------------ 账号子命令 ------------------------------

if [ "$MODE" = "user" ]; then
  [ -f "$APP_DIR/scripts/add_user.py" ] || die "服务还没部署，先运行：sudo $0 install"
  cd "$APP_DIR"
  sudo -u "$APP_USER" "$PY_BIN" scripts/add_user.py "$NEW_USER"
  exit 0
fi

if [ "$MODE" = "status" ]; then
  systemctl status "$SERVICE_NAME" --no-pager || true
  echo
  echo "---- 最近 30 行日志 ----"
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
  exit 0
fi

# ------------------------------ 源文件检查 ------------------------------

[ -f "$SRC_DIR/server/app.py" ] || die "未找到 $SRC_DIR/server/app.py，请在项目根目录内运行"
[ -f "$SRC_DIR/server/web/index.html" ] || die "缺少 server/web/index.html，请先运行：python3 scripts/build_app.py"
[ -d "$SRC_DIR/banks" ] || die "缺少 banks/ 题库目录"

# update --pull：先在源码目录拉最新
if [ "$DO_PULL" = "1" ]; then
  if [ -d "$SRC_DIR/.git" ]; then
    log "git pull（$SRC_DIR）"
    # root 去 pull 别人的 checkout 时会报 dubious ownership，这里显式放行
    git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" pull --ff-only \
      || die "git pull 失败，检查是否有本地改动或冲突"
  else
    warn "$SRC_DIR 不是 git 仓库，跳过 pull"
  fi
fi

# ------------------------------ 创建用户 ------------------------------

if [ "$MODE" = "install" ]; then
  if id "$APP_USER" >/dev/null 2>&1; then
    log "系统用户 $APP_USER 已存在，跳过创建"
  else
    log "创建系统用户 $APP_USER（无登录权限）"
    useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" "$APP_USER"
  fi
else
  id "$APP_USER" >/dev/null 2>&1 || die "系统用户 $APP_USER 不存在，请先执行：sudo $0 install"
fi

# ------------------------------ 复制文件 ------------------------------

mkdir -p "$APP_DIR/server/web" "$APP_DIR/scripts" "$APP_DIR/data"

if [ "$SRC_DIR" = "$APP_DIR" ]; then
  # 就地部署（直接把仓库 checkout 在 /opt/ruankao）
  log "源目录与目标目录相同，跳过文件复制（就地部署）"
else
  log "复制应用文件"

  # 服务本体 + 共用的题库加载模块
  install -o "$APP_USER" -g "$APP_USER" -m 644 "$SRC_DIR/server/app.py" "$APP_DIR/server/app.py"
  install -o "$APP_USER" -g "$APP_USER" -m 644 "$SRC_DIR/banklib.py" "$APP_DIR/banklib.py"

  # 线上前端（构建产物）
  for f in "$SRC_DIR"/server/web/*; do
    [ -f "$f" ] || continue
    install -o "$APP_USER" -g "$APP_USER" -m 644 "$f" "$APP_DIR/server/web/$(basename "$f")"
  done

  # 题库：整棵树同步，删掉源里已不存在的旧卷
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$SRC_DIR/banks/" "$APP_DIR/banks/"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/banks"
  else
    warn "未找到 rsync，用 cp -a 覆盖（不会删除已移除的旧卷）"
    cp -a "$SRC_DIR/banks/." "$APP_DIR/banks/"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/banks"
  fi

  # 运维脚本（建账号 / 题库发布 / 体检报告）
  for f in "$SRC_DIR"/scripts/*.py; do
    [ -f "$f" ] || continue
    install -o "$APP_USER" -g "$APP_USER" -m 644 "$f" "$APP_DIR/scripts/$(basename "$f")"
  done

  # 部署文件：留一份在目标机器上，方便日后照着重装 Nginx
  mkdir -p "$APP_DIR/deploy"
  for f in "$SRC_DIR"/deploy/*; do
    [ -f "$f" ] || continue
    install -o root -g root -m 644 "$f" "$APP_DIR/deploy/$(basename "$f")"
  done
fi

# data/ 是唯一可写目录：SQLite 库 + 会话密钥
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data"
chmod 700 "$APP_DIR/data"

log "文件已就位："
find "$APP_DIR" -maxdepth 2 -not -path "$APP_DIR/deploy/*" -printf '    %M %u:%g  %p\n' 2>/dev/null | sort || true

# 关键文件校验：缺了服务必然起不来，早点报出来
for f in server/app.py banklib.py server/web/index.html banks; do
  [ -e "$APP_DIR/$f" ] || die "缺少文件：$APP_DIR/$f"
done

# ------------------------------ 安装 systemd ------------------------------

if [ "$MODE" = "install" ]; then
  log "安装 systemd 单元 /etc/systemd/system/${SERVICE_NAME}.service"

  sed -e "s|^User=.*|User=$APP_USER|" \
      -e "s|^Group=.*|Group=$APP_USER|" \
      -e "s|^WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" \
      -e "s|^Environment=PORT=.*|Environment=PORT=$PORT|" \
      -e "s|^Environment=DB_PATH=.*|Environment=DB_PATH=$APP_DIR/data/app.db|" \
      -e "s|^Environment=SECRET_FILE=.*|Environment=SECRET_FILE=$APP_DIR/data/secret.key|" \
      -e "s|^Environment=WEB_DIR=.*|Environment=WEB_DIR=$APP_DIR/server/web|" \
      -e "s|^ExecStart=.*|ExecStart=$PY_BIN $APP_DIR/server/app.py|" \
      -e "s|^ReadWritePaths=.*|ReadWritePaths=$APP_DIR/data|" \
      "$SRC_DIR/deploy/ruankao.service" > "/etc/systemd/system/${SERVICE_NAME}.service"

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME" >/dev/null
else
  log "update 模式：保留现有 systemd 单元，不重新生成"
fi

log "重启服务"
systemctl restart "$SERVICE_NAME"

# ------------------------------ 自检 ------------------------------

for i in 1 2 3 4 5; do
  sleep 1
  systemctl is-active --quiet "$SERVICE_NAME" && break
  [ "$i" = "5" ] && { warn "服务启动失败，最近日志："; journalctl -u "$SERVICE_NAME" -n 40 --no-pager || true; exit 1; }
done
log "服务已启动"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/api/health" | grep -q '"ok"'; then
    log "健康检查通过：/api/health"
  else
    warn "健康检查失败，请查看：journalctl -u $SERVICE_NAME -n 50"
  fi

  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/api/bootstrap" || true)"
  case "$CODE" in
    401) log "鉴权生效：未登录访问 /api/bootstrap 返回 401（符合预期）" ;;
    200) warn "未登录也能拿到题库（$CODE），请检查服务版本" ;;
    *)   warn "/api/bootstrap 返回 $CODE，请自行确认" ;;
  esac

  QCOUNT="$(journalctl -u "$SERVICE_NAME" -n 200 --no-pager 2>/dev/null | sed -n 's/.*questions: \([0-9]*\).*/\1/p' | tail -1 || true)"
  [ -n "$QCOUNT" ] && log "题库已加载：$QCOUNT 道题"
fi

# ------------------------------ 收尾提示 ------------------------------

# 首次部署时顺手建账号
if [ -n "$NEW_USER" ]; then
  log "创建账号：$NEW_USER"
  ( cd "$APP_DIR" && sudo -u "$APP_USER" "$PY_BIN" scripts/add_user.py "$NEW_USER" ) || warn "建账号失败，可稍后手动执行"
fi

if [ "$MODE" = "install" ]; then
  cat <<EOF

────────────────────────────────────────────────
 应用侧部署完成

   服务状态：  systemctl status $SERVICE_NAME
   实时日志：  journalctl -u $SERVICE_NAME -f
   重启服务：  systemctl restart $SERVICE_NAME
   更新代码：  sudo $0 update
   更新题库：  sudo $0 update --pull
   新建账号：  sudo $0 user 名字

 还需完成：
   1. 配置 Nginx
      cp $APP_DIR/deploy/nginx.conf /etc/nginx/conf.d/ruankao.conf
      改掉 server_name，然后 nginx -t && systemctl reload nginx

   2. 申请证书
      certbot --nginx -d 你的域名

   3. 放行防火墙 80/443
      ${PORT} 端口只监听 127.0.0.1，不要对外开放

   4. 建账号（如果刚才没带 --user）
      sudo $0 user 你的名字
      会打印一个随机密码，记下来

   5. 备份（建议加进 crontab）
      0 4 * * * sqlite3 $APP_DIR/data/app.db ".backup /var/backups/ruankao-\$(date +\\%F).db"
────────────────────────────────────────────────
EOF
else
  cat <<EOF

────────────────────────────────────────────────
 代码已更新（update 模式）

   服务状态：  systemctl status $SERVICE_NAME
   实时日志：  journalctl -u $SERVICE_NAME -f

 本次只更新了程序与题库，未改动账号、密码和 systemd 配置。
 题库是按文件 mtime 热加载的，即使不重启也会生效。
────────────────────────────────────────────────
EOF
fi
