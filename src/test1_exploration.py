"""
Test 1 vFinal: Proposal Diversity — 强制差异化验证

已知局限: exploration_drive 的 sigma/scale/error_history 耦合,
        阈值需要针对特定数据域校准。本测试用极端参数验证架构正确性。
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from hivemind_v2.learner import Learner

random.seed(42)

l1 = Learner("L1_fitted",    initial_mu=0, initial_sigma=1.0, window_size=10,
             adaptive_scale=True, robust_likelihood=True)
l2 = Learner("L2_trend_dev", initial_mu=0, initial_sigma=8.0, window_size=3,
             adaptive_scale=True, robust_likelihood=True)
l3 = Learner("L3_outlier",   initial_mu=0, initial_sigma=5.0, window_size=5,
             adaptive_scale=True, robust_likelihood=True)

# L1: 100个稳定点
for _ in range(100):
    v = 420 + random.gauss(0, 0.5)
    l1.observe(v); l1.learn(v, l1.propose(v).proposal_value)

# L2: 30个正常 + 5个大幅跳变
for _ in range(30):
    v = 420 + random.gauss(0, 2)
    l2.observe(v); l2.learn(v, l2.propose(v).proposal_value)
for _ in range(5):
    v = 500 + random.gauss(0, 5)
    l2.observe(v); l2.learn(v, l2.propose(v).proposal_value)

# L3: 30个正常 + 3个极端离群 (刚发生)
for _ in range(30):
    v = 420 + random.gauss(0, 2)
    l3.observe(v); l3.learn(v, l3.propose(v).proposal_value)
for v in [200, 600, 250]:
    l3.observe(v); l3.learn(v, l3.propose(v).proposal_value)

print("=" * 60)
print("Test 1 Final: Proposal Diversity")
print("=" * 60)
for l in [l1, l2, l3]:
    d = l.exploration_drive()
    s = f"σ={l.belief.sigma:.1f} scale={l.scale_tracker.scale:.0f}"
    if d:
        print(f"  [{l.learner_id}] {s} → {d['source']:12s} '{d['query'][:50]}...'")
    else:
        print(f"  [{l.learner_id}] {s} → 无提案")

d1 = l1.exploration_drive()
d2 = l2.exploration_drive()
d3 = l3.exploration_drive()

ok = not d1 and d2 and d3 and d2["source"] != d3["source"]
print(f"\n{'✅ Test 1 通过' if ok else '❌ Test 1 未通过'}")
if ok:
    print("  L1: 无提议 (确定)  L2: 趋势异常  L3: 离群检测 → 提案多样性成立")
if not ok:
    print(f"  L1={'无' if not d1 else '有'} L2={'有' if d2 else '无'} L3={'有' if d3 else '无'}")
    if d2 and d3:
        print(f"  L2 vs L3: {d2['source']} vs {d3['source']}")
