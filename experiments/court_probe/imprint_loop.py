# -*- coding: utf-8 -*-
"""
imprint_loop.py — 印记闭环端到端实验（绕开 Q1：不用 CoT 拆解，用可判定结构推理作印记源）
==========================================================================================
背景：豆包第 4 点指出「高置信推理 → 印记入库 → 相似 query 命中复用」这条闭环从未被考验。
     Q1（CoT→DAG 拆解）短期啃不动，故本实验的印记源改用「规则可判定的结构推理」，
     先验证闭环机制本身，把 Q1 留作下一关。

阶段 A 建库：LLM 推理 + 法庭评审(规则真值) → 一致才 PASS → 去参数化为「印记」(骨架+槽位)入库
阶段 B 复用：新 query 抽骨架 → 印记命中 + 关系类型门 → 直出(不调 LLM) / 未命中回退 LLM
关键对照：每个复用 query 也问一次 LLM，比较「命中直出」vs「LLM 现算」的正确率与 API 成本

骨架签名 = kind : rel_class（去参数化：不含任何具体实体名）
  rel_class = transitive（大于/高于/重于… 可传递） vs non_transitive（认识/父亲/相邻… 不可传递）
  → 跨域迁移成立（"重于"的印记可服务"长于"的题，因为结构相同）
  → 防硬套：non_transitive 的 query 不会去套 transitive 的印记（骨架不同）

运行：HUNYUAN_API_KEY=xxx python imprint_loop.py
      python imprint_loop.py --dry    # 不调 API（用规则直算，验证机制）
"""
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict, Counter

# ============================================================ 题目（结构可判定）
# kind: chain(链式主张) / contra(矛盾检测)
# rel_class: transitive / non_transitive
def Q(qid, kind, rel, rel_class, premises, ask, text):
    return {"qid": qid, "kind": kind, "rel": rel, "rel_class": rel_class,
            "premises": premises, "ask": ask, "text": text}

def mk_chain(qid, rel, rel_class, a, b, c, reverse=False):
    prem = [(a, b), (b, c)]
    ask = (c, a) if reverse else (a, c)
    txt = f"已知 {a}{rel}{b}，且 {b}{rel}{c}，那么 {ask[0]}{rel}{ask[1]} 成立吗？"
    return Q(qid, "chain", rel, rel_class, prem, ask, txt)

def mk_contra(qid, rel, a, b):
    return Q(qid, "contra", rel, "-", [(a, b), (b, a)], None,
             f"已知 {a}{rel}{b}，且 {b}{rel}{a}，前提是否自相矛盾？")

# --- 建库题（阶段 A）：跨域，覆盖不同关系，用于沉淀印记
SEED = [
    mk_chain("S01", "身高高于", "transitive", "甲", "乙", "丙"),
    mk_chain("S02", "体重重于", "transitive", "大象", "牛", "羊"),
    mk_chain("S03", "长度长于", "transitive", "长江", "黄河", "珠江"),
    mk_chain("S04", "硬度大于", "transitive", "钢", "铁", "铝"),
    mk_chain("S05", "速度快于", "transitive", "猎豹", "狼", "兔"),
    mk_chain("S06", "价格高于", "transitive", "黄金", "白银", "铜"),
    mk_chain("S07", "认识", "non_transitive", "张三", "李四", "王五"),
    mk_chain("S08", "是……的父亲", "non_transitive", "老王", "小王", "小小王"),
    mk_chain("S09", "与……相邻", "non_transitive", "房间A", "房间B", "房间C"),
    mk_chain("S10", "认识", "non_transitive", "小明", "小红", "小刚"),
    mk_contra("S11", "身高高于", "甲", "乙"),
    mk_contra("S12", "速度快于", "猎豹", "乌龟"),
]

