# 线上部署（不用 Docker）

一台小 VPS + nginx + 一个 Python 进程，内存占用约 40–60 MB。

## 一键部署

```bash
git clone <你的仓库> ~/ruankao && cd ~/ruankao
python3 scripts/build_app.py          # 生成线上前端（只需本地做一次）
sudo ./deploy/deploy.sh --user 我      # 建系统用户 + 装 systemd + 自检 + 建账号
```

脚本会打印随机密码。之后：

```bash
sudo ./deploy/deploy.sh status        # 看状态和日志
sudo ./deploy/deploy.sh user 朋友A     # 加账号
sudo ./deploy/deploy.sh update --pull # 拉代码并更新（题库改动走这个）
```

Nginx 配置在 `deploy/nginx.conf`，证书用 certbot。下面是手动流程，脚本做的事和它一致。

```
nginx :443
 ├── /            → 静态文件 server/web/（一个 34 KB 的 html）
 └── /api/        → 反代 127.0.0.1:8787（Python 服务）

Python 服务（stdlib，无第三方依赖）
 ├── banks/      → 题库，只读，git pull 后自动生效
 └── data/app.db → SQLite，用户和进度
```

---

## 一、首次部署

```bash
# 1. 拉代码
git clone <你的仓库> ~/ruankao && cd ~/ruankao

# 2. 建账号（会打印一个随机密码，记下来发给对方）
python3 scripts/add_user.py 我
python3 scripts/add_user.py 朋友A

# 3. 试跑
PORT=8787 python3 server/app.py
curl -s localhost:8787/api/health     # {"ok": true}
```

不需要 pip install，也不需要 venv——`server/app.py` 只用标准库。

## 二、systemd 托管

`/etc/systemd/system/ruankao.service`：

```ini
[Unit]
Description=ruankao quiz service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/home/www/ruankao
Environment=PORT=8787
Environment=BIND=127.0.0.1
ExecStart=/usr/bin/python3 server/app.py
Restart=always
RestartSec=2
# 小内存机器限制一下，异常时先自杀而不是把机器拖垮
MemoryMax=200M

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ruankao
sudo systemctl status ruankao
```

## 三、nginx

```nginx
server {
    listen 443 ssl http2;
    server_name rk.example.com;

    ssl_certificate     /etc/letsencrypt/live/rk.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rk.example.com/privkey.pem;

    # 静态页面
    root /home/www/ruankao/server/web;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反代
    location /api/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_read_timeout 60s;
    }

    # 题库一次性返回 ~2MB，压缩一下
    gzip on;
    gzip_types application/json text/html;
    gzip_min_length 1024;
}
```

证书用 certbot：

```bash
sudo certbot --nginx -d rk.example.com
```

## 四、题库更新流程

本地整理好一个 JSON（格式见 `scripts/publish.py` 顶部注释）：

```bash
# 1. 校验并写入 banks/
python3 scripts/publish.py 2019-05.json \
    --paper 2019-05 --title "2019年上半年"

# 2. 提交
git add -A && git commit -m "题库: 2019 上半年" && git push

# 3. 服务器上拉取
ssh 服务器 'cd ~/ruankao && git pull'

# 4. 不用重启
```

**为什么不用重启**：服务每次请求都会检查 `banks/` 里文件的 mtime，变了就重新扫描并热替换。
`git pull` 之后下一个请求就会用新题库（响应里会打印 `[banks] reloaded`）。

也可以手动触发：

```bash
curl -b cookies.txt -X POST https://rk.example.com/api/reload
```

> 注意：题库是整个仓库的一部分，所以服务器上**不要改 banks/**，否则 pull 会冲突。
> 所有题库改动都在本地做，走 publish → push。

## 五、登录状态（会话）

输一次密码后，浏览器会拿到一个 `rk_sess` Cookie：

```
Set-Cookie: rk_sess=<uid>.<exp>.<sig>; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax
```

- **有效期 365 天**，关浏览器、重启电脑都不会丢，除非主动点「退出」
- 走 HTTPS 时（nginx 带 `X-Forwarded-Proto: https`）会自动加上 `Secure`
- `HttpOnly`：JS 读不到，避免被脚本窃取
- 会话是无状态签名（HMAC-SHA256，密钥在 `data/secret.key`），**删掉 secret.key 会让所有人重新登录**

会重新要求输密码的几种情况：

| 情况 | 说明 |
|---|---|
| 换了域名或端口 | Cookie 按 host 隔离，`127.0.0.1:8787` 和 `rk.example.com` 是两套 |
| 隐私/无痕窗口 | 关掉即清空 |
| 手动清 Cookie | 同上 |
| 点了「退出」 | 主动清除 |
| 换浏览器/换设备 | Cookie 不跨设备，这正是多用户能分开的原因 |

要改有效期，编辑 `server/app.py` 里的 `SESSION_DAYS`（单位：天）。

## 六、备份

SQLite 是单文件，直接拷即可（WAL 模式下先 checkpoint 更稳妥）：

```bash
# /etc/cron.d/ruankao-backup
0 4 * * * www-data sqlite3 /home/www/ruankao/data/app.db ".backup /home/www/backup/app-$(date +\%F).db" && find /home/www/backup -name 'app-*.db' -mtime +14 -delete
```

`banks/` 有 git 兜底，不用单独备份。

## 七、账号管理

```bash
python3 scripts/add_user.py --list            # 看所有账号
python3 scripts/add_user.py 朋友B              # 新建，打印随机密码
python3 scripts/add_user.py 朋友B --reset      # 换个新密码（进度保留）
python3 scripts/add_user.py 朋友B --disable    # 停用
```

密码只存 scrypt 哈希，**没有找回流程**——丢了就 `--reset` 给一个新的，进度挂在 user_id 上不会丢。

## 八、常见问题

| 现象 | 原因 |
|---|---|
| 打开是 404 / 白屏 | nginx 的 `root` 没指向 `server/web`，或没跑 `python3 scripts/build_app.py` |
| `/api/` 502 | 服务没起来，`systemctl status ruankao` 看日志 |
| 登录一直提示密码错 | 账号是在**另一台机器**的 `data/app.db` 里建的；账号库跟着服务器走，不是 git 里的 |
| 换题库后页面没变 | 前端有缓存，强刷；或直接 `systemctl restart ruankao` |
| 忘记密码 | `python3 scripts/add_user.py 名字 --reset` |

## 九、内存与并发

- 单进程 + 线程，几十个用户完全够用
- 常驻内存 40–60 MB（题库 2 MB 常驻在内存里）
- 如果要更强并发，前面有 nginx 顶着，再加 `--workers` 级别的改造即可（当前实现是单进程多线程，够用）

## 十、合规提醒

题库是公开流通的历年真题，**自用和小范围共享风险较低，但公网可被搜索引擎索引就不一样了**。建议：

- 不要在任何公开渠道贴链接
- 需要的话在 nginx 加 `add_header X-Robots-Tag "noindex" always;` 并放一个 `robots.txt` 禁止抓取
- 最稳的做法是只开给自己和朋友，不对外宣传
