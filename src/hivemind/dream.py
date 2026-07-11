"""
梦境机制 - HiveMind 离线蒸馏 + 反事实杂交 + 知识蒸馏引擎

v0.4 升级：集成 DistillationEngine，梦境不仅是"反思"，更是"训练"。
系统在低负载或检测到"僵化"时进入离线阶段：
- 蒸馏（v0.1→v0.4 升级）：从统计提取 → 监督学习模型训练
- 反事实杂交：将历史失败方案与当前主流方案强行组合
"""

import random
import logging
from typing import List, Optional

from .consensus import ConsensusTracker
from .submodule import SubModule
from .config import HiveMindConfig
from .distill import DistillationEngine

logger = logging.getLogger("hivemind.dream")


class DreamMechanism:
    """
    梦境机制（v0.4：集成知识蒸馏引擎）。

    触发条件：系统僵化检测（共识变化率低于阈值）
    执行内容：
    1. 蒸馏 — v0.4 升级：用 DistillationEngine 训练 mini 模型（非仅统计提取）
    2. 反事实杂交 — 组合失败方案与当前方案，测试增益
    成本：低功耗推演（成本比例 dream_cost_ratio）
    """

    def __init__(self, config: HiveMindConfig, consensus: ConsensusTracker):
        self.config = config
        self.consensus = consensus
        self.dream_count: int = 0
        self.dream_log: List[dict] = []
        self.distilled_rules: List[str] = []         # 蒸馏出的规则（兼容旧版）
        self.last_distill_result: Optional[dict] = None

        # ── v0.4：知识蒸馏引擎 ──
        self.distiller = DistillationEngine(config) if config.distill_enabled else None

    def should_trigger(self) -> bool:
        """检测是否应触发梦境（系统僵化）"""
        return self.consensus.is_stagnant()

    def record_proposal(self, module: SubModule, proposal_value: float):
        """
        v0.4 新增：每轮仿真结束后记录提案特征+标签。

        不消耗能量（纯记账），供蒸馏引擎积累训练数据。
        """
        if self.distiller is None:
            return
        consensus_val = self.consensus.current.value
        self.distiller.record(module, proposal_value, consensus_val)

    def execute(self, modules: List[SubModule], round_num: int) -> dict:
        """
        执行一轮梦境推演。
        返回梦境结果摘要。
        """
        self.dream_count += 1
        dream_cost = self.config.inference_cost * self.config.dream_cost_ratio

        # ── 1. 蒸馏（v0.4：训练 mini 模型） ──
        distilled = self._distill(modules, dream_cost)

        # ── 2. 知识蒸馏训练（v0.4 新增） ──
        distill_result = None
        if self.distiller is not None and self.distiller.has_enough_data():
            # 不是每次梦境都蒸馏，而是有足够数据后每 N 次梦境蒸馏一次
            if self.dream_count % 5 == 0:
                distill_result = self.distiller.distill()
                self.last_distill_result = distill_result
                logger.info(f"梦境#{self.dream_count} 执行知识蒸馏: samples={self.distiller.training_data.__len__()}")

        # ── 3. 反事实杂交 ──
        hybrids = self._counterfactual_hybridize(modules, dream_cost)

        result = {
            "round": round_num,
            "dream_id": self.dream_count,
            "distilled_rules": distilled,
            "hybrids": hybrids,
            "knowledge_distilled": distill_result is not None,
            "distill_summary": distill_result,
        }
        self.dream_log.append(result)

        logger.info(
            f"梦境 round={round_num}, "
            f"蒸馏规则={len(distilled)}, "
            f"杂交方案={len(hybrids)}, "
            f"知识蒸馏={'是' if distill_result else '否'}"
        )
        return result

    def _distill(self, modules: List[SubModule], dream_cost: float) -> List[str]:
        """
        蒸馏 v0.4：从模块历史数据中提取模式规则。

        与 v0.3 兼容，保留统计特征提取作为"表层蒸馏"。
        深层蒸馏（模型训练）由 KnowledgeDistiller 独立处理。
        """
        rules = []
        for m in modules:
            if not m.alive or len(m.history) < 3:
                continue

            floor = m.config.energy_floor
            if m.wallet.can_afford(dream_cost, floor=floor):
                m.wallet.spend(dream_cost, reason="梦境蒸馏", floor=floor)

                avg = sum(m.history) / len(m.history)
                trend = m.history[-1] - m.history[0] if len(m.history) > 1 else 0
                volatility = max(m.history) - min(m.history)

                rule = (
                    f"[{m.module_id}] avg={avg:.2f}, "
                    f"trend={trend:.2f}, volatility={volatility:.2f}"
                )
                rules.append(rule)
                self.distilled_rules.append(rule)

        return rules

    def _counterfactual_hybridize(
        self, modules: List[SubModule], dream_cost: float
    ) -> List[dict]:
        """
        反事实杂交：将不同模块的历史方案强行组合。
        如果组合结果产生意外增益（比当前共识更接近目标），记录下来并注入扰动。

        v0.4 增强：如果蒸馏模型可用，用模型预测来评估杂交增益。
        """
        hybrids = []
        alive_modules = [m for m in modules if m.alive and len(m.history) >= 2]

        for i in range(len(alive_modules)):
            if random.random() > self.config.counterfactual_mix_prob:
                continue

            m1 = alive_modules[i]
            m2 = random.choice(alive_modules) if alive_modules else None
            if m2 is None or m2.module_id == m1.module_id:
                continue

            floor = m1.config.energy_floor
            if m1.wallet.can_afford(dream_cost, floor=floor):
                m1.wallet.spend(dream_cost, reason="梦境杂交", floor=floor)

            weight = random.uniform(0.3, 0.7)
            hybrid_value = weight * m1.history[-1] + (1 - weight) * m2.history[-1]

            # v0.4 增强：用蒸馏模型辅助评估（如果可用）
            current_dist = abs(self.consensus.current.value - self.config.target_value)
            hybrid_dist = abs(hybrid_value - self.config.target_value)
            gain = current_dist - hybrid_dist

            # 蒸馏模型置信度加成（v0.4 实验性，暂关闭避免过度扰动）
            distill_boost = 0.0
            # if self.distiller is not None and self.last_distill_result is not None:
            #     trust_m1 = self.distiller.predict_module_trust(m1, self.consensus.current.value)
            #     trust_m2 = self.distiller.predict_module_trust(m2, self.consensus.current.value)
            #     distill_boost = (trust_m1 + trust_m2) * 0.1

            hybrid = {
                "module1": m1.module_id,
                "module2": m2.module_id,
                "weight": weight,
                "hybrid_value": hybrid_value,
                "gain": gain,
                "distill_boost": distill_boost,
                "useful": gain > 0,
            }
            hybrids.append(hybrid)

            # 如果杂交有增益（含蒸馏加成），注入共识扰动
            if gain + distill_boost > 0:
                perturbation_rate = 0.05
                self.consensus.current.value += perturbation_rate * (hybrid_value - self.consensus.current.value)
                logger.info(f"反事实杂交注入扰动: hybrid={hybrid_value:.2f}, gain={gain:.4f}, distill_boost={distill_boost:.4f}")

        return hybrids

    def summary(self) -> dict:
        """返回梦境机制状态摘要"""
        base = {
            "dream_count": self.dream_count,
            "distilled_rules_count": len(self.distilled_rules),
            "last_dream": self.dream_log[-1] if self.dream_log else None,
        }
        # v0.4：追加蒸馏引擎状态
        if self.distiller is not None:
            base["distillation_engine"] = self.distiller.summary()
        return base
