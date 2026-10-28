#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「答案详解」docx 解析成结构化题目（tagged 型）。

排版样例：
    常用的虚拟存储器由（1）两级存储器组成。
    (1)A.主存-辅存   B.主存-网盘   C.Cache-主存   D.Cache-硬盘
    【答案】A
    【解析】本题考查计算机系统存储系统基础知识。
    ...（解析可能多段）

双空题：连续两行选项 + 一个「【答案】B  C」，对应两个空。

用法：
  PYTHONPATH=.tools/pylibs python3 scripts/parse_docx.py 2013年上半年
"""
import json
import os
import re
import sys

from docx import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "_docx")
OUT = os.path.join(ROOT, "data", "_docx_parsed")

OPT_LINE = re.compile(r"^[（(](\d{1,2})[）)]\s*A\s*[.．、]")
ANS_TAG = re.compile(r"^【答案】\s*([A-D](?:\s+[A-D])*)")
JX_TAG = re.compile(r"^【解析】")
OPT_SPLIT = re.compile(r"(?<![A-Za-z0-9])([A-D])\s*[.．、]\s*")


def load_paras(path):
    return [p.text.strip() for p in Document(path).paragraphs if p.text.strip()]


def split_all_options(text):
    """返回文本里所有 A-D 选项组：[{A:..,B:..,C:..,D:..}, ...]"""
    marks = [(m.start(), m.end(), m.group(1)) for m in OPT_SPLIT.finditer(text)]
    groups, cur = [], []
    for m in marks:
        if m[2] == "A" and cur:
            groups.append(cur)
            cur = []
        cur.append(m)
    if cur:
        groups.append(cur)

    out = []
    for gi, g in enumerate(groups):
        if [x[2] for x in g] != ["A", "B", "C", "D"]:
            continue
        # 最后一个选项要在「下一组的 A」处收尾，否则会把下一空的选项吞进来
        group_end = groups[gi + 1][0][0] if gi + 1 < len(groups) else len(text)
        opts = {}
        for i, (_s, e, letter) in enumerate(g):
            end = g[i + 1][0] if i + 1 < len(g) else group_end
            v = re.sub(r"\s+", " ", text[e:end]).strip(" \t，,。;；")
            v = re.sub(r"[（(]\d{1,2}[）)]\s*$", "", v).strip()   # 去掉尾部的 (18)
            opts[letter] = v
        if all(opts.values()):
            out.append(opts)
    return out


def locate_stem(ps, opt_idx, num, back=6):
    """从选项行往前找包含「（N）」的段落，找不到返回 None（说明是上一题的第二组选项）"""
    pat = re.compile(r"[（(]%d[）)]" % num)
    for j in range(opt_idx - 1, max(-1, opt_idx - back - 1), -1):
        if pat.search(ps[j]):
            return j
    return None


def parse_file(path):
    ps = load_paras(path)

    # 1) 定位每行选项，并回推它属于哪一段题干
    marks = [(i, int(m.group(1))) for i, p in enumerate(ps) for m in [OPT_LINE.match(p)] if m]
    questions = []
    for idx, num in marks:
        stem_idx = locate_stem(ps, idx, num)
        if questions and (stem_idx is None or stem_idx == questions[-1]["stem_idx"]):
            questions[-1]["opt_idx"].append(idx)     # 同一题的第二组选项（双空）
            continue
        questions.append({
            "stem_idx": stem_idx if stem_idx is not None else max(0, idx - 1),
            "opt_idx": [idx],
            "nums": [num],
        })

    # 2) 切块并抽取
    out = []
    for k, q in enumerate(questions):
        start = q["stem_idx"]
        end = questions[k + 1]["stem_idx"] if k + 1 < len(questions) else len(ps)
        first_opt = q["opt_idx"][0]

        ans_i = next((i for i in range(first_opt, end) if ANS_TAG.match(ps[i])), None)
        opt_end = ans_i if ans_i is not None else end

        stem = re.sub(r"\s+", " ", " ".join(ps[start:first_opt])).strip()
        opt_text = " ".join(ps[first_opt:opt_end])
        groups = split_all_options(opt_text)

        ans = ""
        analysis = []
        if ans_i is not None:
            m = ANS_TAG.match(ps[ans_i])
            ans = "".join(m.group(1).split())
            body = ps[ans_i + 1:end]
            for p in body:
                jm = JX_TAG.match(p)
                analysis.append(p[jm.end():].strip() if jm else p)
        elif opt_end < end:
            analysis = ps[opt_end:end]

        answers = list(ans)
        out.append({
            "no": q["nums"][0],
            "stem": stem,
            "blanks": [{"options": g, "answer": answers[i] if i < len(answers) else ""}
                       for i, g in enumerate(groups)],
            "analysis": re.sub(r"\s+", " ", " ".join(a for a in analysis if a)).strip(),
        })
    return out


def main():
    files = [f for f in sorted(os.listdir(SRC)) if f.endswith(".docx") and not f.startswith("~$")]
    targets = sys.argv[1:]
    if targets:
        files = [f for f in files if any(t in f for t in targets)]
    os.makedirs(OUT, exist_ok=True)

    for f in files:
        recs = parse_file(os.path.join(SRC, f))
        complete = [r for r in recs if r["blanks"] and all(b["answer"] for b in r["blanks"])]
        multi = sum(1 for r in complete if len(r["blanks"]) > 1)
        print(f"{f[:26]:28s} 题块 {len(recs):3d}  完整 {len(complete):3d}  "
              f"多空 {multi:3d}  带解析 {sum(1 for r in recs if r['analysis']):3d}")
        if not recs:
            print(f"  → 该版本式不匹配（tagged），跳过不写文件")
            continue
        if targets:
            for r in recs[:3]:
                print("    stem:", r["stem"][:50])
                print("    blanks:", [(b["answer"], list(b["options"].values())[0][:12]) for b in r["blanks"]])
                print("    analysis:", r["analysis"][:40])
        with open(os.path.join(OUT, f.replace(".docx", ".json")), "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- ref 型
REF_Q = re.compile(r"^(\d{1,2})[.．、]\s*(?=\S)")
REF_ANS = re.compile(r"^参考答案\s*[:：]?\s*([A-D](?:\s*[A-D])*)")
REF_JX = re.compile(r"^试题解析")


def parse_ref_file(path):
    """2018 下半年这类：N. 题干 / A. 选项 / 参考答案B / 试题解析：…"""
    ps = load_paras(path)
    # 只接受严格递增的题号：解析正文里的 "1. 2. 3." 列表项会被自动排除
    starts, last = [], 0
    for i, p in enumerate(ps):
        m = REF_Q.match(p)
        if m and int(m.group(1)) > last and int(m.group(1)) <= 75:
            starts.append((i, int(m.group(1))))
            last = int(m.group(1))
    out = []
    for k, (idx, num) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(ps)
        block = ps[idx:end]
        stem_parts, opt_parts, ans, jx = [], [], "", []
        state = "stem"
        for j, p in enumerate(block):
            if j == 0:
                stem_parts.append(REF_Q.sub("", p))
                continue
            m = REF_ANS.match(p)
            if m:
                ans = "".join(m.group(1).split()); state = "ans"; continue
            if REF_JX.match(p):
                state = "jx"; jx.append(REF_JX.sub("", p).lstrip("：: ").strip()); continue
            if state == "ans" and not ans == "":
                state = "jx"
            if state in ("ans", "jx"):
                jx.append(p); continue
            # stem 还没结束？
            if OPT_SPLIT.search(p) and re.match(r"^[ABCD]\s*[.．、]", p.strip()):
                opt_parts.append(p); state = "opt"; continue
            if state == "opt":
                opt_parts.append(p); continue
            stem_parts.append(p)

        groups = split_all_options(" ".join(opt_parts))
        answers = list(ans)
        out.append({
            "no": num,
            "stem": re.sub(r"\s+", " ", " ".join(stem_parts)).strip(),
            "blanks": [{"options": g, "answer": answers[i] if i < len(answers) else ""}
                       for i, g in enumerate(groups)],
            "analysis": re.sub(r"\s+", " ", " ".join(a for a in jx if a)).strip(" ：:，,"),
        })
    return out


# ---------------------------------------------------------------- 2018 上半年（选项无标点）
Q_MARK = re.compile(r"^[（(](\d{1,2})[）)]\s*([A-D])\s*[.．、]?\s*")
SEG = re.compile(r"\t+|\s{2,}|　+")


def parse_2018up(path):
    ps = load_paras(path)
    # 1) 找所有 (N)A 位置
    marks = []
    for i, p in enumerate(ps):
        m = Q_MARK.match(p)
        if m:
            marks.append((i, int(m.group(1))))
    questions = []
    for idx, num in marks:
        # 题干 = 从上一个 ●/数字 段之后到选项之前
        j = idx
        stem_parts = []
        while j > 0 and not ps[j - 1].startswith("●") and not Q_MARK.match(ps[j - 1]):
            j -= 1
            stem_parts.insert(0, ps[j])
        if j > 0 and ps[j - 1].startswith("●"):
            stem_parts.insert(0, ps[j - 1].lstrip("● "))
            j -= 1

        # 选项 = 本题选项段，直到遇到 ● 或下一个 (N) 题干
        opt_text = [re.sub(r"^[（(]\d{1,2}[）)]\s*", "", ps[idx])]
        k = idx + 1
        while k < len(ps) and not ps[k].startswith("●") and not Q_MARK.match(ps[k]):
            opt_text.append(ps[k]); k += 1

        # 拼接并按空白切段，按首字母归位
        joined = " ".join(opt_text)
        if joined.count("\t") == 0:
            joined = joined  # 保留原样
        segs = SEG.split(" ".join(opt_text))
        opts, letter = {}, "A"
        for s in segs:
            s = s.strip()
            if not s: continue
            m = re.match(r"^([A-D])\s*[.．、]?\s*(.*)$", s)
            if m and m.group(1) == letter:
                opts[letter] = m.group(2).strip()
                letter = chr(ord(letter) + 1)
            elif letter in opts and letter <= "D":
                opts[letter] += " " + s     # 选项内换行，接上继续
        questions.append({
            "no": num,
            "stem": re.sub(r"\s+", " ", " ".join(stem_parts)).strip(),
            "blanks": [{"options": opts, "answer": ""}] if len(opts) == 4 else [],
        })
    return questions
