#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题库加载的唯一入口：离线构建（scripts/build_app.py）和线上服务（server/app.py）共用。

这样就不会出现「离线版有选项、线上版没选项」这种分叉——
之前就是这个坑：PDF 题在 banks/ 里是老结构（options/answer），
把它补成 blanks 的逻辑写在了构建脚本里，服务端没做，导致线上 131 道题渲染不出选项。
"""
import json
import os
import re

OPT_KEYS = ("A", "B", "C", "D")
XREF = re.compile(r"\s*\d{4}年\d{1,2}月第[\d、，\s]+题\s*$")
LEAD_ANS = re.compile(r"^([A-D])[\s.．、]+(?=[\u4e00-\u9fa5])")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_question(q, overlay=None, excluded=None):
    """把一道题统一成前端要的形状，返回是否可用。"""
    overlay = overlay or {}
    excluded = excluded or set()

    # 1) 老结构 options/answer -> blanks
    if not q.get("blanks") and q.get("options"):
        ans = q.get("answer", "")
        # 老数据的双空题答案会连成 "CB"，单空结构放不下，判为不可用
        q["blanks"] = [{"options": q["options"], "answer": ans if len(ans) == 1 else ""}]

    blanks = q.get("blanks") or []

    # 2) 人工补写的解析：只覆盖空的或明显残缺的，原卷解析优先
    cur = (q.get("analysis") or "").strip()
    if q.get("id") in overlay and len(cur) < 30:
        q["analysis"] = overlay[q["id"]]
        q["analysisSource"] = "auto"

    # 3) 清理原卷解析里的跨题引用和行首多余的答案字母
    if q.get("analysis"):
        a = XREF.sub("", q["analysis"])
        a = LEAD_ANS.sub(r"\1 选项：", a)
        q["analysis"] = a.strip()

    q["multiBlank"] = len(blanks) > 1

    # 4) 答案存疑的题移出练习池
    if q.get("id") in excluded:
        q["practiceable"] = False
        q["excluded"] = "答案存疑"
        return False

    q["practiceable"] = bool(
        q.get("stem") and blanks
        and all(len(b.get("options") or {}) == 4 and b.get("answer") for b in blanks)
    )
    return q["practiceable"]


def scan_banks(banks_dir):
    """扫 banks/<级别>/<资格>/<科目>/*.json，返回原始 banks 与 questions（未归一化）"""
    banks, questions = [], []
    if not os.path.isdir(banks_dir):
        return banks, questions

    for level in sorted(os.listdir(banks_dir)):
        level_dir = os.path.join(banks_dir, level)
        if not os.path.isdir(level_dir) or level.startswith("."):
            continue

        for subject in sorted(os.listdir(level_dir)):
            bank_dir = os.path.join(level_dir, subject)
            if not os.path.isdir(bank_dir) or subject.startswith("."):
                continue

            meta = read_json(os.path.join(bank_dir, "bank.json"), {}) or {}
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
                    doc = read_json(os.path.join(sec_dir, fname), {}) or {}
                    qs = doc.get("questions", [])
                    for q in qs:
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
                "id": bank_id, "level": level, "subject": subject,
                "name": meta.get("subject") or subject, "exam": meta.get("exam", ""),
                "chapters": meta.get("chapters", []), "sections": sections, "papers": papers,
            })
    return banks, questions


def load_banks(banks_dir, overlay_path=None, excluded_path=None):
    """完整加载：扫描 -> 归一化 -> 返回 (banks, questions)、可刷题数"""
    banks, questions = scan_banks(banks_dir)
    overlay = read_json(overlay_path, {}) if overlay_path else {}
    excluded_doc = read_json(excluded_path, {}) if excluded_path else {}
    excluded = set((excluded_doc or {}).get("ids", []))

    usable = 0
    for q in questions:
        if normalize_question(q, overlay, excluded):
            usable += 1

    # papers 里的 practiceable 要按归一化后的结果重算
    by_paper = {}
    for q in questions:
        if q.get("practiceable"):
            key = (q.get("bank"), q.get("paper"))
            by_paper[key] = by_paper.get(key, 0) + 1
    for b in banks:
        for p in b["papers"]:
            p["practiceable"] = by_paper.get((b["id"], p["id"]), 0)

    return banks, questions, usable
