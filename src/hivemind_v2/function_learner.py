"""
FunctionLearner — v2.8 结构学习入口

在线 RLS 学习 y = F(x), 独立于 ResidualLearner。
检测结构断层 (structure_gap), 作为 CuriosityEngine 第五触发器。
"""
import math
from typing import List


class FunctionLearner:
    """在线 RLS: y = a*x + b, 增量更新, 零全量存储"""

    def __init__(self, dim: int = 2, forgetting: float = 0.995):
        self.dim = dim
        self.forgetting = forgetting
        self.theta: List[float] = [0.0] * dim          # [a, b]
        self.P: List[List[float]] = [                   # 协方差, 高初始不确定性
            [1000.0 if i == j else 0.0 for j in range(dim)]
            for i in range(dim)
        ]
        self.residuals: List[float] = []
        self.y_obs: List[float] = []                     # 用于 R² 计算
        self.residual_avg: float = 0.0
        self.residual_std: float = 1.0
        self.max_history: int = 200
        self.n_updates: int = 0
        self.r_squared: float = 0.0
        self.structure_gaps: int = 0

    def update(self, x: float, y: float) -> float:
        """RLS 增量更新, 返回残差"""
        phi = [x, 1.0]
        y_pred = self.theta[0] * x + self.theta[1]
        error = y - y_pred

        # P × φ
        P_phi = [
            self.P[0][0] * phi[0] + self.P[0][1] * phi[1],
            self.P[1][0] * phi[0] + self.P[1][1] * phi[1],
        ]
        phi_P_phi = phi[0] * P_phi[0] + phi[1] * P_phi[1]
        denom = max(self.forgetting + phi_P_phi, 1e-8)
        K = [p / denom for p in P_phi]

        # θ += K × error
        self.theta[0] += K[0] * error
        self.theta[1] += K[1] * error

        # P = (P - K·φ^T·P) / λ
        for i in range(self.dim):
            for j in range(self.dim):
                self.P[i][j] = (self.P[i][j] - K[i] * P_phi[j]) / self.forgetting

        # 防协方差发散
        if any(abs(self.P[i][j]) > 1e10 for i in range(self.dim) for j in range(self.dim)):
            s = max(abs(self.theta[0]), abs(self.theta[1]), 1.0) * 10
            for i in range(self.dim):
                for j in range(self.dim):
                    self.P[i][j] = s if i == j else 0.0

        # 残差 & y 缓冲
        self.residuals.append(error)
        self.y_obs.append(y)
        for buf in [self.residuals, self.y_obs]:
            if len(buf) > self.max_history:
                buf.pop(0)

        self.n_updates += 1

        # 残差统计
        if len(self.residuals) >= 5:
            n = len(self.residuals)
            rm = sum(self.residuals) / n
            rv = sum((r - rm) ** 2 for r in self.residuals) / n
            self.residual_avg = rm
            self.residual_std = max(math.sqrt(rv), 0.01)

        # R² = 1 - Σ(r²) / Σ((y - ȳ)²)
        if len(self.y_obs) >= 10:
            ss_res = sum(r ** 2 for r in self.residuals[-50:])
            y_vals = self.y_obs[-50:]
            y_mean = sum(y_vals) / len(y_vals)
            ss_tot = sum((yv - y_mean) ** 2 for yv in y_vals) + 1e-8
            self.r_squared = max(0.0, 1.0 - ss_res / ss_tot)

        return error

    def predict(self, x: float) -> float:
        return self.theta[0] * x + self.theta[1]

    def structure_gap(self, z_threshold: float = 3.0) -> bool:
        """检测结构断层: 最近残差 vs 历史基线"""
        if len(self.residuals) < 15:
            return False
        recent = self.residuals[-5:]
        baseline = self.residuals[-15:-5]
        if len(baseline) < 5:
            return False
        r_avg = sum(recent) / len(recent)
        b_avg = sum(baseline) / len(baseline)
        b_std = max(math.sqrt(sum((r - b_avg)**2 for r in baseline) / len(baseline)), 0.01)
        z = abs(r_avg - b_avg) / b_std
        if z > z_threshold:
            self.structure_gaps += 1
            return True
        return False

    def summary(self) -> dict:
        return {
            "theta": [float(t) for t in self.theta],
            "a": float(self.theta[0]),
            "b": float(self.theta[1]),
            "r_squared": self.r_squared,
            "residual_std": self.residual_std,
            "n_updates": self.n_updates,
            "structure_gaps": self.structure_gaps,
        }
