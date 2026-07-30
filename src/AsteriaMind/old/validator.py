"""
CrossValidator — 方案 B 静默期交叉验证 + 隔离状态机 (Anchor 2)

轮询式旁观者 + 动态隔离：
- 正常：每轮抽一个 learner 当旁观者，不参与共识、不 learn()
- 隔离触发：任一 learner 的静默/活跃误差比持续超过阈值 → 进入隔离
- 隔离期间：被隔离 learner 始终静默（不从环境学习也不参与共识），
  其他 learner 在它们之间正常轮询旁观者
- 恢复：隔离期满后，若近期比恢复至阈值以下则释放
"""


class CrossValidator:
    """轮询式交叉验证器 + 隔离状态机。"""

    def __init__(
        self,
        isolation_threshold: float = 2.0,
        isolation_sustain: int = 3,
        isolation_duration: int = 20,
        recovery_threshold: float = 1.5,
    ):
        # ── 误差追踪 ──
        self.silent_errors: dict[str, list[float]] = {}
        self.active_errors: dict[str, list[float]] = {}
        self._round = 0
        self._observer: str | None = None

        # ── 隔离参数 ──
        self.isolation_threshold = isolation_threshold
        self.isolation_sustain = isolation_sustain
        self.isolation_duration = isolation_duration
        self.recovery_threshold = recovery_threshold

        # ── 隔离状态 ──
        self._isolated: set[str] = set()
        self._ratio_streak: dict[str, int] = {}       # 连续超过阈值的次数
        self._isolation_counter: dict[str, int] = {}  # 已隔离的轮数
        self._isolation_history: list[dict] = []       # [{learner, action, round, ratio}]

    # ── 观察者轮询 ──

    @property
    def observer(self) -> str | None:
        return self._observer

    def select_observer(self, learner_ids: list[str]) -> str:
        """从给定列表中轮询选取本轮旁观者。"""
        if not learner_ids:
            return ""
        self._observer = learner_ids[self._round % len(learner_ids)]
        self._round += 1
        return self._observer

    # ── 误差记录（方案 B） ──

    def record_silent(self, learner_id: str, error: float):
        """记录静默时的预测误差。"""
        self.silent_errors.setdefault(learner_id, []).append(error)

    def record_active(self, learner_id: str, error: float):
        """记录活跃参与时的预测误差。"""
        self.active_errors.setdefault(learner_id, []).append(error)

    # ── 隔离状态机 ──

    def is_isolated(self, learner_id: str) -> bool:
        return learner_id in self._isolated

    def get_isolated(self) -> set[str]:
        return self._isolated.copy()

    def evaluate_isolation(self) -> list[dict]:
        """每轮讨论后调用一次。返回本轮隔离动作列表。

        返回 list[dict], 每条:
          {learner, action: 'isolate'|'release'|'keep'|'none', ratio}
        """
        events = []
        for lid in set(self.silent_errors.keys()) | set(self.active_errors.keys()):
            s = self._mean(self.silent_errors.get(lid, []))
            a = self._mean(self.active_errors.get(lid, []))
            ratio = s / a if (a > 0 and s > 0) else 0.0

            if lid in self._isolated:
                # ── 隔离中 → 计轮、检查释放条件 ──
                self._isolation_counter[lid] = self._isolation_counter.get(lid, 0) + 1
                if self._isolation_counter[lid] >= self.isolation_duration:
                    recent = self._recent_silent(lid, self.isolation_duration)
                    if recent > 0 and a > 0 and (recent / a) < self.recovery_threshold:
                        self._isolated.discard(lid)
                        self._isolation_counter[lid] = 0
                        self._isolation_history.append({
                            "learner": lid, "action": "release",
                            "round": self._round, "ratio": recent / a,
                        })
                        events.append({"learner": lid, "action": "release", "ratio": recent / a})
                    else:
                        # 已经隔离过一轮但未恢复 → 重置计数器再观察
                        self._isolation_counter[lid] = 0
                        events.append({"learner": lid, "action": "keep", "ratio": ratio})
            else:
                # ── 正常 → 检查是否应隔离 ──
                if ratio > self.isolation_threshold:
                    self._ratio_streak[lid] = self._ratio_streak.get(lid, 0) + 1
                    if self._ratio_streak[lid] >= self.isolation_sustain:
                        self._isolated.add(lid)
                        self._isolation_counter[lid] = 0
                        self._ratio_streak[lid] = 0
                        self._isolation_history.append({
                            "learner": lid, "action": "isolate",
                            "round": self._round, "ratio": ratio,
                        })
                        events.append({"learner": lid, "action": "isolate", "ratio": ratio})
                else:
                    self._ratio_streak[lid] = 0

        return events

    def _recent_silent(self, learner_id: str, n: int) -> float:
        vals = self.silent_errors.get(learner_id, [])[-n:]
        return self._mean(vals) if vals else 0.0

    # ── 诊断报告 ──

    def diagnosis(self) -> list[dict]:
        """产出各 learner 的诊断报告（含隔离状态）。"""
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

            # 隔离子项
            isolated = lid in self._isolated
            isolation_rounds = self._isolation_counter.get(lid, 0)
            iso_events = [e for e in self._isolation_history if e["learner"] == lid]

            rows.append({
                "learner": lid,
                "silent_err": s_err,
                "active_err": a_err,
                "ratio": ratio,
                "diagnosis": tag,
                "isolated": isolated,
                "isolation_rounds": isolation_rounds,
                "isolation_history": iso_events,
            })
        return sorted(rows, key=lambda r: r["ratio"])

    def isolation_summary(self) -> list[dict]:
        return self._isolation_history

    # ── 辅助 ──

    @staticmethod
    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0