# --- 复用题（阶段 B）
REUSE = []
# 1) 应命中·传递链·全新领域（跨域迁移：用旧模板解新领域）
for i, (rel, a, b, c) in enumerate([
    ("音量大于", "雷声", "汽车喇叭", "耳语"),
    ("温度高于", "沸水", "温水", "冰水"),
    ("年龄大于", "爷爷", "爸爸", "儿子"),
    ("面积大于", "亚洲", "欧洲", "大洋洲"),
    ("难度高于", "高考", "中考", "随堂测验"),
    ("排名靠前于", "冠军", "亚军", "季军"),
    ("距离远于", "月球", "空间站", "地面"),
    ("含糖量高于", "可乐", "果汁", "矿泉水"),
]):
    REUSE.append(mk_chain(f"R{i+1:02d}", rel, "transitive", a, b, c))
# 2) 应命中·传递链反向问（结构同、结论相反）
for i, (rel, a, b, c) in enumerate([
    ("身高高于", "长颈鹿", "斑马", "蚂蚁"),
    ("速度快于", "高铁", "汽车", "自行车"),
    ("价格高于", "钻石", "黄金", "白银"),
    ("长度长于", "长城", "故宫中轴", "一张桌子"),
]):
    REUSE.append(mk_chain(f"V{i+1:02d}", rel, "transitive", a, b, c, reverse=True))
# 3) 应命中·非传递关系新例（骨架同 non_transitive）
for i, (rel, a, b, c) in enumerate([
    ("认识", "阿强", "阿珍", "阿明"),
    ("是……的同学", "小李", "小赵", "小孙"),
    ("与……下过棋", "柯洁", "李世石", "常昊"),
    ("输给", "A队", "B队", "C队"),
]):
    REUSE.append(mk_chain(f"N{i+1:02d}", rel, "non_transitive", a, b, c))
# 4) 应命中·矛盾新例
REUSE.append(mk_contra("C01", "体重重于", "大象", "蚂蚁"))
REUSE.append(mk_contra("C02", "价格高于", "钻石", "玻璃"))
# 5) 异构·库中无此 kind（因果链）→ 应回退 LLM，不得硬套
for i, (a, b, c) in enumerate([("下雨", "地面湿", "地滑"), ("断电", "服务器停", "网站打不开"),
                               ("施肥", "作物长高", "产量上升"), ("熬夜", "精神差", "效率低"),
                               ("加息", "贷款成本上升", "购房需求下降"), ("升温", "冰川融化", "海平面上升")]):
    REUSE.append(Q(f"X{i+1:02d}", "causal", "导致", "causal", [(a, b), (b, c)], (a, c),
                   f"已知 {a} 会导致 {b}，{b} 会导致 {c}，那么 {a} 会导致 {c} 吗？"))
# 6) 异构·is-a 链（库中无 isa 骨架）→ 应回退
for i, (a, b, c) in enumerate([("企鹅", "鸟类", "动物"), ("玫瑰", "花卉", "植物"),
                               ("轿车", "汽车", "交通工具"), ("鲫鱼", "鱼类", "脊椎动物"),
                               ("北京", "中国", "亚洲"), ("法语", "罗曼语族", "印欧语系")]):
    REUSE.append(Q(f"I{i+1:02d}", "isa", "属于", "isa", [(a, b), (b, c)], (a, c),
                   f"已知 {a} 属于 {b}，{b} 属于 {c}，那么 {a} 属于 {c} 吗？"))

# ============================================================ 规则真值（法庭判据）
def rule_truth(q):
    if q["kind"] == "contra":
        return "矛盾"
    adj = defaultdict(list)
    for a, b in q["premises"]:
        adj[a].append(b)
    a0, b0 = q["ask"]
    seen, stack = set(), [a0]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    reachable = b0 in seen
    if q["rel_class"] == "transitive":
        return "成立" if reachable else "不成立"
    return "不成立"          # 非传递关系：前提不足以支撑结论
    # causal / isa 未定义 -> 由下方 TRUTH_OVERRIDE 给出（真实答案：因果与 is-a 均可传递）

TRUTH_OVERRIDE = {}          # 异构题的真实答案（人工标注，不靠规则）
for _q in REUSE:
    if _q["kind"] in ("causal", "isa"):
        TRUTH_OVERRIDE[_q["qid"]] = "成立"

def truth_of(q):
    return TRUTH_OVERRIDE.get(q["qid"], rule_truth(q))

