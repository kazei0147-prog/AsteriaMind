"""
v2.6 尺度自适应验证 — Learner 能否在数据尺度突变后继续学习？

场景: 
  阶段1: CO2 数据 (~420) → 学习正常
  阶段2: 线性数学数据 y=2x+5 (~5→305) → 尺度突变
  关键: σ 应该在阶段2增大而非缩小
"""
import sys, random
sys.path.insert(0, "C:/Users/Administrator/WorkBuddy/2026-07-01-13-51-12/HiveMind_repo/src")

from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

random.seed(42)

# ── 方案A (默认) + 方案B (额外对照) ──
learners_A = [
    Learner(name="A_optimist",  initial_mu=+3.0, initial_sigma=12.0, window_size=5,
            adaptive_scale=True, robust_likelihood=False),
    Learner(name="A_skeptic",   initial_mu= 0.0, initial_sigma=20.0, window_size=10,
            adaptive_scale=True, robust_likelihood=False),
    Learner(name="A_adaptable", initial_mu= 0.0, initial_sigma=10.0, window_size=7,
            adaptive_scale=True, robust_likelihood=False),
]
learners_B = [
    Learner(name="B_optimist",  initial_mu=+3.0, initial_sigma=12.0, window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner(name="B_skeptic",   initial_mu= 0.0, initial_sigma=20.0, window_size=10,
            adaptive_scale=True, robust_likelihood=True),
]

live = LiveSource(max_buffer=300)

# 阶段1: CO2 数据 (~405-435)
for i in range(20):
    live.push(420 + random.gauss(0, 5))

# 阶段2: 数学数据 y=2x+5 (~5-305)
for x in range(0, 30):
    y = 2 * x + 5 + random.gauss(0, 3)
    live.push(y)

portal = Portal(source=live, sinks=[ConsoleSink()],
                curiosity=CuriosityEngine(stale_threshold=0.3, confidence_low=0.6))

trust_A = TrustEngine()
trust_B = TrustEngine()
for l in learners_A + learners_B:
    (trust_A if l.learner_id.startswith("A") else trust_B).register(l.learner_id)

mother_A = MotherMind()
mother_B = MotherMind()

# 预热
for _ in range(15):
    val = portal.poll()
    if val is None: break
    for l in learners_A + learners_B:
        l.observe(val)

# 运行
rounds_A = rounds_B = 0
for i in range(40):
    val = portal.poll()
    if val is None: break
    for l in learners_A + learners_B:
        l.observe(val)

    if i % 3 == 0:
        # 方案A
        chains_A = [l.propose(val) for l in learners_A if l.observation_window]
        if chains_A:
            d = mother_A.deliberate(learners_A, chains_A, trust_A, val)
            rounds_A += 1
            for l in learners_A:
                # 总是学习: 第一次调用时 history 为空，用 proposal 值
                if l.history:
                    l.learn(val, l.history[-1])
                elif chains_A:
                    # 首次: 用刚生成的 proposal 值
                    prop = chains_A[learners_A.index(l)].proposal_value if l in learners_A else val
                    l.learn(val, prop)
                trust_A.verify(l.learner_id, l.history[-1] if l.history else val, val)
        # 方案B
        chains_B = [l.propose(val) for l in learners_B if l.observation_window]
        if chains_B:
            d = mother_B.deliberate(learners_B, chains_B, trust_B, val)
            rounds_B += 1
            for l in learners_B:
                if l.history:
                    l.learn(val, l.history[-1])
                elif chains_B:
                    idx = next((i for i, lb in enumerate(learners_B) if lb.learner_id == l.learner_id), 0)
                    prop = chains_B[min(idx, len(chains_B)-1)].proposal_value
                    l.learn(val, prop)
                trust_B.verify(l.learner_id, l.history[-1] if l.history else val, val)

# ── 结果 ──
print(f"\n{'='*60}")
print(f"v2.6 尺度自适应对比")
print(f"{'='*60}")

for label, learners_list, trust_eng in [
    ("方案A: 尺度归一化", learners_A, trust_A),
    ("方案B: +Student-t鲁棒", learners_B, trust_B),
]:
    print(f"\n{label}:")
    print(f"{'Learner':15s} {'mu':>7s}  {'sigma':>7s}  {'数据尺度':>10s}  {'准确率':>7s}")
    for l in sorted(learners_list, key=lambda x: x.track_record(), reverse=True):
        print(f"{l.learner_id:15s} {l.belief.mu:>+7.3f}  {l.belief.sigma:>6.1f}  "
              f" {l.scale_tracker.scale:>7.1f}  {l.track_record():>6.3f}")

    # 关键指标: σ 是否适应了新尺度
    sigmas = [l.belief.sigma for l in learners_list]
    scales = [l.scale_tracker.scale for l in learners_list]
    initial_sigmas = [l.belief.adaptive_scale and 10 or 12 for l in learners_list]
    sigma_adapted = all(s > 12 for s in sigmas) or all(s > 10 for s in sigmas)
    scale_tracked = any(s > 50 for s in scales)  # 数学数据 ~100

    print(f"  σ 是否增长 (适应新尺度)? {'✅' if sigma_adapted else '❌'}  avg σ={sum(sigmas)/len(sigmas):.1f}")
    print(f"  尺度追踪 (>50)? {'✅' if scale_tracked else '❌'}  avg scale={sum(scales)/len(scales):.1f}")
