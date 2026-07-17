"""
CrossValidator — 方案 B 静默期交叉验证 (Anchor 2)

轮询式旁观者机制：每轮抽一个 learner 当"旁观者"——
照常 propose 但不参与共识辩论、不 learn()，纯记录其原始信念预测误差。
为"共识是帮了还是拖了"提供因果隔离的对照基线。
"""


class CrossValidator:
    """轮询式交叉验证器。"""

    def __init__(self):
        self.silent_errors: dict[str, list[float]] = {}
        self.active_errors: dict[str, list[float]] = {}
        self._round = 0
        self._observer: str | None = None

    @property
    def observer(self) -> str | None:
        return self._observer

    def select_observer(self, learner_ids: list[str]) -> str:
        """轮询选取本轮旁观者（不参与共识、不 learn()）。"""
        self._observer = learner_ids[self._round % len(learner_ids)]
        self._round += 1
        return self._observer

    def record_silent(self, learner_id: str, error: float):
        """记录旁观时的原始信念预测误差（|proposal - ground_truth|）。"""
        self.silent_errors.setdefault(learner_id, []).append(error)

    def record_active(self, learner_id: str, error: float):
        """记录活跃参与时的原始信念预测误差。"""
        self.active_errors.setdefault(learner_id, []).append(error)

    def diagnosis(self) -> list[dict]:
        """产出各 learner 的诊断报告。

        返回 list[dict], 每条含:
          learner, silent_err (均值), active_err (均值), ratio, diagnosis

        diagnosis 标签:
          - "independent":       静默 ≈ 活跃 → 自己会，共识没拖也没奶
          - "consensus_drags":   静默 < 活跃  → 共识在拖累它 ⚠️
          - "free_rider":        静默 > 活跃  → 搭便车
          - "insufficient_data": 无足够数据
        """
        rows = []
        for lid in self.silent_errors:
            s_err = self._mean(self.silent_errors.get(lid, []))
            a_err = self._mean(self.active_errors.get(lid, []))
            if a_err > 0 and s_err > 0:
                ratio = s_err / a_err
                if ratio < 0.9:
                    tag = "consensus_drags"
                elif ratio > 1.1:
                    tag = "free_rider"
                else:
                    tag = "independent"
            else:
                ratio = 0.0
                tag = "insufficient_data"
            rows.append({
                "learner": lid,
                "silent_err": s_err,
                "active_err": a_err,
                "ratio": ratio,
                "diagnosis": tag,
            })
        return sorted(rows, key=lambda r: r["ratio"])

    @staticmethod
    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0
