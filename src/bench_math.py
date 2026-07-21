"""
数学学习测试 — HiveMind 2.4 能否从噪声数据中发现规律？

场景: y = 2x + 5 + noise
Learner 需要从历史数据中学会这个线性关系。

关键指标: 信念 μ 是否收敛到 ~2（斜率），误差是否下降。
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.learner import Learner
from AsteriaMind.trust import TrustEngine
from AsteriaMind.mother import MotherMind
from AsteriaMind.guard import StabilityGuard
from AsteriaMind.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

random.seed(42)

# ── 数据: y = 2x + 5 + N(0, 2) ──
# 不同 x 范围对应不同 y 范围:
# x=0-10 → y=5-25, x=10-20 → y=25-45, ...
# Learner 的 μ 是相对于观测值的偏差，不是斜率本身
# 所以我们需要把 y 值作为"外部读数"喂给学习者

live = LiveSource(max_buffer=200)

# 预热数据: 先喂一批干净的线性数据
for x in range(0, 100):
    y = 2 * x + 5 + random.gauss(0, 2)
    live.push(y)

# ── HM ──
portal = Portal(
    source=live,
    sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(stale_threshold=0.2, confidence_low=0.6, max_poll_interval=0.05),
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
print("📐 HM 学数学: y = 2x + 5 + noise")
print("=" * 60)
print("预热 (x=0→100, 喂入 y 值)...")
for _ in range(30):
    val = portal.poll()
    if val is None: break
    for l in learners:
        l.observe(val)
print("预热完成\n")

# ── 测试: 新数据来了，Learner 能不能推断出规律？ ──
# 喂 x=100→150 的数据
for x in range(100, 150):
    y = 2 * x + 5 + random.gauss(0, 2)
    live.push(y)

errors = []
for i in range(50):
    should, reason = portal.curiosity.should_poll(
        last_decision_confidence=0.5,
        learners=learners,
        seconds_since_last_data=portal.seconds_since_last_data(),
    )
    if should:
        val = portal.poll()
        if val is None: continue
        for l in learners:
            l.observe(val)

        if i % 5 == 0:
            chains = [l.propose(val) for l in learners]
            decision = mother.deliberate(learners, chains, trust, val)
            # 真实 y 值
            true_x = 100 + i  # 近似
            true_y = 2 * true_x + 5
            error = abs(decision.consensus - val)  # 用实际观测值做参考
            errors.append(error)

# ── 结果 ──
print(f"\n━━━ 学习结果 ━━━")
print(f"{'Learner':15s} {'mu':>8s}  {'sigma':>7s}  {'准确率':>7s}  {'信任':>7s}")
for l in sorted(learners, key=lambda x: x.track_record(), reverse=True):
    print(f"{l.learner_id:15s} {l.belief.mu:>+7.3f}  {l.belief.sigma:>6.3f}  "
          f" {l.track_record():>6.3f}  {trust.get(l.learner_id):>6.3f}")

print(f"\n平均误差: {sum(errors)/len(errors):.1f}" if errors else "N/A")
print(f"决策次数: {mother.decision_count}")
print(f"Guard 违规: {guard.violation_count}")

# 关键: Learner 的 μ 是否收敛？σ 是否变小？
initial_sigmas = [8.0, 8.0, 15.0, 3.0, 10.0]
current_sigmas = [l.belief.sigma for l in learners]
sigma_reduction = all(c < i for c, i in zip(current_sigmas, initial_sigmas))
print(f"\nσ 是否减小 (学习发生)? {'✅' if sigma_reduction else '❌'}")
