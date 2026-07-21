"""
自主查询演示 — HiveMind 2.4 + 知识缺口触发搜索

场景:
- 初始只有少量 CO2 数据 → 置信度持续低 → 触发 knowledge_gap
- 系统自动搜索 "Mauna Loa CO2 latest" → 拿到新数据 → 置信度回升

第四触发器: curiosity → "search" → WebSearch → push_result → HM 处理
"""
import sys, time
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.learner import Learner
from AsteriaMind.trust import TrustEngine
from AsteriaMind.mother import MotherMind
from AsteriaMind.guard import StabilityGuard
from AsteriaMind.portal import (
    Portal, LiveSource, SearchDataSource, ConsoleSink, CuriosityEngine
)

# ── 数据源: 初始数据极少 ──
live = LiveSource(max_buffer=50)
search = SearchDataSource()

# 初始只有 3 个数据点 → Learner 高度不确定
for v in [415, 420, 418]:
    live.push(v)

portal = Portal(
    source=live,
    sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(
        stale_threshold=0.5,
        confidence_low=0.7,          # 高阈值 → 容易触发低置信
        knowledge_gap_rounds=2,       # 2 轮低置信就搜索
    ),
)

learners = [
    Learner(name="L1_optimist",  initial_mu=+3.0, initial_sigma=12.0, window_size=3),
    Learner(name="L2_pessimist", initial_mu=-3.0, initial_sigma=12.0, window_size=3),
    Learner(name="L3_skeptic",   initial_mu= 0.0, initial_sigma=20.0, window_size=5),
]
mother = MotherMind()
guard = StabilityGuard()
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

# ── 预热 ──
print("=" * 60)
print("🔍 自主查询演示: 知识缺口 → 搜索 → 学习")
print("=" * 60)
print("初始数据: 仅 3 个 CO2 读数 → Learner 高度不确定\n")
for _ in range(5):
    val = portal.poll()
    if val is None: break
    for l in learners:
        l.observe(val)

# ── 持续运行 ──
low_conf_count = 0
searches = 0

for i in range(20):
    should, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.4,  # 故意低置信
        learners=learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )

    if should == "search":
        # ── 知识缺口! 触发搜索 ──
        query = "Mauna Loa CO2 latest weekly ppm"
        portal.emit_alert(f"🔍 自主搜索: '{query}' — {reason}")
        searches += 1

        # 模拟 WebSearch 返回结果 (实际: WebSearch → parse → push)
        # 用 NOAA 真实数据: 427.79, 428.40, 429.11
        for v in [427.8, 428.4, 429.1]:
            search.push_result(v)

        # 切换到搜索结果数据源
        val = search.poll()
        if val is not None:
            for l in learners:
                l.observe(val)

    elif should:
        val = portal.poll()
        if val is None:
            # 尝试 search 源
            val = search.poll()
        if val is not None:
            for l in learners:
                l.observe(val)

    # 讨论
    if i % 3 == 0 and any(l.history for l in learners):
        obs = learners[0].observation_window[-1] if learners[0].observation_window else 420
        chains = [l.propose(obs) for l in learners]
        decision = mother.deliberate(learners, chains, trust, obs)
        portal.emit_decision(decision)
        if decision.confidence < 0.6:
            low_conf_count += 1
        for l in learners:
            if l.history:
                l.learn(obs, l.history[-1])
                trust.verify(l.learner_id, l.history[-1], obs)

    time.sleep(0.02)

# ── 结果 ──
print(f"\n━━━ 自主查询结果 ━━━")
print(f"触发搜索: {searches} 次")
print(f"低置信轮: {low_conf_count}")
print(f"Learner 状态:")
for l in sorted(learners, key=lambda x: x.track_record(), reverse=True):
    print(f"  {l.learner_id:15s} μ={l.belief.mu:+.2f}  σ={l.belief.sigma:.1f}  "
          f"准确率={l.track_record():.2f}  信任={trust.get(l.learner_id):.2f}")
print(f"\n{'✅' if searches > 0 else '❌'} 知识缺口触发器已激活")
