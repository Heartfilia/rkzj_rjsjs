#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫 banks/ 出一份题库体检报告：data/bank-report.md"""
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = os.path.join(ROOT, "banks")
OUT = os.path.join(ROOT, "data", "bank-report.md")


def _clean(a):
    a = re.sub(r"\s*\d{4}年\d{1,2}月第[\d、，\s]+题\s*$", "", a or "")
    return a.strip()


def main():
    overlay_path = os.path.join(ROOT, "data", "analyses.json")
    overlay = json.load(open(overlay_path, encoding="utf-8")) if os.path.exists(overlay_path) else {}
    excl_path = os.path.join(ROOT, "data", "excluded.json")
    excluded = set(json.load(open(excl_path, encoding="utf-8"))["ids"]) if os.path.exists(excl_path) else set()
    rows = []
    for level in sorted(os.listdir(BANKS)):
        for subject in sorted(os.listdir(os.path.join(BANKS, level))):
            bank_dir = os.path.join(BANKS, level, subject)
            if not os.path.isdir(bank_dir):
                continue
            meta = json.load(open(os.path.join(bank_dir, "bank.json"), encoding="utf-8"))
            ch = {c["id"]: c["name"] for c in meta.get("chapters", [])}
            for section in sorted(os.listdir(bank_dir)):
                sec = os.path.join(bank_dir, section)
                if not os.path.isdir(sec):
                    continue
                for f in sorted(os.listdir(sec)):
                    if not f.endswith(".json"):
                        continue
                    doc = json.load(open(os.path.join(sec, f), encoding="utf-8"))
                    qs = doc["questions"]
                    ok = [q for q in qs if q.get("practiceable") and q["id"] not in excluded]
                    rows.append({
                        "paper": doc.get("paper", f),
                        "title": doc.get("paperTitle", ""),
                        "section": section,
                        "total": len(qs),
                        "usable": len(ok),
                        "multi": sum(1 for q in ok if len(q.get("blanks") or []) > 1),
                        "analysis": sum(1 for q in ok if (q.get("analysis") or "").strip()
                                        or q["id"] in overlay),
                        "written": sum(1 for q in ok if q["id"] in overlay
                                       and len(_clean(q.get("analysis") or "")) < 30),
                        "year": doc.get("paper", "")[:4],
                    })
                    rows[-1]["_qs"] = ok

    rows.sort(key=lambda r: (r["section"], r["paper"]))
    total = sum(r["total"] for r in rows)
    usable = sum(r["usable"] for r in rows)
    multi = sum(r["multi"] for r in rows)
    ana = sum(r["analysis"] for r in rows)
    written = sum(r["written"] for r in rows)

    lines = ["# 题库体检报告", "",
             f"- 卷子：**{len(rows)}** 套",
             f"- 题目：**{total}** 道，可刷 **{usable}** 道",
             f"- 其中双空题：{multi} 道（{multi*100//max(usable,1)}%）",
             f"- 带解析：{ana} 道（{ana*100//max(usable,1)}%），其中**补写 {written} 道**", "",
             "## 分卷明细", "",
             "| 卷子 | 题数 | 可刷 | 双空 | 带解析 |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['title']} | {r['total']} | {r['usable']} | {r['multi']} | {r['analysis']} |")

    lines += ["", "## 年份覆盖", ""]
    by_year = defaultdict(int)
    for r in rows:
        by_year[r["year"]] += r["usable"]
    lines.append(" | ".join(f"{y}:{n}" for y, n in sorted(by_year.items())))

    # 章节分布（用当前题库的章节名）
    meta = json.load(open(os.path.join(BANKS, "中级", "软件设计师", "bank.json"), encoding="utf-8"))
    ch = {c["id"]: c["name"] for c in meta.get("chapters", [])}
    cnt = Counter()
    for r in rows:
        for q in r["_qs"]:
            cnt[q.get("chapter", "ch13")] += 1
    lines += ["", "## 章节分布", "", "| 章节 | 题数 |", "|---|---|"]
    for k, v in cnt.most_common():
        lines.append(f"| {ch.get(k, k)} | {v} |")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:10]))
    print(f"\n写出 {OUT}")


if __name__ == "__main__":
    main()
