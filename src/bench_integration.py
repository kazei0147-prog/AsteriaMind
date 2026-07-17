"""
v2.9 集成测试: 四层自主探索管道接入 orchestrator
"""
import sys, random
sys.path.insert(0, "C:/Users/Administrator/WorkBuddy/2026-07-01-13-51-12/HiveMind_repo/src")

from hivemind_v2.orchestrator import HiveMindV2
from hivemind_v2.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

random.seed(42)
live = LiveSource(max_buffer=50)
live.push(415); live.push(420)

portal = Portal(source=live, sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(confidence_low=0.7, knowledge_gap_rounds=2))

# 用完整 orchestrator
hm = HiveMindV2(n_learners=3, use_personas=False, warmup_rounds=5)
hm.learners = [
    type(hm.learners[0])(name="L1_optimist",  initial_mu=+3.0, initial_sigma=12.0,
                         window_size=3, adaptive_scale=True, robust_likelihood=True),
    type(hm.learners[0])(name="L2_pessimist", initial_mu=-3.0, initial_sigma=12.0,
                         window_size=3, adaptive_scale=True, robust_likelihood=True),
    type(hm.learners[0])(name="L3_skeptic",   initial_mu= 0.0, initial_sigma=20.0,
                         window_size=5, adaptive_scale=True, robust_likelihood=True),
]

print("=" * 60)
print("🔬 v2.9 四层管道集成测试")
print("=" * 60)

# 触发测试
for step in range(6):
    should, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.3,
        learners=hm.learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )

    if should == "search":
        print(f"[{should}] {reason}")
        hm._autonomous_exploration(portal)
    elif should:
        val = portal.poll()
        if val is not None:
            for l in hm.learners:
                l.observe(val)
                if l.observation_window:
                    l.learn(val, l.observation_window[-1])

print(f"\n竞标统计: {hm.contest.summary()}")
print(f"Learner 状态:")
for l in hm.learners:
    print(f"  {l.learner_id}: σ={l.belief.sigma:.1f} track={l.track_record():.2f}")

assert hm.contest.total_contests > 0, "BudgetContest should have fired"
assert any(l.track_record() > 0 for l in hm.learners), "Learners should have learned"
print("\n✅ 四层管道 (CuriosityEngine → Learner.drive → BudgetContest → MotherMind) 已接入 orchestrator")
