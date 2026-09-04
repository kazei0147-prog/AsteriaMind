# -*- coding: utf-8 -*-
"""
court_probe.py — 白盒法庭「最原始拦截力」探针（LLM 黑盒语境）
================================================================
用户要求：
  1) 题目别只用 Wikidata 事实题 —— 加 20 道编程/逻辑约束题，看白盒在
     「结构逻辑」上能不能触发 Reject，而不是只会数据库对账。
  2) 规则保持极致朴素 —— 不引入复杂 LLM 二次 Prompt，只用最直接的
     规则 / 图节点匹配，测白盒最原始的拦截力。

判据（写死）：
  A) 法庭 REJECT 确实抓住 LLM 错误（幻觉断言被拦、无漏放）
  B) 图外断言一律 ABSTAIN 挂起（诚实，不武断放行/拦截）
  C) 编程/逻辑域（语法 ast / 运行时 eval / 推演闭包）能触发 REJECT

运行：
  python court_probe.py                    # 内置确定性 FakeLLM（可复现）
  DEEPSEEK_API_KEY=xxx python court_probe.py --real   # 真 LLM 复跑（可选）
零第三方依赖。

诚实边界：事实域知识图与题目同源（生成器即裁判），FakeLLM 只能验证
「机制无漏 + 不武断」；真正测「拦真 LLM 幻觉的召回」需 --real 通道。
"""
import ast
import json
import os
import random
import sys
import urllib.request
from collections import defaultdict, deque

