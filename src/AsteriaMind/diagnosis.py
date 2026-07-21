"""
诊断引擎 — 从"发现错了"到"知道为什么错了"

层级:
  观察 → 发现错误 → 提出原因 → 设计验证 → 选择原因 → 修正

三个假说:
  A: 函数形式变了  → 残差与 x 相关 (结构性残差)
  B: 噪声变大了    → 残差标准差跳变 (无结构性残差)
  C: 数据分布变了  → 外推区误差大, 内插区误差小
"""
import math
from typing import List


class DiagnosticEngine:
    """多假说诊断 — 把"R²掉了"升级为"R²掉了, 因为..." """

    def __init__(self, history_window: int = 50):
        self.history_window = history_window

        # 残差追踪
        self._residuals: List[float] = []
        self._x_values: List[float] = []
        self._r2_history: List[float] = []

        # 诊断记录
        self.diagnosis_log: list[dict] = []

    def observe(self, x: float, residual: float, r2: float):
        """每轮喂入: x值、当前模型的残差、R²"""
        self._x_values.append(x)
        self._residuals.append(residual)
        self._r2_history.append(r2)

        for buf in [self._x_values, self._residuals, self._r2_history]:
            if len(buf) > self.history_window * 3:
                buf.pop(0)

    def detect(self) -> bool:
        """是否检测到异常?"""
        if len(self._r2_history) < 20:
            return False
        recent = self._r2_history[-10:]
        older = self._r2_history[-30:-10]
        if not older:
            return False
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        return recent_avg < older_avg * 0.7  # R² 跌超 30%

    def diagnose(self) -> dict:
        """提出三个假说并给出证据得分。"""
        n = min(self.history_window, len(self._x_values))
        if n < 10:
            return {"error": "insufficient_data"}

        xs = self._x_values[-n:]
        res = self._residuals[-n:]
        half = n // 2
        res_old = res[:half]
        res_new = res[half:]

        # ── 假说 A: 函数形式变了 (残差与 x 相关) ──
        a_score = self._residual_correlation(xs, res)

        # ── 假说 B: 噪声变大 (残差 std 跳变, 但无结构) ──
        std_old = self._std(res_old)
        std_new = self._std(res_new)
        b_score = (std_new / max(std_old, 1e-6) - 1.0) * (1.0 - a_score)
        b_score = max(0.0, min(1.0, b_score))

        # ── 假说 C: 数据分布变了 (外推误差 vs 内插) ──
        c_score = self._domain_shift_score(xs, res)

        return {
            "hypothesis_A": {
                "label": "函数形式变化",
                "score": round(a_score, 3),
                "metric": "残差-x相关性",
                "evidence": f"r={a_score:.3f}",
            },
            "hypothesis_B": {
                "label": "噪声增大",
                "score": round(b_score, 3),
                "metric": "残差标准差跳变",
                "evidence": f"σ {std_old:.2f}→{std_new:.2f}",
            },
            "hypothesis_C": {
                "label": "数据分布偏移",
                "score": round(c_score, 3),
                "metric": "内外域误差比",
                "evidence": f"偏移度={c_score:.3f}",
            },
        }

    def select_cause(self) -> dict:
        """选出最可能的假说"""
        d = self.diagnose()
        if "error" in d:
            return d
        best = max([d["hypothesis_A"], d["hypothesis_B"], d["hypothesis_C"]],
                    key=lambda h: h["score"])
        self.diagnosis_log.append(best)
        return best

    # ── 内部计算 ──

    def _residual_correlation(self, xs, res) -> float:
        """残差与 x 的绝对相关度 (0=无相关, 1=强相关)"""
        n = len(xs)
        mx = sum(xs) / n
        mr = sum(res) / n
        cov = sum((xs[i] - mx) * (res[i] - mr) for i in range(n))
        sx = math.sqrt(sum((x - mx)**2 for x in xs) / n)
        sr = math.sqrt(sum((r - mr)**2 for r in res) / n)
        if sx < 1e-6 or sr < 1e-6:
            return 0.0
        r = abs(cov / (n * sx * sr))
        return min(1.0, r)

    def _domain_shift_score(self, xs, res) -> float:
        """检测是否外推区误差大"""
        n = len(xs)
        if n < 10:
            return 0.0
        mid = n // 2
        x_old, x_new = xs[:mid], xs[mid:]
        r_old, r_new = res[:mid], res[mid:]
        # 如果新区域 x 明显偏离旧区域 → 域偏移
        old_range = max(x_old) - min(x_old)
        new_mean = sum(x_new) / len(x_new)
        old_mean = sum(x_old) / len(x_old)
        shift = abs(new_mean - old_mean) / max(old_range, 1e-6)
        # 新区域残差是否明显更大
        err_ratio = (self._std(r_new) / max(self._std(r_old), 1e-6)) if len(r_new) > 2 else 1.0
        return min(1.0, shift * 0.5 + max(0, err_ratio - 1) * 0.5)

    @staticmethod
    def _std(vals: list) -> float:
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m)**2 for v in vals) / len(vals))


class ExperimentDesigner:
    """根据诊断结果, 设计针对性的验证实验"""

    def design(self, cause: dict) -> dict:
        label = cause.get("label", "")
        score = cause.get("score", 0)

        if "函数形式" in label and score > 0.3:
            return {
                "action": "test_new_basis",
                "description": "在更大 x 范围采样, 测试多项式以外基函数",
                "params": {"n_samples": 20, "x_range": (0, 25)},
            }
        elif "噪声" in label and score > 0.3:
            return {
                "action": "test_noise_level",
                "description": "密集采样少量点, 估计局部噪声水平",
                "params": {"n_samples": 30, "x_range": (5, 15)},
            }
        elif "分布偏移" in label and score > 0.3:
            return {
                "action": "test_boundary",
                "description": "在已知区域边界额外采样, 验证外推能力",
                "params": {"n_samples": 15, "x_range": (15, 25)},
            }
        else:
            return {
                "action": "default_explore",
                "description": "全域随机采样, 增加数据多样性",
                "params": {"n_samples": 20, "x_range": (0, 20)},
            }
