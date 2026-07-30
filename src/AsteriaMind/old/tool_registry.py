"""
工具注册中心 — AsteriaMind 的自我认知

每个工具在这里注册自己的:
  - 能力 (capability): 我能做什么
  - 触发 (trigger): 什么情况下考虑我
  - 代价 (cost): 用我需要多少资源
  - 前置 (requires): 调用我之前需要什么信息

MotherMind 通过 Registry 了解自己能支配什么资源,
不需要知道每个工具的内部实现。
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, List


@dataclass
class Tool:
    name: str
    capability: str                              # 一句话: "诊断 R² 崩塌原因"
    trigger: str                                 # 触发词: "structure_gap", "low_confidence"
    cost: float = 1.0
    requires: List[str] = field(default_factory=list)  # 前置条件
    _execute: Optional[Callable] = None

    def execute(self, **kwargs):
        if self._execute:
            return self._execute(**kwargs)
        return None


class ToolRegistry:
    """MotherMind 的工具箱"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def find_by_trigger(self, trigger: str) -> list[Tool]:
        return [t for t in self._tools.values()
                if trigger in t.trigger or t.trigger in trigger]

    def find_by_capability(self, keyword: str) -> list[Tool]:
        return [t for t in self._tools.values()
                if keyword.lower() in t.capability.lower()]

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def summary(self) -> list[dict]:
        return [{
            "name": t.name, "capability": t.capability,
            "trigger": t.trigger, "cost": t.cost,
        } for t in self._tools.values()]


# ═══════════════════ 动作计划 ═══════════════════

@dataclass
class ActionPlan:
    diagnosis: str = ""          # 当前诊断
    steps: List[dict] = field(default_factory=list)  # [{tool, reason, params}]


def orchestrate(
    state: dict,           # {r2, diagnosis, confidence, learner_count, isolated_count}
    registry: ToolRegistry,
) -> ActionPlan:
    """
    MotherMind 的指挥逻辑: 根据系统状态, 编排工具调用顺序。
    这是你问的"她怎么知道该用哪个"的核心——不是硬编码, 是状态驱动的编排。
    """
    plan = ActionPlan()
    r2 = state.get("r2", 0.5)
    diagnosis = state.get("diagnosis", {})
    top_cause = diagnosis.get("label", "") if diagnosis else ""

    # ── 阶段 1: 认知崩塌 → 先诊断, 别乱动 ──
    if r2 < 0.3 and r2 >= 0.0:
        plan.diagnosis = "structure_collapse"
        plan.steps.append({
            "tool": "DiagnosticEngine",
            "reason": f"R²崩塌到{r2:.2f}, 先确定原因再行动",
            "params": {"mode": "full_diagnosis"},
        })
        plan.steps.append({
            "tool": "ExperimentDesigner",
            "reason": "根据诊断结果设计验证实验",
            "params": {"cause": top_cause},
        })
        plan.steps.append({
            "tool": "CuriosityEngine",
            "reason": "授权主动采样验证",
            "params": {"mode": "active_sampling"},
        })
        return plan

    # ── 阶段 2: 函数形式怀疑 → 实验 + 基函数切换 ──
    if "函数形式" in top_cause:
        plan.diagnosis = "function_change"
        plan.steps.append({
            "tool": "ExperimentDesigner",
            "reason": "函数形式可能变了, 设计扩域实验",
            "params": {"cause": top_cause, "n_samples": 25},
        })
        plan.steps.append({
            "tool": "MetaLearner",
            "reason": "切换基函数测试新假设",
            "params": {"action": "check_bases"},
        })
        return plan

    # ── 阶段 3: 噪声怀疑 → 密集局部采样 ──
    if "噪声" in top_cause:
        plan.diagnosis = "noise_increase"
        plan.steps.append({
            "tool": "ExperimentDesigner",
            "reason": "噪声变大, 密集采样估计真实噪声水平",
            "params": {"cause": top_cause, "n_samples": 30, "dense": True},
        })
        plan.steps.append({
            "tool": "MetaLearner",
            "reason": "增加鲁棒性: 切 Student-t 或提高正则化",
            "params": {"action": "increase_robustness"},
        })
        return plan

    # ── 阶段 4: 一切正常 → 定期体检 + 隔离检查 ──
    if r2 > 0.7:
        plan.diagnosis = "healthy"
        plan.steps.append({
            "tool": "CrossValidator",
            "reason": "定期检查 Learner 是否有搭便车",
            "params": {"mode": "periodic_check"},
        })
        if state.get("isolated_count", 0) > 0:
            plan.steps.append({
                "tool": "IsolationManager",
                "reason": f"有{state['isolated_count']}个被隔离的Learner, 检查是否应释放",
                "params": {"action": "reassess"},
            })
        plan.steps.append({
            "tool": "CuriosityEngine",
            "reason": "定期实验, 验证当前假设是否最优",
            "params": {"mode": "periodic_experiment"},
        })
        return plan

    # ── 默认: 继续观察 ──
    plan.diagnosis = "uncertain"
    plan.steps.append({
        "tool": "DiagnosticEngine",
        "reason": "状态不确定, 先做完整诊断",
        "params": {"mode": "full_diagnosis"},
    })
    return plan
