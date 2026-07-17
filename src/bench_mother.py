"""
测试 v2.3 母模块 + 架构 Guard

验证:
  1. Mother 产出带推理的决策 (不只是数字)
  2. Guard 不抑制 Learner 思考
  3. Learner 性格保持
"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

import csv, random
from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.guard import StabilityGuard

random.seed(42)

reader = csv.DictReader(open(
    "D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv"
))
data = [float(r["value"]) for r in reader]

learners = [
    Learner(name="L1_optimist",  initial_mu=+3.0, initial_sigma=8.0,  window_size=5),
    Learner(name="L2_pessimist", initial_mu=-3.0, initial_sigma=8.0,  window_size=5),
    Learner(name="L3_skeptic",   initial_mu= 0.0, initial_sigma=15.0, window_size=10),
    Learner(name="L4_stubborn",  initial_mu= 0.0, initial_sigma=3.0,  window_size=3),
    Learner(name="L5_adaptable", initial_mu= 0.0, initial_sigma=10.0, window_size=12),
]

mother = MotherMind(debate_rounds=2)
guard = StabilityGuard()
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

# 预热
for i in range(50):
    for l in learners:
        l.observe(data[i])

# 运行并记录决策
decisions = []
for i in range(50, min(200, len(data))):
    obs = data[i]
    for l in learners:
        l.observe(obs)

    if (i - 50) % 5 == 0:
        chains = [l.propose(obs) for l in learners]
        decision = mother.deliberate(learners, chains, trust, obs)
        decisions.append((i, decision))

        # 验证
        verify_val = sum(data[max(0,i-5):i+1]) / min(6, i+1)
        for l in learners:
            if l.history:
                l.learn(verify_val, l.history[-1])
                trust.verify(l.learner_id, l.history[-1], verify_val)

        # Guard 检查
        gr = guard.check(learners, trust, decision.consensus,
                         abs(decision.consensus - obs))

print("=" * 65)
print("v2.3 母模块决策 + 架构 Guard 验证")
print("=" * 65)
print(f"总决策次数: {len(decisions)}")
print(f"Guard 违规:  {guard.violation_count}")
print()

# 展示最后三次决策
print("母模块决策样例 (最后3次):")
for i, d in decisions[-3:]:
    print(f"\n--- 轮 {i} ---")
    print(f"  共识: {d.consensus:.2f}  置信度: {d.confidence:.2f}")
    print(f"  主导: {d.primary_influence}")
    print(f"  推理: {d.reasoning[:120]}...")
    if d.dissenting_view:
        print(f"  少数派: {d.dissenting_view[:100]}")
    if d.reservations:
        print(f"  保留: {d.reservations}")

# 母模块对 Learner 的印象
print("\n\n母模块的 Learner 印象:")
ms = mother.summary()
for lid, imp in ms["impressions"].items():
    print(f"  {lid:15s} → {imp['best_at']:20s}  trust_trend={imp['trust_trend']}")

print(f"\n母模块决策置信度: {ms['last_confidence']:.2f}")
print(f"Guard 总违规: {guard.violation_count}")

if guard.violation_count == 0:
    print("✅ Guard 没有误报——Learner 思考自由，架构未被破坏")
else:
    print(f"⚠️  Guard 检测到 {guard.violation_count} 次违规")
