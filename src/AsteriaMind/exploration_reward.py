"""
探索奖励引擎 — 延迟验证 + 三项加权合成

核心思路: 不是每个提案都立即给奖励，而是:
  1. 存入延迟验证队列
  2. 延迟 N 轮后，用那时的实际观测做回溯验证
  3. 奖励 = 事后验证(0.3) + 跨时间稳定性(0.3) + 共识偏离×事后验证(0.4)

奖励信号用于引导"独立看远一步"的行为，惩罚"抄共识作业"。
"""

import math
from dataclasses import dataclass, field


@dataclass
class PendingVerification:
    learner_id: str
    prediction: float
    obs_at_predict: float
    round_num: int

@dataclass
class ResolvedVerification:
    learner_id: str
    prediction: float
    obs_at_predict: float
    future_observation: float
    error: float       # |prediction - future_observation|
    round_num: int
    resolved_round: int


class DelayedVerificationQueue:
    """延迟验证队列。"""

    def __init__(self, delay_rounds: int = 10):
        self.delay = delay_rounds
        self.pending: list[PendingVerification] = []
        self.resolved: list[ResolvedVerification] = []

    def submit(self, learner_id: str, prediction: float,
               observation: float, round_num: int):
        """提交一个待验证的预测。"""
        self.pending.append(PendingVerification(
            learner_id=learner_id,
            prediction=prediction,
            obs_at_predict=observation,
            round_num=round_num,
        ))

    def resolve(self, current_round: int, current_obs: float):
        """解析所有到期的延迟验证。"""
        still_pending = []
        for pv in self.pending:
            if current_round >= pv.round_num + self.delay:
                rv = ResolvedVerification(
                    learner_id=pv.learner_id,
                    prediction=pv.prediction,
                    obs_at_predict=pv.obs_at_predict,
                    future_observation=current_obs,
                    error=abs(pv.prediction - current_obs),
                    round_num=pv.round_num,
                    resolved_round=current_round,
                )
                self.resolved.append(rv)
            else:
                still_pending.append(pv)
        self.pending = still_pending

    def drain_resolved(self) -> list[ResolvedVerification]:
        """取出并清空已解析的验证结果。"""
        r = self.resolved
        self.resolved = []
        return r


