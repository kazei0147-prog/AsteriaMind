"""
MetaHypothesisGenerator — 不是给世界生成解释, 是给解释世界的方法生成反思 (v3.1)
"""
from dataclasses import dataclass, field
from typing import List
import time


@dataclass
class MetaHypothesis:
    """关于"我为什么一直想不明白"的假说"""
    id: str
    label: str
    evidence: str           # 观察到的框架级失败模式
    proposed_fix: str       # 建议怎么改
    confidence: float
    generation_round: int
    timestamp: float = field(default_factory=time.time)


class MetaHypothesisGenerator:
    """
    监控 H1-H6 的集体表现, 提出关于假说框架本身的假说。

    不是: "世界中的 X 为什么导致 Y?"
    而是: "我为什么总是用同一种方式去解释 X 和 Y?"

    当发现系统性失败模式时, 生成元假说——指向认知框架的缺陷。
    """

    def __init__(self):
        self.meta_log: list[dict] = []
        self.generated: list[MetaHypothesis] = []
        self.generation_count = 0

        # 诊断细化: 追踪失败集中在什么数据类型上
        self.failure_by_type: dict[str, int] = {
            "numeric": 0,    # 数值关系 (如 x^2 → 2x)
            "relational": 0, # 关系模式 (如 类比/共因)
            "temporal": 0,   # 时序模式
            "unknown": 0,    # 未分类
        }
        self.refined_diagnosis: str = ""

    def observe(self, goals: list[dict], hypotheses: list[dict],
                kg, exploration_round: int) -> dict:
        if not hypotheses or len(hypotheses) < 2:
            return {"alert": "insufficient_data"}

        patterns = self._analyze_patterns(goals, hypotheses, kg)

        # 自动检测: H3/H5 主导 = 预测必然失败
        if patterns.get("top_mechanism") in ("统计偶然", "未建模模式"):
            patterns["prediction_failures"] = patterns.get("prediction_failures", 0) + 1
            # 反思: 失败发生在什么数据上?
            data_type = self._infer_data_type(goals, hypotheses, kg)
            self.reflect_on_failure({"data_type": data_type})

        self.meta_log.append(patterns)

        if self._should_generate(patterns):
            mh = self._generate(patterns, exploration_round)
            self.generated.append(mh)
            return {"alert": "meta_hypothesis_generated", "hypothesis": mh}

        return {"alert": "none", "patterns": patterns}

    def reflect_on_failure(self, failed_prediction: dict):
        """
        预测失败后, MH 反思失败集中在什么数据类型上。
        随着失败积累, 诊断自然细化到具体方向——不是预设目标。
        """
        data_type = failed_prediction.get("data_type", "unknown")
        self.failure_by_type[data_type] = self.failure_by_type.get(data_type, 0) + 1

        # 细化诊断
        threshold = 3
        if self.failure_by_type["numeric"] >= threshold:
            self.refined_diagnosis = (
                "预测失败集中在数值关系上——"
                "现有假说(H1-H6)缺乏从多条例示中提取数值规律的能力。"
                "需要一种能识别'系数线性增长/指数递减'等数值模式的操作性模板。"
            )
        elif self.failure_by_type["temporal"] >= threshold:
            self.refined_diagnosis = (
                "预测失败集中在时序模式上——需要时间序列建模能力。"
            )
        elif self.failure_by_type["relational"] >= threshold:
            self.refined_diagnosis = (
                "预测失败集中在关系模式上——需要更丰富的图推理模板。"
            )

    def _analyze_patterns(self, goals, hypotheses, kg) -> dict:
        """分析本次探索中 H1-H6 的集体表现"""
        occam_scores = [h.get("occam_score", h.get("confidence", 0)) for h in hypotheses]
        mechanisms = [h.get("mechanism", "") for h in hypotheses]
        top_mechanism = mechanisms[0] if mechanisms else "none"

        patterns = {
            "n_hypotheses": len(hypotheses),
            "top_mechanism": top_mechanism,
            "max_occam": max(occam_scores) if occam_scores else 0,
            "all_low_confidence": all(s < 0.15 for s in occam_scores),
            "dominated_by_coincidence": top_mechanism == "统计偶然" and len(hypotheses) > 0,
            "no_causal": "共因" not in str(mechanisms) and "因果" not in str(mechanisms),
            "no_temporal": all("时间" not in h.get("label", "") for h in hypotheses),
            "no_scale": all("尺度" not in h.get("label", "") for h in hypotheses),
            "single_direction": all("单向" not in h.get("label", "") for h in hypotheses),
        }

        # 跨实体同质化检测: 所有假说都指向同一个解释类型
        unique_mechanisms = set(mechanisms)
        patterns["homogeneous"] = len(unique_mechanisms) <= 1 and len(hypotheses) >= 2

        return patterns

    def _should_generate(self, patterns: dict) -> bool:
        """
        TRIGGER_CognitiveGap_FunctionalFailure:
          H3(巧合)或H5(未建模)连续主导,
          且都无法产生可验证预测 → 系统性功能缺失。
        """
        if len(self.meta_log) < 3:
            return False

        recent = self.meta_log[-5:]

        # 无用的解释者: H3 或 H5 主导
        useless_winner = sum(1 for p in recent
                             if p.get("top_mechanism") in ("统计偶然", "未建模模式"))
        prediction_fails = sum(1 for p in recent
                               if p.get("prediction_failures", 0) > 0)
        no_other_active = all(
            p.get("max_occam", 0) < 0.5 for p in recent
        )

        return useless_winner >= 3 and prediction_fails >= 2 and no_other_active

    def _infer_data_type(self, goals, hypotheses, kg) -> str:
        """从目标实体和假说中推断数据类型"""
        import re
        # 检查 KG 中的关系是否有大量数字
        numeric_count = 0
        for r in kg.relations:
            if re.findall(r'\d+', r.subject + r.object):
                numeric_count += 1
        if numeric_count >= len(kg.relations) * 0.6:
            return "numeric"
        # 检查目标实体
        for g in goals:
            if re.findall(r'\^?\d+', g.get("target", "")):
                return "numeric"
        return "relational"

    def _generate(self, patterns: dict, round_num: int) -> MetaHypothesis:
        """使用细化诊断 (如果有的话) 生成更精确的元假说"""
        self.generation_count += 1

        if self.refined_diagnosis:
            label = self.refined_diagnosis
            evidence = (f"诊断细化: 累计 {sum(self.failure_by_type.values())} 次预测失败, "
                        f"其中数值关系 {self.failure_by_type['numeric']} 次")
            fix = "需要一种能将数值规律转化为可验证预测的操作性模板 (如: 从x^1→1, x^2→2x 中提取幂律)"
        else:
            label = "现有框架存在功能性缺口——'未建模模式'是最优假说, 但无法产生可验证预测"
            evidence = "H3(巧合)或H5(未建模)连续主导, 但基于它们的预测持续失败——拥有解释, 缺乏操作性工具"
            fix = "需要一种能将'结构相似性/数值规律'转化为可验证预测的操作性模板"
        conf = 0.7

        return MetaHypothesis(
            id=f"MH_{self.generation_count}",
            label=label,
            evidence=evidence,
            proposed_fix=fix,
            confidence=conf,
            generation_round=round_num,
        )

    def apply_to_framework(self, kg, meta_h: MetaHypothesis) -> bool:
        """
        将元假说转化为框架的实际扩展。

        这是"改变认知框架"的真正执行:
          不是记录一条日志说"我需要时序建模"
          而是在假说生成管道中真的添加一个新的假说模板。
        """
        if meta_h.confidence < 0.4:
            return False  # 不够确信, 不执行

        # 根据元假说内容, 注册对应的扩展模板
        if "时间" in meta_h.label or "时序" in meta_h.label:
            kg.register_hypothesis_template({
                "id": f"H7_TEMPORAL",
                "label": "时序因果",
                "mechanism": "时间条件",
                "condition_fn": _temporal_condition,
                "generate_fn": _temporal_generate,
                "complexity": {"free_params": 2, "assumptions": 2, "base_cost": 0.08},
            })
            return True

        if "反馈" in meta_h.label or "动态" in meta_h.label:
            kg.register_hypothesis_template({
                "id": f"H8_FEEDBACK",
                "label": "反馈环",
                "mechanism": "双向因果",
                "condition_fn": _feedback_condition,
                "generate_fn": _feedback_generate,
                "complexity": {"free_params": 3, "assumptions": 3, "base_cost": 0.12},
            })
            return True

        if "尺度" in meta_h.label or "非线性" in meta_h.label:
            kg.register_hypothesis_template({
                "id": f"H9_NONLINEAR",
                "label": "非线性/尺度效应",
                "mechanism": "阈值/规模依赖",
                "condition_fn": _nonlinear_condition,
                "generate_fn": _nonlinear_generate,
                "complexity": {"free_params": 2, "assumptions": 2, "base_cost": 0.10},
            })
            return True

        return False


