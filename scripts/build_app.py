#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描 banks/ 目录树，打包成单文件 HTML（双击即用）。

目录约定：
  banks/<级别>/<资格>/bank.json          # 元信息 + 章节定义
  banks/<级别>/<资格>/<科目>/<paper>.json # 一套卷一个文件

加题库 = 往目录里丢 json 文件，然后重跑这个脚本。
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = os.path.join(ROOT, "banks")
TPL = os.path.join(ROOT, "app", "template.html")
OUT = os.path.join(ROOT, "dist", "软件设计师-刷题.html")
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
OVERLAY = os.path.join(ROOT, "data", "analyses.json")   # 人工/补写的解析，覆盖题库里的空解析

LEVEL_ORDER = {"初级": 0, "中级": 1, "高级": 2}


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scan():
    sys.path.insert(0, ROOT)
    from banklib import load_banks
    banks, questions, _usable = load_banks(BANKS, OVERLAY, os.path.join(ROOT, "data", "excluded.json"))
    return banks, questions


def main():
    if not os.path.isdir(BANKS):
        raise SystemExit(f"找不到题库目录：{BANKS}")

    banks, questions = scan()
    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "banks": banks,
        "questions": questions,
    }

    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": payload["generatedAt"],
            "banks": [{k: b[k] for k in ("id", "level", "subject", "sections", "papers")}
                      for b in banks],
        }, f, ensure_ascii=False, indent=2)

    tpl = open(TPL, encoding="utf-8").read()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/", data)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)

    # 线上版：不内联题库，启动时向 /api/bootstrap 取
    online = tpl.replace("/*__DATA__*/", "null")
    web_dir = os.path.join(ROOT, "server", "web")
    os.makedirs(web_dir, exist_ok=True)
    open(os.path.join(web_dir, "index.html"), "w", encoding="utf-8").write(online)
    print(f"生成 {os.path.relpath(os.path.join(web_dir, 'index.html'), ROOT)}  (线上版，题库走 API)")
    # 起本地服务时用 / 直接访问
    open(os.path.join(os.path.dirname(OUT), "index.html"), "w", encoding="utf-8").write(html)

    usable = sum(1 for q in questions if q.get("practiceable"))
    from banklib import audit_options
    missing = audit_options(questions)
    if missing:
        raise SystemExit(
            f"题库校验失败：{len(missing)} 道可练习题缺少完整 A–D 选项："
            + "、".join(missing[:20])
        )
    print(f"生成 {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    for b in banks:
        n = sum(p["count"] for p in b["papers"])
        u = sum(p["practiceable"] for p in b["papers"])
        print(f"  · {b['level']} {b['subject']}：{len(b['papers'])} 套卷 / {n} 题（可刷 {u}）")
    print(f"  合计可刷 {usable} 题")
    print(f"  选项校验：{usable} 道可练习题均含完整 A–D 选项")


if __name__ == "__main__":
    main()
