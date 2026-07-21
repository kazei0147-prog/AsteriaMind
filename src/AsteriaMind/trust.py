"""
信任引擎 - AsteriaMind 的信任机制

v2.0 核心创新: 信任不是"被采纳=赚能量"，而是"事后被验证准确=赚信任"。
信任是滞后奖励——只有当一个学习器的提案被事后数据验证为准确时，它才获得信任。

v2.10 自适应阈值 (思路 A + B):
  思路 A: 每个 learner 维护自己的误差基线(EMA)，中性区缩放为 baseline 的倍数。
          当 learner 平时误差小(如 0.5%)时，中性区也缩(如 1-4%)，使小偏移也能触发更新。
  思路 B: 噪声地板——取自 learner 自身历史最小误差，防止阈值在极端精确时变得荒谬。
"""

import logging
from typing import List, Dict

logger = logging.getLogger("AsteriaMind.trust")


class TrustEngine:
    """信任引擎——支持固定阈值（兼容）和自适应阈值。"""

    def __init__(
        self,
        initial_trust: float = 0.5,
        decay_rate: float = 0.001,
        adaptive_thresholds: bool = True,
        baseline_alpha: float = 0.1,
    ):
        self.trust_scores: Dict[str, float] = {}
        self.verification_history: List[Dict] = []
        self.initial_trust = initial_trust
        self.decay_rate = decay_rate

        # ── 自适应阈值 ──
        self.adaptive_thresholds = adaptive_thresholds
        self.baseline_alpha = baseline_alpha
        self._baselines: Dict[str, float] = {}      # EMA of relative_error per learner
        self._baseline_min: Dict[str, float] = {}   # noise floor (lowest observed)

    # ──────────────────── 注册 ────────────────────

    def register(self, learner_id: str):
        if learner_id not in self.trust_scores:
            self.trust_scores[learner_id] = self.initial_trust

    # ──────────────────── 自适应阈值计算 ────────────────────

    def _compute_thresholds(self, learner_id: str, rel_err: float) -> tuple:
        """返回 (b1, b2, b3, b4) — 四个边界。

        b1: 低于此 → +0.08 (error 在 learner 正常水平以内)
        b2: 低于此 → +0.04 (略高于正常但还不错)
        b3: 低于此 →   0.0 (偏离但尚可容忍 — 中性区)
        b4: 低于此 → -0.08 (异常)
        超 b4  → -0.15 (严重异常)

        阈值基于 learner 自身的误差历史（思路 A）+ 噪声地板（思路 B）。
        """
        # 基线 = 噪声地板（历史最低误差，只降不升）。
        # 用最低值而非 EMA，防止持续故障时基线被污染抬高 → 阈值跟着涨 → 故障"消失"。
        baseline = max(self._baseline_min.get(learner_id, 0.05), 0.005)

        # 各边界 = baseline 的固定倍数
        b1 = baseline * 1.0
        b2 = baseline * 2.0
        b3 = baseline * 4.0
        b4 = baseline * 10.0

        # 保序: 如果重叠则展开
        b2 = max(b2, b1 + 0.001)
        b3 = max(b3, b2 + 0.001)
        b4 = max(b4, b3 + 0.001)

        return b1, b2, b3, b4

    def _update_baseline(self, learner_id: str, rel_err: float):
        """用本次误差更新该 learner 的基线（EMA）和噪声地板。"""
        if learner_id not in self._baselines:
            self._baselines[learner_id] = rel_err
            self._baseline_min[learner_id] = rel_err
        else:
            # 思路 A: EMA 平滑
            self._baselines[learner_id] += self.baseline_alpha * (
                rel_err - self._baselines[learner_id]
            )
            # 思路 B: 追最低（噪声地板）
            if rel_err < self._baseline_min[learner_id]:
                self._baseline_min[learner_id] += 0.05 * (
                    rel_err - self._baseline_min[learner_id]
                )

    # ──────────────────── 核心 ────────────────────

    def verify(self, learner_id: str, proposed_value: float, true_value: float):
        """事后验证：用真实值评估提案质量，更新信任。"""
        if learner_id not in self.trust_scores:
            self.register(learner_id)

        error = abs(proposed_value - true_value)
        relative_error = error / max(abs(true_value), 0.01)

        if self.adaptive_thresholds:
            b1, b2, b3, b4 = self._compute_thresholds(learner_id, relative_error)

            if relative_error < b1:
                delta = +0.08
            elif relative_error < b2:
                delta = +0.04
            elif relative_error < b3:
                delta = 0.0
            elif relative_error < b4:
                delta = -0.08
            else:
                delta = -0.15

            # 更新基线（用本次误差——阈值已用旧基线算出）
            self._update_baseline(learner_id, relative_error)
        else:
            # 固定阈值（保持向后兼容）
            if relative_error < 0.05:
                delta = +0.08
            elif relative_error < 0.10:
                delta = +0.04
            elif relative_error < 0.20:
                delta = 0.0
            elif relative_error < 0.50:
                delta = -0.08
            else:
                delta = -0.15

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

    # ──────────────────── 查询 ────────────────────

    def get(self, learner_id: str) -> float:
        return self.trust_scores.get(learner_id, self.initial_trust)

    def decay(self, active_learner_ids: List[str]):
        for lid in self.trust_scores:
            if lid not in active_learner_ids:
                self.trust_scores[lid] = max(0.01, self.trust_scores[lid] - self.decay_rate)

    def rank(self) -> List[tuple]:
        return sorted(self.trust_scores.items(), key=lambda x: x[1], reverse=True)

    def summary(self) -> dict:
        return {
            "trust_scores": self.trust_scores.copy(),
            "n_verifications": len(self.verification_history),
            "most_trusted": self.rank()[0] if self.trust_scores else None,
        }
