"""
BudgetContest — v2.9 群体治理机制

不是中央调度者决定探索什么。
而是每个 Learner 提交 exploration proposal，
BudgetContest 按"预期价值 / 成本"竞标，胜者获得搜索资源。

母驱动，子探索: MotherMind 提供框架，Learner 生成探索方向。
"""
from typing import List, Dict
from dataclasses import dataclass, field
import math


@dataclass
class ExplorationProposal:
    """一个 Learner 提交的探索提案"""
    learner_id: str
    query: str                   # 想搜索什么
    hypothesis: str              # 为什么认为这值得探索
    expected_value: float        # 预估收益 (0-1)
    cost: float                  # 预估资源消耗
    uncertainty_source: str      # 触发探索的根源: "sigma_high" | "surprise" | "structure_gap"
    track_record: float          # 该 Learner 的历史准确率

    def score(self) -> float:
        """竞标分数 = 收益 × 准确率 / 成本"""
        if self.cost < 0.01:
            self.cost = 0.01
        return self.expected_value * max(self.track_record, 0.01) / self.cost


class BudgetContest:
    """
    群体治理: 所有 Learner 提交提案 → 竞标 → 分配资源。

    规则:
    - 每轮最多 N 个胜者
    - 同一 Learner 不能连续 3 轮胜出（防止垄断）
    - 10% 概率随机选择（探索陌生领域，防止信息茧房）
    """

    def __init__(
        self,
        max_winners: int = 1,
        monopoly_limit: int = 3,
        random_explore_chance: float = 0.10,
    ):
        self.max_winners = max_winners
        self.monopoly_limit = monopoly_limit
        self.random_explore_chance = random_explore_chance
        self.streak: Dict[str, int] = {}          # 连胜计数
        self.total_contests = 0
        self.random_wins = 0

    def evaluate(self, proposals: List[ExplorationProposal]) -> List[ExplorationProposal]:
        """
        评估提案，返回获胜者列表。

        流程:
        1. 检查垄断限制（连胜 >3 的 Learner 被降权）
        2. 按 score 排序
        3. 10% 概率随机选一个
        4. 返回胜者
        """
        if not proposals:
            return []

        self.total_contests += 1

        # 随机探索 (10%) — 完全随机选一个，打破信息茧房
        import random
        if random.random() < self.random_explore_chance and len(proposals) > 1:
            winner = random.choice(proposals)
            self.random_wins += 1
            return [winner]

        # 正常竞标
        # 垄断惩罚: 渐进式 — 3连胜×0.5, 4连胜×0.25, 5+×0.1
        scored = []
        for p in proposals:
            s = p.score()
            streak_count = self.streak.get(p.learner_id, 0)
            if streak_count >= 3:
                penalty = max(0.1, 1.0 / (streak_count - 1))
                s *= penalty
            scored.append((s, p))

        scored.sort(key=lambda x: x[0], reverse=True)

        winners = []
        for i in range(min(self.max_winners, len(scored))):
            _, p = scored[i]
            winners.append(p)

        # 更新连胜计数
        for lid in self.streak:
            if lid not in [w.learner_id for w in winners]:
                self.streak[lid] = 0  # 没赢就清零
        for w in winners:
            self.streak[w.learner_id] = self.streak.get(w.learner_id, 0) + 1

        return winners

    def summary(self) -> dict:
        return {
            "total_contests": self.total_contests,
            "random_wins": self.random_wins,
            "streaks": dict(self.streak),
        }