class ExplorationReward:
    """
    三项加权合成探索奖励。

    探索奖励 =
        0.3 × (1 - |预测 - 后续观测| / 观测范围)       # 事后验证
      + 0.3 × (1 - |预测 - 历史均值| / 历史波动)        # 跨时间稳定性
      + 0.4 × (归一化偏离共识 × 事后验证权重)           # 共识偏离+验证
    """

    def __init__(
        self,
        w_posthoc: float = 0.3,
        w_stability: float = 0.3,
        w_deviation: float = 0.4,
        history_window: int = 20,
    ):
        self.w_posthoc = w_posthoc
        self.w_stability = w_stability
        self.w_deviation = w_deviation
        self.history_window = history_window

        # 每个 learner 的预测历史
        self._prediction_history: dict[str, list[float]] = {}

    def record_prediction(self, learner_id: str, prediction: float):
        """维护各 learner 的预测历史（用于稳定性和历史均值计算）。"""
        if learner_id not in self._prediction_history:
            self._prediction_history[learner_id] = []
        self._prediction_history[learner_id].append(prediction)
        if len(self._prediction_history[learner_id]) > self.history_window * 2:
            self._prediction_history[learner_id] = \
                self._prediction_history[learner_id][-self.history_window * 2:]

    def _posthoc_score(self, rv: ResolvedVerification, obs_range: float) -> float:
        """事后验证得分: 预测有多接近后续实际观测。"""
        if obs_range <= 0:
            return 1.0
        return max(0.0, 1.0 - rv.error / obs_range)

    def _stability_score(self, learner_id: str, prediction: float) -> float:
        """跨时间稳定性: 当前预测与自身历史的一致性。"""
        hist = self._prediction_history.get(learner_id, [])
        if len(hist) < 5:
            return 1.0  # 数据不足时默认满分，不惩罚
        recent = hist[-self.history_window:]
        mean_val = sum(recent) / len(recent)
        variance = sum((v - mean_val) ** 2 for v in recent) / len(recent)
        volatility = math.sqrt(variance)
        if volatility <= 0:
            return 1.0
        deviation = abs(prediction - mean_val)
        return max(0.0, 1.0 - deviation / volatility)

    def _deviation_score(
        self,
        prediction: float,
        consensus: float,
        posthoc_ok: bool,
        obs_range: float,
    ) -> float:
        """共识偏离 × 事后验证权重。

        鼓励"偏离共识且后来被证明是对的"的预测。
        惩罚"偏离共识且后来被证明是错的"。
        如果没偏离共识，这项接近 0（中性的安全区）。
        """
        if obs_range <= 0:
            return 0.0
        norm_deviation = min(abs(prediction - consensus) / obs_range, 1.0)
        weight = 1.0 if posthoc_ok else -1.0
        return norm_deviation * weight

    def compute(
        self,
        learner_id: str,
        rv: ResolvedVerification,
        consensus_at_predict: float,
        obs_range: float,
    ) -> dict:
        """计算一个已解析验证的三项奖励。

        返回 dict:
          total (最终奖励), posthoc, stability, deviation, breakdown
        """
        # 事后验证: "预测" 比 "后续观测" 差距多大
        posthoc = self._posthoc_score(rv, obs_range)
        # 跨时间稳定性
        stability = self._stability_score(learner_id, rv.prediction)
        # 共识偏离
        posthoc_ok = rv.error < obs_range * 0.3  # 误差小于 30% 范围 = "对"
        deviation = self._deviation_score(
            rv.prediction, consensus_at_predict, posthoc_ok, obs_range
        )

        total = (
            self.w_posthoc * posthoc
            + self.w_stability * stability
            + self.w_deviation * deviation
        )

        return {
            "learner": learner_id,
            "total": total,
            "posthoc": posthoc,
            "stability": stability,
            "deviation": deviation,
            "consensus": consensus_at_predict,
            "prediction": rv.prediction,
            "future_obs": rv.future_observation,
            "error": rv.error,
        }

    def compute_all(
        self,
        resolved: list[ResolvedVerification],
        consensus_map: dict[int, float],  # round_num -> consensus
        obs_range: float,
    ) -> list[dict]:
        """批量计算所有已解析验证的三项奖励。"""
        results = []
        for rv in resolved:
            consensus = consensus_map.get(rv.round_num, rv.obs_at_predict)
            result = self.compute(rv.learner_id, rv, consensus, obs_range)
            results.append(result)
        return results

    def summary_by_learner(self, results: list[dict]) -> dict[str, dict]:
        """按 learner 汇总奖励统计。"""
        by_learner: dict[str, list[float]] = {}
        by_learner_posthoc: dict[str, list[float]] = {}
        by_learner_stability: dict[str, list[float]] = {}
        by_learner_deviation: dict[str, list[float]] = {}

        for r in results:
            lid = r["learner"]
            by_learner.setdefault(lid, []).append(r["total"])
            by_learner_posthoc.setdefault(lid, []).append(r["posthoc"])
            by_learner_stability.setdefault(lid, []).append(r["stability"])
            by_learner_deviation.setdefault(lid, []).append(r["deviation"])

        summary = {}
        for lid in by_learner:
            totals = by_learner[lid]
            summary[lid] = {
                "avg_total": sum(totals) / len(totals),
                "avg_posthoc": sum(by_learner_posthoc[lid]) / len(by_learner_posthoc[lid]),
                "avg_stability": sum(by_learner_stability[lid]) / len(by_learner_stability[lid]),
                "avg_deviation": sum(by_learner_deviation[lid]) / len(by_learner_deviation[lid]),
                "n_verified": len(totals),
            }
        return summary
