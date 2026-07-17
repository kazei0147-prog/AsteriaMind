"""
Mother-Learner 反馈适配器 (v2.10)

将 Mother 的自然语言反馈转译为 Learner 可执行的指令。
三条路径 (按安全性排序):
  1. 切 Student-t 稳健似然 (最安全, 纯数学模型切换)
  2. 窗口调整 (改一个 int, 可回滚)
  3. 学习率临时加倍 (有衰减, 不可累积)
"""
from collections import defaultdict


class MotherAdapter:
    """监听 Mother 的决策, 将反馈转译为 Learner 指令。"""

    def __init__(self, rate_limit: int = 5):
        self.rate_limit = rate_limit  # 每个 learner 的建议冷却轮数
        self._last_action: dict[str, int] = defaultdict(int)  # learner → 最后动它的轮次
        self.log: list[dict] = []

    def apply(
        self,
        decision,
        learners,
        round_num: int,
    ) -> list[dict]:
        """解析 Decision.learner_feedback, 执行有效建议。

        返回本轮的动作日志。"""
        actions = []
        for lid, feedback in decision.learner_feedback.items():
            learner = self._find(learners, lid)
            if not learner:
                continue

            # 冷却检查: 不对同一个 learner 频繁修改
            if round_num - self._last_action.get(lid, -self.rate_limit) < self.rate_limit:
                continue

            # ── 存储反馈 ──
            learner.last_feedback = feedback

            # ── 路径 1: 切换 Student-t (最安全) ──
            if learner.belief.sigma > 6.0 and not learner.belief.robust_likelihood:
                learner.set_robust(True)
                actions.append({"learner": lid, "action": "switch_robust",
                                "sigma": round(learner.belief.sigma, 1),
                                "feedback": feedback[:60]})
                self._last_action[lid] = round_num

            # ── 路径 2: 窗口调整 ──
            if "加大窗口" in feedback:
                learner.adjust_window(+3)
                actions.append({"learner": lid, "action": "window_up",
                                "new_window": learner.window_size,
                                "feedback": feedback[:60]})
                self._last_action[lid] = round_num
            elif "缩小窗口" in feedback:
                learner.adjust_window(-2)
                actions.append({"learner": lid, "action": "window_down",
                                "new_window": learner.window_size,
                                "feedback": feedback[:60]})
                self._last_action[lid] = round_num

            # ── 路径 3: 学习率加速 ──
            if ("偏高" in feedback or "偏低" in feedback) and learner.learning_rate_boost < 1.5:
                learner.boost_learning(2.0)
                actions.append({"learner": lid, "action": "boost_lr",
                                "mu": round(learner.belief.mu, 2),
                                "feedback": feedback[:60]})
                self._last_action[lid] = round_num

        self.log.extend(actions)
        return actions

    @staticmethod
    def _find(learners, lid):
        for l in learners:
            if l.learner_id == lid:
                return l
        return None
