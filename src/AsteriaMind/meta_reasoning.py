"""
MetaReasoningLayer — 学习如何学习 (AsteriaMind v3.2)

不是 Semantic (这句话什么意思)
不是 Hypothesis (为什么这个现象发生)
而是 MetaReasoning (为什么我的认知系统一直错?)

监控整个系统的预测误差趋势, 当发现系统性失败时:
  - 生成框架级反思
  - 标记需要调整的策略
  - 提请 BudgetContest 分配资源给反思
"""
import time, math
from collections import deque, defaultdict
from dataclasses import dataclass, field


@dataclass
class SystemHealth:
    """系统健康状况快照"""
    total_predictions: int = 0
    total_errors: float = 0.0
    error_trend: list[float] = field(default_factory=list)  # 最近 20 次误差
    strategy_performance: dict = field(default_factory=dict)  # 每种生成策略的准确率
    failure_patterns: list[str] = field(default_factory=list)
    last_reflection: float = 0.0


class MetaReasoningLayer:
    """
    元推理层——AM 的"自我意识"。

    不是做决策, 是观察决策的效果。
    """

    def __init__(self, window_size: int = 20, reflection_interval: float = 300):
        self.window_size = window_size
        self.reflection_interval = reflection_interval
        self.health = SystemHealth()
        self.error_history: deque = deque(maxlen=window_size)
        # 每种策略的误差追踪
        self.strategy_errors: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self.reflections: list[dict] = []

    def record_prediction(self, strategy: str, predicted: float,
                          actual: float, importance: float = 1.0):
        """
        记录一次预测结果——元推理层的原料。

        strategy: "analogy" / "transitive" / "causal" / "correlation" / "direct"
        predicted: 预测值 (0-1)
        actual: 实际值 (0/1)
        importance: 这条知识的重要程度
        """
        error = abs(actual - predicted)
        self.error_history.append(error * importance)
        self.strategy_errors[strategy].append(error)
        self.health.total_predictions += 1
        self.health.total_errors += error

    def record_outcome(self, strategy: str, was_correct: bool,
                       predicted_confidence: float = 0.5):
        """
        v3.3: 用真实反馈替代硬编码 actual=0.5。

        was_correct: True = 用户确认/追问(正反馈)
                     False = 用户纠正/转移(负反馈)
        predicted_confidence: 系统本轮给出的置信度
        """
        actual = 1.0 if was_correct else 0.0
        self.record_prediction(strategy, predicted_confidence, actual)

    def get_system_health(self) -> dict:
        """系统健康报告"""
        if not self.error_history:
            return {"status": "cold_start", "avg_error": 0.0}

        avg_error = sum(self.error_history) / len(self.error_history)
        recent_avg = sum(list(self.error_history)[-5:]) / max(len(self.error_history), 1)

        status = "stable"
        if avg_error > 0.4:
            status = "struggling"
        elif recent_avg > avg_error * 1.5:
            status = "degrading"  # 近期变差
        elif recent_avg < avg_error * 0.5:
            status = "improving"  # 近期变好

        # 策略表现
        strategy_stats = {}
        for name, errors in self.strategy_errors.items():
            if errors:
                strategy_stats[name] = {
                    "avg_error": sum(errors) / len(errors),
                    "count": len(errors),
                }

        return {
            "status": status,
            "avg_error": avg_error,
            "recent_avg": recent_avg,
            "total_predictions": self.health.total_predictions,
            "strategies": strategy_stats,
        }

    def reflect(self) -> list[dict]:
        """
        框架级反思——"我的认知机制有系统性问题吗?"

        返回反思列表, 每个包含建议行动。
        """
        now = time.time()
        if now - self.health.last_reflection < self.reflection_interval:
            return []

        health = self.get_system_health()
        reflections = []

        # 1. 全局健康检查
        if health["status"] == "struggling":
            reflections.append({
                "type": "global_degradation",
                "severity": "high",
                "observation": f"系统平均预测误差 {health['avg_error']:.0%} 过高",
                "hypothesis": "认知框架可能在多个领域同时失效",
                "suggested_action": "检查 DreamModule 的策略池是否需要调整",
            })

        # 2. 策略级诊断
        for name, stats in health.get("strategies", {}).items():
            if stats["avg_error"] > 0.5 and stats["count"] > 3:
                reflections.append({
                    "type": "strategy_failure",
                    "severity": "medium",
                    "strategy": name,
                    "observation": f"策略 '{name}' 误差 {stats['avg_error']:.0%} (n={stats['count']})",
                    "hypothesis": f"{name} 策略可能不适合当前知识域",
                    "suggested_action": f"降低 {name} 策略的置信度权重, 或替换为其他策略",
                })

        # 3. 退化趋势
        if health["status"] == "degrading":
            reflections.append({
                "type": "degrading_trend",
                "severity": "medium",
                "observation": f"近期误差 {health['recent_avg']:.0%} > 长期 {health['avg_error']:.0%}",
                "hypothesis": "系统可能在衰退——最近的知识或策略有问题",
                "suggested_action": "检查最近 20 条认知痕迹是否有系统性错误",
            })

        self.health.last_reflection = now
        self.reflections.extend(reflections)
        return reflections

    def get_actionable_reflections(self) -> list[dict]:
        """获取需要 BudgetContest 竞标的反思"""
        return [r for r in self.reflections if r.get("severity") in ("high", "medium")][-5:]