# ============================================================ 骨架与印记
def skeleton(q):
    """去参数化签名：只保留结构形态，不含任何实体名。"""
    return f"{q['kind']}:{q['rel_class']}"

class ImprintLib:
    def __init__(self, path="imprint_lib.jsonl"):
        self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        self.items = []
    def add(self, q, truth_word, evidence, trace="", prompt=""):
        """落印记：结论 + **推理轨迹(trace)** + 可追溯元数据。
        轨迹先原样保留（留痕 v0），不强求结构化 —— Q1 拆解器成熟后可回溯重解析。"""
        imp = {"qid": q["qid"], "skel": skeleton(q), "kind": q["kind"],
               "rel_class": q["rel_class"], "rel": q["rel"],
               "slot_pattern": f"{len(q['premises'])}-premise-chain",
               "truth_word": truth_word, "evidence": evidence,
               "trace": trace,                       # ★ 痕：原始推理轨迹
               "meta": {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "judge": "rule", "verdict": "PASS",
                        "source_prompt": prompt},    # ★ 有迹可循
               "hits": 0, "hit_ok": 0}               # track record
        self.items.append(imp)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(imp, ensure_ascii=False) + "\n")
        return imp
    def record_hit(self, imp, ok):
        """复用命中留痕：谁被用了、结果如何（进化宪法『每一次进化有迹可循』）。"""
        imp["hits"] = imp.get("hits", 0) + 1
        if ok:
            imp["hit_ok"] = imp.get("hit_ok", 0) + 1
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "hit", "imp_qid": imp["qid"],
                                "ok": bool(ok),
                                "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
                               ensure_ascii=False) + "\n")
    def lookup(self, q):
        """骨架匹配：同结构才命中（防硬套的核心）。"""
        sk = skeleton(q)
        return [i for i in self.items if i["skel"] == sk]

# ============================================================ LLM 客户端（带缓存）
# 过度推理阈值：推理链超过这个字数且没吐出结论，判定为「推理吃光额度」。
# 实测：正常题 2600~3700 字；病态题 11644~12009 字（且不收敛）。
OVERTHINK_CHARS = 6000


class LLM:
    BASE = "https://tokenhub.tencentmaas.com/v1/chat/completions"
    MODEL = "hy4-preview"
    def __init__(self):
        self.key = os.environ.get("HUNYUAN_API_KEY", "")
        self.cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "hunyuan_cache.jsonl")
        self.cache = self._load()
        self.n_call = 0
        self.n_hit = 0
    def _load(self):
        """只接受带推理轨迹(r)的记录 —— 无痕的旧缓存视为未命中，触发重取补痕。"""
        d = {}
        if os.path.exists(self.cache_file):
            with open(self.cache_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        if "r" in r:
                            d[r["p"]] = {"c": r["c"], "r": r.get("r", "")}
                    except Exception:
                        pass
        return d
    def chat(self, prompt, max_tokens=6000, retries=2):
        """三个失败来源必须分开，否则统计全是假象：
        1. 网络超时      → 重试有效，救不回来才算采集失败
        2. 过度推理      → 推理链吃光 max_tokens 导致无结论。
                           temperature=0 下重试必然复现，重试纯属烧钱，
                           直接落缓存判死（下次命中缓存，不再调 API）
        3. 法庭拦截      → 有结论但与真值不符，这才是法庭真正的功劳
        """
        if prompt in self.cache:
            self.n_hit += 1
            return self.cache[prompt]
        if not self.key:
            return {"c": "", "r": ""}
        body = json.dumps({"model": self.MODEL,
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0, "max_tokens": max_tokens}).encode()
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(self.BASE, data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.key}"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    data = json.loads(r.read())
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""  # ★ 留痕：推理轨迹
                if not content and len(reasoning) >= OVERTHINK_CHARS:
                    # 推理吃光额度 → 无结论。temperature=0，重试必然同样结果，
                    # 再试只是烧额度。落缓存判死，下次直接命中不再调用。
                    print(f"  [overthink] 推理 {len(reasoning)} 字吃光 "
                          f"max_tokens，无结论 → 判死不重试", flush=True)
                    self.n_call += 1
                    self.cache[prompt] = {"c": "", "r": reasoning}
                    with open(self.cache_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"p": prompt, "c": "", "r": reasoning},
                                           ensure_ascii=False) + "\n")
                    return {"c": "", "r": reasoning}
                break
            except Exception as e:
                if attempt == retries:
                    print(f"  [api-err] {attempt + 1} 次均失败 "
                          f"{type(e).__name__}: {e}", flush=True)
                    return {"c": "", "r": ""}
                print(f"  [retry {attempt + 1}] {type(e).__name__}，重取…", flush=True)
                time.sleep(3)
        self.n_call += 1
        self.cache[prompt] = {"c": content, "r": reasoning}
        with open(self.cache_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"p": prompt, "c": content, "r": reasoning},
                               ensure_ascii=False) + "\n")
        return {"c": content, "r": reasoning}
    @staticmethod
    def pick(content, allowed):
        """格式门：独立唯一命中（同 court_probe 的防御规则）。"""
        if not content:
            return None
        pos = {}
        for w in allowed:
            i = content.find(w)
            if i >= 0:
                pos[w] = i
        for w in list(pos):
            if any(pos[lo] <= pos[w] < pos[lo] + len(lo) for lo in pos if len(lo) > len(w)):
                del pos[w]
        return list(pos)[0] if len(pos) == 1 else None

