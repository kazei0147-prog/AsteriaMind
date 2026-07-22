"""
Hypothesis Template Registry + Engine — 理论作为一等公民 (AsteriaMind v3.1)

核心理念:
  不是 H1-H6 写死在代码里。
  而是 Registry 存着当前可用的理论模板,
  HypothesisEngine 从 Registry 取模板来生成假说,
  新理论通过 CognitiveEvolutionLayer 的审稿流程才能加入。

四层结构:
  Layer 1: HypothesisEngine        — "现有理论谁能解释这个现象?"
  Layer 2: TemplateRegistry         — "当前认知体系里有哪些理论可用?"
  Layer 3: TheoryGovernance         — "哪些理论在变老? 哪些该退休了?"
  Layer 4: CognitiveEvolutionLayer  — "我需要提出一个新理论候选吗?"
"""
import time, math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict


# ═══════════════ Template 数据模型 ═══════════════

@dataclass
class HypothesisTemplate:
    """
    一个理论模板——不是在代码里写 if, 而是作为数据存在 Registry 中。

    每个模板自包含:
      - 什么时候适用 (condition)
      - 怎么生成假说 (generate)
      - 复杂度代价 (Occam)
      - 可证伪条件 (falsifiable)
      - 使用统计 (governance)
    """
    id: str                             # "H1_direct_cause"
    name: str                           # "直接因果"
    mechanism: str                      # "单向因果"
    version: int = 1
    status: str = "active"              # candidate | testing | active | deprecated | archived

    # 何时使用
    condition_description: str = ""
    condition_fn: Callable = field(default=lambda kg, e, s: True, repr=False)

    # 如何生成假说
    generate_fn: Callable = field(default=lambda kg, e, s: [], repr=False)

    # 奥卡姆代价
    complexity_cost: float = 0.0
    free_params: int = 0
    assumptions: int = 0

    # 可证伪性
    falsifiable: bool = True
    fail_condition: str = ""  # 什么情况下这个理论应该被推翻

    # 治理数据
    times_used: int = 0
    times_successful: int = 0   # 预测被确认的次数
    total_occam_rank: float = 0  # 累计奥卡姆排名 (1=最高)
    explain_gain: float = 0.0    # 历史解释增益
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    parent_template: str = ""    # 从哪个模板演化来的
    notes: str = ""

    @property
    def success_rate(self) -> float:
        return self.times_successful / max(1, self.times_used)

    @property
    def health(self) -> float:
        """
        理论健康度: 兼顾使用频率、成功率和简洁性。
        健康度低的模板会被 Governance 降级或归档。
        """
        usage = min(1.0, self.times_used / 50)       # 至少用 50 次才能满分
        success = self.success_rate
        simplicity = 1.0 / (1.0 + self.complexity_cost)
        return (usage * 0.3 + success * 0.4 + simplicity * 0.3)


# ═══════════════ Layer 1: HypothesisEngine ═══════════════

class HypothesisEngine:
    """
    假说生成引擎: 不再硬编码 H1-H6, 而是从 Registry 查询可用理论。

    流程:
      1. registry.get_active_templates() → [H1, H2, ..., H6, ...]
      2. 对每个 template, 调用 template.condition_fn(kg, entity, sigs)
      3. 如果条件满足, 调用 template.generate_fn(...) 生成假说
      4. 收集所有假说, 应用奥卡姆评分, 排序返回
    """

    def __init__(self, registry=None):
        self.registry = registry

    def generate(self, kg, target_entity: str, target_type: str,
                 sigs: dict = None) -> list[dict]:
        """
        给定一个目标实体和类型, 生成所有适用理论的假说。
        """
        if sigs is None:
            sigs = kg._build_signatures()

        templates = []
        if self.registry:
            templates = self.registry.get_active_templates()
        else:
            templates = _builtin_templates()  # 兜底

        all_hypotheses = []
        for tmpl in templates:
            try:
                if tmpl.condition_fn(kg, target_entity, sigs):
                    hypotheses = tmpl.generate_fn(kg, target_entity, sigs)
                    for h in hypotheses:
                        h["template_id"] = tmpl.id
                        h["complexity"] = {
                            "free_params": tmpl.free_params,
                            "assumptions": tmpl.assumptions,
                            "base_cost": tmpl.complexity_cost,
                        }
                    all_hypotheses.extend(hypotheses)
                    tmpl.times_used += 1
            except Exception:
                pass  # 模板失败不影响其他模板

        # 奥卡姆排序
        return self._occam_rank(all_hypotheses)

    def _occam_rank(self, hypotheses: list[dict]) -> list[dict]:
        ALPHA, BETA = 0.10, 0.08
        for h in hypotheses:
            cx = h.get("complexity", {})
            score = (h.get("confidence", 0)
                     - ALPHA * cx.get("free_params", 0)
                     - BETA * cx.get("assumptions", 0)
                     - cx.get("base_cost", 0))
            h["occam_score"] = round(max(0.0, score), 3)
        return sorted(hypotheses, key=lambda h: -h["occam_score"])


