"""
论证引擎 - HiveMind 2.0 的共识机制

v2.0 核心创新: 不再做加权平均，而是评估每个学习器的论证质量，
选出最佳解释，并允许学习器基于他人的论证修正自己的立场。

流程:
1. 各学习器独立提案（附带推理链）
2. 母模块评估每条推理链的论证强度
3. 学习器看到彼此的推理链后，可以修正自己的提案
4. 最终共识 = 最佳论证的提案（不是平均）
"""

import logging
from typing import List, Optional, Tuple
from .learner import ReasoningChain

logger = logging.getLogger("AsteriaMind.argument")


class ArgumentEvaluator:
    """
    论证评估器。
    
    替代 v0.x 的加权平均共识。不是"谁的 confidence 最高就信谁"，
    而是"谁的推理最站得住脚就信谁"。
    """

    def __init__(self, debate_rounds: int = 2, agreement_threshold: float = 0.3):
        """
        debate_rounds: 每轮讨论的学习器修正次数
        agreement_threshold: 当论证强度差距小于此值时，用加权平均（大家差不多对）
        """
        self.debate_rounds = debate_rounds
        self.agreement_threshold = agreement_threshold

    def evaluate(self, chains: List[ReasoningChain]) -> Tuple[float, List[ReasoningChain], str]:
        """
        评估所有推理链，输出共识值和评估过程。
        
        返回: (共识值, 排序后的推理链, 评估说明)
        """
        if not chains:
            return 0.0, [], "无提案"

        # 按论证强度排序
        ranked = sorted(chains, key=lambda c: c.strength(), reverse=True)
        best = ranked[0]
        
        # 检查论证差距
        if len(ranked) >= 2:
            gap = ranked[0].strength() - ranked[1].strength()
        else:
            gap = 1.0
        
        if gap > self.agreement_threshold:
            # 有明显的赢家 → 直接采纳最佳论证的提案
            consensus = best.proposal_value
            method = f"best_argument (gap={gap:.2f}, leader={best.learner_id})"
        else:
            # 论证强度接近 → 用论证强度加权（不是 confidence 加权！）
            total_strength = sum(c.strength() for c in ranked)
            consensus = sum(c.proposal_value * c.strength() / total_strength for c in ranked)
            method = f"argument_weighted (gap={gap:.2f}, {len(ranked)} participants)"
        
        return consensus, ranked, method

    def debate(self, chains: List[ReasoningChain]) -> List[ReasoningChain]:
        """
        一轮"讨论"：学习器看到彼此的推理后，有机会修正。
        
        修正逻辑：
        - 如果一个学习器的论证强度远低于最佳论证，它向最佳论证靠拢
        - 靠拢程度 = 自己的 track_record / 最佳论证的 track_record
        """
        if len(chains) < 2:
            return chains
        
        ranked = sorted(chains, key=lambda c: c.strength(), reverse=True)
        best = ranked[0]
        
        revised = [best]  # 最佳论证不变
        for chain in ranked[1:]:
            best_advantage = best.strength() - chain.strength()
            if best_advantage > 0.2:  # 差距显著
                # 向最佳论证靠拢
                pull = min(best_advantage, 0.5) * (chain.track_record / max(best.track_record, 0.01))
                pull = min(pull, 0.5)  # 最多修正 50%
                
                revised_value = chain.proposal_value * (1 - pull) + best.proposal_value * pull
                # 创建修正后的推理链（保持原有论证结构）
                from .learner import ReasoningChain
                revised_chain = ReasoningChain(
                    learner_id=chain.learner_id,
                    proposal_value=revised_value,
                    observation=chain.observation,
                    belief=chain.belief,
                    recent_window=chain.recent_window,
                    track_record=chain.track_record,
                    confidence_interval=chain.confidence_interval,
                )
                revised.append(revised_chain)
            else:
                revised.append(chain)
        
        return revised

    def full_discussion(self, chains: List[ReasoningChain]) -> Tuple[float, List[ReasoningChain], str]:
        """
        完整的讨论流程：多轮辩论 → 评估
        """
        current_chains = chains
        for i in range(self.debate_rounds):
            prev_strengths = [c.strength() for c in current_chains]
            current_chains = self.debate(current_chains)
            new_strengths = [c.strength() for c in current_chains]
            
            # 如果论证强度不再显著变化，停止讨论
            max_change = max(abs(s - n) for s, n in zip(prev_strengths, new_strengths))
            if max_change < 0.01:
                logger.debug(f"讨论收敛于第 {i+1} 轮")
                break
        
        return self.evaluate(current_chains)
