"""
MetaCognition — 轻量仲裁层 (AsteriaMind v3.3)

MotherFallback 的进化版。

不是总调度者——只做一件事: 当多个模块信号冲突时, 裁决。

v3.3: 权重学习 — 从 ReflectionEngine 的反馈中调整各模块投票权重。
      准确率高的模块获得更高权重, 准确率低的降权。
"""
from collections import defaultdict


class MetaCognition:
    """
    仲裁层——不是独裁者, 是加权投票。

    不控制模块怎么运行, 只对它们的结果做最终加权。
    """

    def __init__(self):
        self.conflict_log: list[dict] = []
        # ── v3.3: 权重学习 (EMA) ──
        self.module_accuracy: dict[str, float] = {}   # module → EMA 准确率
        self.module_evidence: dict[str, int] = {}     # module → 总评估次数
        self.default_weight = 1.0
        self.ema_alpha = 0.3  # EMA 衰减因子

    def learn_from_reflection(self, module_name: str, was_correct: bool):
        """
        从反馈中学习模块准确率。

        was_correct: True = 模块的预测被用户确认
                     False = 模块的预测被用户纠正
        """
        target = 1.0 if was_correct else 0.0
        if module_name in self.module_accuracy:
            # EMA: new = α * target + (1-α) * old
            old = self.module_accuracy[module_name]
            self.module_accuracy[module_name] = (
                self.ema_alpha * target + (1 - self.ema_alpha) * old
            )
        else:
            self.module_accuracy[module_name] = target
        self.module_evidence[module_name] = (
            self.module_evidence.get(module_name, 0) + 1
        )

    def get_module_weight(self, module_name: str) -> float:
        """
        返回模块的当前投票权重。

        准确率高的模块 → 权重 > 1.0
        准确率低的模块 → 权重 < 1.0
        未评估的模块 → 默认权重 1.0
        """
        if module_name not in self.module_accuracy:
            return self.default_weight
        acc = self.module_accuracy[module_name]
        evidence = self.module_evidence.get(module_name, 0)
        # 证据不足时不激进调整
        if evidence < 3:
            return 0.8 + 0.4 * acc  # 范围 [0.8, 1.2]
        # 充分证据时: 权重 ∝ 准确率
        return 0.5 + 1.0 * acc       # 范围 [0.5, 1.5]

    def get_all_weights(self) -> dict:
        """获取所有模块的当前权重"""
        return {
            name: {
                "accuracy": acc,
                "weight": self.get_module_weight(name),
                "evidence": self.module_evidence.get(name, 0),
            }
            for name, acc in self.module_accuracy.items()
        }

    def arbitrate(self, signals: dict) -> dict:
        """
        多模块信号 → 统一裁决 (v3.3: 使用学习权重)。

        signals = {
            "semantic": {"action": "IS_A", "confidence": 0.75},
            "pragmatic": {"action": "info_request", "confidence": 0.70},
            "belief": {"action": "confirmed", "confidence": 0.62},
        }

        返回: { "action", "confidence", "reason", "conflict", "weights_used" }
        """
        # 收集所有模块的投票 (用学习权重)
        votes: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for source, sig in signals.items():
            if sig and sig.get("action"):
                weight = self.get_module_weight(source)
                raw_conf = sig.get("confidence", 0.5)
                weighted_conf = raw_conf * weight
                votes[sig["action"]].append((source, weighted_conf, weight))

        if not votes:
            return {"action": "unknown", "confidence": 0.0,
                    "reason": "无信号", "conflict": False, "weights_used": {}}

        # 加权投票: 每个 action 的总权重 = Σ (confidence × module_weight)
        scored = {}
        for action, sources in votes.items():
            scored[action] = sum(c for _, c, _ in sources)

        # 找出最高分
        best_action = max(scored, key=scored.get)
        best_score = scored[best_action]

        # 检测冲突
        sorted_scores = sorted(scored.items(), key=lambda x: -x[1])
        has_conflict = False
        conflict_detail = ""
        if len(sorted_scores) > 1:
            runner_up = sorted_scores[1]
            if runner_up[1] > best_score * 0.6:
                has_conflict = True
                conflict_detail = (
                    f"{best_action}({best_score:.0%}) "
                    f"vs {runner_up[0]}({runner_up[1]:.0%})"
                )

        # 置信度归一化
        total_weight = sum(scored.values()) or 1
        confidence = best_score / total_weight

        # 记录使用的权重
        weights_used = {
            source: round(self.get_module_weight(source), 2)
            for source in signals
        }

        result = {
            "action": best_action,
            "confidence": min(confidence, 0.95),
            "reason": f"加权投票: {best_action} ({', '.join(src for src, _, _ in votes[best_action])})",
            "conflict": has_conflict,
            "conflict_detail": conflict_detail,
            "all_votes": {a: f"{scored[a]:.2f}" for a in scored},
            "weights_used": weights_used,
        }

        if has_conflict:
            self.conflict_log.append(result)

        return result

    def get_recent_conflicts(self, limit: int = 5) -> list[dict]:
        return self.conflict_log[-limit:]