# ═══════════════ Layer 2: TemplateRegistry ═══════════════

class TemplateRegistry:
    """理论模板注册表: 认知体系的"论文库" """

    def __init__(self):
        self.templates: Dict[str, HypothesisTemplate] = {}
        self._history: list[dict] = []  # 注册/退役/升级记录

    def register(self, template: HypothesisTemplate):
        self.templates[template.id] = template
        self._history.append({
            "action": "registered", "template_id": template.id,
            "version": template.version, "time": time.time(),
        })

    def get_active_templates(self) -> list:
        return [t for t in self.templates.values() if t.status in ("active", "testing")]

    def get(self, template_id: str) -> Optional[HypothesisTemplate]:
        return self.templates.get(template_id)

    def deprecate(self, template_id: str, reason: str = ""):
        if template_id in self.templates:
            self.templates[template_id].status = "deprecated"
            self.templates[template_id].notes += f" | 退役原因: {reason}"
            self._history.append({
                "action": "deprecated", "template_id": template_id,
                "reason": reason, "time": time.time(),
            })

    def archive(self, template_id: str, reason: str = ""):
        if template_id in self.templates:
            self.templates[template_id].status = "archived"
            self.templates[template_id].notes += f" | 归档原因: {reason}"
            self._history.append({
                "action": "archived", "template_id": template_id,
                "reason": reason, "time": time.time(),
            })

    def promote_to_active(self, template_id: str):
        if template_id in self.templates:
            self.templates[template_id].status = "active"
            self._history.append({
                "action": "promoted", "template_id": template_id, "time": time.time(),
            })


# ═══════════════ Layer 3: TheoryGovernance ═══════════════

class TheoryGovernance:
    """
    理论治理: 防止 Registry 变成垃圾场。

    定期审查:
      - health < 0.2 → deprecate (降级)
      - 连续 100+ 轮未使用 → archive (归档)
      - 两个模板高度冗余 → 建议合并
      - 低版本模板被高版本替代 → 自动 deprecate
    """

    def __init__(self, registry: TemplateRegistry):
        self.registry = registry
        self.review_interval = 50   # 每 50 轮审查一次
        self.round = 0
        self.review_log: list[dict] = []

    def review(self, round_num: int):
        self.round = round_num
        actions = []

        for tid, tmpl in self.registry.templates.items():
            if tmpl.status == "archived":
                continue

            health = tmpl.health

            # 理论健康度过低
            if tmpl.times_used > 20 and health < 0.2:
                self.registry.deprecate(tid, f"健康度 {health:.2f} < 0.2")
                actions.append({"action": "deprecated", "template": tid, "health": health})

            # 长期未使用 (candidate/testing 状态尤甚)
            if tmpl.status in ("candidate", "testing"):
                inactivity = round_num - (tmpl.last_used or tmpl.created_at)
                if inactivity > 200 and tmpl.times_used < 10:
                    self.registry.archive(tid, f"候选模板 {inactivity} 轮未充分使用")
                    actions.append({"action": "archived", "template": tid, "reason": "stale candidate"})

        if actions:
            self.review_log.append({"round": round_num, "actions": actions})
        return actions


# ═══════════════ 内置模板 (H1-H6 作为注册进去的默认理论) ═══════════════

