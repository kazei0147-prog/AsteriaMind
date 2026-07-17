"""
v2.9 三层自治探索 — 母驱动，子探索

C: Learner 产生 exploration_drive → 生成提案
A: BudgetContest 竞标 → 分配资源
B: 胜者获得搜索权 → 得到新数据 → 学习
"""
import sys, random
sys.path.insert(0, "C:/Users/Administrator/WorkBuddy/2026-07-01-13-51-12/HiveMind_repo/src")

from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine
from hivemind_v2.budget_contest import BudgetContest, ExplorationProposal

random.seed(42)

live = LiveSource(max_buffer=100)
live.push(415); live.push(420)

portal = Portal(source=live, sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(confidence_low=0.7, knowledge_gap_rounds=2))

learners = [
    Learner("L1_optimist",  initial_mu=+3.0, initial_sigma=12.0, window_size=3,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L2_pessimist", initial_mu=-3.0, initial_sigma=12.0, window_size=3,
            adaptive_scale=True, robust_likelihood=True),
    Learner("L3_skeptic",   initial_mu= 0.0, initial_sigma=20.0, window_size=5,
            adaptive_scale=True, robust_likelihood=True),
]
mother = MotherMind()
contest = BudgetContest(max_winners=1, random_explore_chance=0.10)
trust = TrustEngine()
for l in learners: trust.register(l.learner_id)

SEARCH_DB = {
    "latest data reading": [427.8, 428.4, 429.1],
    "anomaly detection": [428, 415, 429],  # 2nd is anomalous
    "trend analysis": [427.5, 427.8, 428.1],
    "pattern discovery": [427, 428, 427],
    "temperature": [1.2, 1.3, 1.25],
    "CO2": [427.8, 427.9, 428.0],
    "default": [427.8, 428.0, 427.9],
}

def execute_search(query: str):
    """模拟搜索执行 — 实际: WebSearch(query) → parse → results"""
    for key in SEARCH_DB:
        if key in query.lower():
            return SEARCH_DB[key]
    return SEARCH_DB["default"]

# 预热
for _ in range(3):
    val = portal.poll()
    if val is None: break
    for l in learners: l.observe(val)

# ── 自治探索循环 ──
print("=" * 60)
print("🔬 v2.9 三层自治: 母驱动，子探索")
print("=" * 60)
print(f"Learner 初始状态:")
for l in learners:
    print(f"  {l.learner_id}: σ={l.belief.sigma:.1f} track={l.track_record():.2f}")

rounds = 0
for epoch in range(6):
    # ── 第1层 (C): 每个 Learner 产生探索欲 ──
    proposals = []
    for l in learners:
        drive = l.exploration_drive()
        if drive:
            proposals.append(ExplorationProposal(
                learner_id=l.learner_id,
                query=drive["query"],
                hypothesis=drive["hypothesis"],
                expected_value=drive["value"],
                cost=drive["cost"],
                uncertainty_source=drive["source"],
                track_record=l.track_record(),
            ))

    if not proposals:
        print(f"\n[轮{epoch}] 所有 Learner 都很确定，跳过探索")
        continue

    # ── 第2层 (A): BudgetContest 竞标 ──
    winners = contest.evaluate(proposals)
    print(f"\n[轮{epoch}] {len(proposals)} 个提案 → 胜者: {winners[0].learner_id if winners else '无'}")

    # ── 第3层 (B): 胜者执行搜索 ──
    for w in winners:
        results = execute_search(w.query)
        source_tag = w.uncertainty_source
        print(f"  [{w.learner_id}] 搜索: '{w.query[:50]}...' ({source_tag})")
        print(f"    理由: {w.hypothesis[:80]}")
        print(f"    结果: {[f'{v:.1f}' for v in results]}")

        for v in results:
            live.push(v)

        # 处理搜索结果
        for _ in range(3):
            val = portal.poll()
            if val is None: break
            for l in learners: l.observe(val)

            chains = [l1.propose(val) for l1 in learners if l1.observation_window]
            if chains:
                decision = mother.deliberate(learners, chains, trust, val)
                rounds += 1
                for l1 in learners:
                    if l1.history:
                        l1.learn(val, l1.history[-1])
                    elif chains:
                        idx = next((i for i, lb in enumerate(learners)
                                   if lb.learner_id == l1.learner_id), 0)
                        prop = chains[min(idx, len(chains)-1)].proposal_value
                        l1.learn(val, prop)
                    trust.verify(l1.learner_id, l1.history[-1] if l1.history else val, val)

# ── 结果 ──
print(f"\n━━━ 三层自治结果 ━━━")
print(f"探索轮次: {epoch+1}")
print(f"总竞标: {contest.total_contests}  随机探索: {contest.random_wins}")
print(f"垄断统计: {contest.streak}")
print(f"\nLearner 最终状态:")
for l in sorted(learners, key=lambda x: x.track_record(), reverse=True):
    print(f"  {l.beliefs_summary()}")

print(f"\n{'✅' if contest.total_contests > 0 and rounds > 0 else '❌'} "
      f"三层 (C→A→B) 自治探索已运行")
