#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软考刷题 · 线上小服务（纯标准库，无第三方依赖）

- 只做 API：静态文件交给 nginx
- 密码登录，密码即身份，Cookie 会话
- 进度存 SQLite
- 题库直接读 banks/ 目录（git pull 后重启即生效，或调 /api/reload）

环境变量：
  PORT        监听端口，默认 8787
  BIND        监听地址，默认 127.0.0.1
  DB_PATH     SQLite 路径，默认 <repo>/data/app.db
  SECRET_FILE 会话密钥文件，默认 <repo>/data/secret.key
  WEB_DIR     静态目录（仅本地调试用），默认 <repo>/dist

用法：
  python3 server/app.py
"""
import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 兼容两种布局：仓库根目录 或 部署后的 /opt/ruankao
sys.path[:0] = [ROOT, os.path.dirname(os.path.abspath(__file__))]

try:
    from banklib import load_banks, audit_options
except ModuleNotFoundError:
    sys.exit(
        "缺少 banklib.py。请确认它和 server/ 在同一层目录：\n"
        f"  期望位置：{os.path.join(ROOT, 'banklib.py')}\n"
        "  修复：在仓库目录执行 sudo ./deploy/deploy.sh update"
    )
BANKS = os.path.join(ROOT, "banks")
OVERLAY = os.path.join(ROOT, "data", "analyses.json")
EXCLUDED = os.path.join(ROOT, "data", "excluded.json")
DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT, "data", "app.db"))
SECRET_FILE = os.environ.get("SECRET_FILE", os.path.join(ROOT, "data", "secret.key"))
def _default_web_dir():
    online = os.path.join(ROOT, "server", "web")
    if os.path.exists(os.path.join(online, "index.html")):
        return online
    return os.path.join(ROOT, "dist")


WEB_DIR = os.environ.get("WEB_DIR") or _default_web_dir()
PORT = int(os.environ.get("PORT", "8787"))
BIND = os.environ.get("BIND", "127.0.0.1")

COOKIE = "rk_sess"
SESSION_DAYS = 365

# ---------------------------------------------------------------- 基础设施


def load_secret():
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE, "rb").read()
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    s = secrets.token_bytes(32)
    with open(SECRET_FILE, "wb") as f:
        f.write(s)
    os.chmod(SECRET_FILE, 0o600)
    return s


SECRET = load_secret()
_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pwd TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            qid TEXT NOT NULL,
            choices TEXT NOT NULL,
            correct INTEGER NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attempt_uid ON attempts(uid, qid);
        CREATE TABLE IF NOT EXISTS flags(
            uid INTEGER NOT NULL,
            qid TEXT NOT NULL,
            fav INTEGER NOT NULL DEFAULT 0,
            bad INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(uid, qid)
        );
        CREATE TABLE IF NOT EXISTS settings(
            uid INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY(uid, key)
        );
        """)