def _builtin_templates() -> list:
    """H1-H6 不在代码里写 if——作为默认模板注册进 Registry"""
    return [
        HypothesisTemplate(
            id="H1_direct_cause", name="直接因果", mechanism="单向因果",
            condition_description="当两个实体高度相关时适用",
            complexity_cost=0.00, free_params=1, assumptions=1,
            condition_fn=_h1_condition, generate_fn=_h1_generate,
            fail_condition="如果加入第三方变量后关系消失",
        ),
        HypothesisTemplate(
            id="H2_common_cause", name="共同原因", mechanism="共因混淆",
            condition_description="当两个实体共享同一上级节点时适用",
            complexity_cost=0.05, free_params=1, assumptions=2,
            condition_fn=_h2_condition, generate_fn=_h2_generate,
            fail_condition="如果排除共同父节点后仍存在显著关系",
        ),
        HypothesisTemplate(
            id="H3_coincidence", name="统计偶然", mechanism="随机巧合",
            condition_description="始终适用 (作为基准假说)",
            complexity_cost=0.00, free_params=0, assumptions=0,
            condition_fn=_always_true, generate_fn=_h3_generate,
            fail_condition="如果数据积累后关系不消失 (此时该假说被更强的假说替代)",
        ),
        HypothesisTemplate(
            id="H4_indirect_path", name="间接路径", mechanism="中介效应",
            condition_description="当存在 2-hop 路径时适用",
            complexity_cost=0.10, free_params=2, assumptions=2,
            condition_fn=_h4_condition, generate_fn=_h4_generate,
            fail_condition="如果控制中介变量后直接效应不消失",
        ),
        HypothesisTemplate(
            id="H5_residual", name="残差驱动", mechanism="未建模模式",
            condition_description="当现有假说覆盖度 < 0.6 时触发",
            complexity_cost=0.15, free_params=2, assumptions=3,
            condition_fn=_h5_condition, generate_fn=_h5_generate,
            fail_condition="如果残差在增加数据后消失 (可能是采样不足)",
        ),
        HypothesisTemplate(
            id="H6_condition_missing", name="条件缺失", mechanism="条件依赖",
            condition_description="当存在一对 NOT_X 和 X 的冲突关系时触发",
            complexity_cost=0.05, free_params=1, assumptions=2,
            condition_fn=_h6_condition, generate_fn=_h6_generate,
            fail_condition="如果控制条件变量后冲突不消失",
        ),
    ]


# ── 条件/生成函数 (从 knowledge.py 迁移) ──

def _always_true(kg, entity, sigs):
    return True

def _h1_condition(kg, entity, sigs):
    analogies = _find_analogies_standalone(entity, sigs)
    return len(analogies) > 0

def _h1_generate(kg, entity, sigs):
    hyps = []
    analogies = _find_analogies_standalone(entity, sigs)
    for a in analogies[:3]:
        hyps.append({
            "id": "H1", "label": f"类比: {entity} 可能也 {a['predicate']} {a['counterpart']}",
            "mechanism": "结构相似性",
            "detail": f"与\"{a['source_entity']}\"相似度 {a['similarity']:.2f}",
            "confidence": round(a["similarity"] * 0.4, 3),
            "prediction": f"如果 H1 正确, 应观察到: {entity} {a['predicate']} {a['counterpart']} 频繁出现",
            "test": "多次观察",
            "discrimination": f"区别于 H2: H1 预测 {entity} 主动影响 {a['counterpart']}, H2 预测都是被动结果",
        })
    return hyps

def _h2_condition(kg, entity, sigs):
    return len(_find_common_causes_standalone(entity, sigs)) > 0

def _h2_generate(kg, entity, sigs):
    hyps = []
    for cc in _find_common_causes_standalone(entity, sigs)[:3]:
        hyps.append({
            "id": "H2", "label": f"共同原因: {cc['cause']} 同时导致了 {entity} 和 {cc['associated']}",
            "mechanism": "共因混淆",
            "detail": f"共享 {cc['cause']} ({cc['shared_count']} 个共享节点)",
            "confidence": round(len(cc["shared"]) / max(1, len(sigs.get(entity, set()))) * 0.35, 3),
            "prediction": f"如果 H2 正确, 控制 {cc['cause']} 后相关性消失",
            "test": "条件独立",
            "discrimination": "区别于 H1: 认为相关性来自共因",
        })
    return hyps

def _h3_condition(kg, entity, sigs):
    return True

def _h3_generate(kg, entity, sigs):
    return [{
        "id": "H3", "label": f"巧合: {entity} 的相似性只是噪音",
        "mechanism": "统计偶然", "detail": "当前证据不足以建立因果或类比关系",
        "confidence": 0.1,
        "prediction": f"增加数据后相似度下降而非上升",
        "test": "增加样本量",
        "discrimination": "区别于 H1/H2: 预测持续增加数据不会让关系变强",
    }]

def _h4_condition(kg, entity, sigs):
    return _find_indirect_standalone(entity, sigs)

def _h4_generate(kg, entity, sigs):
    hyps = []
    for ip in _find_indirect_standalone(entity, sigs)[:3]:
        hyps.append({
            "id": "H4", "label": f"间接路径: {entity} 通过 {ip['mid']} 间接连接到 {ip['target']}",
            "mechanism": "中介效应",
            "detail": f"存在路径 {entity} → {ip['mid']} → {ip['target']}",
            "confidence": round(ip["strength"] * 0.3, 3),
            "prediction": f"控制 {ip['mid']} 后直接效应消失",
            "test": "中介分析",
            "discrimination": "区别于 H1: 预测关系是间接的",
        })
    return hyps

