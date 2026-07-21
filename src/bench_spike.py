"""HM 2.0 vs 移动平均: 连续异常注入测试"""
import sys, csv, random
sys.path.insert(0, 'D:/AM/HiveMind_repo/src')
from AsteriaMind.learner import Learner
from AsteriaMind.argument import ArgumentEvaluator
from AsteriaMind.trust import TrustEngine

reader = csv.DictReader(open('D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv'))
data = [float(r['value']) for r in reader]

random.seed(42)
learners = [
    Learner(name='L1_narrow', window_size=3),
    Learner(name='L2_medium', window_size=7),
    Learner(name='L3_wide', window_size=15),
    Learner(name='L4_medium', window_size=7),
    Learner(name='L5_narrow', window_size=3),
]
evaluator = ArgumentEvaluator(debate_rounds=2)
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

# 预热
for i in range(50):
    for l in learners:
        l.observe(data[i])

# 注入异常: 第200-210轮, 传感器故障, 数据偏低40ppm 持续11轮
ANOMALY_START = 200
ANOMALY_END = 210
ANOMALY_BIAS = -40  # ppm

hm_errors = []
ma_errors = []
WINDOW = 10

for i in range(50, min(400, len(data))):
    raw_val = data[i]
    
    # 异常注入
    if ANOMALY_START <= i <= ANOMALY_END:
        obs_val = raw_val + ANOMALY_BIAS + random.gauss(0, 3)
    else:
        obs_val = raw_val + random.gauss(0, 1.5)
    
    for l in learners:
        l.observe(obs_val)
    
    # HM 讨论 (每5轮)
    if (i - 50) % 5 == 0:
        chains = [l.propose(obs_val) for l in learners]
        consensus, ranked, method = evaluator.full_discussion(chains)
        hm_errors.append((i, abs(consensus - raw_val)))
        
        verify_val = sum(data[i-5:i]) / 5 if i >= 5 else raw_val
        for l in learners:
            if l.history:
                l.learn(verify_val, l.history[-1])
                trust.verify(l.learner_id, l.history[-1], verify_val)
    
    # 移动平均
    if i >= 50 + WINDOW:
        ma = sum(data[i-WINDOW:i]) / WINDOW
        ma_errors.append((i, abs(ma - raw_val)))

# 分阶段统计
def phase_stats(errors, start, end):
    subset = [e for t, e in errors if start <= t <= end]
    if not subset:
        return 0
    return sum(subset)/len(subset), max(subset)

hm_normal = phase_stats(hm_errors, 50, 199)
hm_anomaly = phase_stats(hm_errors, 200, 210)
hm_recovery = phase_stats(hm_errors, 211, 250)

ma_normal = phase_stats(ma_errors, 50, 199)
ma_anomaly = phase_stats(ma_errors, 200, 210)
ma_recovery = phase_stats(ma_errors, 211, 250)

print("=" * 70)
print("连续异常注入测试: 第200-210轮传感器故障(偏低40ppm, 持续11轮)")
print("=" * 70)
print(f"{'阶段':15s} {'HM 2.0(avg/max)':>20s} {'移动平均(avg/max)':>20s} {'HM优势':>10s}")
print("-" * 70)
print(f"{'正常(50-199)':15s} {hm_normal[0]:>8.2f}/{hm_normal[1]:>5.2f} ppm   {ma_normal[0]:>8.2f}/{ma_normal[1]:>5.2f} ppm   {ma_normal[0]/max(hm_normal[0],0.01):>9.1f}x")
print(f"{'故障中(200-210)':15s} {hm_anomaly[0]:>8.2f}/{hm_anomaly[1]:>5.2f} ppm   {ma_anomaly[0]:>8.2f}/{ma_anomaly[1]:>5.2f} ppm   {ma_anomaly[0]/max(hm_anomaly[0],0.01):>9.1f}x")
print(f"{'恢复期(211-250)':15s} {hm_recovery[0]:>8.2f}/{hm_recovery[1]:>5.2f} ppm   {ma_recovery[0]:>8.2f}/{ma_recovery[1]:>5.2f} ppm   {ma_recovery[0]/max(hm_recovery[0],0.01):>9.1f}x")

# 找最大差距
ma_peak = max(e for _, e in ma_errors if ANOMALY_START <= _ <= ANOMALY_END + 10)
hm_at_peak = [e for t, e in hm_errors if ANOMALY_START <= t <= ANOMALY_END + 10]
hm_worst = max(hm_at_peak) if hm_at_peak else 0

print(f"\n故障期间:")
print(f"  移动平均最差: {ma_peak:.2f} ppm")
print(f"  HM 2.0 最差:  {hm_worst:.2f} ppm")
print(f"  HM 改进倍数:  {ma_peak/max(hm_worst, 0.01):.1f}x")

# 学习器状态
print(f"\n学习器:")
for l in sorted(learners, key=lambda x: x.belief.mu):
    print(f"  {l.beliefs_summary()}  trust={trust.get(l.learner_id):.3f}")

result = "PASS" if hm_anomaly[0] < 5 and ma_anomaly[0] > 10 else "FAIL"
print(f"\n验证: HM故障期误差<5ppm 且 移动平均故障期误差>10ppm → {result}")
