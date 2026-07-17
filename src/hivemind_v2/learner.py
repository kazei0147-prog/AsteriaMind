"""
学习器 - HiveMind 2.6 可成长认知节点

v2.6 修复: 先验可自适应数据尺度
- ScaleTracker: 运行尺度估计，跟踪数据的位置和离散度
- BayesianBelief 方案A: 尺度归一化更新 (时变位置高斯)
- BayesianBelief 方案B: Student-t 似然 + 离群阻尼 (更强鲁棒)
- 上层 CuriosityEngine/Portal/SearchDataSource 完全不动
"""
import random
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ──────────── 尺度追踪器 ────────────

class ScaleTracker:
    """
    追踪数据流的运行位置和尺度。

    核心作用: 当数据从 CO2 (~420) 变为线性 y=x (~200) 时，
    自动调整归一化，让 BayesianBelief 的更新不受原始尺度影响。
    """
    def __init__(self, alpha: float = 0.05, min_scale: float = 0.01):
        self.location: float = 0.0     # EMA of raw observations
        self.scale: float = 1.0        # EMA of |obs - location|
        self.variance: float = 1.0     # EMA of squared deviations
        self.alpha: float = alpha
        self.min_scale: float = min_scale
        self.n_obs: int = 0

    def observe(self, value: float) -> float:
        """更新尺度估计，返回当前 scale"""
        self.n_obs += 1
        if self.n_obs == 1:
            self.location = value
            self.scale = max(abs(value), 1.0) * 0.1
            self.variance = self.scale ** 2
        else:
            # 指数平滑
            self.location += self.alpha * (value - self.location)
            deviation = abs(value - self.location)
            self.scale += self.alpha * (deviation - self.scale)
            self.variance += self.alpha * (deviation**2 - self.variance)

        self.scale = max(self.min_scale, self.scale)
        self.variance = max(self.min_scale**2, self.variance)
        return self.scale

    @property
    def robust_scale(self) -> float:
        """鲁棒尺度: MAD-like (median absolute deviation 近似)"""
        return max(self.min_scale, self.scale * 0.6745)


# ──────────── 方案A: 尺度自适应的贝叶斯信念 ────────────

@dataclass
class BayesianBelief:
    """
    贝叶斯信念 v2.6 — 时变位置高斯

    关键修复: error 用数据尺度做归一化 → 不管数据是 0-1 还是 0-1000，更新步长一致
    sigma 可以双向调整 → 数据尺度变大了，sigma 也能增长
    """
    mu: float = 0.0
    sigma: float = 10.0
    alpha: float = 1.0

    # v2.6: 尺度自适应参数
    adaptive_scale: bool = True          # 方案A: 尺度归一化
    robust_likelihood: bool = False      # 方案B: Student-t 似然 (二选一或叠加)
    t_df: float = 3.0                    # Student-t 自由度

    def sample(self) -> float:
        return random.gauss(self.mu, max(self.sigma, 0.01))

    def update(
        self,
        error: float,
        learning_rate: float = 0.1,
        data_scale: float | None = None,
    ):
        """
        基于预测误差更新信念。

        v2.6:
        - data_scale: ScaleTracker 提供的当前数据尺度
        - 方案A (adaptive_scale=True): error 归一化后更新
        - 方案B (robust_likelihood=True): 叠加 Student-t 阻尼
        """
        # 归一化尺度
        scale = max(data_scale if data_scale is not None else 10.0, 0.01)
        norm_error = error / scale

        if self.robust_likelihood:
            # 方案B: Student-t 似然 — 大误差被自然阻尼
            # t-分布的对数梯度: -error / (error²/df + scale²)
            damped = norm_error / (1.0 + (norm_error**2) / self.t_df)
            grad = -damped * learning_rate / (self.alpha + 1e-8)
        else:
            # 方案A: 尺度归一化高斯
            grad = -norm_error * learning_rate / (self.alpha + 1e-8)

        self.mu += grad

        # sigma 双向调整: 向数据尺度靠拢
        if self.adaptive_scale:
            target_sigma = scale * 0.3  # 目标: sigma ≈ 数据尺度的 30%
            self.sigma += learning_rate * 0.2 * (target_sigma - self.sigma)
        else:
            # 旧的单调缩小 (保持兼容)
            self.sigma = max(0.1, self.sigma * (1.0 - learning_rate * 0.5))

        self.alpha += learning_rate * 0.05

    def clone(self) -> "BayesianBelief":
        return BayesianBelief(
            mu=self.mu, sigma=self.sigma, alpha=self.alpha,
            adaptive_scale=self.adaptive_scale,
            robust_likelihood=self.robust_likelihood,
            t_df=self.t_df,
        )


# ──────────── 推理链 ────────────

@dataclass
class ReasoningChain:
    """推理链——学习器提案时附带的论证依据"""
    learner_id: str
    proposal_value: float
    observation: float
    belief: BayesianBelief
    recent_window: List[float] = field(default_factory=list)
    track_record: float = 0.5
    confidence_interval: Tuple[float, float] = (0, 0)

    def strength(self) -> float:
        precision = 1.0 / max(self.belief.sigma, 0.1)
        recent_volatility = self._recent_volatility()
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
        var = sum((x - avg)**2 for x in self.recent_window) / len(self.recent_window)
        return min(1.0, math.sqrt(max(var, 0.0)) / max(abs(avg), 0.1))

    def summary(self) -> str:
        interval = self.confidence_interval
        return (
            f"[{self.learner_id}] "
            f"proposal={self.proposal_value:.2f}, "
            f"belief=N({self.belief.mu:.2f},{self.belief.sigma:.2f}), "
            f"track_record={self.track_record:.2f}, "
            f"95%CI=({interval[0]:.1f},{interval[1]:.1f})"
        )


