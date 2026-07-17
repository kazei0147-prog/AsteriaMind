"""
v2.7 完全自主探索 — 简化版

流程: 预热 → 低置信触发搜索 → MotherMind 生成 query → 搜索结果喂回 → 学习
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.guard import StabilityGuard
from hivemind_v2.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

random.seed(42)

live = LiveSource(max_buffer=50)
live.push(415); live.push(420)  # 仅 2 个点

portal = Portal(source=live, sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(confidence_low=0.7, knowledge_gap_rounds=2))

learners = [
    Learner(name="L1_optimist",  initial_mu=+3.0, initial_sigma=12.0,
            window_size=3, adaptive_scale=True, robust_likelihood=True),
    Learner(name="L2_pessimist", initial_mu=-3.0, initial_sigma=12.0,
            window_size=3, adaptive_scale=True, robust_likelihood=True),
    Learner(name="L3_skeptic",   initial_mu= 0.0, initial_sigma=20.0,
            window_size=5, adaptive_scale=True, robust_likelihood=True),
]
mother = MotherMind()
guard = StabilityGuard()
trust = TrustEngine()
for l in learners: trust.register(l.learner_id)

# 预热
print("=" * 60)
print("🌀 v2.7 完全自主探索")
print("=" * 60)
for _ in range(3):
    val = portal.poll()
    if val is None: break
    for l in learners: l.observe(val)

# ── 自主循环: 不依赖 sleep/debounce, 直接 step ──
SEARCH_RESULTS = [427.8, 428.4, 429.1]
si = 0
rounds = 0

for step in range(12):
    # 第一步: 检查好奇心
    signal, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.3,
        learners=learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )

    if signal == "search" and si < len(SEARCH_RESULTS):
        query = mother.formulate_query(learners)
        portal.emit_search(query)
        live.push(SEARCH_RESULTS[si])
        si += 1
        continue

    if signal:
        val = portal.poll()
        if val is None: continue
        for l in learners: l.observe(val)

        chains = [l.propose(val) for l in learners if l.observation_window]
        if not chains: continue

        decision = mother.deliberate(learners, chains, trust, val)
        portal.emit_decision(decision)
        rounds += 1

        if rounds >= 5: break

        for l in learners:
            if l.history:
                l.learn(val, l.history[-1])
            elif chains:
                idx = next((i for i, lb in enumerate(learners)
                           if lb.learner_id == l.learner_id), 0)
                prop = chains[min(idx, len(chains)-1)].proposal_value
                l.learn(val, prop)
            trust.verify(l.learner_id, l.history[-1] if l.history else val, val)

        gr = guard.check(learners, trust, decision.consensus,
                         abs(decision.consensus - val))
        if gr.get("violations"):
            portal.emit_alert(f"GUARD: {gr['violations']}")

# ── 结果 ──
print(f"\n━━━ 自主探索结果 ━━━")
print(f"搜索: {portal.curiosity.search_count} 次")
print(f"讨论: {rounds} 轮")
for l in sorted(learners, key=lambda x: x.track_record(), reverse=True):
    print(f"  {l.beliefs_summary()}")
print(f"\n{'✅' if portal.curiosity.search_count > 0 else '❌'} "
      f"自主搜索已触发")
