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
import re
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
    banks, questions = [], []
    overlay = read_json(OVERLAY) if os.path.exists(OVERLAY) else {}
    excluded_path = os.path.join(ROOT, "data", "excluded.json")
    excluded = set(read_json(excluded_path)["ids"]) if os.path.exists(excluded_path) else set()

    for level in sorted(os.listdir(BANKS), key=lambda x: LEVEL_ORDER.get(x, 9)):
        level_dir = os.path.join(BANKS, level)
        if not os.path.isdir(level_dir) or level.startswith("."):
            continue

        for subject in sorted(os.listdir(level_dir)):
            bank_dir = os.path.join(level_dir, subject)
            if not os.path.isdir(bank_dir) or subject.startswith("."):
                continue

            meta_path = os.path.join(bank_dir, "bank.json")
            meta = read_json(meta_path) if os.path.exists(meta_path) else {}
            bank_id = meta.get("id") or f"{level}-{subject}"

            papers, sections = [], []
            for section in sorted(os.listdir(bank_dir)):
                sec_dir = os.path.join(bank_dir, section)
                if not os.path.isdir(sec_dir) or section.startswith("."):
                    continue
                sections.append(section)
                for fname in sorted(os.listdir(sec_dir)):
                    if not fname.endswith(".json"):
                        continue
                    doc = read_json(os.path.join(sec_dir, fname))
                    qs = doc.get("questions", [])
                    for q in qs:
                        # 统一成 blanks 结构（老 PDF 题是 options/answer 单空）
                        if not q.get("blanks") and q.get("options"):
                            a = q.get("answer", "")
                            # 老数据的双空题答案会连成 "CB"，单空结构放不下，直接判为不可用
                            q["blanks"] = [{"options": q["options"],
                                            "answer": a if len(a) == 1 else ""}]
                        # 去掉原卷解析里混入的跨题引用、行首多出来的答案字母
                        if q.get("analysis"):
                            a = q["analysis"]
                            a = re.sub(r"\s*\d{4}年\d{1,2}月第[\d、，\s]+题\s*$", "", a)
                            a = re.sub(r"^([A-D])[\s.．、]+(?=[\u4e00-\u9fa5])", r"\1 选项：", a)
                            q["analysis"] = a.strip()

                        # 只补「没有解析」或「解析过短」的题，原卷解析优先保留
                        cur = (q.get("analysis") or "").strip()
                        if q.get("id") in overlay and len(cur) < 30:
                            q["analysis"] = overlay[q["id"]]
                            q["analysisSource"] = "auto"
                        q["multiBlank"] = len(q.get("blanks") or []) > 1
                        if q.get("id") in excluded:
                            q["practiceable"] = False
                            q["excluded"] = "答案存疑"
                            continue
                        q["practiceable"] = bool(
                            q.get("stem") and q.get("blanks")
                            and all(len(b.get("options") or {}) == 4 and b.get("answer")
                                    for b in q["blanks"]))
                        q["bank"] = bank_id
                        q["level"] = level
                        q["subject"] = subject
                        q["section"] = section
                    questions.extend(qs)
                    papers.append({
                        "id": doc.get("paper", fname[:-5]),
                        "title": doc.get("paperTitle", fname[:-5]),
                        "section": section,
                        "count": len(qs),
                        "practiceable": sum(1 for q in qs if q.get("practiceable")),
                    })

            banks.append({
                "id": bank_id,
                "level": level,
                "subject": subject,
                "name": meta.get("subject") or subject,
                "exam": meta.get("exam", ""),
                "chapters": meta.get("chapters", []),
                "sections": sections,
                "papers": papers,
            })
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
    print(f"生成 {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    for b in banks:
        n = sum(p["count"] for p in b["papers"])
        u = sum(p["practiceable"] for p in b["papers"])
        print(f"  · {b['level']} {b['subject']}：{len(b['papers'])} 套卷 / {n} 题（可刷 {u}）")
    print(f"  合计可刷 {usable} 题")


if __name__ == "__main__":
    main()