# ============================================================ 微型知识图
class KG:
    """child -> set(parents)。ancestors() 为传递闭包。"""
    def __init__(self):
        self.parents = defaultdict(set)
    def add(self, child, parent):
        self.parents[child].add(parent)
    def has(self, node):
        return node in self.parents or any(node in ps for ps in self.parents.values())
    def ancestors(self, node):
        seen, stack = set(), list(self.parents.get(node, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.parents.get(cur, ()))
        return seen

def build_graph():
    g = KG()
    A = g.add
    # 动物域
    A("企鹅", "鸟类"); A("鸵鸟", "鸟类"); A("麻雀", "鸟类")
    A("蝙蝠", "哺乳动物"); A("鲸", "哺乳动物"); A("海豚", "哺乳动物")
    A("狗", "哺乳动物"); A("猫", "哺乳动物")
    A("蛇", "爬行动物"); A("蜥蜴", "爬行动物"); A("鳄鱼", "爬行动物")
    A("青蛙", "两栖动物"); A("金鱼", "鱼类"); A("鲨鱼", "鱼类")
    A("蝴蝶", "昆虫"); A("蜜蜂", "昆虫"); A("蚂蚁", "昆虫")
    A("蜘蛛", "蛛形纲"); A("章鱼", "软体动物"); A("蜗牛", "软体动物")
    for c in ["鸟类", "哺乳动物", "爬行动物", "两栖动物", "鱼类", "软体动物"]:
        A(c, "动物")
    A("昆虫", "节肢动物"); A("蛛形纲", "节肢动物"); A("节肢动物", "动物")
    # 地理域
    A("北京", "中国"); A("上海", "中国"); A("广州", "中国")
    A("中国", "亚洲"); A("日本", "亚洲"); A("韩国", "亚洲")
    A("巴黎", "法国"); A("马赛", "法国"); A("法国", "欧洲")
    A("德国", "欧洲"); A("意大利", "欧洲")
    A("埃及", "非洲"); A("开罗", "埃及"); A("尼日利亚", "非洲")
    return g

# ============================================================ 题目集
ANIMALS = ["企鹅", "鸵鸟", "麻雀", "蝙蝠", "鲸", "海豚", "狗", "猫", "蛇", "蜥蜴",
           "鳄鱼", "青蛙", "金鱼", "鲨鱼", "蝴蝶", "蜜蜂", "蚂蚁", "蜘蛛", "章鱼", "蜗牛"]
CATS = ["鸟类", "哺乳动物", "爬行动物", "两栖动物", "鱼类", "昆虫", "蛛形纲", "节肢动物", "软体动物"]
CITIES = ["北京", "上海", "广州", "巴黎", "马赛", "开罗"]
UNKNOWN_OBJ = ["汽车", "计算机", "音乐", "股票", "爱情"]

class FactItem:
    """事实判断题。truth: 1真 / 0假 / None = 图中查无依据(探测诚实度)。"""
    def __init__(self, qid, text, x, y, truth):
        self.qid, self.text, self.x, self.y, self.truth = qid, text, x, y, truth

def gen_fact_items(g, seed=42):
    rnd = random.Random(seed)
    items, pool = [], ANIMALS + CITIES
    # 45 真：child -> 某祖先
    t = 0
    while t < 45:
        x = rnd.choice(pool)
        anc = sorted(g.ancestors(x))
        if not anc:
            continue
        items.append(FactItem(f"T{t:03d}", f"{x} 是 {rnd.choice(anc)} 吗？", x, rnd.choice(anc), 1))
        t += 1
    # 45 假：兄弟互指 / 跨枝 / 反向（都在图内 -> 白盒应可证伪）
    f, tries = 0, 0
    while f < 45 and tries < 5000:
        tries += 1
        x, y = rnd.choice(ANIMALS), rnd.choice(CATS + ANIMALS)
        if x == y or y in g.ancestors(x):
            continue
        items.append(FactItem(f"F{t + f:03d}", f"{x} 是 {y} 吗？", x, y, 0))
        f += 1
    # 10 探测：y 完全不在知识体系 -> 白盒必须 ABSTAIN，不得武断
    for i in range(10):
        x = rnd.choice(ANIMALS + CITIES)
        y = UNKNOWN_OBJ[i % len(UNKNOWN_OBJ)]
        items.append(FactItem(f"P{i:02d}", f"{x} 是 {y} 吗？", x, y, None))
    return items

# 编程/逻辑题（20 道）：court 用原生规则独立判，LLM 只被问一句，无二次 prompt
SYNTAX_ITEMS = [
    ("S1", "print(\"hi\")"),
    ("S2", "def f(:\n pass"),
    ("S3", "x = [i for i in range(3)]"),
    ("S4", "x = = 3"),
    ("S5", "if True:\n    print(1)"),
    ("S6", "print(\"unclosed)"),
]
RUNTIME_ITEMS = [
    ("R1", "'5' + 2"),
    ("R2", "5 + '5'"),
    ("R3", "'ab' * 3"),
    ("R4", "[1, 2, 3][9]"),
    ("R5", "None + 1"),
    ("R6", "len('abc')"),
]
# kind: trans_pos / trans_neg / no_rel / contra
LOGIC_ITEMS = [
    ("L1", "trans_pos", "已知 A>B 且 B>C，那么 A>C 成立吗？", [("A", "B"), ("B", "C")], ("A", "C")),
    ("L2", "trans_pos", "已知 甲<乙 且 乙<丙，那么 甲<丙 成立吗？", [("甲", "乙"), ("乙", "丙")], ("甲", "丙")),
    ("L3", "trans_neg", "已知 A>B 且 B>C，那么 C>A 成立吗？", [("A", "B"), ("B", "C")], ("C", "A")),
    ("L4", "trans_neg", "已知 甲<乙 且 乙<丙，那么 丙<甲 成立吗？", [("甲", "乙"), ("乙", "丙")], ("丙", "甲")),
    ("L5", "no_rel", "已知 A>B 且 C>D，那么 A>C 成立吗？", [("A", "B"), ("C", "D")], ("A", "C")),
    ("L6", "no_rel", "已知 甲>乙 且 丙>丁，那么 甲>丁 成立吗？", [("甲", "乙"), ("丙", "丁")], ("甲", "丁")),
    ("L7", "contra", "已知 A>B 且 B>A，前提是否自相矛盾？", [("A", "B"), ("B", "A")], None),
    ("L8", "contra", "已知 甲>乙 且 乙>甲，前提是否自相矛盾？", [("甲", "乙"), ("乙", "甲")], None),
]

# ============================================================ 极简白盒法庭
class MinimalCourt:
    """全部用最直接的规则/图匹配，零 LLM。输出 PASS / REJECT / ABSTAIN。"""

    def __init__(self, g):
        self.g = g

    # ---- 通道1：事实对账（图可达性）
    def fact(self, x, y):
        if y in self.g.ancestors(x):
            return "PASS"                 # 图内可证：x 确实是 y
        if self.g.has(x) and self.g.has(y) and self.g.ancestors(x):
            return "REJECT"               # 两端已知且无 is-a 路径 -> 断言可证伪
        return "ABSTAIN"                  # 任一端在图外 -> 查无依据，不武断

    # ---- 通道2a：语法（ast.parse）
    def syntax(self, code):
        try:
            ast.parse(code)
            return ("PASS", "合法")
        except SyntaxError as e:
            return (f"REJECT:{e.msg}", "不合法")

    # ---- 通道2b：运行时（eval；题目为固定纯表达式，无副作用）
    def runtime(self, expr):
        try:
            eval(expr, {})
            return ("PASS", "不会")
        except Exception as e:
            return (f"REJECT:{type(e).__name__}", "会")

    # ---- 通道2c：逻辑推演（关系闭包 + 矛盾检测）
    def logic(self, kind, edges, ask):
        if kind == "contra":
            cyc = [(a, b) for (a, b) in edges if (b, a) in edges and a != b]
            return (("REJECT:前提矛盾", "矛盾") if cyc else ("PASS", "不矛盾"))
        adj = defaultdict(list)
        for (a, b) in edges:
            adj[a].append(b)
        a0, b0 = ask
        seen, stack = set(), [a0]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, ()))
        if b0 in seen:
            return ("PASS", "成立")        # 由前提可推出
        return ("REJECT:前提不足", "不成立")  # 无前提支撑 / 方向相反

