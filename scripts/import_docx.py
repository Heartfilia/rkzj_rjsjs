#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/_docx_parsed/*.json 转成 banks/ 里的题库文件。

用法：python3 scripts/import_docx.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from parse_papers import CHAPTERS, classify            # noqa: E402

PARSED = os.path.join(ROOT, "data", "_docx_parsed")
BANK_DIR = os.path.join(ROOT, "banks", "中级", "软件设计师", "基础知识")

NAME_RE = re.compile(r"(\d{4})年(上|下)半年")


def paper_id(year, half):
    return f"{year}-{'05' if half == '上' else '11'}"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def main():
    files = sorted(f for f in os.listdir(PARSED) if f.endswith(".json"))
    total, kept = 0, 0

    for fname in files:
        m = NAME_RE.search(fname)
        if not m:
            print(f"[skip] {fname}")
            continue
        year, half = m.group(1), m.group(2)
        pid = paper_id(year, half)
        title = f"{year}年{'上' if half == '上' else '下'}半年"

        recs = json.load(open(os.path.join(PARSED, fname), encoding="utf-8"))
        questions = []
        for r in recs:
            total += 1
            blanks = [b for b in r["blanks"] if b.get("options") and b.get("answer")]
            q = {
                "id": f"sd-{pid.replace('-', '')}-{r['no']:02d}",
                "no": r["no"],
                "paper": pid,
                "paperTitle": title,
                "stem": clean(r["stem"]),
                "blanks": [{"options": b["options"], "answer": b["answer"]} for b in blanks],
                "analysis": clean(r["analysis"]),
                "source": "答案详解 docx",
            }
            q["multiBlank"] = len(q["blanks"]) > 1
            q["practiceable"] = bool(
                q["stem"] and len(q["stem"]) >= 5
                and q["blanks"] and all(len(b["options"]) == 4 for b in q["blanks"])
            )
            q["chapter"] = classify({"no": q["no"], "stem": q["stem"], "analysis": q["analysis"]})
            q["flags"] = [] if q["analysis"] else ["无解析"]
            if not q["practiceable"]:
                q["flags"].append("不完整")
            if re.search(r"如图|如下图|下表|下图", q["stem"]):
                q["flags"].append("含图")
            questions.append(q)

        if not questions:
            continue
        ok = sum(1 for q in questions if q["practiceable"])
        kept += ok
        doc = {
            "paper": pid,
            "paperTitle": title,
            "section": "基础知识",
            "source": f"{title}软件设计师基础知识真题（答案详解 docx）",
            "questions": questions,
        }
        os.makedirs(BANK_DIR, exist_ok=True)
        out = os.path.join(BANK_DIR, f"{pid}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"{pid}: {len(questions):3d} 题，可用 {ok:3d}，多空 "
              f"{sum(1 for q in questions if q['multiBlank']):2d}，带解析 "
              f"{sum(1 for q in questions if q['analysis']):3d}")

    print(f"\n合计 {total} 块 → 可用 {kept}")


if __name__ == "__main__":
    main()
