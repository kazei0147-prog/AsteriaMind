"""HiveMind 2.0 CO2 基准测试"""
import sys, csv
sys.path.insert(0, 'D:/AM/HiveMind_repo/src')
from hivemind_v2.learner import Learner
from hivemind_v2.argument import ArgumentEvaluator
from hivemind_v2.trust import TrustEngine

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

for i in range(warmup, min(400, len(data))):
    obs = data[i]
    for l in learners:
        l.observe(obs)

    if (i - warmup) % 5 == 0:
        chains = [l.propose(obs) for l in learners]
        proposals = {l.learner_id: c.proposal_value for l, c in zip(learners, chains)}
        consensus, ranked, method = evaluator.full_discussion(chains)
        consensus_errors.append(abs(consensus - obs))

        verify_val = sum(data[i-5:i]) / 5 if i >= 5 else obs
        for l in learners:
            # FIX (2026-07-17): learn() is the only writer of l.history, so the
            # old `if l.history:` guard deadlocked the learning loop (it never ran).
            # Verify against THIS round's proposal so the loop actually executes.
            l.learn(verify_val, proposals[l.learner_id])
            trust.verify(l.learner_id, proposals[l.learner_id], verify_val)

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