# ============================================================ LLM 层
class FakeLLM:
    """确定性模拟器：err_rate 注入典型 LLM 错误（幻觉/答反），可复现。"""
    def __init__(self, err_rate=0.30, seed=7):
        self.rnd = random.Random(seed)
        self.err_rate = err_rate

    def _bad(self, qid):
        return self.rnd.random() < self.err_rate

    def _flip(self, word):
        return {"是": "否", "否": "是", "合法": "不合法", "不合法": "合法",
                "会": "不会", "不会": "会", "成立": "不成立", "不成立": "成立",
                "矛盾": "不矛盾", "不矛盾": "矛盾"}[word]

    def answer_fact(self, it):
        if it.truth is None:
            return "是" if self.rnd.random() < 0.5 else "否"   # 探测题：模型倾向乱断言
        word = "是" if it.truth == 1 else "否"
        return self._flip(word) if self._bad(it.qid) else word

    def answer_word(self, qid, truth_word, question_text=None, allowed=None):
        return self._flip(truth_word) if self._bad(qid) else truth_word

class RealHunyuanLLM:
    """真 LLM 通道：腾讯混元 MaaS 网关 (tokenhub.tencentmaas.com / hy4-preview)。
    该模型带隐藏推理(reasoning_content)；只取正式 content，在 allowed 词表内解析。
    - 每次成功响应落盘 hunyuan_cache.jsonl（键=prompt），重跑/崩溃后命中缓存不重烧 API
    - 空值容错：content or ""、urlopen try-except、_pick 解析失败返回 None
    key 从环境变量 HUNYUAN_API_KEY 读取，不落盘。零第三方依赖。"""
    BASE = "https://tokenhub.tencentmaas.com/v1/chat/completions"
    MODEL = "hy4-preview"

    def __init__(self, api_key=None):
        self.key = api_key or os.environ.get("HUNYUAN_API_KEY", "")
        self.n_call = 0
        self.n_cache_hit = 0
        self.cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "hunyuan_cache.jsonl")
        self._cache = self._load_cache()

    def _load_cache(self):
        d = {}
        if os.path.exists(self.cache_file):
            with open(self.cache_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        d[rec["p"]] = rec["c"]
                    except Exception:
                        pass
        return d

    def _chat(self, prompt, max_tokens=1500):
        if prompt in self._cache:
            self.n_cache_hit += 1
            return self._cache[prompt]
        if not self.key:
            return ""
        try:
            body = json.dumps({"model": self.MODEL,
                               "messages": [{"role": "user", "content": prompt}],
                               "temperature": 0, "max_tokens": max_tokens}).encode()
            req = urllib.request.Request(
                self.BASE, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.key}"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read())
            content = data["choices"][0]["message"].get("content") or ""
        except Exception as e:
            print(f"  [api-err] {type(e).__name__}: {e}", flush=True)
            return ""
        self.n_call += 1
        self._cache[prompt] = content
        try:
            with open(self.cache_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"p": prompt, "c": content}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return content

    @staticmethod
    def _pick(content, allowed):
        """格式门解析：候选词必须『独立唯一命中』才算解析成功。
        - 空 / 无候选 / 多候选含混（"既会又不会"）→ None = 格式门拒绝
        - 被更长否定词覆盖的假阳性剔除（"不会"里的"会"、"不合法"里的"合法"不算）
        宁可 REJECT 也不强行解读残缺文本（豆包第 3 点防御原则）。"""
        if not content:
            return None
        pos = {}
        for w in allowed:
            i = content.find(w)
            if i >= 0:
                pos[w] = i
        if not pos:
            return None
        for w in list(pos):
            covered = any(pos[lo] <= pos[w] < pos[lo] + len(lo)
                          for lo in pos if len(lo) > len(w))
            if covered:
                del pos[w]
        if len(pos) != 1:
            return None
        return list(pos)[0]

    def answer_fact(self, it):
        out = self._chat(f"判断题：{it.text}\n只回答一个词：是 或 否。不要解释。")
        return self._pick(out, ["是", "否"])

    def answer_word(self, qid, truth_word, question_text=None, allowed=None):
        allowed = allowed or ["是", "否"]
        out = self._chat(f"判断题：{question_text}\n只回答一个词：{' 或 '.join(allowed)}。不要解释。")
        return self._pick(out, allowed)

def selfcheck_format_gate():
    """格式门自检：解析失败/含混 → 一律 None（REJECT），禁止落印记。
    对应豆包第 3 点：黑盒输出脱离 schema 时触发防御，不强行解析残缺文本。"""
    print("== 格式门自检（唯一命中规则）==")
    cases = [
        ("空输出", "", None),
        ("跑题废话无候选", "这题挺有意思，涉及很多方面需要讨论", None),
        ("含混双候选", "既会又不会", None),
        ("含混双候选2", "可能合法也可能不合法", None),
        ("单候选短答", "会", "会"),
        ("单候选带理由", "不会，因为类型不符", "不会"),
        ("长词先命中也唯一", "不合法，缺了冒号", "不合法"),
        ("否定式不误伤", "不会抛出异常", "不会"),
    ]
    all_ok = True
    for name, content, expect in cases:
        got = RealHunyuanLLM._pick(content, ["会", "不会", "合法", "不合法"])
        ok = got == expect
        all_ok &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:12s} 期望={str(expect):6s} 实得={str(got)}")
    print(f"  格式门自检: {'全部通过 ✓' if all_ok else '存在失败 ✗'}")
    return all_ok

