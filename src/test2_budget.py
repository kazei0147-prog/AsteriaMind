"""
Test 2: BudgetContest — 竞标机制验证

验证:
1. 高价值提案获胜
2. 垄断惩罚生效
3. 随机探索打破信息茧房
4. 不同 Learner 交替获胜
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from hivemind_v2.budget_contest import BudgetContest, ExplorationProposal

random.seed(123)

contest = BudgetContest(max_winners=1, random_explore_chance=0.15)

# 模拟三个 Learner 在不同轮次提交不同质量的提案
win_counts = {"A_accurate": 0, "B_medium": 0, "C_unreliable": 0}
random_wins = 0

for round_num in range(50):
    # A: 高准确率 + 高价值
    p_a = ExplorationProposal("A_accurate", "query_a", "hyp_a",
                               expected_value=0.9, cost=1.5,
                               uncertainty_source="sigma_high",
                               track_record=0.85)
    # B: 中等
    p_b = ExplorationProposal("B_medium", "query_b", "hyp_b",
                               expected_value=0.6, cost=1.0,
                               uncertainty_source="curiosity",
                               track_record=0.50)
    # C: 低准确率 — 应该很少赢
    p_c = ExplorationProposal("C_unreliable", "query_c", "hyp_c",
                               expected_value=0.5, cost=2.0,
                               uncertainty_source="curiosity",
                               track_record=0.20)

    winners = contest.evaluate([p_a, p_b, p_c])
    for w in winners:
        win_counts[w.learner_id] += 1

print("=" * 60)
print("Test 2: BudgetContest — 50轮竞标")
print("=" * 60)
print(f"总竞标: {contest.total_contests}")
print(f"随机探索: {contest.random_wins} ({contest.random_wins/50*100:.0f}%)")
print(f"\n获胜统计:")
for lid in ["A_accurate", "B_medium", "C_unreliable"]:
    pct = win_counts[lid] / 50 * 100
    bar = "█" * int(pct / 2)
    print(f"  {lid:15s}: {win_counts[lid]:2d} 胜 ({pct:4.1f}%) {bar}")
print(f"  随机探索:     {contest.random_wins:2d} 胜")

# 判定
a_win = win_counts["A_accurate"]
b_win = win_counts["B_medium"]
c_win = win_counts["C_unreliable"]

checks = []
checks.append(("A > B (准确者胜)", a_win > b_win))
checks.append(("A > C (低准确者少胜)", a_win > c_win))
checks.append(("B > 0 (中等者有机会)", b_win > 0))
checks.append(("随机探索 > 0", contest.random_wins > 0))

for label, result in checks:
    print(f"  {label}: {'✅' if result else '❌'}")

if all(r for _, r in checks):
    print("\n✅ Test 2 通过")
else:
    print("\n❌ Test 2 未通过")