def _h5_condition(kg, entity, sigs):
    return _analyze_residual_standalone(entity, sigs)

def _h5_generate(kg, entity, sigs):
    pattern = _analyze_residual_standalone(entity, sigs)
    return [{
        "id": "H5", "label": f"未知机制: {pattern['description']}",
        "mechanism": "未建模模式",
        "detail": f"现有框架无法充分解释",
        "confidence": 0.3,
        "prediction": f"需要一个现有框架无法描述的新机制",
        "test": "探索性分析",
        "discrimination": "区别于 H1-H4: 需要新机制",
    }]

def _h6_condition(kg, entity, sigs):
    for r in kg.relations:
        if r.predicate.startswith("NOT_") and r.confidence > 0.05:
            base = r.predicate[4:]
            for r2 in kg.relations:
                if (r2.subject == r.subject and r2.predicate == base
                        and r2.object == r.object and r2.confidence > 0.1):
                    return True
    return False

def _h6_generate(kg, entity, sigs):
    hyps = []
    for r in kg.relations:
        if r.predicate.startswith("NOT_") and r.confidence > 0.05:
            base = r.predicate[4:]
            for r2 in kg.relations:
                if (r2.subject == r.subject and r2.predicate == base
                        and r2.object == r.object and r2.confidence > 0.1):
                    hyps.append({
                        "id": "H6", "label": f"隐藏条件: {r.subject} 可能在某些条件下 {base} {r.object}, 其他条件下则不",
                        "mechanism": "条件依赖",
                        "detail": f"两方都有证据",
                        "confidence": min(0.4, (r.confidence + r2.confidence) / 2),
                        "prediction": "控制未观测变量后矛盾消失",
                        "test": "条件对照实验",
                        "discrimination": "区别于 H1/H2: 认为冲突是表面的",
                    })
    return hyps


# ── 独立工具函数 (从 knowledge.py 的 _find_* 系列迁移) ──

def _find_analogies_standalone(entity, sigs, n=3):
    results = []
    target_sig = sigs.get(entity, set())
    if not target_sig:
        return results
    existing_preds = set(p for p, _ in target_sig)
    for other, other_sig in sigs.items():
        if other == entity:
            continue
        shared = target_sig & other_sig
        total = target_sig | other_sig
        if not total:
            continue
        sim = len(shared) / len(total)
        novel = set(p for p, _ in other_sig) - existing_preds
        for pred in novel:
            cps = [cp for p, cp in other_sig if p == pred]
            for cp in cps[:1]:
                results.append({"source_entity": other, "predicate": pred,
                                "counterpart": cp, "similarity": sim})
    return sorted(results, key=lambda r: -r["similarity"])[:n]

def _find_common_causes_standalone(entity, sigs):
    incoming = set(cp for p, cp in sigs.get(entity, set()) if p.startswith("←"))
    results = []
    for other, other_sig in sigs.items():
        if other == entity:
            continue
        shared = incoming & set(cp for p, cp in other_sig if p.startswith("←"))
        if shared:
            results.append({"cause": list(shared)[0], "associated": other,
                            "shared": list(shared), "shared_count": len(shared)})
    return sorted(results, key=lambda r: -r["shared_count"])

def _find_indirect_standalone(entity, sigs):
    results = []
    outgoing = [(p, cp) for p, cp in sigs.get(entity, set()) if not p.startswith("←")]
    for pred, mid in outgoing:
        mid_out = [(p, cp) for p, cp in sigs.get(mid, set()) if not p.startswith("←")]
        for mp, target in mid_out:
            if target != entity:
                results.append({"mid": mid, "target": target, "strength": 0.5})
    return results

def _analyze_residual_standalone(entity, sigs):
    target_sig = sigs.get(entity, set())
    incoming = sum(1 for p, _ in target_sig if p.startswith("←"))
    outgoing = len(target_sig) - incoming
    if incoming == 0 and outgoing == 0:
        return {"description": f"{entity} 与图谱完全孤立", "param_count": 2, "assumption_count": 3}
    elif incoming > outgoing * 2:
        return {"description": f"{entity} 主要是被动方, 可能受隐变量驱动", "param_count": 2, "assumption_count": 3}
    elif outgoing > incoming * 2:
        return {"description": f"{entity} 可能是未观测的因果源", "param_count": 2, "assumption_count": 3}
    return {"description": f"{entity} 残差无显著结构特征", "param_count": 2, "assumption_count": 3}