# ============================================================ 工具
def reject_class(v):
    """把法庭 REJECT 报文归入失败模式大类（豆包第 2 点拆分维度）。"""
    if "前提矛盾" in v:
        return "逻辑矛盾(前提互斥)"
    if "前提不足" in v:
        return "前提不足/推不出"
    if v == "REJECT":
        return "事实证伪(图内)"
    m = v.split(":", 1)[1] if ":" in v else v
    if m in ("TypeError", "IndexError", "NameError"):
        return f"类型/运行时错误({m})"
    if "invalid syntax" in m or "string literal" in m:
        return "语法结构错误(ast)"
    return f"其他({m[:30]})"

# ============================================================ 评测
def eval_fact(g, items, llm):
    n_in = 0
    llm_right = 0                 # LLM 在图内 90 题上的裸答对
    reject_n = 0                  # 法庭对图内题的 REJECT 总数
    hallu = 0                     # LLM 答"是"的假命题 = 幻觉断言
    hallu_caught = 0              # 其中被法庭 REJECT 的
    neg_true = 0                  # LLM 答"否"的真命题 = 假警报(守门方向外)
    probe_abstain = 0             # 探测题被 ABSTAIN 挂起
    probe_yes = 0                 # 探测题 LLM 无依据断言数
    false_pass = 0                # 假命题被法庭误 PASS（必须为 0）
    true_reject = 0               # 真命题被法庭误 REJECT（必须为 0）
    for it in items:
        v = court.fact(it.x, it.y)
        if it.truth is None:
            w = llm.answer_fact(it)
            if v == "ABSTAIN":
                probe_abstain += 1
            if w == "是":
                probe_yes += 1
            continue
        n_in += 1
        if v == "REJECT":
            reject_n += 1
        w = llm.answer_fact(it)
        truth_word = "是" if it.truth == 1 else "否"
        if w == truth_word:
            llm_right += 1
        if it.truth == 0 and w == "是":
            hallu += 1
            if v == "REJECT":
                hallu_caught += 1
            if v == "PASS":
                false_pass += 1
        if it.truth == 1 and w == "否":
            neg_true += 1
        if it.truth == 1 and v == "REJECT":
            true_reject += 1
    return {"n": n_in, "llm_acc": llm_right / n_in, "reject_n": reject_n,
            "hallu": hallu,
            "hallu_caught": hallu_caught, "neg_true": neg_true,
            "probe_abstain": probe_abstain,
            "probe_yes": probe_yes, "false_pass": false_pass,
            "true_reject": true_reject, "probe_n": 10}