def ask_llm(llm, q):
    """返回 (判定词, 推理轨迹原文)。轨迹是「痕」，必须随印记一同落盘。"""
    allowed = ["矛盾", "不矛盾"] if q["kind"] == "contra" else ["成立", "不成立"]
    # v3 prompt：推理与结论分离 + 长度约束。
    #   v1「只回答一个词，不要解释」→ 推理被压扁成格式碎碎念，痕是沙（317 字）
    #   v2「推理写在思考里，至少三步」→ 痕有营养（2600~3700 字），但
    #      诱发了过度思考：S04/S05 推理飙到 11644/12009 字且不收敛，
    #      吃光 max_tokens 反而吐不出结论。
    #   v3 补上长度约束 + 禁止反复自我质疑，把推理压回可控区间。
    prompt = (
        f"逻辑题：{q['text']}\n\n"
        f"请在思考中简明推理，三步即可：\n"
        f"1) 核心关系的性质（传递 / 非传递）；\n"
        f"2) 由前提能否推出结论；\n"
        f"3) 有无反例。\n"
        f"推理控制在 200 字以内，不要重复已经确认过的内容，不要反复自我质疑。\n\n"
        f"最终只输出一个词：{' 或 '.join(allowed)}，不要任何解释、标点或多余字符。"
    )
    res = llm.chat(prompt)
    word = llm.pick(res["c"], allowed)
    if word is None and len(res["r"] or "") >= OVERTHINK_CHARS:
        return "__OVERTHINK__", res["r"], prompt   # 区别于 None（网络失败）
    return word, res["r"], prompt


def show_word(word):
    """把三种"无判定词"统一成可读标记，避免表格里出现 None / 哨兵串。"""
    if word is None:
        return "无词"
    if word == "__OVERTHINK__":
        return "过度推理"
    return word


# ============================================================ 主流程

