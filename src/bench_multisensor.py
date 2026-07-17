"""HM 2.0 多传感器故障容错 — 验证信任系统能否识别故障传感器"""
import sys, csv, random
sys.path.insert(0, 'D:/AM/HiveMind_repo/src')
from hivemind_v2.learner import Learner
from hivemind_v2.argument import ArgumentEvaluator
from hivemind_v2.trust import TrustEngine

reader = csv.DictReader(open('D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv'))
truth = [float(r['value']) for r in reader]
random.seed(42)

learners = [
    Learner(name='L1_sA_narrow', window_size=3),
    Learner(name='L2_sA_wide',   window_size=15),
    Learner(name='L3_sB_medium', window_size=7),
    Learner(name='L4_sB_narrow', window_size=3),
    Learner(name='L5_sC_wide',   window_size=15),  # 接故障传感器C
]
sensor_map = {'L1_sA_narrow':'A','L2_sA_wide':'A','L3_sB_medium':'B','L4_sB_narrow':'B','L5_sC_wide':'C'}

evaluator = ArgumentEvaluator(debate_rounds=2)
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)

FAULT_S = 200; FAULT_E = 230; FAULT_BIAS = -50

hm_errs = []; avg_errs = []
last_proposals = {}

for i in range(50, min(300, len(truth))):
    tv = truth[i]
    sA = tv + random.gauss(0, 1.0)
    sB = tv + random.gauss(0, 1.5)
    sC = tv + random.gauss(0, 1.0) + (FAULT_BIAS if FAULT_S <= i <= FAULT_E else 0)
    readings = {'A': sA, 'B': sB, 'C': sC}

    for l in learners:
        l.observe(readings[sensor_map[l.learner_id]])

    # 讨论(每5轮)
    if (i - 50) % 5 == 0:
        chains = [l.propose(readings[sensor_map[l.learner_id]]) for l in learners]
        last_proposals = {l.learner_id: c.proposal_value for l, c in zip(learners, chains)}
        consensus, ranked, method = evaluator.full_discussion(chains)
        hm_errs.append((i, abs(consensus - tv)))

    # 验证(故障期每轮, 正常期每5轮)
    vf = 1 if FAULT_S <= i <= FAULT_E else 5
    if (i - 50) % vf == 0:
        vv = sum(truth[max(0,i-5):i]) / min(i, 5)
        for l in learners:
            pid = l.learner_id
            if pid in last_proposals:
                # FIX (2026-07-17): same deadlock as bench_v2 — `if l.history:`
                # guard + learn() as sole history writer → learning never started.
                l.learn(vv, last_proposals[pid])
                trust.verify(pid, last_proposals[pid], vv)

    avg_errs.append((i, abs((sA+sB+sC)/3 - tv)))

def ss(e, s, e2):
    sub = [v for t, v in e if s <= t <= e2]
    return (sum(sub)/len(sub), max(sub)) if sub else (0, 0)

hp = ss(hm_errs, 50, 199); hf = ss(hm_errs, 200, 230); hr = ss(hm_errs, 231, 300)
ap = ss(avg_errs, 50, 199); af = ss(avg_errs, 200, 230); ar = ss(avg_errs, 231, 300)

print("=" * 70)
print(f"多传感器故障: 传感器C 第{FAULT_S}-{FAULT_E}轮故障(偏低{abs(FAULT_BIAS)}ppm)")
print("=" * 70)
print(f"{'':15s} {'HM 2.0':>20s} {'简单平均':>20s}")
print(f"{'正常期':15s} {hp[0]:>8.2f}/max{hp[1]:5.1f}      {ap[0]:>8.2f}/max{ap[1]:5.1f}")
print(f"{'故障期':15s} {hf[0]:>8.2f}/max{hf[1]:5.1f}      {af[0]:>8.2f}/max{af[1]:5.1f}  ← HM {af[0]/max(hf[0],0.01):.1f}x better")
print(f"{'恢复期':15s} {hr[0]:>8.2f}/max{hr[1]:5.1f}      {ar[0]:>8.2f}/max{ar[1]:5.1f}")

print(f"\n信任变化:")
for l in sorted(learners, key=lambda x: trust.get(x.learner_id)):
    s = sensor_map[l.learner_id]
    m = " ← 故障!" if s == 'C' else ""
    print(f"  {l.learner_id:18s} [{s}] trust={trust.get(l.learner_id):.3f} mu={l.belief.mu:+.2f}{m}")

ft = trust.get('L5_sC_wide')
ht = sum(trust.get(l.learner_id) for l in learners if sensor_map[l.learner_id]!='C') / 4
print(f"\n故障传感器信任: {ft:.3f} vs 正常平均: {ht:.3f} ({'已识别✓' if ft < ht-0.05 else '未充分识别'})")

ok = hf[0] < 5 and af[0] > 10
print(f"\n目标: HM<5ppm 且 简单平均>10ppm → {'✓ PASS!' if ok else '接近 (' + f'HM={hf[0]:.2f}' + ')'}")