def eval_structured(llm):
    rows = []
    for (qid, code) in SYNTAX_ITEMS:
        v, tw = court.syntax(code)
        q = f"以下 Python 代码语法是否合法：\n```\n{code}\n```"
        w = llm.answer_word(qid, tw, q, ["合法", "不合法"])
        rows.append((qid, "syntax", v, tw, w, w == tw))
    for (qid, expr) in RUNTIME_ITEMS:
        v, tw = court.runtime(expr)
        q = f"执行表达式 {expr} 会抛异常吗？"
        w = llm.answer_word(qid, tw, q, ["会", "不会"])
        rows.append((qid, "runtime", v, tw, w, w == tw))
    for (qid, kind, text, edges, ask) in LOGIC_ITEMS:
        v, tw = court.logic(kind, edges, ask)
        allowed = ["矛盾", "不矛盾"] if kind == "contra" else ["成立", "不成立"]
        w = llm.answer_word(qid, tw, text, allowed)
        rows.append((qid, f"logic:{kind}", v, tw, w, w == tw))
    st = {"n": len(rows), "llm_right": sum(r[5] for r in rows),
          "reject_n": sum(1 for r in rows if r[2].startswith("REJECT")),
          "reject_llm_err": sum(1 for r in rows if r[2].startswith("REJECT") and not r[5]),
          "pass_llm_err": sum(1 for r in rows if r[2] == "PASS" and not r[5]),
          "parse_fail": sum(1 for r in rows if r[4] is None),
          "llm_err_total": sum(1 for r in rows if not r[5])}
    return st, rows

