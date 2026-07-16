"""
信任引擎 - HiveMind 2.0 的信任机制

v2.0 核心创新: 信任不是"被采纳=赚能量"，而是"事后被验证准确=赚信任"。
信任是滞后奖励——只有当一个学习器的提案被事后数据验证为准确时，它才获得信任。

这不是活跃度的度量，而是可信度的度量。
"""

import logging
from typing import List, Dict
from .learner import Learner

logger = logging.getLogger("hivemind_v2.trust")


class TrustEngine:
    """
    信任引擎。
    
    核心规则:
    1. 每个学习器有一个信任值 [0, 1]
    2. 提案被事后验证准确 → 信任上升
    3. 提案被事后验证错误 → 信任下降
    4. 长期不活跃 → 信任缓慢衰减 (但不会归零)
    5. 信任高的学习器在论证评估中享有更高的 track_record 权重
    """

    def __init__(self, initial_trust: float = 0.5, decay_rate: float = 0.001):
        self.trust_scores: Dict[str, float] = {}
        self.verification_history: List[Dict] = []  # 验证记录
        self.initial_trust = initial_trust
        self.decay_rate = decay_rate

    def register(self, learner_id: str):
        """注册新学习器"""
        if learner_id not in self.trust_scores:
            self.trust_scores[learner_id] = self.initial_trust

    def verify(self, learner_id: str, proposed_value: float, true_value: float):
        """
        事后验证：用真实值评估提案质量，更新信任。
        
        这是信任系统的核心——信任基于"被证明正确"，不是"被采纳"。
        """
        if learner_id not in self.trust_scores:
            self.register(learner_id)
        
        error = abs(proposed_value - true_value)
        relative_error = error / max(abs(true_value), 0.01)
        
        # 信任变化: 误差越小，奖励越大
        if relative_error < 0.05:       # 误差 < 5% → 强奖励
            delta = +0.05
        elif relative_error < 0.10:     # 误差 < 10% → 弱奖励
            delta = +0.02
        elif relative_error < 0.20:     # 误差 < 20% → 中性
            delta = 0.0
        elif relative_error < 0.50:     # 误差 < 50% → 轻罚
            delta = -0.02
        else:                           # 严重错误 → 重罚
            delta = -0.05
        
        old_trust = self.trust_scores[learner_id]
        self.trust_scores[learner_id] = max(0.01, min(0.99, old_trust + delta))
        
        self.verification_history.append({
            "learner_id": learner_id,
            "error": error,
            "relative_error": relative_error,
            "delta": delta,
            "trust_before": old_trust,
            "trust_after": self.trust_scores[learner_id],
        })
        
        logger.debug(
            f"[{learner_id}] 验证: error={error:.2f} ({relative_error*100:.1f}%), "
            f"delta={delta:+.3f}, trust={self.trust_scores[learner_id]:.3f}"
        )

    def get(self, learner_id: str) -> float:
        """获取学习器的当前信任值"""
        return self.trust_scores.get(learner_id, self.initial_trust)

    def decay(self, active_learner_ids: List[str]):
        """对不活跃的学习器进行信任衰减"""
        for lid in self.trust_scores:
            if lid not in active_learner_ids:
                self.trust_scores[lid] = max(0.01, self.trust_scores[lid] - self.decay_rate)

    def rank(self) -> List[tuple]:
        """按信任值排序学习器"""
        return sorted(self.trust_scores.items(), key=lambda x: x[1], reverse=True)

    def summary(self) -> dict:
        return {
            "trust_scores": self.trust_scores.copy(),
            "n_verifications": len(self.verification_history),
            "most_trusted": self.rank()[0] if self.trust_scores else None,
        }
