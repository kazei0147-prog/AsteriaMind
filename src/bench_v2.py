"""HiveMind 2.0 CO2 基准测试"""
import sys, csv
sys.path.insert(0, 'D:/AM/HiveMind_repo/src')
from hivemind_v2.learner import Learner
from hivemind_v2.argument import ArgumentEvaluator
from hivemind_v2.trust import TrustEngine
from hivemind_v2.validator import CrossValidator

reader = csv.DictReader(open('D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv'))
data = [float(r['value']) for r in reader]

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

warmup = 50
for i in range(warmup):
    obs = data[i]
    for l in learners:
        l.observe(obs)

consensus_errors = []
ma_errors = []
WINDOW = 10

validator = CrossValidator()

for i in range(warmup, min(400, len(data))):
    obs = data[i]
    for l in learners:
        l.observe(obs)

    if (i - warmup) % 5 == 0:
        chains = [l.propose(obs) for l in learners]
        proposals = {l.learner_id: c.proposal_value for l, c in zip(learners, chains)}

        # === Anchor 2: 方案 B 交叉验证 ===
        # 旁观者不参与共识辩论、不 learn()——冻结其内部状态，
        # 纯记录原始信念的预测误差，做因果隔离对照。
        observer = validator.select_observer([l.learner_id for l in learners])
        non_observer_chains = [c for c in chains if c.learner_id != observer]
        consensus, ranked, method = (
            evaluator.full_discussion(non_observer_chains)
            if non_observer_chains else (0.0, [], "no debate (all silent)")
        )
        consensus_errors.append(abs(consensus - obs))

        verify_val = sum(data[i-5:i]) / 5 if i >= 5 else obs
        for l in learners:
            pid = l.learner_id
            err = abs(proposals[pid] - verify_val)
            if pid == observer:
                # 方案 B: 静默期跳过学习，只记录原始信念误差
                validator.record_silent(pid, err)
            else:
                l.learn(verify_val, proposals[pid])
                trust.verify(pid, proposals[pid], verify_val)
                validator.record_active(pid, err)

    if i >= warmup + WINDOW:
        ma = sum(data[i-WINDOW:i]) / WINDOW
        ma_errors.append(abs(ma - data[i]))

hm_mae = sum(consensus_errors)/len(consensus_errors)
ma_mae = sum(ma_errors)/len(ma_errors)

print('===== HiveMind 2.0 vs Moving Average (CO2) =====')
print(f'HM 2.0 consensus MAE: {hm_mae:.2f} ppm')
print(f'Moving avg MAE:       {ma_mae:.2f} ppm')
print(f'Ratio:                {ma_mae/hm_mae:.2f}x' if hm_mae > 0 else '')

print('\nLearner final states:')
for l in sorted(learners, key=lambda x: x.belief.mu):
    print(f'  {l.beliefs_summary()}  trust={trust.get(l.learner_id):.3f}')

print(f'\nMost trusted: {trust.rank()[0]}')
print('\n=== Comparison ===')
print(f'v0.6 HM error on CO2: 31.69 ppm')
print(f'v2.0 HM error on CO2: {hm_mae:.2f} ppm')
print(f'Improvement:          {(31.69 - hm_mae):.2f} ppm')

print(f'\n===== CrossValidator 诊断 (Anchor 2: 静默期对照) =====')
print(f'  {"Learner":20s} {"静默误差":>8s} {"活跃误差":>8s} {"比值":>8s} {"诊断":>20s}')
for row in validator.diagnosis():
    tag = {"consensus_drags": "共识在拖累它 ⚠️",
           "free_rider": "搭共识便车",
           "independent": "独立准确 ✓",
           "insufficient_data": "数据不足"}.get(row["diagnosis"], row["diagnosis"])
    print(f'  {row["learner"]:20s} {row["silent_err"]:>7.2f}  {row["active_err"]:>7.2f}  {row["ratio"]:>7.2f}  {tag:>20s}')
