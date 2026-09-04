#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
痕迹质量分析器 —— 回答一个关键问题：
    采到的 reasoning_content 到底是「真推理」还是「贴标签」？

背景：
  留痕 v0 把 LLM 的 reasoning_content 原样存进印记。但"存下来"不等于"有价值"。
  如果模型只是说 "A>B, B>C, so A>C, transitive, 成立"，那这道痕对
  Q1（CoT→DAG 拆解器）毫无营养 —— 它没有暴露可抽取的结构，只有一句结论式断言。

本脚本不改数据，只读 imprint_lib.jsonl，输出：
  1. 噪音占比：轨迹开头有多少是在复述 prompt（我们自己有，存了就是冗余）
  2. 结构化信号：是否出现「关系性质判断 / 逐条验前提 / 反例检验」三类推理动作
  3. 语言：英文思考 vs 中文思考占比
  4. 分类标签：真推理(3/3 动作) / 半成品(1-2) / 贴标签(0，只有一句 transitivity 断言)
  5. 对比：传递题 vs 非传递题（"认识"这类）的推理深度 —— 非传递题最容易露馅，
     因为模型不能靠套传递模板蒙混，必须真的论证为什么不能推。

用法：
    python trace_analyze.py            # 全量分析
    python trace_analyze.py --show S07 # 打印指定 qid 的轨迹全文
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "imprint_lib.jsonl")

# 三类推理动作的信号词（中英双语，hy4 用英文思考）
SIG = {
    "关系性质判断": [
        r"transitiv", r"非传递", r"传递性", r"传递关系", r"strict (partial )?order",
        r"irreflexive", r"asymmetric", r"is a strict", r"partial order",
    ],
    "逐条验前提": [
        r"premise", r"前提", r"given", r"from the (first|second)", r"step \d",
        r"逐条", r"first,", r"secondly", r"we have.*and.*therefore", r"由.*且.*可(得|推)",
    ],
    "反例检验": [
        r"counterexample", r"反例", r"例外", r"exception", r"trick",
        r"is there any", r"could fail", r"not necessarily", r"does not hold",
        r"不成立的情况", r"无法推出",
    ],
}
# 贴标签式断言：只说结论，不展开
LABEL_ONLY = [
    r"so (the )?(conclusion|it) (holds|is)", r"therefore.*成立",
    r"this is transitive.*so", r"is transitive\.",
]
CJK = re.compile(r"[\u4e00-\u9fff]")


def strip_prompt_echo(trace, prompt):
    """去掉轨迹开头对 prompt 的复述 —— 那段我们自己有，是纯噪音。

    必须用「prompt 头部定位起点 + 尾部定位终点」，只找头部会在复述块
    内部的空行处提前收刀，把噪音低估成 2%（实测真实噪音约 15%）。
    """
    if not trace or not prompt:
        return trace, 0
    head, tail = prompt[:24], prompt[-24:]
    i = trace.find(head)
    if i < 0 or i > len(trace) * 0.6:
        return trace, 0
    j = trace.find(tail, i)
    if j < 0:
        return trace, 0
    cut = j + len(tail)
    nl = trace.find("\n\n", cut)          # 吃到复述块结束后的第一个空行
    if nl > 0:
        cut = nl + 2
    return trace[cut:], cut


def analyze(imp):
    trace = imp.get("trace") or ""
    prompt = imp.get("meta", {}).get("source_prompt", "")
    net, echo = strip_prompt_echo(trace, prompt)
    low = net.lower()
    hits = {k: bool(re.search(p, low)) for k, p in
            [(k, "|".join(v)) for k, v in SIG.items()]}
    n_act = sum(hits.values())
    label_only = bool(re.search("|".join(LABEL_ONLY), low))
    cjk = len(CJK.findall(net))
    zh_ratio = cjk / max(len(net), 1)
    if n_act == 3:
        cls = "真推理"
    elif n_act in (1, 2):
        cls = "半成品"
    elif label_only:
        cls = "贴标签"
    else:
        cls = "无结构"
    return {
        "qid": imp.get("qid"), "rel": imp.get("rel"),
        "rel_class": imp.get("rel_class"), "kind": imp.get("kind"),
        "raw": len(trace), "echo": echo,
        "net": len(net), "net_ratio": len(net) / max(len(trace), 1),
        "acts": hits, "n_act": n_act, "cls": cls,
        "zh_ratio": zh_ratio, "hits": imp.get("hits", 0),
        "hit_ok": imp.get("hit_ok", 0), "trace": trace, "net_text": net,
    }


