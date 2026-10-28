#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把一套整理好的题目发布进题库目录（之后 commit + push，服务器 pull 即可）。

  python3 scripts/publish.py 2019-05.json \
      --level 中级 --subject 软件设计师 --section 基础知识 --paper 2019-05 \
      --title "2019年上半年"

输入 JSON 支持两种形态：
  1. {"paper":"2019-05","questions":[...]}        # 已经是题库格式
  2. [ {...}, {...} ]                             # 裸题目数组

每道题至少要有：id 或 no、stem、选项（blanks[].options 或 options）、答案。
校验不过会逐条报错，一条都不写。
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = os.path.join(ROOT, "banks")

OPT_KEYS = {"A", "B", "C", "D"}


def blanks_of(q):
    if q.get("blanks"):
        return q["blanks"]
    if q.get("options"):
        return [{"options": q["options"], "answer": q.get("answer", "")}]
    return []


def validate(q, idx):
    errs = []
    if not (q.get("stem") or "").strip():
        errs.append("题干为空")
    bl = blanks_of(q)
    if not bl:
        errs.append("没有选项")
    for i, b in enumerate(bl, 1):
        opts = b.get("options") or {}
        if set(opts.keys()) != OPT_KEYS:
            errs.append(f"第 {i} 空选项不是 A-D")
        elif not all(str(v).strip() for v in opts.values()):
            errs.append(f"第 {i} 空有选项内容为空")
        ans = str(b.get("answer") or "").strip().upper()
        if ans not in OPT_KEYS:
            errs.append(f"第 {i} 空答案不是 A-D")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--level", default="中级")
    ap.add_argument("--subject", default="软件设计师")
    ap.add_argument("--section", default="基础知识")
    ap.add_argument("--paper")
    ap.add_argument("--title")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.load(open(args.file, encoding="utf-8"))
    if isinstance(raw, dict):
        questions = raw.get("questions") or []
        paper = args.paper or raw.get("paper") or os.path.basename(args.file).rsplit(".", 1)[0]
        title = args.title or raw.get("paperTitle") or paper
    else:
        questions = raw
        paper = args.paper
        title = args.title or paper
        if not paper:
            sys.exit("纯数组输入必须给 --paper")

    if not questions:
        sys.exit("没有题目")

    problems, ok = [], []
    seen = set()
    for i, q in enumerate(questions, 1):
        errs = validate(q, i)
        qid = q.get("id") or f"sd-{paper.replace('-', '')}-{q.get('no', i):02d}"
        if qid in seen:
            errs.append(f"id 重复：{qid}")
        seen.add(qid)
        if errs:
            problems.append((i, qid, errs))
        else:
            ok.append((i, qid, q))

    print(f"读入 {len(questions)} 题：合格 {len(ok)}，有问题 {len(problems)}")
    for i, qid, errs in problems[:20]:
        print(f"  #{i} {qid}: {'；'.join(errs)}")
    if problems:
        print("\n有问题的题不会写入，修正后重跑。")
        if not args.dry_run:
            return

    out_dir = os.path.join(BANKS, args.level, args.subject, args.section)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{paper}.json")

    if os.path.exists(out):
        old = json.load(open(out, encoding="utf-8")).get("questions", [])
        print(f"注意：{os.path.relpath(out, ROOT)} 已存在（{len(old)} 题），将被覆盖")

    doc = {
        "paper": paper, "paperTitle": title, "section": args.section,
        "source": f"{title}（手工发布）",
        "questions": [q for _, _, q in ok],
    }
    if args.dry_run:
        print(f"[dry-run] 将写入 {os.path.relpath(out, ROOT)}，{len(ok)} 题")
        return

    json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已写入 {os.path.relpath(out, ROOT)}（{len(ok)} 题）")
    print("下一步：git add -A && git commit -m '题库: 新增 " + paper + "' && git push")


if __name__ == "__main__":
    main()
