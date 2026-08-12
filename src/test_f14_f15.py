# -*- coding: utf-8 -*-
"""
test_f14_f15.py — AsteriaMind MVP 验收测试 (U-03 方案 B)

F14 意图覆盖扩展: IntentLearner 复杂意图 (COMPARE/HYPOTHESIS/COUNTERFACTUAL)
  1. 先验正则识别 13 组问句
  2. 统计锚点学习闭环 (learn → support>=2 覆盖先验)

F15 预测研究版: ActiveInference 增强 → 自发发言器第 5 类想法源 predict
  3. plan_actions → collect_thoughts 产出 predict 想法 (质量门)
  4. express 输出预测类发言 (含行动类型分支)
  5. tick 全流程 (节流 + 队列 + 防重复)

运行: python test_f14_f15.py
"""
import sys, os, sqlite3, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    mark = "✅" if cond else "❌"
    if cond: PASS += 1
    else: FAIL += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not cond else ""))

# ─────────────────────────── F14 ───────────────────────────
print("=" * 60)
print("F14 意图覆盖扩展 — 复杂意图识别")
from AsteriaMind.intent_learner import IntentLearner

F14_CASES = [
    ('如果企鹅会飞会怎样', 'COUNTERFACTUAL'),
    ('要是人类不会睡觉就好了', 'COUNTERFACTUAL'),
    ('假如月球被撞碎会怎样', 'COUNTERFACTUAL'),
    ('假设企鹅能飞会怎样', 'COUNTERFACTUAL'),
    ('如果明天下雨就不出门', 'HYPOTHESIS'),
    ('假设地球突然停止自转', 'HYPOTHESIS'),
    ('假如人类学会了读心术', 'HYPOTHESIS'),
    ('企鹅和鸟有什么区别', 'COMPARE'),
    ('海豚和鲨鱼谁更快', 'COMPARE'),
    ('哪个动物更适合当宠物', 'COMPARE'),
    ('企鹅会飞吗', 'CAN'),            # 基本意图不受影响
    ('企鹅属于什么', 'IS_A'),
    ('熊猫吃什么', 'EATS'),
    ('你好', 'ASK'),
]
ok14 = 0
for text, expect in F14_CASES:
    got = IntentLearner._infer_prior(text)
    check(f"F14 识别 {text!r} → {expect}", got == expect, f"实际 {got}")
    if got == expect: ok14 += 1
print(f"  F14 先验: {ok14}/{len(F14_CASES)}")

print("-" * 60)
print("F14 统计锚点学习闭环")
class FakeSM:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
il = IntentLearner(FakeSM())
# 冷启动: 先验
check("F14 冷启动 COMPARE", il.predict('企鹅和鸟有什么区别') == 'COMPARE')
check("F14 冷启动 COUNTERFACTUAL", il.predict('如果企鹅会飞会怎样') == 'COUNTERFACTUAL')
# 学习: 2 次正确反馈 → support>=2 统计覆盖先验
il.learn('企鹅和鸟有什么区别', 'COMPARE', True)
il.learn('企鹅和鸟有什么区别', 'COMPARE', True)
check("F14 统计后仍 COMPARE (support>=2)", il.predict('企鹅和鸟有什么区别') == 'COMPARE')
s = il.summary()
check("F14 summary 有统计锚点", s["learned_patterns"] >= 1, f"{s}")

# ─────────────────────────── F15 ───────────────────────────
print("=" * 60)
print("F15 预测研究版 — 自发发言器第 5 类想法源 predict")

# 内存 DB + 假 star_map (collect_thoughts 其他源缺表会被 try/except 吞掉)
class FakeStarMap:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row

class FakeActiveInference:
    """模拟 plan_actions 返回, 含各类行动"""
    def plan_actions(self, top_k=6):
        return [
            {"subj": "企鹅", "pred": "CAN", "obj": "飞",
             "action_type": "suggest", "belief": 0.8, "uncertainty": 0.2,
             "evidence_count": 3, "score": 0.9},
            {"subj": "海豚", "pred": "IS_A", "obj": "哺乳动物",
             "action_type": "verify", "belief": 0.5, "uncertainty": 0.6,
             "evidence_count": 1, "score": 0.7},
            {"subj": "火星", "pred": "HAS", "obj": "大气层",
             "action_type": "explore", "belief": 0.3, "uncertainty": 0.8,
             "evidence_count": 0, "score": 0.5},   # 无证据 → 应被质量门挡
            {"subj": "因此", "pred": "IS_A", "obj": "鸟类",
             "action_type": "suggest", "belief": 0.7, "uncertainty": 0.3,
             "evidence_count": 2, "score": 0.4},   # 残片 → 应被质量门挡
        ]

sm = FakeStarMap()
speaker = None
from AsteriaMind.spontaneous_speaker import SpontaneousSpeaker
speaker = SpontaneousSpeaker(
    star_map=sm, active_inference=FakeActiveInference())

# 3. collect_thoughts 应产出 predict 想法 (质量门过滤后)
thoughts = speaker.collect_thoughts(limit=10)
predicts = [t for t in thoughts if t["kind"] == "predict"]
check("F15 collect_thoughts 产出 predict", len(predicts) >= 1, f"{predicts}")
# 质量门: 无证据 (火星) 与残片 (因此) 应被过滤
check("F15 质量门过滤无证据预测", all(t["source"] != "火星" for t in predicts), f"{predicts}")
check("F15 质量门过滤残片", all(t["source"] != "因此" for t in predicts), f"{predicts}")

# 4. express 输出预测类发言
texts = []
for t in predicts:
    txt, kind = speaker.express(t)
    if txt:
        texts.append((kind, txt))
check("F15 express 产出预测发言", len(texts) >= 1, f"{texts}")
kinds = {k for k, _ in texts}
check("F15 发言类型含 predict", "predict" in kinds, f"{kinds}")
for k, t in texts[:2]:
    print(f"    💭 [{k}] {t}")

# 5. tick 全流程: 节流 + 入队 + 防重复
speaker._last_spoke = 0   # 重置节流
n = speaker.tick(force=True)
check("F15 tick 说出 ≥1 条", n >= 1, f"n={n}")
check("F15 队列非空", len(speaker._pending) >= 1)
drained = speaker.drain()
check("F15 drain 取出发言", len(drained) >= 1, f"{drained}")

# ─────────────────────────── 汇总 ───────────────────────────
print("=" * 60)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
if FAIL:
    sys.exit(1)
print("MVP F14+F15 验收全部通过 ✅")
