"""
调度器 - HiveMind 2.0 的主循环 v2.1

v2.1 新增: 差异化初始先验 + 梦境记忆(checkpoint 保存/加载)
"""

import random
import logging
from typing import List, Optional
from .learner import Learner
from .argument import ArgumentEvaluator
from .trust import TrustEngine
from .dream import DreamStore

logger = logging.getLogger("hivemind_v2.orchestrator")


# 预设的学习器个性配置
PRESET_PERSONAS = [
    {"name": "L1_optimist",    "mu": +3.0, "sigma": 8.0,  "window": 5,  "hint": "天生乐观"},
    {"name": "L2_pessimist",   "mu": -3.0, "sigma": 8.0,  "window": 5,  "hint": "天生悲观"},
    {"name": "L3_skeptic",     "mu":  0.0, "sigma": 15.0, "window": 10, "hint": "高度不确定，爱怀疑"},
    {"name": "L4_stubborn",    "mu":  0.0, "sigma": 3.0,  "window": 3,  "hint": "很自信，学得慢"},
    {"name": "L5_adaptable",   "mu":  0.0, "sigma": 10.0, "window": 12, "hint": "灵活，窗口大"},
]

class HiveMindV2:
    """
    HiveMind 2.0 调度器。
    """

    def __init__(
        self,
        n_learners: int = 5,
        warmup_rounds: int = 50,
        propose_interval: int = 5,
        debate_rounds: int = 2,
        verify_ratio: float = 0.1,
        use_personas: bool = True,
    ):
        if use_personas:
            self.learners = [
                Learner(
                    name=p["name"], window_size=p["window"],
                    initial_mu=p["mu"], initial_sigma=p["sigma"]
                )
                for p in PRESET_PERSONAS[:n_learners]
            ]
        else:
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
        self.verify_buffer: List[float] = []
        self.consensus_history: List[float] = []
        self.log: List[dict] = []

    def save_dream(self, filepath: str):
        """v2.1: 保存所有学习器状态到梦境文件"""
        store = DreamStore()
        return store.save(self.learners, filepath)

    @classmethod
    def from_dream(cls, filepath: str, **kwargs) -> "HiveMindV2":
        """v2.1: 从梦境文件恢复 HiveMind（跳过预热）"""
        store = DreamStore()
        states = store.load(filepath)
        instance = cls(use_personas=False, n_learners=0)  # 空壳
        instance.learners = DreamStore.restore_learners(states)
        for l in instance.learners:
            instance.trust.register(l.learner_id)
        instance.warmup_rounds = 0  # 不需要预热
        logger.info(f"从梦境恢复: {len(instance.learners)} 个学习器, 跳过预热")
        return instance

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
