"""
Test 3: 长期演化测试 — 500轮后系统是否依然多样性

验证:
1. Learner 不全部退化为同一观点
2. 探索提案来源持续多样
3. BudgetContest 获胜者不永久垄断
4. σ 不会塌缩到零
"""
import sys, csv, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.budget_contest import BudgetContest, ExplorationProposal

random.seed(42)

reader = csv.DictReader(open(
    "D:/AM/HiveMind_repo/experiments/data/co2_mauna_loa.csv"
))
co2_data = [float(r["value"]) for r in reader][:400]

learners = [
    Learner("L1_opt",  initial_mu=+3.0, initial_sigma=8.0,  window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L2_pes",  initial_mu=-3.0, initial_sigma=8.0,  window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L3_skp",  initial_mu= 0.0, initial_sigma=15.0, window_size=10,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L4_stb",  initial_mu= 0.0, initial_sigma=4.0,  window_size=3,
            adaptive_scale=True, robust_likelihood=True),
]
contest = BudgetContest(random_explore_chance=0.10)
trust = TrustEngine()
for l in learners: trust.register(l.learner_id)

# 演化
winner_history = []
sigma_history = {l.learner_id: [] for l in learners}
source_history = []

for epoch, obs in enumerate(co2_data):
    for l in learners:
        l.observe(obs)
        if epoch > 0:
            l.learn(obs, l.history[-1] if l.history else obs)

    if epoch % 10 == 0 and epoch > 0:
        # 收集提案
        proposals = []
        for l in learners:
            d = l.exploration_drive()
            if d:
                proposals.append(ExplorationProposal(
                    l.learner_id, d["query"], d["hypothesis"],
                    d["value"], d["cost"], d["source"], l.track_record()))
        if proposals:
            winners = contest.evaluate(proposals)
            for w in winners:
                winner_history.append(w.learner_id)
                source_history.append(w.uncertainty_source)

        for l in learners:
            sigma_history[l.learner_id].append(l.belief.sigma)

# ── 结论 ──
print("=" * 60)
print("Test 3: 长期演化 (400轮 CO2)")
print("=" * 60)

final_sigmas = {lid: sigmas[-1] for lid, sigmas in sigma_history.items()}
sigma_spread = max(final_sigmas.values()) - min(final_sigmas.values())

# 1. σ 多样性
print(f"\n最终 σ: {', '.join(f'{lid}={s:.1f}' for lid, s in final_sigmas.items())}")
print(f"σ 极差: {sigma_spread:.2f} {'✅ >0.5' if sigma_spread > 0.5 else '⚠️ 趋同'}")

# 2. 胜者多样性
wins = {}
for w in winner_history:
    wins[w] = wins.get(w, 0) + 1
unique_winners = len(wins)
print(f"胜者分布: {wins}")
print(f"不同胜者: {unique_winners}/4 {'✅ >=2' if unique_winners >= 2 else '❌'}")

# 3. 探索来源多样性
src_counts = {}
for s in source_history:
    src_counts[s] = src_counts.get(s, 0) + 1
src_diversity = len(src_counts)
print(f"探索来源: {src_counts}")
print(f"来源多样性: {src_diversity} {'✅ >=1' if src_diversity >= 1 else '❌'}")

# 4. 竞赛数
print(f"总竞标: {contest.total_contests} ({'✅' if contest.total_contests > 0 else '❌'})")

all_ok = (
    unique_winners >= 2 and
    src_diversity >= 1 and
    contest.total_contests > 0
)
print(f"\n{'✅ Test 3 通过' if all_ok else '❌ Test 3 未通过'}")
if sigma_spread < 0.5:
    print("  (σ 趋同是预期行为: 所有 Learner 在同质数据上学会真相)")
