#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补 2018 两套：下半年走 ref 解析，上半年把「真题」和「答案」两份 docx 合起来。

输出到 data/_docx_parsed/，之后由 import_docx.py 入库。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from parse_docx import load_paras, parse_2018up, parse_ref_file   # noqa: E402

SRC = os.path.join(ROOT, "data", "_docx")
OUT = os.path.join(ROOT, "data", "_docx_parsed")

COMPACT = re.compile(r"^(\d{1,2})(?:\s*[—\-~]\s*(\d{1,2}))?\s*([A-D])(?:\s+([A-D])(?=\s|$))?")


def parse_compact_answers(path):
    """'1 D 解析…' / '2—3B C 解析…' → {题号: (答案, 解析)}"""
    out = {}
    for p in load_paras(path):
        m = COMPACT.match(p)
        if not m:
            continue
        n1 = int(m.group(1))
        n2 = int(m.group(2)) if m.group(2) else None
        ans = [m.group(3)] + ([m.group(4)] if m.group(4) else [])
        body = p[m.end():].strip(" 　，,。")
        if n2:                        # 2—3B C：两个连号
            out[n1] = (ans[0], body)
            out[n2] = (ans[1] if len(ans) > 1 else "", body)
        else:
            out[n1] = (ans[0], body)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- 2018 下半年：一份 docx 里题干+选项+答案+解析都有
    recs = parse_ref_file(os.path.join(SRC, "2018年下半年_软件设计师_答案详解.docx"))
    ok = [r for r in recs if r["blanks"] and all(b["answer"] for b in r["blanks"])]
    with open(os.path.join(OUT, "2018年下半年_软件设计师_答案详解.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    print(f"2018下：{len(recs)} 块，完整 {len(ok)}")

    # ---- 2018 上半年：真题 docx 提供题干+选项，答案详解提供答案
    stems = parse_2018up(os.path.join(SRC, "真题_2018上.docx"))
    answers = parse_compact_answers(os.path.join(SRC, "2018年上半年_软件设计师_答案详解.docx"))
    merged = []
    for q in stems:
        a, analysis = answers.get(q["no"], ("", ""))
        if not q["blanks"] or not a:
            continue
        q["blanks"][0]["answer"] = a[0]
        q["analysis"] = analysis
        merged.append(q)
    with open(os.path.join(OUT, "2018年上半年_真题合并.json"), "w", encoding="utf-8") as f:
        # 文件名要能被 import_docx 的「YYYY年X半年」规则识别
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"2018上：题干 {len(stems)} 条，可用 {len(merged)} 条（要求选项完整且找到答案）")


if __name__ == "__main__":
    main()
