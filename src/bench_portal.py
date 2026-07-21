"""
v2.4 持续运行 + Portal I/O 验证

系统主动轮询数据源，好奇心驱动节奏。
输出通过 ConsoleSink 实时可见。
"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

import csv, os
from AsteriaMind.learner import Learner
from AsteriaMind.trust import TrustEngine
from AsteriaMind.mother import MotherMind
from AsteriaMind.guard import StabilityGuard
from AsteriaMind.portal import (
    Portal, CSVSource, ConsoleSink, LogSink, CuriosityEngine
)

# ── 数据源: CO2 数据，不循环（模拟有限数据流） ──
data_path = ("D:/AM/"
             "HiveMind_repo/experiments/data/co2_mauna_loa.csv")
source = CSVSource(data_path, loop=False)

# ── 出口: 控制台实时输出 ──
sink = ConsoleSink()

# ── 好奇心: 快速触发（测试用） ──
curiosity = CuriosityEngine(
    stale_threshold=0.1,   # 0.1秒无数据就触发（测试用）
    confidence_low=0.7,
    max_poll_interval=0.01,
)

portal = Portal(source=source, sinks=[sink], curiosity=curiosity)

# ── 手动创建 HiveMind（不走 orchestrator 的完整包装） ──
learners = [
    Learner(name="L1_optimist",  initial_mu=+3.0, initial_sigma=8.0,  window_size=5),
    Learner(name="L2_pessimist", initial_mu=-3.0, initial_sigma=8.0,  window_size=5),
    Learner(name="L3_skeptic",   initial_mu= 0.0, initial_sigma=15.0, window_size=10),
    Learner(name="L4_stubborn",  initial_mu= 0.0, initial_sigma=3.0,  window_size=3),
    Learner(name="L5_adaptable", initial_mu= 0.0, initial_sigma=10.0, window_size=12),
]
mother = MotherMind()
guard = StabilityGuard()
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

# ── 预热 ──
print("=" * 60)
print("v2.4 Portal + 好奇心驱动持续运行")
print("=" * 60)
print("预热中...")
for _ in range(30):
    val = portal.poll()
    if val is None: break
    for l in learners:
        l.observe(val)
print("预热完成, 进入好奇心驱动循环\n")

# ── 持续运行 ──
import time
round_num = 30
decisions = 0
MAX_DECISIONS = 8  # 测试用，够了就停

while portal.running and decisions < MAX_DECISIONS:
    should, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.5,
        learners=learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )

    if should:
        val = portal.poll()
        if val is None:
            if not source.has_more():
                portal.emit_status("数据源耗尽")
                break
            time.sleep(0.05)
            continue

        round_num += 1
        for l in learners:
            l.observe(val)

        if round_num % 5 == 0:
            chains = [l.propose(val) for l in learners]
            decision = mother.deliberate(learners, chains, trust, val)
            decisions += 1

            # 输出
            portal.emit_decision(decision)

            # Learner 表达
            if decision.dissenting_view:
                portal.emit_expression(
                    decision.primary_influence,
                    f"我认为共识应为 {decision.consensus:.1f}，但有不同意见: {decision.dissenting_view[:60]}"
                )

            # Guard
            gr = guard.check(learners, trust, decision.consensus,
                             abs(decision.consensus - val))
            if gr.get("violations"):
                portal.emit_alert(f"GUARD: {gr['violations']}")

            # 验证
            verify_val = val
            for l in learners:
                if l.history:
                    l.learn(verify_val, l.history[-1])
                    trust.verify(l.learner_id, l.history[-1], verify_val)

    time.sleep(0.02)

# ── 输出 Mother 印象 ──
print(f"\n━━━ 母模块印象 ━━━")
for lid, imp in mother.summary()["impressions"].items():
    print(f"  {lid:15s} → {imp['best_at']}")

print(f"\n总决策次数: {decisions}")
print(f"Guard 违规: {guard.violation_count}")
