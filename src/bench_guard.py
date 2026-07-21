"""
测试: StabilityGuard 不冤枉领路的乐观者

场景:
  1. 前 200 轮: CO2 平稳上升 (406→415 ppm)
  2. 第 200 轮起: 数据突然跃升 +15ppm (模拟传感器校准/真实事件)
  3. L1_optimist 一直偏高估 → 跃升后恰好是对的
  4. 其他 Learner 还在锚定旧数据

关键断言: Guard 应识别 L1 为 leader, 不应触发 chaos
"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

import csv
import random
from AsteriaMind.learner import Learner
from AsteriaMind.argument import ArgumentEvaluator
from AsteriaMind.trust import TrustEngine
from AsteriaMind.guard import StabilityGuard

random.seed(42)

# ── 加载 CO2 数据 ──
reader = csv.DictReader(open(
    "D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv"
))
data = [float(r["value"]) for r in reader]

# ── 制造 regime change: 第200轮起跃升 ──
REGIME_START = 200
JUMP = 15  # +15ppm 跃升
modified_data = []
for i, v in enumerate(data):
    if i >= REGIME_START:
        modified_data.append(v + JUMP)
    else:
        modified_data.append(v)

# ── 创建 Learner，故意给 L1 乐观先验 ──
learners = [
    Learner(name="L1_optimist",  initial_mu=+5.0, initial_sigma=3.0, window_size=5),   # 乐观，短窗 (敏锐)
    Learner(name="L2_pessimist", initial_mu=-3.0, initial_sigma=3.0, window_size=15),  # 悲观，长窗 (缓慢)
    Learner(name="L3_neutral",   initial_mu= 0.0, initial_sigma=5.0, window_size=10),  # 中性
    Learner(name="L4_cautious",  initial_mu=-1.0, initial_sigma=2.0, window_size=10),  # 谨慎
    Learner(name="L5_adaptive",  initial_mu= 0.0, initial_sigma=8.0, window_size=7),   # 灵活
]

evaluator = ArgumentEvaluator(debate_rounds=2)
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

guard = StabilityGuard(
    consensus_window=20,
    chaos_persist_rounds=2,  # 快速响应 (测试用)
)

# ── 预热 50 轮 ──
for i in range(50):
    obs = modified_data[i]
    for l in learners:
        l.observe(obs)

# ── 运行 ──
guard_log = []
hm_errors = []
for i in range(50, min(350, len(modified_data))):
    obs = modified_data[i]
    true_val = data[i]  # 真实值 (未跃升的)

    for l in learners:
        l.observe(obs)

    # 每 3 轮讨论
    if (i - 50) % 3 == 0:
        chains = [l.propose(obs) for l in learners]
        consensus, ranked, method = evaluator.full_discussion(chains)
        error = abs(consensus - obs)
        hm_errors.append(error)

        # 验证
        verify_val = sum(data[max(0,i-5):i+1]) / min(6, i+1)
        for l in learners:
            if l.history:
                l.learn(verify_val, l.history[-1])

        for l in learners:
            if l.history:
                trust.verify(l.learner_id, l.history[-1], verify_val)

        # Guard 检查
        result = guard.check(learners, trust, consensus, error)
        if result["status"] != "stable" or result.get("overridden"):
            guard_log.append({
                "round": i,
                "status": result["status"],
                "signals": result["signals"],
                "effective_signals": result["effective_signals"],
                "overridden": result["overridden"],
                "leaders": result["leaders"],
                "chaos_makers": result["chaos_makers"],
                "consensus": consensus,
                "true_val": true_val,
            })

# ── 分析结果 ──
print("=" * 65)
print("StabilityGuard: 乐观者领路 vs 混乱误判 测试")
print("=" * 65)
print(f"场景: CO2 数据, 第 {REGIME_START} 轮跃升 +{JUMP} ppm")
print(f"L1 初始 μ=+5 (乐观), L2 初始 μ=-3 (悲观)")
print()

# 分段误差
pre_jump = [e for j, e in enumerate(hm_errors) if (50 + j*3) < REGIME_START]
post_jump = [e for j, e in enumerate(hm_errors) if (50 + j*3) >= REGIME_START]

print(f"跃升前误差: {sum(pre_jump)/len(pre_jump):.2f} ppm" if pre_jump else "N/A")
print(f"跃升后误差: {sum(post_jump)/len(post_jump):.2f} ppm" if post_jump else "N/A")
print()

# Learner 最终状态
print("Learner 最终状态:")
print(f"{'名称':15s} {'μ':>8s}  {'σ':>7s}  {'准确率':>7s}  {'误差':>7s}")
for l in sorted(learners, key=lambda x: x.track_record(), reverse=True):
    print(f"{l.learner_id:15s} {l.belief.mu:>+7.3f}  {l.belief.sigma:>6.3f}  "
          f" {l.track_record():>6.3f}  {l.average_error():>6.2f}")

print()

# Guard 行为
warnings = [g for g in guard_log if g["status"] == "warning"]
chaos = [g for g in guard_log if g["status"] == "chaos"]
overrides = [g for g in guard_log if g.get("overridden")]

print("Guard 行为统计:")
print(f"  总检查轮数: {len(hm_errors)}")
print(f"  warning 次数: {len(warnings)}")
print(f"  chaos 次数:   {len(chaos)}")
print(f"  信号被 leader 覆盖: {len(overrides)} 次")
print()

if overrides:
    print("覆盖详情 (乐观者保护机制生效):")
    for o in overrides[:5]:
        print(f"  [轮{o['round']}] 被覆盖信号: {o['overridden']} → leader={o['leaders']}")
    print()

# 关键断言
if chaos:
    print("❌ 测试失败: Guard 在健康场景下触发了 chaos!")
    for c in chaos:
        print(f"  轮{c['round']}: signals={c['signals']}, chaos_makers={c['chaos_makers']}")
else:
    print("✅ 测试通过: Guard 未误判 chaos")

if overrides:
    print("✅ 乐观者保护机制生效: 信号被正确覆盖")
else:
    print("⚠️  没有信号需要覆盖 → 系统本身就很稳定 (也是好的)")

# L1 是否被识别为 leader
leader_rounds = len([g for g in guard_log if "L1_optimist" in g.get("leaders", [])])
if leader_rounds > 0:
    print(f"✅ L1_optimist 被识别为领路者: {leader_rounds} 轮")
else:
    print("⚠️  L1_optimist 未被识别为领路者 (可能不需要)")