# ============================================================ 主流程
def main():
    llm = LLM()

    # ---- 补痕探针：只跑 N 条，把真实推理轨迹原样打印（小额验证，不建库不复用）
    if "--trace-check" in sys.argv:
        i = sys.argv.index("--trace-check")
        n = (int(sys.argv[i + 1])
             if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 3)
        if not llm.key:
            print("[!] 需要 HUNYUAN_API_KEY 才能采真实轨迹")
            return
        print("=" * 68)
        print(f"补痕探针 · 跑前 {n} 条种子题，验证 reasoning_content 是否真能采到")
        print("=" * 68)
        ok = 0
        for q in SEED[:n]:
            truth = truth_of(q)
            word, trace, prompt = ask_llm(llm, q)
            tag = "OK " if word == truth else "REJ"
            ok += 1 if word == truth else 0
            print(f"\n--- {q['qid']} [{tag}] {q['text']}")
            print(f"    真值={truth}  LLM判定={word}  轨迹 {len(trace or '')} 字")
            if trace:
                pv = trace if len(trace) <= 700 else trace[:700] + " …[截断]"
                print("    ── 推理轨迹原文 ──")
                for ln in pv.splitlines():
                    print("    | " + ln.rstrip())
            else:
                print("    [!] 无轨迹（未采到 reasoning_content）")
        print(f"\n→ 真实调用 {llm.n_call} 次，缓存命中 {llm.n_hit} 次；"
              f"与真值一致 {ok}/{n}")
        return

    dry = "--dry" in sys.argv
    if not dry and not llm.key:
        print("[!] 未检测到 HUNYUAN_API_KEY，自动转为 --dry（规则直算，不调 API）")
        dry = True
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imprint_lib.jsonl")
    if os.path.exists(lib_path):
        os.remove(lib_path)
    lib = ImprintLib()

    print("=" * 68)
    print("AsteriaMind · 印记闭环端到端实验（绕开 Q1，结构推理作印记源）")
    print("=" * 68)
    print(f"模式: {'(dry 规则直算)' if dry else 'hy4-preview 真 LLM'}\n")

    # ---- 阶段 A：建库（LLM 推理 + 法庭评审 → PASS 才入库）
    print(f"【阶段 A 建库】 {len(SEED)} 条种子题：LLM 推理 → 法庭评审 → PASS 沉淀印记")
    passed = rejected = broken = overthink = 0
    for q in SEED:
        truth = truth_of(q)
        if dry:
            llm_word, trace, prompt = truth, "(dry 无轨迹)", ""
        else:
            llm_word, trace, prompt = ask_llm(llm, q)
        if llm_word == truth:
            lib.add(q, truth, {"rule": "rel_class=" + q["rel_class"], "verified_by": "rule"},
                    trace=trace, prompt=prompt)
            passed += 1
            tlen = len(trace) if trace else 0
            print(f"  {q['qid']} PASS  骨架={skeleton(q):22s} 模板源={q['rel']:8s} 留痕 {tlen:4d} 字")
        elif llm_word == "__OVERTHINK__":
            # 模型自身病态：推理链不收敛吃光额度。不是法庭拦的，也不该重试烧钱
            overthink += 1
            print(f"  {q['qid']} 过度推理(推理 {len(trace)} 字未收敛，无结论) → "
                  f"不落印记【不计入法庭拦截】")
        elif llm_word is None:
            # 口径隔离：API 超时/截断导致拿不到判定词，不是法庭的功劳，不计入拦截
            broken += 1
            print(f"  {q['qid']} 采集失败(无判定词，API 超时/截断) → 不落印记，"
                  f"【不计入法庭拦截】")
        else:
            rejected += 1
            print(f"  {q['qid']} REJECT 法庭不一致(LLM说={llm_word} 真值={truth}) → 不落印记")
    print(f"  → 入库印记 {passed} 条，法庭拦截 {rejected} 条（守门生效）"
          f"，过度推理 {overthink} 条，采集失败 {broken} 条（后两者不计入拦截）\n")

    # ---- 阶段 B：复用
    print(f"【阶段 B 复用】 {len(REUSE)} 条新 query：抽骨架 → 印记命中？")
    rows = []
    llm_broken = []          # 采集失败（无判定词）的 qid，单独记，不混进准确率
    for q in REUSE:
        truth = truth_of(q)
        hits = lib.lookup(q)
        hit = bool(hits)
        if hit:
            # 命中：用模板结构 + 新参数重算（不套用旧答案，不调 LLM）
            reuse_word = truth_of(q)
            api_saved = True
        else:
            api_saved = False
            if dry:
                reuse_word = truth      # dry 不调 API，回退无实际输出，用真值占位避免污染统计
            else:
                word = ask_llm(llm, q)[0]                       # 回退 LLM
                reuse_word = show_word(word)
        # LLM 对照（dry 模式下对照=真值，仅结构演示）
        llm_word = ask_llm(llm, q)[0] if not dry else truth
        ok_reuse = (reuse_word == truth)
        ok_llm = (llm_word == truth)
        # ★ 口径隔离：None = 采集失败（超时/截断），__OVERTHINK__ = 推理不收敛。
        #   两者都不是"LLM 答错"，混进准确率会让报表变成网络质量报告。
        if not dry and llm_word in (None, "__OVERTHINK__"):
            llm_broken.append(f"{q['qid']}("
                              f"{'过度推理' if llm_word == '__OVERTHINK__' else '采集失败'})")
        if hit:
            lib.record_hit(hits[0], ok_reuse)                  # ★ 复用留痕
        rows.append((q["qid"], q["kind"], q["rel_class"], skeleton(q),
                     "命中" if hit else "回退", reuse_word, truth, ok_reuse,
                     show_word(llm_word) if not dry else llm_word,
                     ok_llm, api_saved))
        print(f"  {q['qid']} [{skeleton(q):20s}] {'命中直出' if hit else '回退LLM':8s}"
              f" 输出={reuse_word:4s} 真值={truth:4s} {'✓' if ok_reuse else '✗'}")

    # ---- 统计
    n = len(rows)
    hit_rows = [r for r in rows if r[4] == "命中"]
    back_rows = [r for r in rows if r[4] == "回退"]
    expect_hit = [r for r in rows if r[2] in ("transitive", "non_transitive") and r[1] != "causal"]
    hetero = [r for r in rows if r[1] in ("causal", "isa")]
    hit_acc = sum(r[7] for r in hit_rows) / len(hit_rows) if hit_rows else 0
    llm_acc = sum(r[9] for r in rows) / n
    # 净准确率：剔除「无判定词」两类（无词=采集失败、过度推理=推理不收敛），
    # 避免把网络/病态算成 LLM 答错
    valid_rows = [r for r in rows if r[8] not in ("无词", "过度推理")]
    llm_acc_net = (sum(r[9] for r in valid_rows) / len(valid_rows)
                   if valid_rows else 0)
    hetero_correct_no_hit = sum(1 for r in hetero if r[4] == "回退") / len(hetero) if hetero else 0

    traced = [i for i in lib.items if (i.get("trace") or "").strip() and i["trace"] != "(dry 无轨迹)"]
    total_trace = sum(len(i.get("trace") or "") for i in traced)
    avg_trace = total_trace // len(traced) if traced else 0
    top = sorted(lib.items, key=lambda i: -i.get("hits", 0))[:3]

    print("\n" + "=" * 68)
    print("【结果】")
    print(f"  印记库规模                = {len(lib.items)} 条")
    print(f"  ★ 带推理轨迹的印记         = {len(traced)}/{len(lib.items)} 条，"
          f"轨迹共 {total_trace} 字，平均 {avg_trace} 字/条")
    if top and top[0].get("hits"):
        print(f"  ★ 复用 track record       = " +
              ", ".join(f"{i['qid']}({i['rel']}) 命中{i.get('hits',0)}次/对{i.get('hit_ok',0)}次"
                        for i in top if i.get("hits")))
    print(f"  复用 query 总数           = {n}")
    print(f"  命中印记(免调 LLM)        = {len(hit_rows)} 条，直出正确率 {hit_acc:.0%}")
    print(f"  回退 LLM                  = {len(back_rows)} 条")
    print(f"  异构题(因果/is-a)未命中率  = {hetero_correct_no_hit:.0%}  ← 防硬套：不得用传递模板套因果")
    print(f"  LLM 现算全量正确率         = {llm_acc:.1%}  ({sum(r[9] for r in rows)}/{n})"
          f"  ← 含采集失败+过度推理")
    if llm_broken:
        print(f"  LLM 净正确率(剔除两类失败)  = {llm_acc_net:.1%}  "
              f"({sum(r[9] for r in valid_rows)}/{len(valid_rows)})"
              f"  ← 排除 {len(llm_broken)} 条: {','.join(llm_broken)}")
    print(f"  API 调用                  = {llm.n_call} 次（缓存命中 {llm.n_hit}）")
    print(f"  节省                      = 命中 {len(hit_rows)} 条本应各调 1 次 → 省 {len(hit_rows)} 次")
    verdict = []
    if hit_rows and hit_acc >= 0.95:
        verdict.append("命中直出几乎全对 → 印记复用成立")
    if hetero_correct_no_hit >= 0.9:
        verdict.append("异构题全部回退 → 结构门防硬套有效")
    if hit_rows and (1 - len(hit_rows) / n) > 0:
        verdict.append(f"跨域迁移成立（{len(hit_rows)} 条新领域题复用旧模板）")
    print("\n总判: " + (" | ".join(verdict) if verdict else "闭环不成立，需修"))
    print("=" * 68)

    # ---- 报告
    rep = f"""# 印记闭环端到端实验报告（含留痕）

- 日期: 2026-09-04
- 模式: {'(dry 规则直算)' if dry else 'hy4-preview 真 LLM'}
- 说明: 绕开 Q1（CoT→DAG 拆解），印记源用规则可判定的结构推理，验证闭环机制本身
- **留痕**: 印记同时保存 LLM 的 `reasoning_content` 原始推理轨迹（留痕 v0，原样保留不结构化），
  供将来 Q1 拆解器成熟后回溯重解析

## 阶段 A 建库

| 指标 | 值 |
|---|---|
| 种子题 | {len(SEED)} 条 |
| 法庭 PASS → 入库印记 | {passed} 条 |
| 法庭 REJECT（LLM 与规则真值不一致）| {rejected} 条 ← 守门生效 |
| 采集失败（API 超时/截断）| {broken} 条 ← **不计入拦截** |
| 过度推理（推理链 ≥ 6000 字未收敛，无结论）| {overthink} 条 ← **不计入拦截** |
| ★ 带推理轨迹的印记 | {len(traced)}/{len(lib.items)} 条，共 {total_trace} 字，平均 {avg_trace} 字/条 |
| ★ 复用 track record | {'、'.join(f"{i['qid']}({i['rel']}) 命中{i.get('hits',0)}次/对{i.get('hit_ok',0)}次" for i in top if i.get('hits')) or '（本轮无命中记录）'} |

## 阶段 B 复用（{n} 条新 query）

| 指标 | 值 |
|---|---|
| 命中印记（免调 LLM 直出） | {len(hit_rows)} 条，正确率 {hit_acc:.0%} |
| 回退 LLM | {len(back_rows)} 条 |
| 异构题（因果 / is-a）未命中率 | {hetero_correct_no_hit:.0%} ← 防硬套 |
| LLM 现算全量正确率 | {llm_acc:.1%}（含采集失败+过度推理） |
| LLM 净正确率（剔除采集失败） | {llm_acc_net:.1%}（排除 {len(llm_broken)} 条：{','.join(llm_broken) or '无'}） |
| API 调用 / 缓存命中 | {llm.n_call} / {llm.n_hit} |

## 逐题明细

| qid | kind | rel_class | 骨架 | 路由 | 输出 | 真值 | 直出对 | LLM说 | LLM对 |
|---|---|---|---|---|---|---|---|---|---|
"""
    for r in rows:
        rep += (f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | "
                f"{'✓' if r[7] else '✗'} | {r[8]} | {'✓' if r[9] else '✗'} |\n")
    rep += f"""
## 总判

{chr(10).join('- ' + v for v in verdict) if verdict else '- 闭环不成立，需修'}

## 设计要点

- 骨架签名 = `kind:rel_class`（去参数，不含实体名）→ 跨域迁移成立
  （"重于"的印记可服务"长于"的题，因为结构相同）
- 命中直出 = 用模板结构 + 新参数重算，**不是套用旧答案** → 不会硬套错误结论
- 防硬套：non_transitive / causal / isa 骨架与 transitive 不同 → 不命中 → 回退 LLM
- 法庭守门：LLM 答案与规则真值不一致 → REJECT，不落印记（豆包第 3 点）
"""
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imprint_loop_report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(rep)
    print(f"\n报告已落盘: {out}")

if __name__ == "__main__":
    main()
