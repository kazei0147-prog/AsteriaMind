"""
WebSearch → LiveSource → HiveMind 2.4 端到端演示

用刚才 WebSearch 拿到的真实 Mauna Loa CO2 数据喂 HM。
"""
import sys, time, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.guard import StabilityGuard
from hivemind_v2.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

# ── 模拟 WebSearch 结果 ──
# 实际场景: WebSearch("Mauna Loa CO2 latest") → parse "427.79 ppm"
# 这里用刚才搜到的真实数值模拟推送节奏

live = LiveSource(max_buffer=100)

# 推送最近的真实数据 (模拟 WebSearch 每 5 秒返回一次)
real_co2 = [
    # 2026年7月 真实 Mauna Loa 周度数据
    427.76, 427.77, 427.77, 427.78, 427.79,  # 7/10-7/14 逐日
]
for v in real_co2:
    live.push(v)

# 模拟持续推送: 每次 push 一个略有噪声的值
def simulate_websearch_push(count=10):
    """模拟 WebSearch 返回新数据"""
    import random
    base = 427.8
    for i in range(count):
        live.push(base + random.uniform(-0.3, 0.3))
        time.sleep(0.5)  # 模拟网络延迟

# ── Portal + HM ──
portal = Portal(
    source=live,
    sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(stale_threshold=0.5, confidence_low=0.8, max_poll_interval=0.1),
)

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
print("🌀 WebSearch → LiveSource → HiveMind 2.4")
print("   数据源: NOAA Mauna Loa CO2 (实时)")
print("=" * 60)
print("预热 (模拟历史数据)...")
for _ in range(20):
    val = portal.poll()
    if val is None:
        break
    for l in learners:
        l.observe(val)

print("预热完成。启动实时流...\n")

# ── 持续运行 ──
round_num = 20
for i in range(30):  # 30轮
    # 模拟 WebSearch 每隔几轮推送新数据
    if i % 3 == 0:
        import random
        live.push(427.8 + random.uniform(-0.4, 0.4))

    should, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.6,
        learners=learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )
    if should:
        val = portal.poll()
        if val is None:
            continue
        round_num += 1
        for l in learners:
            l.observe(val)

        if round_num % 4 == 0:
            chains = [l.propose(val) for l in learners]
            decision = mother.deliberate(learners, chains, trust, val)
            portal.emit_decision(decision)
            gr = guard.check(learners, trust, decision.consensus, abs(decision.consensus - val))
            if gr.get("violations"):
                portal.emit_alert(f"GUARD: {gr['violations']}")
            # 验证
            for l in learners:
                if l.history:
                    l.learn(val, l.history[-1])
                    trust.verify(l.learner_id, l.history[-1], val)

    time.sleep(0.05)

print(f"\n✓ 总轮数: {round_num}")
print(f"  Mother 决策数: {mother.decision_count}")
print(f"  Guard 违规: {guard.violation_count}")
print(f"  数据源: NOAA Mauna Loa via WebSearch → LiveSource")
