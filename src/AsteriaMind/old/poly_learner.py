"""
PolyLearner — 多项式结构学习器 (v2.10)

从 FunctionLearner (仅 y=ax+b) 升级:
  - 支持任意次多项式: y = a₀ + a₁x + a₂x² + ... + aₙxⁿ
  - 自动结构发现: 检测到线性不拟合时, 尝试升阶
  - 导数计算: 从系数直接推出 dy/dx

核心: RLS 框架不变, phi 从 [x,1] 扩展为 [xⁿ,...,x²,x,1]。
"""
import math
from typing import List


class PolyLearner:
    """在线多项式 RLS — 自动升阶"""

    def __init__(self, max_degree: int = 5, forgetting: float = 0.995,
                 l2_lambda: float = 0.001, upgrade_cooldown: int = 8):
        self.max_degree = max_degree
        self.current_degree = 1       # 从线性起步
        self.forgetting = forgetting
        self.l2_lambda = l2_lambda    # L2 正则化系数
        self.upgrade_cooldown = upgrade_cooldown  # 升阶冷却轮数
        self._upgrades_since_last = 0  # 上次升阶后的更新轮数

        # ── state per degree ──
        self.theta: List[List[float]] = []   # theta[d] = coefficients of degree d
        self.P: List[List[List[float]]] = [] # covariance matrices
        self.r_squared: List[float] = []      # per degree
        self.residual_std: List[float] = []
        self.n_updates: List[int] = []

        # 历史
        self.x_hist: List[float] = []
        self.y_hist: List[float] = []
        self.max_history = 200

        # 升阶日志
        self.degree_upgrades: list[dict] = []
        self._init_degree(0)  # seed degree 0 (constant)
        self._init_degree(1)  # start with linear

    def _init_degree(self, d: int):
        """为次数 d 初始化 theta/P。"""
        while len(self.theta) <= d:
            n = len(self.theta) + 1  # number of coefficients for degree n-1
            self.theta.append([0.0] * n)
            self.P.append([
                [1000.0 if i == j else 0.0 for j in range(n)]
                for i in range(n)
            ])
            self.r_squared.append(0.0)
            self.residual_std.append(1.0)
            self.n_updates.append(0)

        # 每阶的 R² 峰值追踪
        while len(getattr(self, '_r2_peak', [])) <= d:
            if not hasattr(self, '_r2_peak'):
                self._r2_peak: List[float] = []
            self._r2_peak.append(0.0)

    def _phi(self, x: float, degree: int) -> list:
        """构建 phi 向量: [x^d, x^(d-1), ..., x, 1]"""
        return [x ** (degree - i) for i in range(degree + 1)]

    def update(self, x: float, y: float) -> dict:
        """喂入 (x,y), 更新所有已初始化的度数, 返回各度数残差。"""
        self.x_hist.append(x)
        self.y_hist.append(y)
        for h in [self.x_hist, self.y_hist]:
            if len(h) > self.max_history:
                h.pop(0)

        results = {}
        for d in range(len(self.theta)):
            err = self._update_degree(d, x, y)
            results[d] = err
        return results

    def _update_degree(self, d: int, x: float, y: float) -> float:
        phi = self._phi(x, d)
        theta = self.theta[d]
        P = self.P[d]

        y_pred = sum(phi[i] * theta[i] for i in range(d + 1))
        error = y - y_pred

        # P × φ
        P_phi = [
            sum(P[i][j] * phi[j] for j in range(d + 1))
            for i in range(d + 1)
        ]
        phi_P_phi = sum(phi[i] * P_phi[i] for i in range(d + 1))
        denom = max(self.forgetting + phi_P_phi, 1e-8)
        K = [p / denom for p in P_phi]

        for i in range(d + 1):
            # RLS 增量 + L2 权重衰减 (防过拟合)
            theta[i] = theta[i] * (1.0 - self.l2_lambda) + K[i] * error

        for i in range(d + 1):
            for j in range(d + 1):
                P[i][j] = (P[i][j] - K[i] * P_phi[j]) / self.forgetting

        self.n_updates[d] += 1

        # R² (after enough data)
        if len(self.x_hist) >= 10 and d == self.current_degree:
            recent_n = min(50, len(self.x_hist))
            xs = self.x_hist[-recent_n:]
            ys = self.y_hist[-recent_n:]
            ss_res = sum((self.predict(xi, d) - yi) ** 2 for xi, yi in zip(xs, ys))
            y_mean = sum(ys) / len(ys)
            ss_tot = sum((yi - y_mean) ** 2 for yi in ys) + 1e-8
            self.r_squared[d] = max(0.0, 1.0 - ss_res / ss_tot)
            self.residual_std[d] = math.sqrt(ss_res / recent_n) if recent_n > 0 else 1.0
            # 追 R² 峰值
            if self.r_squared[d] > getattr(self, '_r2_peak', [0]*10)[d]:
                self._r2_peak[d] = self.r_squared[d]

        return error

    def predict(self, x: float, degree: int = None) -> float:
        d = degree if degree is not None else self.current_degree
        phi = self._phi(x, d)
        return sum(phi[i] * self.theta[d][i] for i in range(d + 1))

    def derivative(self, x: float, degree: int = None) -> float:
        """计算 dy/dx = Σ i·a_i·x^(i-1)"""
        d = degree if degree is not None else self.current_degree
        t = self.theta[d]
        return sum(i * t[i] * (x ** (i - 1)) for i in range(1, d + 1))

    def integral(self, a: float, b: float, degree: int = None, n: int = 100) -> float:
        """数值定积分 ∫ₐᵇ f(x)dx (梯形法)"""
        dx = (b - a) / n
        total = 0.0
        for i in range(n):
            x0 = a + i * dx
            x1 = a + (i + 1) * dx
            total += (self.predict(x0, degree) + self.predict(x1, degree)) * dx / 2
        return total

    # ── 结构发现 ──

    def check_upgrade(self, min_samples: int = 30, r2_improvement: float = 0.06,
                      r2_drop: float = 0.05) -> bool:
        """
        检查是否应升阶。触发条件:
          1. R² 从峰值跌超 r2_drop (相对) → 结构可能变了
          2. 距上次升阶已过冷却期
          3. 下一阶 R² 显著高于当前
        """
        d = self.current_degree
        self._upgrades_since_last += 1

        if d >= self.max_degree:
            return False
        if self.n_updates[d] < min_samples:
            return False
        if self._upgrades_since_last < self.upgrade_cooldown:
            return False

        peak = self._r2_peak[d]
        r2_curr = self.r_squared[d]
        if peak > 0.5 and r2_curr > peak * (1.0 - r2_drop):
            return False  # R² 没明显跌

        next_d = d + 1
        self._init_degree(next_d)

        recent_n = min(min_samples * 2, len(self.x_hist))
        xs = self.x_hist[-recent_n:]
        ys = self.y_hist[-recent_n:]
        for xi, yi in zip(xs, ys):
            self._update_degree(next_d, xi, yi)

        # 手工计算下一阶 R² (不依赖 _update_degree 的 current_degree 检查)
        preds = [self.predict(xi, next_d) for xi in xs]
        ss_res = sum((p - yi) ** 2 for p, yi in zip(preds, ys))
        y_mean = sum(ys) / len(ys)
        ss_tot = sum((yi - y_mean) ** 2 for yi in ys) + 1e-8
        r2_next = max(0.0, 1.0 - ss_res / ss_tot)
        r2_curr = self.r_squared[d]

        if r2_next > r2_curr + r2_improvement:
            old_deg = self.current_degree
            self.current_degree = next_d
            self._upgrades_since_last = 0  # 重置冷却
            self.degree_upgrades.append({
                "from": old_deg, "to": next_d,
                "r2_before": round(r2_curr, 4),
                "r2_after": round(r2_next, 4),
                "n_samples": self.n_updates[d],
            })
            return True
        return False

    def structure_gap(self, r2_threshold: float = 0.70) -> bool:
        """CuriosityEngine 兼容: 当前模型是否可修复的崩塌。
        冷却期内不重复报警, 防止恐慌循环。
        检测到崩塌时临时加速遗忘, 帮 RLS 丢弃旧 regime 数据。"""
        if self._upgrades_since_last < self.upgrade_cooldown:
            return False
        d = self.current_degree
        if d >= self.max_degree:
            return False
        gap = self.n_updates[d] >= 15 and self.r_squared[d] < r2_threshold
        if gap:
            self.forgetting = 0.95  # 临时加速遗忘 (vs 默认 0.995)
        else:
            self.forgetting = 0.995  # 恢复正常
        return gap

    # ── 导出 ──

    def formula(self, degree: int = None) -> str:
        """人类可读公式"""
        d = degree if degree is not None else self.current_degree
        t = self.theta[d]
        terms = []
        for i, a in enumerate(t):
            power = d - i
            if abs(a) < 1e-6:
                continue
            if power == 0:
                terms.append(f"{a:+.4f}")
            elif power == 1:
                terms.append(f"{a:+.4f}x")
            else:
                terms.append(f"{a:+.4f}x^{power}")
        return "y = " + " ".join(terms) if terms else "y = 0"

    def summary(self) -> dict:
        d = self.current_degree
        return {
            "current_degree": d,
            "max_degree": self.max_degree,
            "coefficients": [round(c, 4) for c in self.theta[d]],
            "formula": self.formula(),
            "r_squared": round(self.r_squared[d], 4),
            "residual_std": round(self.residual_std[d], 4),
            "n_updates": self.n_updates[d],
            "upgrades": self.degree_upgrades,
        }
