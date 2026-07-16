"""
调度器 - HiveMind 2.0 的主循环

与 v0.x MotherModule 的根本区别:
- 预处理暖身期: 先运行 N 轮让学习器积累经验（偏见自然涌现）
- 不是每轮都做加权平均; 而是定期触发"讨论回合"
- 讨论回合中: 学习器提案 → 互看推理链 → 修正 → 评估 → 共识
- 事后验证: 用验证集评估每个学习器的提案，更新信任
- 没有 energy/energy_floor/death/adoption_reward 等概念
"""

import random
import logging
from typing import List, Optional
from .learner import Learner
from .argument import ArgumentEvaluator
from .trust import TrustEngine

logger = logging.getLogger("hivemind_v2.orchestrator")


class HiveMindV2:
    """
    HiveMind 2.0 调度器。
    
    生命周期:
    1. 预热期 (warmup_rounds): 学习器独立观察数据，积累经验
    2. 运行期: 每 propose_interval 轮触发一次讨论
    3. 验证期: 每 verify_interval 轮用预留数据事后验证
    """

    def __init__(
        self,
        n_learners: int = 5,
        warmup_rounds: int = 50,
        propose_interval: int = 5,
        debate_rounds: int = 2,
        verify_ratio: float = 0.1,
    ):
        self.learners = [Learner(name=f"L{i+1}") for i in range(n_learners)]
        self.evaluator = ArgumentEvaluator(debate_rounds=debate_rounds)
        self.trust = TrustEngine()
        for l in self.learners:
            self.trust.register(l.learner_id)

        self.warmup_rounds = warmup_rounds
        self.propose_interval = propose_interval
        self.verify_ratio = verify_ratio
        
        self.round_num = 0
        self.data_buffer: List[float] = []
        self.verify_buffer: List[float] = []  # 预留的验证数据
        self.consensus_history: List[float] = []
        self.log: List[dict] = []

    def _fetch_data(self, datasource) -> Optional[float]:
        """从数据源获取下一个观测值"""
        val = datasource.fetch()
        if val is None:
            return None
        self.data_buffer.append(val)
        return val

    def run(self, datasource, max_rounds: int = 500) -> dict:
        """
        完整运行流程。
        
        datasource: 数据源（复用 v0.x 的 DataSource 接口）
        max_rounds: 最大轮数
        """
        # === Phase 1: 预热 ===
        logger.info(f"预热期: {self.warmup_rounds} 轮, {len(self.learners)} 个学习器")
        for _ in range(self.warmup_rounds):
            val = self._fetch_data(datasource)
            if val is None:
                break
            # 预热期: 学习器只观察，不讨论
            for learner in self.learners:
                learner.observe(val)
            self.round_num += 1
        
        # === Phase 2: 运行 ===
        logger.info(f"运行期开始, 最大 {max_rounds} 轮")
        for _ in range(max_rounds):
            val = self._fetch_data(datasource)
            if val is None:
                break
            self.round_num += 1
            
            # 每个学习器独立观察
            for learner in self.learners:
                learner.observe(val)
            
            # 定期讨论
            if self.round_num % self.propose_interval == 0:
                round_result = self._discussion_round(val)
                self.log.append(round_result)
                
                # 事后验证 (用预留数据)
                if len(self.verify_buffer) >= 5:
                    self._verify()
                    self.verify_buffer = []
            
            # 预留部分数据用于验证
            if random.random() < self.verify_ratio:
                self.verify_buffer.append(val)
        
        return self._final_summary()

    def _discussion_round(self, current_obs: float) -> dict:
        """
        一轮完整讨论:
        1. 各学习器基于当前观测提案
        2. 评估论证质量，选出最佳
        3. 允许学习器看到彼此推理后修正
        4. 生成共识
        """
        # 各学习器提案
        chains = []
        for learner in self.learners:
            chain = learner.propose(current_obs)
            chains.append(chain)
        
        # 讨论 + 评估
        consensus, ranked, method = self.evaluator.full_discussion(chains)
        self.consensus_history.append(consensus)
        
        return {
            "round": self.round_num,
            "consensus": consensus,
            "method": method,
            "top_argument": ranked[0].summary() if ranked else "N/A",
            "n_chains": len(chains),
            "trust_ranking": [f"{lid}:{t:.2f}" for lid, t in self.trust.rank()[:3]],
        }

    def _verify(self):
        """
        事后验证: 用预留的真实数据检验每个学习器最近提案的准确性。
        
        这是信任系统的核心——只在事后检验，不在事中加权。
        """
        if not self.verify_buffer:
            return
        
        true_value = sum(self.verify_buffer) / len(self.verify_buffer)
        
        for learner in self.learners:
            if learner.history:
                last_proposal = learner.history[-1]
                # 通知学习器真实值 → 更新信念
                learner.learn(true_value, last_proposal)
                # 更新信任
                self.trust.verify(learner.learner_id, last_proposal, true_value)

    def _final_summary(self) -> dict:
        """运行结束摘要"""
        learners_summary = []
        for l in self.learners:
            learners_summary.append({
                "id": l.learner_id,
                "mu": l.belief.mu,
                "sigma": l.belief.sigma,
                "alpha": l.belief.alpha,
                "track_record": l.track_record(),
                "avg_error": l.average_error(),
                "trust": self.trust.get(l.learner_id),
                "total_rounds": l.total_rounds,
            })
        
        most_trusted = max(learners_summary, key=lambda x: x["trust"])
        
        return {
            "version": "2.0.0-alpha",
            "total_rounds": self.round_num,
            "n_learners": len(self.learners),
            "warmup_rounds": self.warmup_rounds,
            "n_discussions": len(self.log),
            "final_consensus": self.consensus_history[-1] if self.consensus_history else None,
            "most_trusted": most_trusted["id"],
            "most_trusted_track_record": most_trusted["track_record"],
            "learners": learners_summary,
            "trust_summary": self.trust.summary(),
        }
