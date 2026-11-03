#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把希赛网「真题及答案」系列文章解析成题库文件。

文章结构：`1、题干` + `A.…` + `试题答案：C`
一篇通常 10 题，多篇拼成一套卷。

用法：python3 scripts/import_educity.py
"""
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from parse_papers import classify   # noqa: E402

BANK_DIR = os.path.join(ROOT, "banks", "中级", "软件设计师", "基础知识")

PAPER = {
    "id": "2024-11",
    "title": "2024年下半年（前30题·回忆版）",
    "source": "希赛网免费回忆版",
    "urls": [
        "https://m.educity.cn/rk/5353327.html",
        "https://m.educity.cn/rk/5353329.html",
        "https://m.educity.cn/rk/5353330.html",
    ],
}

Q_START = re.compile(r"^(\d{1,2})[、\.]\s*")
OPT = re.compile(r"^([A-D])[.．、]\s*(.*)$")
ANS = re.compile(r"^试题答案[：:]\s*([A-D])")
STOP = re.compile(r"^(软件设计师考试真题|责任编辑|温馨提示|分享至)")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 Mobile/15E148",
    })
    raw = urllib.request.urlopen(req, timeout=30).read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def body_lines(doc):
    doc = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?s)<[^>]+>", "\n", doc)
    lines = [re.sub(r"\s+", " ", html.unescape(x)).strip() for x in doc.splitlines()]
    lines = [x for x in lines if x]
    start = next((i for i, x in enumerate(lines) if Q_START.match(x)), 0)
    return lines[start:]


def parse(doc):
    blocks, cur = [], None
    for line in body_lines(doc):
        if STOP.match(line):
            break
        m = Q_START.match(line)
        if m and not OPT.match(line) and not ANS.match(line):
            if cur:
                blocks.append(cur)
            cur = {"no": int(m.group(1)), "stem": [line[m.end():]], "opts": {}, "ans": ""}
            continue
        if cur is None:
            continue
        am = ANS.match(line)
        if am:
            cur["ans"] = am.group(1)
            continue
        om = OPT.match(line)
        if om:
            cur["opts"][om.group(1)] = om.group(2)
            continue
        if cur["opts"]:
            last = sorted(cur["opts"])[-1]
            cur["opts"][last] += " " + line
        else:
            cur["stem"].append(line)
    if cur:
        blocks.append(cur)
    return blocks


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip().strip(" 　，,。")


def build(blocks):
    out = []
    for b in blocks:
        opts = {k: clean(v) for k, v in b["opts"].items() if clean(v)}
        stem = clean(" ".join(b["stem"]))
        if sorted(opts) != ["A", "B", "C", "D"] or not b["ans"] or len(stem) < 5:
            print(f"[skip] 第 {b['no']} 题：题干/选项/答案不完整")
            continue
        has_figure = bool(re.search(r"如图|如下图|下表|下图|如下表", stem))
        q = {
            "id": f"sd-{PAPER['id'].replace('-', '')}-{b['no']:02d}",
            "no": b["no"],
            "paper": PAPER["id"],
            "paperTitle": PAPER["title"],
            "stem": stem,
            "blanks": [{"options": {k: opts[k] for k in "ABCD"}, "answer": b["ans"]}],
            "analysis": "",
            "source": PAPER["source"],
            "multiBlank": False,
            "practiceable": True,
            "chapter": classify({"no": b["no"], "stem": stem, "analysis": ""}),
            "flags": ["无解析"] + (["含图"] if has_figure else []),
            "answerSource": "希赛网",
            "quality": "ok",
        }
        out.append(q)
    return out


def main():
    questions = []
    for url in PAPER["urls"]:
        questions.extend(build(parse(fetch(url))))
    questions.sort(key=lambda q: q["no"])

    doc = {
        "paper": PAPER["id"],
        "paperTitle": PAPER["title"],
        "section": "基础知识",
        "source": PAPER["source"],
        "questions": questions,
    }
    os.makedirs(BANK_DIR, exist_ok=True)
    out = os.path.join(BANK_DIR, f"{PAPER['id']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"{PAPER['id']}: 入库 {len(questions)}，可练 "
          f"{sum(q['practiceable'] for q in questions)}，含图 "
          f"{sum(1 for q in questions if '含图' in q['flags'])}")


if __name__ == "__main__":
    main()