# ──────────── 学习者 ────────────

class Learner:
    _next_id = 1

    def __init__(
        self,
        name: Optional[str] = None,
        window_size: int = 10,
        initial_mu: float = 0.0,
        initial_sigma: float = 10.0,
        adaptive_scale: bool = True,       # v2.6: 方案A
        robust_likelihood: bool = False,    # v2.6: 方案B
    ):
        self.learner_id = name or f"learner_{Learner._next_id}"
        Learner._next_id += 1

        self.belief = BayesianBelief(
            mu=initial_mu,
            sigma=initial_sigma,
            adaptive_scale=adaptive_scale,
            robust_likelihood=robust_likelihood,
        )
        self.scale_tracker = ScaleTracker()  # v2.6: 尺度追踪

        self.window_size = window_size
        self.observation_window: List[float] = []
        self.history: List[float] = []
        self.error_history: List[float] = []
        self.total_rounds = 0
        self.successes = 0
        self.alive = True
        self.current_strategy: Optional[str] = None

    def observe(self, raw_data: float):
        """观测一个新数据点"""
        self.observation_window.append(raw_data)
        if len(self.observation_window) > self.window_size:
            self.observation_window = self.observation_window[-self.window_size:]
        # v2.6: 更新尺度追踪
        self.scale_tracker.observe(raw_data)
        self.total_rounds += 1

    def propose(self, current_obs: float) -> ReasoningChain:
        """
        基于当前观测和内部信念生成提案。

        v2.6: 用尺度归一化的信念采样
        """
        bias = self.belief.sample()
        data_scale = max(self.scale_tracker.scale, 0.1)

        # 提案 = 观测值 + 尺度归一化的信念偏移
        proposal_value = current_obs + bias * data_scale / 10.0

        # 95% 置信区间
        ci_low = proposal_value - 1.96 * max(self.belief.sigma, 0.1) * data_scale / 10.0
        ci_high = proposal_value + 1.96 * max(self.belief.sigma, 0.1) * data_scale / 10.0

        chain = ReasoningChain(
            learner_id=self.learner_id,
            proposal_value=proposal_value,
            observation=current_obs,
            belief=self.belief.clone(),
            recent_window=list(self.observation_window),
            track_record=self.track_record(),
            confidence_interval=(ci_low, ci_high),
        )
        return chain

    def learn(self, true_value: float, proposed_value: float):
        """
        从验证数据中学习。

        v2.6: 传递 data_scale 给 BayesianBelief
        """
        error = proposed_value - true_value
        self.error_history.append(abs(error))
        if len(self.error_history) > 100:
            self.error_history = self.error_history[-100:]

        # 判断是否"成功" (相对误差 < 10%)
        relative_error = abs(error) / max(abs(true_value), 1.0)
        if relative_error < 0.10:
            self.successes += 1

        self.history.append(proposed_value)
        if len(self.history) > 200:
            self.history = self.history[-200:]

        # v2.6: 传递数据尺度
        data_scale = max(self.scale_tracker.scale, 0.1)
        self.belief.update(
            error=error,
            learning_rate=0.1,
            data_scale=data_scale,
        )

    def track_record(self) -> float:
        """历史成功率"""
        total = max(len(self.error_history), 1)
        return self.successes / total

    def average_error(self) -> float:
        if not self.error_history:
            return float("inf")
        return sum(self.error_history) / len(self.error_history)

    def beliefs_summary(self) -> str:
        return (
            f"{self.learner_id}: N(μ={self.belief.mu:.2f}, "
            f"σ={self.belief.sigma:.2f}, α={self.belief.alpha:.1f}) "
            f"scale={self.scale_tracker.scale:.1f} "
            f"track={self.track_record():.2f}"
        )

    def export_state(self) -> dict:
        return {
            "learner_id": self.learner_id,
            "mu": self.belief.mu,
            "sigma": self.belief.sigma,
            "alpha": self.belief.alpha,
            "scale_location": self.scale_tracker.location,
            "scale": self.scale_tracker.scale,
            "window_size": self.window_size,
            "total_rounds": self.total_rounds,
            "successes": self.successes,
            "adaptive_scale": self.belief.adaptive_scale,
            "robust_likelihood": self.belief.robust_likelihood,
        }

    @classmethod
    def from_state(cls, state: dict) -> "Learner":
        learner = cls(
            name=state["learner_id"],
            window_size=state.get("window_size", 10),
            initial_mu=state.get("mu", 0),
            initial_sigma=state.get("sigma", 10),
            adaptive_scale=state.get("adaptive_scale", True),
            robust_likelihood=state.get("robust_likelihood", False),
        )
        learner.scale_tracker.location = state.get("scale_location", 0)
        learner.scale_tracker.scale = state.get("scale", 1)
        learner.total_rounds = state.get("total_rounds", 0)
        learner.successes = state.get("successes", 0)
        return learner
