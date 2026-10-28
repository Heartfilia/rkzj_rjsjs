#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软考·软件设计师 上午卷 PDF → 结构化题库

现实情况：这几套卷子的排版并不统一，所以按「卷」配置适配器：
  - numbered：行首 `12、` / `12.` 起题（题干、选项、答案、解析都在块内）
  - paren   ：题干在前，`（12）A. ...` 标出题号与选项（答案在卷末答案表）

用法：
  PYTHONPATH=.tools/pylibs python3 scripts/parse_papers.py
"""
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

from pypdf import PdfReader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(ROOT, "data", "_pdf")
BANK_ID = "ruankao-zb-software-designer"
BANK_DIR = os.path.join(ROOT, "banks", "中级", "软件设计师")
SECTION = "基础知识"

OUT_REPORT = os.path.join(ROOT, "data", "quality-report.md")

PAPERS = [
    {"id": "2020-11", "file": "2020-11.pdf", "title": "2020年11月", "mode": "numbered"},
    {"id": "2022-05", "file": "2022-05.pdf", "title": "2022年05月", "mode": "numbered"},
    {"id": "2022-11", "file": "2022-11.pdf", "title": "2022年11月", "mode": "paren"},
]

# 这几套 PDF 里没有答案（空白卷 / App 导出残缺），无法判分，直接跳过
SKIPPED = [
    ("2021-05", "空白试卷，全卷无答案"),
    ("2021-11", "App 导出排版，仅末尾英语题有答案"),
]

NOISE_PATTERNS = [
    re.compile(r"手机端题库"),
    re.compile(r"PC\s*端题库"),
    re.compile(r"ruankaodaren"),
    re.compile(r"微信搜索"),
    re.compile(r"内部资料"),
    re.compile(r"禁止传播"),
    re.compile(r"淘宝"),
    re.compile(r"QQ\s*群"),
    re.compile(r"^\s*\d{1,3}\s*/\s*$"),            # "12 /" 页码
    re.compile(r"^\s*\d{1,3}\s*$"),                # 孤立页码
    re.compile(r"^\s*20\d\d\s*年.*软件设计师.*(试卷|真题|解析).*$"),
    re.compile(r"^\s*全国计算机技术与软件专业技术资格.*$"),
    # 卷首「答题卡说明 + 例题」样板文字
    re.compile(r"请按下述要求正确填写答题卡"),
    re.compile(r"在答题卡的指定位置上"),
    re.compile(r"在你写入的准考证号下填涂"),
    re.compile(r"本试卷的试题中共有"),
    re.compile(r"每个空格对应一个序号"),
    re.compile(r"请选择一个最恰当的选项"),
    re.compile(r"解答前务必阅读例题"),
    re.compile(r"时用正规2B"),
    re.compile(r"^\s*例题\s*$"),
    re.compile(r"因为考试日期是"),
    re.compile(r"填涂（参看答题卡）"),
    re.compile(r"^\s*月（?89）?日。?\s*$"),
    re.compile(r"考试日期是（88）"),
]

ANALYSIS_NOISE = [
    re.compile(r"https?://\S+"),
    re.compile(r"^\s*历年.*相关试题.*$"),
    re.compile(r"^\s*试\s*题\s*相\s*关.*$"),
    re.compile(r"^\s*手机端题库.*$"),
    re.compile(r"^\s*内部资料.*$"),
]

Q_START = re.compile(r"^[ \t]*(\d{1,2})(?:[、.．](\d{1,2}))?[、.．][ \t]*(?=\S)")
PAREN_MARK = re.compile(r"^[ \t]*[（(](\d{1,2})[）)][ \t]*([A-D])[.．、][ \t]*")
OPT_MARK = re.compile(r"(?<![A-Za-z0-9])([A-D])[、.．][ \t]*")
ANS_INLINE = re.compile(r"(?:参考答案|答案)[ \t]*[:：][ \t]*([A-D](?:[ \t、,，]*[A-D])*)")
ANS_KEY = re.compile(r"(\d{1,2})[.、]\s*([A-D])\b")

CHAPTERS = [
    ("ch01", "计算机组成与体系结构", ["补码", "原码", "反码", "移码", "浮点", "海明", "CRC", "流水线",
                                 "Cache", "缓存", "主存", "存储器", "总线", "寻址", "RISC", "CISC",
                                 "CPU", "寄存器", "中断", "DRAM", "SRAM", "可靠性", "MIPS", "CPI",
                                 "主频", "冯诺依曼", "磁盘", "编址", "闪存", "指令"]),
    ("ch02", "操作系统", ["进程", "线程", "信号量", "PV", "死锁", "页面", "页式", "段式", "置换",
                       "磁盘调度", "文件系统", "目录", "索引节点", "时间片", "临界", "银行家",
                       "操作系统", "调度", "缓冲区", "虚存", "存储管理", "路径", "位示图", "SPOOLing"]),
    ("ch03", "数据库系统", ["数据库", "关系模式", "范式", "函数依赖", "主键", "外键", "主码", "SQL",
                        "视图", "事务", "E-R", "元组", "完整性", "并发", "聚簇", "触发器", "候选码",
                        "闭包", "数据仓库", "OLAP", "关系代数"]),
    ("ch04", "计算机网络", ["网络", "协议", "IP 地址", "IP地址", "子网", "端口", "路由", "交换机", "TCP",
                        "UDP", "HTTP", "DNS", "OSI", "拓扑", "带宽", "域名", "局域网", "以太网",
                        "报文", "ARP", "防火墙", "SMTP", "FTP", "DHCP", "ICMP", "TELNET"]),
    ("ch05", "信息安全", ["加密", "解密", "数字签名", "证书", "病毒", "攻击", "认证", "木马", "入侵",
                      "密钥", "摘要", "访问控制", "备份", "完整性", "可用性", "对称", "非对称"]),
    ("ch06", "标准化与知识产权", ["著作权", "专利", "商标", "知识产权", "标准", "侵权", "保护期",
                            "发表权", "署名权", "职务作品", "委托开发"]),
    ("ch07", "程序设计语言与编译原理", ["编译", "文法", "自动机", "正规式", "词法", "语法", "语义",
                                 "后缀式", "逆波兰", "表达式", "参数传递", "解释程序", "汇编", "符号表",
                                 "NFA", "DFA", "动态绑定", "静态绑定", "传值", "传址"]),
    ("ch08", "数据结构与算法", ["二叉树", "结点", "有向图", "无向图", "排序", "查找", "哈希", "散列",
                          "栈", "队列", "链表", "复杂度", "邻接", "遍历", "堆", "数组", "矩阵",
                          "广义表", "拓扑", "折半", "循环队列", "线性表", "哈夫曼", "邻接表"]),
    ("ch09", "算法设计与分析", ["动态规划", "贪心", "分治", "回溯", "背包", "算法设计", "最优子结构",
                          "分支限界", "时间复杂度", "空间复杂度", "递归"]),
    ("ch10", "面向对象技术", ["面向对象", "UML", "设计模式", "类图", "用例", "继承", "多态", "封装",
                         "聚合", "组合", "接口", "观察者", "策略", "状态模式", "工厂", "适配器"]),
    ("ch11", "软件工程", ["软件工程", "瀑布", "原型", "增量", "螺旋", "喷泉", "需求分析", "测试",
                      "维护", "耦合", "内聚", "CMM", "风险", "敏捷", "生命周期", "覆盖", "McCabe",
                      "甘特", "PERT", "配置管理", "软件质量", "复用", "数据流图", "数据字典", "模块",
                      "可行性", "结构化", "关键路径", "COCOMO", "估算", "统一过程", "RUP"]),
]
CH_NAME = {c: n for c, n, _ in CHAPTERS}
CH_NAME["ch12"] = "专业英语"
CH_NAME["ch13"] = "其他/未归类"


def sanitize(s: str) -> str:
    return re.sub(r"[\ud800-\udfff]", "", s)


def clean_page_text(raw: str) -> str:
    out = []
    for line in sanitize(raw).splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        if any(p.search(s) for p in NOISE_PATTERNS):
            continue
        out.append(s)
    return "\n".join(out)


def clean_analysis(s: str) -> str:
    keep = []
    for line in s.splitlines():
        if any(p.search(line) for p in ANALYSIS_NOISE):
            continue
        keep.append(line.strip())
    txt = " ".join(keep)
    return re.sub(r"\s{2,}", " ", txt).strip(" ：:，,")


def count_opts(text: str) -> int:
    return len({m.group(1) for m in OPT_MARK.finditer(text)})


# ------------------------------------------------------------------ 切块
def split_numbered(text: str):
    lines = text.splitlines()
    blocks, cur, last = [], None, 0
    for line in lines:
        m = Q_START.match(line)
        if m:
            n1 = int(m.group(1))
            n2 = int(m.group(2)) if m.group(2) else None
            # 只接受严格递增的题号：解析正文里形如 "1.xxx" 的列表项会被自动排除
            accept = n1 > last and n1 <= 75 and (cur is None and n1 == 1 or cur is not None)
            if accept:
                if cur is not None:
                    blocks.append(cur)
                cur = {"no": n1, "lines": [line[m.end():]]}
                last = n2 if n2 else n1
                continue
        if cur is not None:
            cur["lines"].append(line)
    if cur is not None:
        blocks.append(cur)

    merged = []
    for b in blocks:
        body = "\n".join(b["lines"])
        fragment = (not ANS_INLINE.search(body)
                    and count_opts(body) < 4
                    and len(body) < 260)
        if merged and fragment:
            merged[-1]["lines"].extend(b["lines"])
        else:
            merged.append(b)
    return [{"no": b["no"], "text": "\n".join(b["lines"])} for b in merged]


def split_paren(text: str):
    """题干在前，`（12）A. ...` 起选项；凑齐 A-D 即算本题结束。"""
    blocks, pending, cur = [], [], None
    for line in text.splitlines():
        m = PAREN_MARK.match(line)
        if m:
            if not (20 <= int(m.group(1)) <= 75 or int(m.group(1)) <= 75):
                pass
            cur = {"no": int(m.group(1)), "stem": "\n".join(pending).strip(),
                   "opt": ["A. " + line[m.end():]]}
            pending = []
            blocks.append(cur)
            continue
        if cur is not None and count_opts("\n".join(cur["opt"])) < 4:
            if line.strip():
                cur["opt"].append(line)
            continue
        cur = None
        pending.append(line.strip())
    out = []
    for b in blocks:
        if not (1 <= b["no"] <= 75):
            continue
        body = b["stem"] + "\n" + "\n".join(b["opt"])
        out.append({"no": b["no"], "text": body})
    return out


def extract_answer_key(text: str):
    """卷末答案表：1. B 2.B 3.D ..."""
    tail = text[-1500:]
    if "参考答案" not in tail:
        return {}
    seg = tail[tail.index("参考答案"):]
    return {int(a): b for a, b in ANS_KEY.findall(seg)}


# ------------------------------------------------------------------ 单题解析
def parse_question(no: int, raw: str, key: dict) -> dict:
    m = ANS_INLINE.search(raw)
    answer, tail, body = "", "", raw
    if m:
        answer = "".join(re.findall(r"[A-D]", m.group(1)))
        body, tail = raw[: m.start()], raw[m.end():]
    elif no in key:
        answer = key[no]

    am = re.search(r"解析[ \t]*[:：]?", tail)
    analysis = clean_analysis(tail[am.end():] if am else tail)

    marks = [(mm.start(), mm.end(), mm.group(1)) for mm in OPT_MARK.finditer(body)]
    groups, cur = [], []
    for pos in marks:
        if pos[2] == "A" and cur:
            groups.append(cur)
            cur = []
        cur.append(pos)
    if cur:
        groups.append(cur)
    valid = [g for g in groups if [x[2] for x in g] == ["A", "B", "C", "D"]]

    opts, stem = {}, body
    if valid:
        g = valid[0]
        cand = {}
        for i, (_s, e, letter) in enumerate(g):
            end = g[i + 1][0] if i + 1 < len(g) else len(body)
            cand[letter] = re.sub(r"\s{2,}", " ", body[e:end]).strip()
        if all(cand.values()):
            opts, stem = cand, body[: g[0][0]]

    stem = re.sub(r"\s{2,}", " ", stem.replace("\n", " ")).strip()

    flags = []
    if not opts:
        flags.append("无选项")
    if len(valid) > 1:
        flags.append("多空题")
    if not answer:
        flags.append("无答案")
    if not analysis:
        flags.append("无解析")
    elif len(analysis) < 20:
        flags.append("解析过短")
    if re.search(r"如图|如下图|如下表|下图|图①|图②|图 1|图1", stem):
        flags.append("含图")

    return {
        "no": no, "stem": stem, "options": opts, "answer": answer,
        "analysis": analysis, "flags": flags,
        "_multi": len(valid) > 1 or len(answer) > 1,
    }


def classify(q: dict) -> str:
    if 71 <= q["no"] <= 75:
        return "ch12"
    text = q["stem"] + " " + q["analysis"]
    scores = Counter()
    for cid, _n, kws in CHAPTERS:
        scores[cid] += sum(2 if kw in q["stem"] else (1 if kw in text else 0) for kw in kws)
    if not scores or scores.most_common(1)[0][1] < 2:
        return "ch13"
    return scores.most_common(1)[0][0]


def main():
    all_q, per_paper = [], {}
    for p in PAPERS:
        path = os.path.join(PDF_DIR, p["file"])
        if not os.path.exists(path):
            print(f"[skip] {p['file']} 不存在")
            continue
        reader = PdfReader(path)
        text = "\n".join(clean_page_text(pg.extract_text() or "") for pg in reader.pages)
        key = extract_answer_key(text) if p["mode"] == "paren" else {}
        blocks = split_numbered(text) if p["mode"] == "numbered" else split_paren(text)
        qs = []
        for b in blocks:
            q = parse_question(b["no"], b["text"], key)
            q["id"] = f"sd-{p['id'].replace('-', '')}-{q['no']:02d}"
            q["paper"] = p["id"]
            q["paperTitle"] = p["title"]
            q["chapter"] = classify(q)
            q["answerSource"] = ("卷内" if ANS_INLINE.search(b["text"]) else
                                 ("答案表" if b["no"] in key else "缺失"))
            # 双空题/答案错乱的，不进刷题池
            if len(q["answer"]) > 3:
                q["flags"].append("答案存疑")
                q["answer"] = ""
            q["multiBlank"] = q.pop("_multi", False) or len(q["answer"]) > 1
            q["practiceable"] = bool(
                q["stem"] and len(q["stem"]) >= 5
                and len(q["options"]) == 4
                and len(q["answer"]) == 1
            )
            q["quality"] = "ok" if (not q["flags"] and q["practiceable"]) else "check"
            qs.append(q)
        per_paper[p["id"]] = qs
        all_q.extend(qs)
        print(f"{p['id']}: {len(reader.pages)} 页 → {len(qs)} 题"
              f"（有解析 {sum(1 for x in qs if x['analysis'])}，有答案 {sum(1 for x in qs if x['answer'])}）")

    # ---- 写入 banks/ 目录树：一套卷一个 json，bank.json 存元信息 ----
    section_dir = os.path.join(BANK_DIR, SECTION)
    os.makedirs(section_dir, exist_ok=True)
    meta_path = os.path.join(BANK_DIR, "bank.json")
    if not os.path.exists(meta_path):
        meta = {
            "id": BANK_ID,
            "level": "中级",
            "subject": "软件设计师",
            "exam": "计算机技术与软件专业技术资格（水平）考试",
            "chapters": [{"id": cid, "name": n} for cid, n, _ in CHAPTERS]
                        + [{"id": "ch12", "name": "专业英语"}, {"id": "ch13", "name": "其他/未归类"}],
            "sections": [SECTION],
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"新建 {meta_path}")

    for pid, qs in per_paper.items():
        title = next(p["title"] for p in PAPERS if p["id"] == pid)
        doc = {
            "paper": pid,
            "paperTitle": title,
            "section": SECTION,
            "source": f"{title}上午真题（公开卷，仅供个人学习）",
            "questions": qs,
        }
        out = os.path.join(section_dir, f"{pid}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"写出 {os.path.relpath(out, ROOT)}（{len(qs)} 题）")

    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "papers": len(per_paper), "questions": len(all_q),
            "withAnalysis": sum(1 for q in all_q if q["analysis"]),
            "withAnswer": sum(1 for q in all_q if q["answer"]),
            "practiceable": sum(1 for q in all_q if q["practiceable"]),
            "ok": sum(1 for q in all_q if q["quality"] == "ok"),
            "check": sum(1 for q in all_q if q["quality"] == "check"),
        },
    }

    c = payload["counts"]
    lines = ["# 题库抽取质量报告", "", f"生成时间：{payload['generatedAt']}", "",
             "## 总览", "",
             f"- 试卷：{c['papers']} 套",
             f"- 题目：{c['questions']} 道",
             f"- 有答案：{c['withAnswer']} 道",
             f"- **可用于刷题：{c['practiceable']} 道**（有题干、四选项、单一正确答案）",
             f"- 有解析：{c['withAnalysis']} 道",
             f"- 干净可直接用：{c['ok']} 道",
             f"- 需人工看一眼：{c['check']} 道", "",
             "## 分卷明细", "", "| 试卷 | 题数 | 有答案 | 有解析 | 干净 | 需检查 |", "|---|---|---|---|---|---|"]
    for pid, qs in per_paper.items():
        ok = sum(1 for q in qs if q["quality"] == "ok")
        lines.append(f"| {pid} | {len(qs)} | {sum(1 for q in qs if q['answer'])} | "
                     f"{sum(1 for q in qs if q['analysis'])} | {ok} | {len(qs) - ok} |")
    lines += ["", "## 问题分布", ""]
    cnt = Counter(f for q in all_q for f in q["flags"])
    if cnt:
        lines += ["| 问题 | 题数 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in cnt.most_common()]
    else:
        lines.append("无")
    lines += ["", "## 章节分布", "", "| 章节 | 题数 |", "|---|---|"]
    for k, v in Counter(q["chapter"] for q in all_q).most_common():
        lines.append(f"| {k} {CH_NAME.get(k, k)} | {v} |")
    lines += ["", "## 跳过的卷子", ""]
    lines += [f"- `{pid}`：{why}" for pid, why in SKIPPED] or ["无"]
    lines += ["", "## 需检查题目（前 40 条）", ""]
    for q in [x for x in all_q if x["quality"] == "check"][:40]:
        lines.append(f"- `{q['id']}` {'/'.join(q['flags'])} — {q['stem'][:50]}")
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"写出 {OUT_REPORT}")


if __name__ == "__main__":
    main()