def main():
    if "--show" in sys.argv:
        want = sys.argv[sys.argv.index("--show") + 1]
        with open(LIB, encoding="utf-8") as f:
            for line in f:
                imp = json.loads(line)
                if imp.get("qid") == want:
                    a = analyze(imp)
                    print(f"=== {want} [{a['cls']}] {a['rel']} "
                          f"raw={a['raw']} 净={a['net']} 中文占比={a['zh_ratio']:.0%}")
                    print("--- 净推理段（已剔除 prompt 复述）---")
                    print(a["net_text"])
                    return
        print(f"[!] 未找到 {want}")
        return

    if not os.path.exists(LIB):
        print(f"[!] 印记库不存在: {LIB}")
        return
    items = [json.loads(l) for l in open(LIB, encoding="utf-8") if l.strip()]
    # 印记库是 jsonl 混合：印记 + record_hit 事件。事件无 qid，分析器只关心印记。
    items = [i for i in items if "event" not in i]
    if not items:
        print("[!] 印记库为空")
        return
    rs = [analyze(i) for i in items]
    # dry 模式的占位串不是真痕，必须排除，否则会把"无痕"统计成"有痕"
    with_tr = [r for r in rs if r["raw"] > 0 and r["trace"] != "(dry 无轨迹)"]

    print("=" * 72)
    print("痕迹质量分析 · 采到的 reasoning_content 是推理还是贴标签？")
    print("=" * 72)
    print(f"印记总数 {len(rs)} 条，其中有痕 {len(with_tr)} 条\n")

    if not with_tr:
        print("无痕可分析（可能跑在 dry 模式，或 API 未返回 reasoning_content）")
        return

    avg_raw = sum(r["raw"] for r in with_tr) // len(with_tr)
    avg_net = sum(r["net"] for r in with_tr) // len(with_tr)
    avg_echo = sum(r["echo"] for r in with_tr) // len(with_tr)
    print(f"平均总长 {avg_raw} 字  |  平均净推理 {avg_net} 字  |  "
          f"平均 prompt 复述噪音 {avg_echo} 字 ({avg_echo/max(avg_raw,1):.0%})\n")

    cls_cnt = Counter(r["cls"] for r in with_tr)
    print("【推理完整度分级】")
    for c in ("真推理", "半成品", "贴标签", "无结构"):
        if cls_cnt.get(c):
            print(f"  {c:8s} {cls_cnt[c]:2d} 条  "
                  f"{'█' * cls_cnt[c]} ({cls_cnt[c]/len(with_tr):.0%})")
    print("    判定标准：真推理 = 三类动作齐全（关系性质 + 验前提 + 找反例）\n")

    print("【三类推理动作覆盖率】")
    for k in SIG:
        n = sum(1 for r in with_tr if r["acts"][k])
        print(f"  {k:12s} {n:2d}/{len(with_tr)}  ({n/len(with_tr):.0%})")
    print()

    avg_zh = sum(r["zh_ratio"] for r in with_tr) / len(with_tr)
    print(f"【语言】平均中文占比 {avg_zh:.0%}  ← 偏低说明模型在用英文思考")

    # 传递 vs 非传递：非传递题是照妖镜
    tr = [r for r in with_tr if r["rel_class"] == "transitive"]
    nt = [r for r in with_tr if r["rel_class"] == "non_transitive"]
    if tr and nt:
        print("\n【照妖镜：传递题 vs 非传递题】")
        for name, g in (("传递(可套模板)", tr), ("非传递(不能套)", nt)):
            a = sum(r["n_act"] for r in g) / len(g)
            z = sum(1 for r in g if r["cls"] == "真推理")
            print(f"  {name:16s} {len(g):2d} 条 | 平均动作 {a:.1f}/3 | "
                  f"真推理 {z}/{len(g)} | 平均净长 "
                  f"{sum(r['net'] for r in g)//len(g)} 字")
        d = (sum(r["n_act"] for r in nt) / len(nt)) - (sum(r["n_act"] for r in tr) / len(tr))
        if d > 0.3:
            print(f"  → 非传递题推理更深(+{d:.1f})：模型确实被逼着论证，不是套模板")
        elif d < -0.3:
            print(f"  → 非传递题反而更浅({d:.1f})：可疑，可能在靠直觉而非结构")
        else:
            print(f"  → 两者深度相当(差 {d:+.1f})：推理深度与题型无关，更像固定套路")

    print("\n【逐条明细】")
    print(f"{'qid':5s} {'rel':10s} {'rel_class':15s} {'净长':>5s} {'动作':>5s} "
          f"{'分级':7s} {'复用':>6s}")
    for r in sorted(rs, key=lambda x: -x["n_act"]):
        reuse = f"{r['hit_ok']}/{r['hits']}" if r["hits"] else "-"
        print(f"{r['qid']:5s} {str(r['rel'])[:10]:10s} {str(r['rel_class'])[:15]:15s} "
              f"{r['net']:5d} {r['n_act']:>2d}/3  {r['cls']:7s} {reuse:>6s}")

    pct = cls_cnt.get("真推理", 0) / len(with_tr)
    print("\n" + "=" * 72)
    if pct >= 0.6:
        print(f"判：痕有营养（{pct:.0%} 为真推理）→ 值得投 Q1 拆解器")
    elif pct >= 0.3:
        print(f"判：痕有但偏薄（{pct:.0%} 真推理）→ 需先优化 prompt 逼出结构再谈拆解")
    else:
        print(f"判：痕基本是沙（{pct:.0%} 真推理）→ 当前 prompt 下留痕无意义，"
              f"先解决推理诱导")
    print("=" * 72)


if __name__ == "__main__":
    main()