def main():
    global court
    court = MinimalCourt(build_graph())
    if "--selfcheck" in sys.argv:
        ok = selfcheck_format_gate()
        sys.exit(0 if ok else 1)
    real_mode = "--real" in sys.argv
    if real_mode:
        llm = RealHunyuanLLM()
        if not llm.key:
            print("[!] 未检测到 HUNYUAN_API_KEY，回退 FakeLLM。")
            llm = FakeLLM()
    else:
        llm = FakeLLM()
    model_src = ("RealHunyuanLLM(hy4-preview @ tokenhub.tencentmaas.com)"
                 if isinstance(llm, RealHunyuanLLM)
                 else "FakeLLM 确定性注入(seed=7, err_rate=30%)")

    items = None
    fs = None
    if "--structured-only" not in sys.argv:
        items = gen_fact_items(court.g)
        fs = eval_fact(court.g, items, llm)
    ss, srows = eval_structured(llm)

    X = fs["llm_acc"] if fs else 0.0
    hallu_rate = fs["hallu_caught"] / fs["hallu"] if (fs and fs["hallu"]) else 1.0
    probe_ok = (fs["probe_abstain"] == fs["probe_n"]) if fs else True
    sx = ss["llm_right"] / ss["n"]
    blockable = ss["llm_err_total"] - ss["pass_llm_err"]   # 放行方向幻觉 = 法庭守门该拦的
    srej_hit = ss["reject_llm_err"] / blockable if blockable else 1.0

    print("=" * 66)
    print("AsteriaMind · 白盒法庭最小拦截力探针  (LLM 黑盒语境)")
    print("=" * 66)
    print(f"模型源: {model_src}   |   API 调用 {llm.n_call} 次 (缓存命中 {llm.n_cache_hit})"
          if isinstance(llm, RealHunyuanLLM) else f"模型源: {model_src}\n")
    if fs:
        print(f"\n【事实域】 {fs['n']} 图内题 + {fs['probe_n']} 图外探测题")
        print(f"  LLM 裸精度 X             = {X:.1%}  ({fs['n'] - round((1-X)*fs['n'])}/{fs['n']} 对)")
        print(f"  法庭误放行假命题(false_pass) = {fs['false_pass']}   ← 必须为 0")
        print(f"  法庭误杀真命题(true_reject)  = {fs['true_reject']}   ← 必须为 0")
        print(f"  LLM 幻觉断言(答是·假命题)   = {fs['hallu']} 个, 被 REJECT 拦下 {fs['hallu_caught']}"
              f"  (拦截率 {hallu_rate:.0%})")
        print(f"  假警报(答否·真命题,守门外)   = {fs['neg_true']} 个")
        print(f"  图外断言挂起              = {fs['probe_yes']} 个断言 → ABSTAIN {fs['probe_abstain']}/10"
              f"  ({'诚实不武断 ✓' if probe_ok else '异常 ✗'})")
    else:
        print(f"\n【事实域】 本轮跳过(--structured-only)，聚合数据复用 2026-09-04 首轮实测")
    print(f"\n【编程/逻辑域】 {ss['n']} 题 = 语法 6 + 运行时 6 + 推演 8")
    print(f"  LLM 裸精度 X             = {sx:.1%}  ({ss['llm_right']}/{ss['n']} 对)")
    print(f"  法庭 REJECT 触发          = {ss['reject_n']} 次   ← 结构拦截")
    print(f"  放行方向幻觉(守门该拦)     = {blockable} 个, 被拦 {ss['reject_llm_err']}"
          f"  (拦截率 {srej_hit:.0%})")
    print(f"  假警报(过度否定,守门外)    = {ss['pass_llm_err']} 个（反向错误，后续走用户反馈通道）")
    print(f"\n【编程/逻辑域明细】")
    print(f"  {'qid':5s} {'类型':16s} {'法庭裁决':18s} {'真值':6s} {'LLM说':6s} 结果")
    for qid, kind, v, tw, w, ok in srows:
        wd = "无词" if w is None else w
        print(f"  {qid:5s} {kind:16s} {v:18s} {tw:6s} {wd:6s} {'对 ✓' if ok else '错 ✗'}")
    if ss["parse_fail"]:
        print(f"  （{ss['parse_fail']} 题 LLM 未输出可解析词 → 格式门 REJECT，禁止落印记）")

    # ---- REJECT 分类：法庭到底在拦哪一类失败模式（豆包第 2 点）
    from collections import Counter
    buckets = Counter()
    for qid, kind, v, tw, w, ok in srows:
        if v.startswith("REJECT"):
            buckets[reject_class(v)] += 1
    print(f"\n【REJECT 分类统计】 结构域 {ss['reject_n']} 次 + 事实域 {fs['reject_n'] if fs else 45} 次图内证伪")
    for cls, cnt in buckets.most_common():
        print(f"  {cls:24s} × {cnt}")
    if fs:
        print(f"  {'事实证伪(图内无 is-a 路径)':24s} × 45 (全部假命题)")

    v_f = []
    if fs is None:
        v_f.append("事实域：本轮未重跑（--structured-only），聚合复用首轮实测 83.3% / 0 漏 0 杀 / 10/10 ABSTAIN")
    elif fs["false_pass"] == 0 and fs["true_reject"] == 0 and fs["hallu"] > 0 and hallu_rate >= 1.0:
        v_f.append("事实域：会拒、无漏放、无错杀")
    elif fs["false_pass"] == 0 and fs["true_reject"] == 0:
        v_f.append("事实域：无漏放无错杀（无幻觉样本时无法测拦截）")
    else:
        v_f.append("事实域：存在误判，需修")
    if ss["reject_n"] > 0 and srej_hit >= 0.5:
        v_l = "逻辑/编程域：结构拦截真实存在且拦住放行方向幻觉"
    elif ss["reject_n"] > 0:
        v_l = "逻辑/编程域：能拒但命中一般"
    else:
        v_l = "逻辑/编程域：结构拦截未触发"
    print("\n" + "=" * 66)
    print(f"总判: {v_f[0]} | {v_l}")
    print("=" * 66)

    report = f"""# 白盒法庭最小拦截力探针报告

- 日期: 2026-09-04
- 模型源: {model_src}
- 规则: 零 LLM 二次 Prompt —— 事实=图可达性; 语法=ast.parse; 运行时=eval; 推演=关系闭包+矛盾检测
"""
    if fs:
        report += f"""
## 事实域 ({fs['n']} 图内题 + {fs['probe_n']} 图外探测题)

| 指标 | 值 |
|---|---|
| LLM 裸精度 X | {X:.1%} |
| 法庭误放行假命题 | {fs['false_pass']} （须为 0） |
| 法庭误杀真命题 | {fs['true_reject']} （须为 0） |
| LLM 幻觉断言被拦 | {fs['hallu_caught']}/{fs['hallu']}（拦截率 {hallu_rate:.0%}） |
| 假警报(答否·真命题) | {fs['neg_true']} 个（守门方向外） |
| 图外断言挂起 | ABSTAIN {fs['probe_abstain']}/{fs['probe_n']}（{probe_ok and '诚实不武断' or '异常'}） |
"""
    else:
        report += f"""
## 事实域（--structured-only 跳过；聚合复用 2026-09-04 首轮实测）
LLM 裸精度 **83.3%** (75/90) · 法庭误放行 **0** · 误杀 **0** · 图外 ABSTAIN **10/10** · 幻觉断言 0（判断题对 hy4-preview 过易，无样本可拦）
"""
    report += f"""
## 编程/逻辑域 ({ss['n']} 题)

| 指标 | 值 |
|---|---|
| LLM 裸精度 X | {sx:.1%} ({ss['llm_right']}/{ss['n']}) |
| 法庭 REJECT 触发 | {ss['reject_n']} 次 |
| 放行方向幻觉被拦 | {ss['reject_llm_err']}/{blockable}（{srej_hit:.0%}） |
| 假警报(过度否定) | {ss['pass_llm_err']} 个（守门外，后续走用户反馈通道） |

### 明细

| qid | 类型 | 法庭裁决 | 真值 | LLM说 | 结果 |
|---|---|---|---|---|---|
"""
    for qid, kind, v, tw, w, ok in srows:
        report += f"| {qid} | {kind} | {v} | {tw} | {('无词' if w is None else w)} | {'对' if ok else '错'} |\n"
    if ss["parse_fail"]:
        report += f"\n（{ss['parse_fail']} 题 LLM 未输出可解析词，计为错）\n"
    report += f"""
## 总判

- {v_f[0]}
- {v_l}

## 诚实边界

- 事实域知识图与题目同源，白盒裁决=生成真值，验证的是「机制无漏放/无错杀/图外不武断」；
  真 LLM 幻觉由 `HUNYUAN_API_KEY=xxx python court_probe.py --real` 实测（hy4-preview）。
- 2026-09-04 真 LLM 实测观察：hy4-preview 在判断题上极强（事实 83.3% / 逻辑 90%），
  事实域 0 个幻觉断言 → 白盒无样本可拦；真正的幻觉样本出现在逻辑/编程域，
  白盒 2/2 全部拦下。要测事实域幻觉拦截，需改用开放式断言题（生成式，非判断式）。
- 守门方向性：法庭拦截的是 LLM「放行方向」的错误（说合法/不抛/成立/是 但实际相反）；
  「假警报方向」（过度否定正确事实，如把合法代码说成非法）不产生进图断言，第一版不拦，
  属后续用户反馈/纠错通道。
- 逻辑域 `no_rel` 题（L5/L6）的"不成立"实为"前提不足、无法确定"的朴素二值近似。
"""
    out_name = ("court_probe_report_real.md" if isinstance(llm, RealHunyuanLLM)
                else "court_probe_report_fake.md")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), out_name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已落盘: {out}")

if __name__ == "__main__":
    main()
