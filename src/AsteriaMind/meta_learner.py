"""
MetaLearner — 多基函数结构学习 + Bayesian 选择 (v2.10)

核心: 同时维护多个 BasisLearner (多项式、Fourier、指数),
      用 BayesianBelief 风格的选择逻辑比较各基的 R²,
      自动选出对当前数据最优的假设空间。

这是"系统自己发现该用 sin 还是多项式"的引擎。
"""
import math
from dataclasses import dataclass, field
from typing import List, Callable, Optional


# ═══════════════════ 基函数定义 ═══════════════════

@dataclass
class BasisSet:
    """一组基函数 {f₀(x), f₁(x), ..., fₙ(x)}"""
    name: str
    functions: List[Callable[[float], float]] = field(default_factory=list)
    # 自动加常数项 f(x)=1

    def __post_init__(self):
        if not any(f(1) == 1 and f(2) == 1 for f in self.functions):
            self.functions.append(lambda x: 1.0)  # 常数项

    def phi(self, x: float) -> list:
        return [f(x) for f in self.functions]

    def dim(self) -> int:
        return len(self.functions)

    @staticmethod
    def polynomial(max_degree: int = 3) -> "BasisSet":
        fs = [(lambda d: lambda x: x ** d)(i) for i in range(max_degree, 0, -1)]
        return BasisSet(name=f"多项式(deg≤{max_degree})", functions=fs)

    @staticmethod
    def fourier(n_harmonics: int = 2) -> "BasisSet":
        fs = []
        for k in [1/5, 1/3, 1/2, 1][:n_harmonics]:  # 低频优先
            fs.append((lambda k: lambda x: math.sin(k * x))(k))
            fs.append((lambda k: lambda x: math.cos(k * x))(k))
        return BasisSet(name=f"Fourier({n_harmonics}谐波)", functions=fs)

    @staticmethod
    def exponential(n_rates: int = 2) -> "BasisSet":
        rates = [0.05, 0.1, 0.2, 0.5][:n_rates]
        fs = [(lambda r: lambda x: math.exp(r * x))(r) for r in rates]
        fs.append(lambda x: x)
        return BasisSet(name=f"指数({n_rates}速率)", functions=fs)


# ═══════════════════ 基学习器 ═══════════════════

class BasisLearner:
    """单基函数 RLS: y = Σ aᵢ·fᵢ(x)"""

    def __init__(self, basis: BasisSet, forgetting: float = 0.995,
                 l2_lambda: float = 0.001):
        self.basis = basis
        self.dim = basis.dim()
        self.forgetting = forgetting
        self.l2_lambda = l2_lambda

        self.theta: List[float] = [0.0] * self.dim
        self.P: List[List[float]] = [
            [1000.0 if i == j else 0.0 for j in range(self.dim)]
            for i in range(self.dim)
        ]
        self.n_updates = 0
        self.r_squared = 0.0
        self.residual_std = 1.0

        # 历史 (用于 R² 计算)
        self._x_hist: List[float] = []
        self._y_hist: List[float] = []
        self._max_history = 200
        self._r2_peak = 0.0

    def update(self, x: float, y: float) -> float:
        phi = self.basis.phi(x)
        y_pred = sum(phi[i] * self.theta[i] for i in range(self.dim))
        error = y - y_pred

        # 崩溃检测: R² 从峰值坠落 > 80% → 重置协方差
        if self._r2_peak > 0.5 and self.r_squared < self._r2_peak * 0.2:
            self.P = [[1000.0 if i == j else 0.0 for j in range(self.dim)] for i in range(self.dim)]
            self._r2_peak = 0.0

        # RLS (with L2 decay)
        P_phi = [sum(self.P[i][j] * phi[j] for j in range(self.dim)) for i in range(self.dim)]
        phi_P_phi = sum(phi[i] * P_phi[i] for i in range(self.dim))
        denom = max(self.forgetting + phi_P_phi, 1e-8)
        K = [p / denom for p in P_phi]

        for i in range(self.dim):
            self.theta[i] = self.theta[i] * (1.0 - self.l2_lambda) + K[i] * error

        for i in range(self.dim):
            for j in range(self.dim):
                self.P[i][j] = (self.P[i][j] - K[i] * P_phi[j]) / self.forgetting

        self.n_updates += 1
        self._x_hist.append(x)
        self._y_hist.append(y)
        for h in [self._x_hist, self._y_hist]:
            if len(h) > self._max_history:
                h.pop(0)

        # R² (on recent data)
        if len(self._x_hist) >= 10:
            recent_n = min(50, len(self._x_hist))
            xs = self._x_hist[-recent_n:]
            ys = self._y_hist[-recent_n:]
            preds = [self.predict(xi) for xi in xs]
            ss_res = sum((p - yi) ** 2 for p, yi in zip(preds, ys))
            y_mean = sum(ys) / len(ys)
            ss_tot = sum((yi - y_mean) ** 2 for yi in ys) + 1e-8
            self.r_squared = max(0.0, 1.0 - ss_res / ss_tot)
            self.residual_std = math.sqrt(ss_res / recent_n) if recent_n > 0 else 1.0
            if self.r_squared > self._r2_peak:
                self._r2_peak = self.r_squared

        return error

    def predict(self, x: float) -> float:
        phi = self.basis.phi(x)
        return sum(phi[i] * self.theta[i] for i in range(self.dim))

    def formula(self) -> str:
        terms = []
        for i, a in enumerate(self.theta):
            if abs(a) < 1e-6:
                continue
            fname = getattr(self.basis.functions[i], '__name__', f'f{i}')
            if '<lambda>' in fname or 'lambda' in fname:
                fname = f"f{i}"
            terms.append(f"{a:+.4f}·{fname}")
        return "y = " + (" ".join(terms) if terms else "0")


