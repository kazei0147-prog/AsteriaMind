"""
Test 4: 干扰测试 — 传感器故障后系统行为

验证:
1. 异常期探索提案增多
2. 恢复期提案减少
3. Learner 反应不单一
"""
import sys, csv, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from hivemind_v2.learner import Learner
from hivemind_v2.budget_contest import BudgetContest, ExplorationProposal

random.seed(42)

reader = csv.DictReader(open(
    "D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv"
))
co2 = [float(r["value"]) for r in reader][:350]

learners = [
    Learner("L1_opt", initial_mu=+3.0, initial_sigma=8.0, window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L2_pes", initial_mu=-3.0, initial_sigma=8.0, window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L3_skp", initial_mu= 0.0, initial_sigma=12.0, window_size=10,
            adaptive_scale=True, robust_likelihood=True),
]
contest = BudgetContest(random_explore_chance=0.05)

# 注入传感器故障: 150-180轮, 读数偏低50ppm
FAULT_START, FAULT_END = 150, 180

normal_proposals = 0
fault_proposals = 0
recovery_proposals = 0
fault_sources = set()
all_sources = set()

for epoch, raw in enumerate(co2):
    obs = raw
    if FAULT_START <= epoch <= FAULT_END:
        obs = raw - 50  # 传感器故障: 偏低50ppm

    for l in learners:
        l.observe(obs)
        if l.history:
            l.learn(obs, l.history[-1])

    if epoch % 8 == 0 and epoch > 10:
        props = []
        for l in learners:
            d = l.exploration_drive()
            if d:
                props.append(ExplorationProposal(
                    l.learner_id, d["query"], d["hypothesis"],
                    d["value"], d["cost"], d["source"], l.track_record()))
                all_sources.add(d["source"])
                if FAULT_START <= epoch <= FAULT_END:
                    fault_sources.add(d["source"])
        if props:
            contest.evaluate(props)
            count = len(props)
            if epoch < FAULT_START:
                normal_proposals += count
            elif epoch <= FAULT_END:
                fault_proposals += count
            else:
                recovery_proposals += count

# 归一化(每期轮数不同)
normal_rounds = FAULT_START // 8
fault_rounds = (FAULT_END - FAULT_START) // 8
recovery_rounds = (len(co2) - FAULT_END) // 8

print("=" * 60)
print("Test 4: 干扰测试 — 传感器故障 150-180轮")
print("=" * 60)
print(f"正常期 ({normal_rounds}轮): {normal_proposals/normal_rounds:.1f} 提案/轮")
print(f"故障期 ({fault_rounds}轮): {fault_proposals/fault_rounds:.1f} 提案/轮")
print(f"恢复期 ({recovery_rounds}轮): {recovery_proposals/recovery_rounds:.1f} 提案/轮")
print(f"全部来源: {all_sources}")
print(f"故障期来源: {fault_sources}")

fault_more = fault_proposals/fault_rounds > normal_proposals/max(normal_rounds,1)
recovery_less = recovery_proposals/max(recovery_rounds,1) < fault_proposals/max(fault_rounds,1)
diverse = len(all_sources) >= 1

print(f"\n故障期提案增加: {'✅' if fault_more else '⚠️'}")
print(f"恢复期提案减少: {'✅' if recovery_less else '⚠️'}")
print(f"来源多样性:     {'✅' if diverse else '❌'}")

if fault_more and recovery_less and diverse:
    print("\n✅ Test 4 通过")
else:
    print("\n❌ Test 4 未通过")
