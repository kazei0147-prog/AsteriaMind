"""
学习器 - HiveMind 2.0 的可成长认知节点

v2.0 核心创新: 每个学习器维护一个贝叶斯先验，从经验中更新，
而不是被预设一个硬编码的偏见系数。

设计:
- 初始: 宽正态先验 N(0, 10) — "我什么都不确定"
- 提议: 采样 N(observation + μ, σ) — "根据我的经验，我认为是..."
- 更新: 当提案被事后验证，更新 μ 和 σ — "我学到了"
- 推理链: 提案附带 "我的数据窗口 + 历史准确率 + 参数分布"
"""

import random
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class BayesianBelief:
    """贝叶斯信念——学习器的内部模型"""
    mu: float = 0.0          # 偏见均值 (学习器认为观测值应该调整多少)
    sigma: float = 10.0      # 不确定性 (越大越不确定)
    alpha: float = 1.0       # 先验强度 (越大越不愿改变)
    
    def sample(self) -> float:
        """从当前信念中采样一个偏移量"""
        return random.gauss(self.mu, max(self.sigma, 0.01))
    
    def update(self, error: float, learning_rate: float = 0.1):
        """
        基于预测误差更新信念。
        
        error > 0: 我高估了 → 降低 μ
        error < 0: 我低估了 → 提高 μ
        sigma 随误差缩小（经验越多，越确定）
        """
        grad = -error * learning_rate / (self.alpha + 1e-8)
        self.mu += grad
        self.sigma = max(0.1, self.sigma * (1.0 - learning_rate * 0.5))
        self.alpha += learning_rate * 0.05  # 经验增长，先验变强
    
    def clone(self) -> "BayesianBelief":
        return BayesianBelief(mu=self.mu, sigma=self.sigma, alpha=self.alpha)


@dataclass
class ReasoningChain:
    """
    推理链——学习器提案时附带的论证依据。
    
    这不是字符串模板，而是结构化数据。母模块用它来评估"谁的论证更合理"。
    """
    learner_id: str
    proposal_value: float
    observation: float
    belief: BayesianBelief                        # 当前信念分布
    recent_window: List[float] = field(default_factory=list)  # 最近的数据窗口
    track_record: float = 0.5                     # 历史准确率 [0,1]
    confidence_interval: Tuple[float, float] = (0, 0)  # 95% 置信区间
    
    def strength(self) -> float:
        """论证强度 [0,1] — 母模块用它来评估"""
        precision = 1.0 / max(self.belief.sigma, 0.1)
        recent_volatility = self._recent_volatility()
        # 论证强 = 信念精确 + 近期数据稳定 + 历史表现好
        score = (
            0.4 * min(precision, 5.0) / 5.0 +
            0.3 * (1.0 - min(recent_volatility, 1.0)) +
            0.3 * self.track_record
        )
        return max(0.0, min(1.0, score))
    
    def _recent_volatility(self) -> float:
        if len(self.recent_window) < 2:
            return 1.0
        avg = sum(self.recent_window) / len(self.recent_window)
        if avg == 0:
            return 1.0
        var = sum((x - avg)**2 for x in self.recent_window) / len(self.recent_window)
        return min(math.sqrt(var) / abs(avg), 1.0)
    
    def summary(self) -> str:
        return (
            f"[{self.learner_id}] 提案 {self.proposal_value:.2f} "
            f"(μ={self.belief.mu:.2f}, σ={self.belief.sigma:.2f}, "
            f"acc={self.track_record:.2f}, strength={self.strength():.2f})"
        )


class Learner:
    """
    HiveMind 2.0 学习器。
    
    没有 bias_type。没有写死的系数。只有从一个宽先验开始，慢慢学到的信念。
    """
    
    _next_id = 0
    
    def __init__(self, name: Optional[str] = None, window_size: int = 10,
                 initial_mu: float = 0.0, initial_sigma: float = 10.0):
        self.learner_id = name or f"learner_{Learner._next_id}"
        Learner._next_id += 1
        
        self.belief = BayesianBelief(mu=initial_mu, sigma=initial_sigma)
        self.window_size = window_size
        self.observation_window: List[float] = []
        self.history: List[float] = []            # 所有提案历史
        self.error_history: List[float] = []       # 事后验证的误差历史
        self.total_rounds = 0
        self.successes = 0                         # 误差 < 阈值的次数
        self.alive = True
    
    def export_state(self) -> dict:
        """导出学习器完整状态（供梦境持久化）"""
        return {
            "learner_id": self.learner_id,
            "window_size": self.window_size,
            "mu": self.belief.mu,
            "sigma": self.belief.sigma,
            "alpha": self.belief.alpha,
            "total_rounds": self.total_rounds,
            "successes": self.successes,
            "track_record": self.track_record(),
            "avg_error": self.average_error(),
        }
    
    def load_state(self, state: dict):
        """从导出的状态恢复学习器"""
        self.belief.mu = state.get("mu", 0.0)
        self.belief.sigma = state.get("sigma", 10.0)
        self.belief.alpha = state.get("alpha", 1.0)
        self.total_rounds = state.get("total_rounds", 0)
        self.successes = state.get("successes", 0)
    
    def observe(self, data: float):
        """接收观测数据，更新窗口"""
        self.observation_window.append(data)
        if len(self.observation_window) > self.window_size:
            self.observation_window.pop(0)
    
    def propose(self, observation: float) -> ReasoningChain:
        """
        基于当前信念和观测生成提案 + 推理链。
        
        提案值 = observation + 从信念分布中采样的偏移
        """
        self.total_rounds += 1
        offset = self.belief.sample()
        proposal_value = observation + offset
        self.history.append(proposal_value)
        
        # 95% 置信区间
        ci = (
            observation + self.belief.mu - 1.96 * self.belief.sigma,
            observation + self.belief.mu + 1.96 * self.belief.sigma,
        )
        
        return ReasoningChain(
            learner_id=self.learner_id,
            proposal_value=proposal_value,
            observation=observation,
            belief=self.belief.clone(),
            recent_window=self.observation_window.copy()[-5:],
            track_record=self.track_record(),
            confidence_interval=ci,
        )
    
    def learn(self, true_value: float, proposal_value: float):
        """
        事后验证：用真实值更新信念。
        
        这是核心学习机制——只有被验证后，学习器才更新自己的偏见。
        """
        error = proposal_value - true_value
        self.error_history.append(abs(error))
        self.belief.update(error)
        
        if abs(error) < abs(true_value) * 0.1:  # 误差 < 10%
            self.successes += 1
    
    def track_record(self) -> float:
        """历史准确率 [0, 1]"""
        if self.total_rounds == 0:
            return 0.5
        return self.successes / max(self.total_rounds, 1)
    
    def average_error(self) -> float:
        """平均预测误差"""
        if not self.error_history:
            return float('inf')
        return sum(self.error_history) / len(self.error_history)
    
    def beliefs_summary(self) -> str:
        return (
            f"[{self.learner_id}] μ={self.belief.mu:.3f}, "
            f"σ={self.belief.sigma:.3f}, α={self.belief.alpha:.1f}, "
            f"track_record={self.track_record():.2f}"
        )
    
    def clone(self) -> "Learner":
        """创建一个复制（保留信念，重置统计）"""
        new = Learner(name=self.learner_id, window_size=self.window_size)
        new.belief = self.belief.clone()
        return new