# ── 扩展假说模板的实现 (条件函数 + 生成函数) ──

def _temporal_condition(kg, entity, sigs) -> bool:
    """时序假说的触发条件: 图谱中有任何关系时触发"""
    return len(kg.relations) >= 2

def _temporal_generate(kg, entity, sigs):
    return {
        "label": f"时序效应: {entity} 的影响可能随时间变化——短期和长期效应不同",
        "detail": "当前所有假说都假设静态关系, 但可能存在时间维度上的条件依赖",
        "confidence": 0.15,
        "prediction": "在不同时间窗口观测, 关系的强度或方向会改变",
        "test": "时间分片对比",
        "discrimination": "区别于静态假说: 预测关系在时间轴上不是均匀的",
    }

def _feedback_condition(kg, entity, sigs) -> bool:
    return len(kg.relations) >= 2

def _feedback_generate(kg, entity, sigs):
    return {
        "label": f"反馈环: {entity} 影响某物, 某物反过来也影响 {entity}",
        "detail": "单向因果可能不完整, 存在未建模的反馈链路",
        "confidence": 0.12,
        "prediction": f"改变 {entity} 会影响下游节点, 下游节点的变化会反馈影响 {entity}",
        "test": "格兰杰因果检验",
        "discrimination": "区别于单向假说: 预测存在双向因果而非单箭头",
    }

def _nonlinear_condition(kg, entity, sigs) -> bool:
    return len(kg.relations) >= 2

def _nonlinear_generate(kg, entity, sigs):
    return {
        "label": f"非线性效应: {entity} 的影响可能有阈值——超过某点后效果突变",
        "detail": "线性假说可能掩盖了非线性/尺度依赖的真实模式",
        "confidence": 0.13,
        "prediction": f"{entity} 的影响在低强度和高强度下显著不同",
        "test": "分段回归/阈值检测",
        "discrimination": "区别于线性假说: 预测关系不是均匀线性的",
    }