# ═══════════════════ 元学习器 (Bayesian 选择) ═══════════════════

class MetaLearner:
    """多基函数管理: 同时跑多个 BasisLearner, 选出最优基。"""

    def __init__(self, bases: List[BasisSet] = None, switch_r2_gap: float = 0.05,
                 check_interval: int = 20):
        if bases is None:
            bases = [
                BasisSet.polynomial(3),
                BasisSet.fourier(2),
                BasisSet.exponential(2),
            ]
        self.learners = [BasisLearner(b) for b in bases]
        self.current_idx = 0  # 当前最优基的索引
        self.switch_r2_gap = switch_r2_gap
        self.check_interval = check_interval
        self._updates_since_check = 0
        self.switch_history: list[dict] = []

    @property
    def current(self) -> BasisLearner:
        return self.learners[self.current_idx]

    def update(self, x: float, y: float) -> dict:
        """喂入 (x,y), 所有基同步学习, 返回各基残差。"""
        results = {}
        for i, learner in enumerate(self.learners):
            err = learner.update(x, y)
            results[learner.basis.name] = err

        self._updates_since_check += 1
        if self._updates_since_check >= self.check_interval:
            self._select_best()
            self._updates_since_check = 0
        return results

    def _select_best(self):
        """选出 R² 最高的基, 必要时切换。"""
        best_idx = max(range(len(self.learners)),
                        key=lambda i: self.learners[i].r_squared)
        if best_idx != self.current_idx:
            curr_r2 = self.current.r_squared
            best_r2 = self.learners[best_idx].r_squared
            if best_r2 > curr_r2 + self.switch_r2_gap:
                old_name = self.current.basis.name
                self.current_idx = best_idx
                self.switch_history.append({
                    "from": old_name, "to": self.current.basis.name,
                    "r2_before": round(curr_r2, 4),
                    "r2_after": round(best_r2, 4),
                })

    def predict(self, x: float) -> float:
        return self.current.predict(x)

    def structure_gap(self, r2_threshold: float = 0.85) -> bool:
        """是否存在结构断层 (可被其他基更好地捕捉)"""
        curr = self.current
        if curr.n_updates < 15:
            return False
        best = max(l.r_squared for l in self.learners)
        return best > curr.r_squared + self.switch_r2_gap

    def summary(self) -> dict:
        rows = []
        for i, learner in enumerate(self.learners):
            star = "← SELECTED" if i == self.current_idx else ""
            rows.append({
                "basis": learner.basis.name,
                "r_squared": round(learner.r_squared, 4),
                "n_updates": learner.n_updates,
                "formula": learner.formula() if i == self.current_idx else "",
                "selected": i == self.current_idx,
            })
        return {
            "current": self.current.basis.name,
            "current_r2": round(self.current.r_squared, 4),
            "all": rows,
            "switches": self.switch_history,
        }
