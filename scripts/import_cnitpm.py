#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把信管网「真题与答案（文字版）」文章解析成题库文件。

来源示例：
  https://m.cnitpm.com/pm1/147936hd4io9v6wq.html   # 2023 上半年综合知识

文章结构：`8、9、题干` + `（8）A．…` + `（9）A．…` + `信管网参考答案：D、C`
用法：python3 scripts/import_cnitpm.py [url]
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

DEFAULT_URL = "https://m.cnitpm.com/pm1/147936hd4io9v6wq.html"
PAPER = {"id": "2023-05", "title": "2023年上半年", "source": "信管网文字版（考生回忆版）"}

NUM_START = re.compile(r"^((?:\d{1,2}、)+)\s*")
OPT_LABELED = re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*([A-D])[．.、]\s*(.*)$")
OPT_PLAIN = re.compile(r"^([A-D])[．.、]\s*(.*)$")
GROUP_LABEL = re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*$")
ANS_LINE = re.compile(r"^信管网参考答案[：:]\s*(.+)$")
SKIP_LINE = re.compile(r"^(查看解析|信管网参考答案|www\.cnitpm\.com/st/)")


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
    start = next((i for i, x in enumerate(lines) if "完整版" in x), 0)
    lines = lines[start + 1:]
    end = next((i for i, x in enumerate(lines) if x.startswith("温馨提示")), len(lines))
    return lines[:end]


def split_blocks(lines):
    blocks, cur, nums = [], None, []
    for line in lines:
        m = NUM_START.match(line)
        if m:
            nums = [int(x) for x in m.group(1).strip("、").split("、")]
            if cur and cur["nums"]:
                blocks.append(cur)
            cur = {"nums": nums, "stem": [line[m.end():]], "opts": {}, "ans": [],
                   "cur": nums[0]}
            continue
        if cur is None:
            continue
        am = ANS_LINE.match(line)
        if am:
            cur["ans"] = am.group(1)
            continue
        if SKIP_LINE.match(line):
            continue
        gm = GROUP_LABEL.match(line)
        if gm:
            cur["cur"] = int(gm.group(1))
            continue
        om = OPT_LABELED.match(line)
        if om:
            cur["cur"] = int(om.group(1))
            cur["opts"].setdefault(cur["cur"], {})[om.group(2)] = om.group(3)
            continue
        om = OPT_PLAIN.match(line)
        if om:
            letter = om.group(1)
            if (letter == "A" and "A" in cur["opts"].get(cur["cur"], {})
                    and cur["cur"] in nums):
                i = nums.index(cur["cur"])
                if i + 1 < len(nums):
                    cur["cur"] = nums[i + 1]
            cur["opts"].setdefault(cur["cur"], {})[letter] = om.group(2)
            continue
        if cur["opts"]:
            # 选项折行
            key = max(cur["opts"])
            last = sorted(cur["opts"][key])[-1]
            cur["opts"][key][last] += " " + line
        else:
            cur["stem"].append(line)
    if cur and cur["nums"]:
        blocks.append(cur)
    return blocks


def parse_answers(raw):
    return re.findall(r"[A-D]", raw)


def clean(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.strip(" 　，,。")


def build(blocks):
    out = []
    for b in blocks:
        nums = b["nums"]
        answers = parse_answers(b["ans"])
        if len(answers) != len(nums):
            print(f"[skip] 题号 {nums}：答案数 {len(answers)} 与空数不一致 -> {b['ans']!r}")
            continue
        blanks = []
        for num, ans in zip(nums, answers):
            opts = b["opts"].get(num) or (b["opts"].get(nums[0]) if len(nums) == 1 else {})
            opts = {k: clean(v) for k, v in opts.items() if clean(v)}
            if sorted(opts) != ["A", "B", "C", "D"]:
                break
            blanks.append({"options": {k: opts[k] for k in "ABCD"}, "answer": ans})
        stem = clean(" ".join(b["stem"]))
        if len(blanks) != len(nums) or not stem or len(stem) < 5:
            print(f"[skip] 题号 {nums}：题干或选项不完整")
            continue
        no = nums[0]
        has_figure = bool(re.search(r"如图|如下图|下表|下图|如下表", stem))
        if nums == [71, 72, 73, 74, 75]:
            # 文末英语阅读原文被站点按行截断，题干不完整，直接丢弃
            print(f"[skip] 题号 {nums}：英语阅读原文截断")
            continue
        q = {
            "id": f"sd-{PAPER['id'].replace('-', '')}-{no:02d}",
            "no": no,
            "paper": PAPER["id"],
            "paperTitle": PAPER["title"],
            "stem": stem,
            "blanks": blanks,
            "analysis": "",
            "source": PAPER["source"],
            "multiBlank": len(blanks) > 1,
            "practiceable": True,
            "chapter": classify({"no": no, "stem": stem, "analysis": ""}),
            "flags": ["无解析"],
            "answerSource": "信管网",
            "quality": "ok",
        }
        if has_figure:
            q["flags"].append("含图")
        out.append(q)
    return out


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    html_doc = fetch(url)
    blocks = split_blocks(body_lines(html_doc))
    questions = build(blocks)
    questions.sort(key=lambda q: q["no"])
    doc = {
        "paper": PAPER["id"],
        "paperTitle": PAPER["title"],
        "section": "基础知识",
        "source": f"{PAPER['title']}软件设计师综合知识真题（{PAPER['source']}）",
        "questions": questions,
    }
    os.makedirs(BANK_DIR, exist_ok=True)
    out = os.path.join(BANK_DIR, f"{PAPER['id']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    nums = [q["no"] for q in questions]
    print(f"{PAPER['id']}: 题块 {len(blocks)} → 入库 {len(questions)}，多空 "
          f"{sum(1 for q in questions if q['multiBlank'])}，含图 "
          f"{sum(1 for q in questions if '含图' in q['flags'])}")
    missing = [n for n in range(1, 76) if n not in nums]
    print("缺少题号:", missing or "无")


if __name__ == "__main__":
    main()
