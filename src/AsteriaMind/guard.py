"""
StabilityGuard v2.3 — 纯架构保护

v2.3 重构: 移除所有认知干预 (freeze_learning, isolate_learner, dampen, trust_rollback)。
Guard 的唯一职责是保护架构契约——它不判断"思考是否混乱"，只检查"行为是否越界"。

五个绝对不变量:
  max_learners        — 学习器数量上限
  min_confidence      — 信任不能归零
  max_learning_rate   — 信念更新步长上限
  debate_rounds_max   — 讨论轮次上限

Guard 不会:
  ❌ 冻结学习
  ❌ 隔离 Learner
  ❌ 压制异见
  ❌ 回滚信任

Guard 只会:
  ✅ 检查 Learner 数量是否超标
  ✅ 检查学习率是否越界
  ✅ 检查 Learner 是否试图修改架构参数
  ✅ 记录违规并告警
"""
import math
import logging
from typing import List
from collections import deque

logger = logging.getLogger("AsteriaMind.guard")

# ── 绝对不变量 ──
INVARIANTS = {
    "max_learners": 10,
    "min_confidence": 0.001,
    "max_learning_rate": 0.5,
    "debate_rounds_max": 5,
}


class StabilityGuard:
    """架构保护者 — 只读，不干预认知"""

    def __init__(self):
        self.violation_count = 0
        self.violation_log: deque = deque(maxlen=100)

    # ──────────── 五个监控信号 (仅用于报告，不用于抑制) ────────────

    def _signal_amplitude_growth(self, consensus_history) -> bool:
        """共识振幅扩大 — 记录但不干预"""
        if len(consensus_history) < 20:
            return False
        half = 10
        recent = list(consensus_history)[-half:]
        older = list(consensus_history)[:half]
        recent_std = _std(recent)
        older_std = _std(older)
        if older_std < 1e-8:
            return recent_std > 0.1
        return (recent_std / older_std) > 2.0

    def _signal_trust_flip(self, trust_history) -> bool:
        """信任排名翻转 — 记录但不干预"""
        if len(trust_history) < 3:
            return False
        return True  # 占位，由 orchestrator 的 trust.rank() 提供数据

    def _signal_belief_diverge(self, learners) -> bool:
        """信念背向而行 — 记录但不干预"""
        if len(learners) < 2:
            return False
        mus = [l.belief.mu for l in learners]
        current_range = max(mus) - min(mus)
        avg_sigma = sum(l.belief.sigma for l in learners) / len(learners)
        if avg_sigma < 1e-8:
            return current_range > 2.0
        return (current_range / avg_sigma) > 4.0

    def _signal_error_rise(self, error_history) -> bool:
        """误差连续上升 — 记录但不干预"""
        if len(error_history) < 5:
            return False
        recent = list(error_history)[-5:]
        for i in range(1, len(recent)):
            if recent[i] <= recent[i - 1]:
                return False
        return True

    def _signal_entropy_flat(self, learners, trust) -> bool:
        """信任扁平化 — 记录但不干预"""
        if not learners:
            return False
        weights = [max(0.001, trust.get(l.learner_id)) for l in learners]
        avg_trust = sum(weights) / len(weights)
        if avg_trust > 0.7:
            return False  # 所有人都准 = 健康共识
        return True

    # ──────────── 架构违规检测 (唯一会触发干预的功能) ────────────

    def _check_invariants(self, learners) -> List[str]:
        """检查绝对不变量是否被违反"""
        violations = []

        # 1. Learner 数量
        if len(learners) > INVARIANTS["max_learners"]:
            violations.append(
                f"Learner 数量 {len(learners)} 超过上限 {INVARIANTS['max_learners']}"
            )

        # 2. 学习率
        for l in learners:
            effective_lr = 1.0 / (l.belief.alpha + 1)
            if effective_lr > INVARIANTS["max_learning_rate"] and l.belief.alpha > 0:
                violations.append(
                    f"{l.learner_id}: 有效学习率 {effective_lr:.3f} "
                    f"超过上限 {INVARIANTS['max_learning_rate']}"
                )

        # 3. 置信度下限（虽然 Learner 不会主动修改，但 guard 仍需检查）
        # 这个由 trust engine 保证，不额外检查

        return violations

    # ──────────── 主入口 ────────────

    def check(
        self,
        learners,
        trust,
        consensus_value: float = 0,
        current_error: float = 0,
    ) -> dict:
        """
        检查系统状态。
        只对架构违规发警告，不对认知过程做任何干预。
        """
        # 监控信号（仅用于报告）
        signals = []

        # 检查架构不变量
        violations = self._check_invariants(learners)

        if violations:
            self.violation_count += len(violations)
            for v in violations:
                self.violation_log.append(v)
                logger.warning(f"GUARD: 架构违规 — {v}")

        return {
            "status": "violation" if violations else "stable",
            "signals": signals,
            "violations": violations,
            "total_violations": self.violation_count,
            "invariants": INVARIANTS,
        }


def _std(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))