# ---------------------------------------------------------------- 密码 / 会话
SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_pwd(pwd: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pwd.encode(), salt=salt, maxmem=64 * 1024 * 1024, **SCRYPT)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT["n"], SCRYPT["r"], SCRYPT["p"],
        base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_pwd(pwd: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
        got = hashlib.scrypt(pwd.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                             dklen=len(want), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, want)
    except Exception:
        return False


def sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_session(uid: int) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{uid}.{exp}"
    return f"{payload}.{sign(payload)}"


def read_session(cookie: str):
    if not cookie:
        return None
    try:
        uid_s, exp_s, sig = cookie.split(".")
        payload = f"{uid_s}.{exp_s}"
        if not hmac.compare_digest(sig, sign(payload)):
            return None
        if int(exp_s) < time.time():
            return None
        return int(uid_s)
    except Exception:
        return None


# ---------------------------------------------------------------- 登录限速
_login_fails = {}          # ip -> [timestamps]
_login_lock = threading.Lock()
FAIL_WINDOW = 600          # 10 分钟
FAIL_LIMIT = 10


def login_blocked(ip):
    now = time.time()
    with _login_lock:
        arr = [t for t in _login_fails.get(ip, []) if now - t < FAIL_WINDOW]
        _login_fails[ip] = arr
        return len(arr) >= FAIL_LIMIT


def login_failed(ip):
    with _login_lock:
        _login_fails.setdefault(ip, []).append(time.time())


def login_ok(ip):
    with _login_lock:
        _login_fails.pop(ip, None)


# ---------------------------------------------------------------- 题库
_banks_cache = {"mtime": 0, "banks": [], "questions": [], "index": {},
                "payload": b"", "payload_gzip": b"", "etag": "",
                "lite": b"", "lite_gzip": b"", "lite_etag": "",
                "banks_json": b"", "questions_json": b""}
_banks_checked_at = 0.0

# 前端只用到这些字段，其余（no/flags/source/quality…）留在服务端，不随网络发送
WIRE_KEYS = ("id", "bank", "paper", "paperTitle", "chapter", "stem",
             "blanks", "analysis", "analysisSource", "practiceable")


def wire_question(q):
    return {k: q[k] for k in WIRE_KEYS if k in q}


def lite_question(q):
    """首屏索引：只带选题/统计需要的字段，题目正文按需通过 /api/questions 取"""
    return {
        "id": q["id"], "bank": q["bank"], "paper": q["paper"], "no": q.get("no", 0),
        "chapter": q.get("chapter", ""), "practiceable": bool(q.get("practiceable")),
        "hasAnalysis": bool((q.get("analysis") or "").strip()),
    }


def banks_version():
    """用目录里最新的 mtime 判断题库有没有变"""
    newest = 0
    for base, _dirs, files in os.walk(BANKS):
        for f in files:
            if f.endswith(".json"):
                newest = max(newest, os.path.getmtime(os.path.join(base, f)))
    return newest


def get_banks(force=False):
    global _banks_checked_at
    now = time.time()
    # mtime 检查做 5 秒节流：/api/banks 会频繁收到带 If-None-Match 的请求
    if not force and now - _banks_checked_at < 5:
        return _banks_cache
    _banks_checked_at = now

    mtime = banks_version()
    if mtime > _banks_cache["mtime"] or not _banks_cache["payload"]:
        banks, questions, _usable = load_banks(BANKS, OVERLAY, EXCLUDED)
        bad = audit_options(questions)
        if bad:
            print(f"[banks] WARNING: {len(bad)} practiceable question(s) missing options: "
                  f"{', '.join(bad[:10])}", flush=True)

        # 一次性序列化好，之后每个请求直接写缓存字节，不再重复 json.dumps 2 MB
        # （之前每个 /api/bootstrap 都序列化一遍，小机器上会被单个页面加载拖住）
        wire = [wire_question(q) for q in questions]
        lite = [lite_question(q) for q in questions]
        payload = json.dumps({"banks": banks, "questions": wire},
                             ensure_ascii=False, separators=(",", ":")).encode()
        lite_payload = json.dumps({"banks": banks, "questions": lite},
                                  ensure_ascii=False, separators=(",", ":")).encode()
        _banks_cache.update({
            "mtime": mtime, "banks": banks, "questions": questions,
            "index": {q["id"]: q for q in questions},
            "payload": payload,
            "payload_gzip": gzip.compress(payload, 6),
            "etag": '"' + hashlib.sha1(payload).hexdigest()[:20] + '"',
            "lite": lite_payload,
            "lite_gzip": gzip.compress(lite_payload, 6),
            "lite_etag": '"' + hashlib.sha1(lite_payload).hexdigest()[:20] + '"',
            "banks_json": json.dumps(banks, ensure_ascii=False, separators=(",", ":")).encode(),
            "questions_json": json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode(),
        })
        print(f"[banks] reloaded: {len(banks)} bank(s), {len(questions)} question(s), "
              f"index {len(lite_payload)//1024} KB / full {len(payload)//1024} KB", flush=True)
    return _banks_cache


def answers_of(q):
    """取出某题的正确答案列表，用来在服务端判分"""
    blanks = q.get("blanks")
    if not blanks and q.get("options"):
        blanks = [{"options": q["options"], "answer": q.get("answer", "")}]
    return [b.get("answer", "") for b in (blanks or [])]


# ---------------------------------------------------------------- 进度聚合


def progress_of(uid: int):
    with db() as c:
        rows = c.execute(
            "SELECT qid, choices, correct, ts FROM attempts WHERE uid=? ORDER BY id", (uid,)
        ).fetchall()
        flags = c.execute("SELECT qid, fav, bad FROM flags WHERE uid=?", (uid,)).fetchall()
        st = c.execute("SELECT key, value FROM settings WHERE uid=?", (uid,)).fetchall()

    hist, daily = {}, {}
    for r in rows:
        h = hist.setdefault(r["qid"], {"right": 0, "wrong": 0, "last": ""})
        if r["correct"]:
            h["right"] += 1
        else:
            h["wrong"] += 1
        h["last"] = r["ts"][:10]
        daily[r["ts"][:10]] = daily.get(r["ts"][:10], 0) + 1

    return {
        "hist": hist,
        "daily": daily,
        "fav": {f["qid"]: True for f in flags if f["fav"]},
        "flag": {f["qid"]: True for f in flags if f["bad"]},
        "settings": {s["key"]: s["value"] for s in st},
    }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "ruankao/1.0"

    # ---- 工具
    def _json(self, code, obj, cookie=None):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        self._send(code, body, cache="no-store", cookie=cookie)

    def _send(self, code, body, cache="no-store", etag=None, encoding=None,
              vary=None, cookie=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if etag:
            self.send_header("ETag", etag)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if vary:
            self.send_header("Vary", vary)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _uid(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return read_session(v)
        return None

    def _need_login(self):
        uid = self._uid()
        if uid is None:
            self._json(401, {"error": "unauthorized"})
        return uid

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- GET
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/health":
            return self._json(200, {"ok": True})

        if path == "/api/index":
            uid = self._need_login()
            if uid is None:
                return
            cache = get_banks()
            etag = cache["lite_etag"]
            if etag and self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                self.send_header("Vary", "Accept-Encoding")
                self.end_headers()
                return
            body, encoding = cache["lite"], None
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body, encoding = cache["lite_gzip"], "gzip"
            return self._send(200, body, cache="private, max-age=0, must-revalidate",
                              etag=etag, encoding=encoding, vary="Accept-Encoding")

        if path == "/api/questions":
            uid = self._need_login()
            if uid is None:
                return
            raw = (parse_qs(urlparse(self.path).query).get("ids") or [""])[0]
            ids = [x for x in raw.split(",")[:200] if x]
            if not ids:
                return self._json(400, {"error": "ids required"})
            cache = get_banks()
            items = [wire_question(cache["index"][i]) for i in ids if i in cache["index"]]
            body = json.dumps({"questions": items},
                              ensure_ascii=False, separators=(",", ":")).encode()
            etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                self.send_header("Vary", "Accept-Encoding")
                self.end_headers()
                return
            encoding = None
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body, encoding = gzip.compress(body, 6), "gzip"
            return self._send(200, body, cache="private, max-age=0, must-revalidate",
                              etag=etag, encoding=encoding, vary="Accept-Encoding")

        if path == "/api/banks":
            uid = self._need_login()
            if uid is None:
                return
            cache = get_banks()
            etag = cache["etag"]
            # 浏览器带 ETag 回来时只回 304，不传题库、也不再序列化
            if etag and self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                self.send_header("Vary", "Accept-Encoding")
                self.end_headers()
                return
            body, encoding = cache["payload"], None
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body, encoding = cache["payload_gzip"], "gzip"
            return self._send(200, body, cache="private, max-age=0, must-revalidate",
                              etag=etag, encoding=encoding, vary="Accept-Encoding")

        if path == "/api/state":
            uid = self._need_login()
            if uid is None:
                return
            with db() as c:
                u = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            return self._json(200, {
                "user": {"id": uid, "name": u["name"] if u else ""},
                "state": progress_of(uid),
            })

        if path == "/api/bootstrap":
            # 兼容旧页面：用缓存好的字节拼接，避免重新序列化整份题库
            uid = self._need_login()
            if uid is None:
                return
            cache = get_banks()
            with db() as c:
                u = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            dumps = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()
            body = (b'{"user":' + dumps({"id": uid, "name": u["name"] if u else ""})
                    + b',"banks":' + cache["banks_json"]
                    + b',"questions":' + cache["questions_json"]
                    + b',"state":' + dumps(progress_of(uid)) + b'}')
            return self._send(200, body)

        if path == "/api/progress":
            uid = self._need_login()
            if uid is None:
                return
            return self._json(200, progress_of(uid))

        if path == "/api/me":
            uid = self._uid()
            if uid is None:
                return self._json(200, {"user": None})
            with db() as c:
                u = c.execute("SELECT id, name FROM users WHERE id=?", (uid,)).fetchone()
            return self._json(200, {"user": dict(u) if u else None})

        return self._static(path)

    # ---- POST
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/login":
            return self._login(body)

        if path == "/api/logout":
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            return self._json(200, {"ok": True},
                              cookie=f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}")

        uid = self._need_login()
        if uid is None:
            return

        if path == "/api/attempt":
            return self._attempt(uid, body)

        if path == "/api/flag":
            return self._flag(uid, body)

        if path == "/api/settings":
            return self._settings(uid, body)

        if path == "/api/reload":
            _banks_cache["mtime"] = 0
            cache = get_banks(force=True)
            return self._json(200, {"ok": True, "questions": len(cache["questions"])})

        self._json(404, {"error": "not found"})

    # ---- 业务
    def _login(self, body):
        ip = self.client_address[0]
        if login_blocked(ip):
            return self._json(429, {"error": "尝试太频繁，请 10 分钟后再试"})
        pwd = (body.get("password") or "").strip()
        if not pwd:
            return self._json(400, {"error": "密码不能为空"})
        with db() as c:
            users = c.execute("SELECT id, name, pwd FROM users WHERE active=1").fetchall()
        for u in users:
            if verify_pwd(pwd, u["pwd"]):
                login_ok(ip)
                sess = make_session(u["id"])
                # nginx 终止 TLS 后会带 X-Forwarded-Proto，https 时给 Cookie 加 Secure
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                return self._json(200, {"ok": True, "name": u["name"]},
                                  cookie=f"{COOKIE}={sess}; Path=/; Max-Age={SESSION_DAYS*86400}; "
                                         f"HttpOnly; SameSite=Lax{secure}")
        login_failed(ip)
        time.sleep(0.3)          # 拖慢爆破
        return self._json(401, {"error": "密码不对"})

    def _attempt(self, uid, body):
        qid = body.get("qid") or ""
        choices = body.get("choices") or []
        banks = get_banks()
        q = banks["index"].get(qid)
        if not q:
            return self._json(404, {"error": "no such question"})
        key = answers_of(q)
        ok = len(key) == len(choices) and all(
            str(c).upper() == str(k).upper() for c, k in zip(choices, key))
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _db_lock, db() as c:
            c.execute("INSERT INTO attempts(uid,qid,choices,correct,ts) VALUES(?,?,?,?,?)",
                      (uid, qid, json.dumps(choices), 1 if ok else 0, ts))
        return self._json(200, {"ok": True, "correct": ok})

    def _flag(self, uid, body):
        qid = body.get("qid")
        if not qid:
            return self._json(400, {"error": "qid required"})
        fav = 1 if body.get("fav") else 0
        bad = 1 if body.get("bad") else 0
        with _db_lock, db() as c:
            c.execute("""INSERT INTO flags(uid,qid,fav,bad) VALUES(?,?,?,?)
                         ON CONFLICT(uid,qid) DO UPDATE SET fav=?, bad=?""",
                      (uid, qid, fav, bad, fav, bad))
        return self._json(200, {"ok": True})

    def _settings(self, uid, body):
        with _db_lock, db() as c:
            for k, v in body.items():
                c.execute("""INSERT INTO settings(uid,key,value) VALUES(?,?,?)
                             ON CONFLICT(uid,key) DO UPDATE SET value=?""",
                          (uid, k, json.dumps(v, ensure_ascii=False), json.dumps(v, ensure_ascii=False)))
        return self._json(200, {"ok": True})

    # ---- 静态（本地调试用；线上由 nginx 承担）
    def _static(self, path):
        if not os.path.isdir(WEB_DIR):
            return self._json(404, {"error": "no static dir"})
        root = os.path.abspath(WEB_DIR)
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            return self._json(403, {"error": "forbidden"})
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.exists(full):
            return self._json(404, {"error": "not found"})
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript",
                 "css": "text/css", "json": "application/json",
                 "png": "image/png", "svg": "image/svg+xml"}.get(full.rsplit(".", 1)[-1], "application/octet-stream")
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    init_db()
    cache = get_banks()
    print(f"banks: {len(cache['banks'])}, questions: {len(cache['questions'])}", flush=True)
    print(f"listen: http://{BIND}:{PORT}", flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
