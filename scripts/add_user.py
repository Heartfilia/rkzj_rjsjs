#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号管理 CLI（直接操作 server 用的 SQLite）

  python3 scripts/add_user.py 小明              # 生成随机密码
  python3 scripts/add_user.py 小明 --pwd abc123 # 指定密码
  python3 scripts/add_user.py --list
  python3 scripts/add_user.py 小明 --reset      # 换一个新密码
  python3 scripts/add_user.py 小明 --disable    # 停用
"""
import argparse
import os
import secrets
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import app            # noqa: E402

WORDS = ["amber", "bamboo", "cedar", "delta", "ember", "fjord", "glide", "harbor",
         "indigo", "juniper", "kite", "lantern", "meadow", "nimbus", "onyx", "pearl",
         "quartz", "river", "summit", "tundra", "umber", "velvet", "willow", "zenith"]


def gen_pwd():
    return "-".join(secrets.choice(WORDS) for _ in range(4)) + "-" + str(secrets.randbelow(90) + 10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--pwd")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--disable", action="store_true")
    args = ap.parse_args()

    app.init_db()

    if args.list or not args.name:
        with app.db() as c:
            rows = c.execute("SELECT id,name,active,created FROM users ORDER BY id").fetchall()
        if not rows:
            print("还没有账号。用法：python3 scripts/add_user.py 小明")
            return
        print(f"{'ID':>3}  {'名字':<10} {'状态':<6} 创建时间")
        for r in rows:
            print(f"{r['id']:>3}  {r['name']:<10} {'启用' if r['active'] else '停用':<6} {r['created']}")
        return

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with app.db() as c:
        row = c.execute("SELECT id FROM users WHERE name=?", (args.name,)).fetchone()

    if row and args.disable:
        with app.db() as c:
            c.execute("UPDATE users SET active=0 WHERE id=?", (row["id"],))
        print(f"已停用：{args.name}")
        return

    pwd = args.pwd or gen_pwd()
    if row:
        if not (args.reset or args.pwd):
            print(f"用户 {args.name} 已存在。要换密码请加 --reset")
            return
        with app.db() as c:
            c.execute("UPDATE users SET pwd=?, active=1 WHERE id=?",
                      (app.hash_pwd(pwd), row["id"]))
        print(f"已更新密码：{args.name}")
    else:
        with app.db() as c:
            c.execute("INSERT INTO users(name,pwd,active,created) VALUES(?,?,1,?)",
                      (args.name, app.hash_pwd(pwd), now))
        print(f"已创建：{args.name}")

    print(f"  密码：{pwd}")
    print("  提示：密码即身份，丢了就用 --reset 换一个，进度不会丢。")


if __name__ == "__main__":
    main()
