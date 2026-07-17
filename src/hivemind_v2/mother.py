"""
母模块 - HiveMind 2.3 决策中心

v2.3 重构: 母模块从"传话筒"升级为真正的决策者。

旧版: learner.propose() → evaluator.full_discussion() → 输出数字
新版: Mother 读取所有推理链 → 形成自己的判断 → 做出决策 → 向 Learner 反馈

核心原则:
- Learner 是大脑（提供推理），Mother 是决策者（综合判断）
- Mother 必须理解 WHY，不只是 WHAT
- 决策后向每个 Learner 解释为什么采纳/拒绝了它的提案
"""
import random
import logging
from typing import List, Dict, Optional, Tuple
from collections import deque

logger = logging.getLogger("hivemind_v2.orchestrator")


class Decision:
    """母模块的一次决策记录"""
    def __init__(self):
        self.consensus: float = 0.0
        self.confidence: float = 0.0
        self.reasoning: str = ""
        self.primary_influence: str = ""      # 影响最大的 Learner
        self.dissenting_view: Optional[str] = None  # 少数派观点
        self.reservations: List[str] = []     # 保留意见
        self.learner_feedback: Dict[str, str] = {}  # 给每个 Learner 的反馈


class MotherMind:
    """
    母模块 — 决策者。

    她不直接观察外部数据（那由 Learner 做），而是:
    1. 读取所有 Learner 的推理链
    2. 基于信任历史 + 论证质量 + 一致性 综合判断
    3. 做出最终决策
    4. 向 Learner 解释决定
    """

    def __init__(
        self,
        debate_rounds: int = 2,
        history_depth: int = 50,
    ):
        self.debate_rounds = debate_rounds
        self.history_depth = history_depth

        # 决策历史 — Mother 自己的记忆
        self.decision_history: deque = deque(maxlen=history_depth)

        # 对每个 Learner 的"印象" — 不仅仅是 trust 数字
        # 而是: 在什么场景下他靠谱 / 不靠谱
        self.impressions: Dict[str, dict] = {}

        self.decision_count = 0

    # ──────────── 核心: 理解 Learner ────────────

    def _read_learner(self, learner, chain, trust_score: float) -> dict:
        """
        Mother 阅读一个 Learner 的提案——不只读数字，
        而是提取"这个 Learner 在说什么、凭什么这么说、可不可信"。
        """
        track = learner.track_record()
        mu = learner.belief.mu
        sigma = learner.belief.sigma

        # Mother 对该 Learner 的印象
        imp = self.impressions.get(learner.learner_id, {
            "trust_trend": [],      # 信任变化趋势
            "best_at": "unknown",   # 擅长什么场景
            "consistency": 1.0,     # 一致性评分
        })

        # 推理链质量
        has_data = len(chain.recent_window) > 0
        chain_strength = chain.strength() if hasattr(chain, 'strength') else 0.5

        # Mother 的综合可信度 = trust × track × 论证质量
        credibility = (
            0.4 * max(0.01, trust_score) +
            0.3 * max(0.01, track) +
            0.3 * chain_strength
        )

        return {
            "learner_id": learner.learner_id,
            "proposal": chain.proposal_value,
            "credibility": credibility,
            "trust": trust_score,
            "track": track,
            "mu": mu,
            "sigma": sigma,
            "chain_strength": chain_strength,
            "summary": chain.summary() if hasattr(chain, 'summary') else str(chain.proposal_value),
            "impression": imp,
        }

    # ──────────── 核心: 形成判断 ────────────

    def _form_judgment(
        self, readings: List[dict], current_obs: float
    ) -> Decision:
        """
        Mother 综合所有 Learner 的提案，形成自己的判断。

        不是加权平均——是:
        1. 找出最有说服力的观点
        2. 找出值得关注的少数派
        3. 基于信任 + 论证 + 历史一致性做出决策
        """
        decision = Decision()

        if not readings:
            decision.consensus = current_obs
            decision.reasoning = "无 Learner 提案，直接采纳观测值"
            return decision

        # 按可信度排序
        ranked = sorted(readings, key=lambda r: r["credibility"], reverse=True)

        # ── 找出主导观点 ──
        top = ranked[0]
        decision.primary_influence = top["learner_id"]

        # ── 共识 = 可信度加权，而不是简单平均 ──
        total_cred = sum(r["credibility"] for r in readings)
        if total_cred > 0:
            weighted_sum = sum(r["proposal"] * r["credibility"] for r in readings)
            decision.consensus = weighted_sum / total_cred
        else:
            decision.consensus = sum(r["proposal"] for r in readings) / len(readings)

        # ── 置信度: 取决于排名靠前的 Learner 的一致程度 ──
        top_three = ranked[:3]
        props = [r["proposal"] for r in top_three]
        spread = max(props) - min(props)
        consensus_range = max(abs(decision.consensus), 1.0)
        decision.confidence = max(0.0, 1.0 - spread / consensus_range)

        # ── 少数派观点 ──
        bottom = ranked[-1]
        if bottom["learner_id"] != top["learner_id"]:
            gap = abs(top["proposal"] - bottom["proposal"])
            if gap > 2.0:  # 分歧显著
                decision.dissenting_view = (
                    f"{bottom['learner_id']} 提案 {bottom['proposal']:.1f} "
                    f"(可信度 {bottom['credibility']:.2f})，与共识偏差 {gap:.1f}"
                )

        # ── 保留意见 ──
        if decision.confidence < 0.6:
            decision.reservations.append(
                f"决策置信度偏低 ({decision.confidence:.2f})，Learner 之间分歧较大"
            )
        if spread > 5.0:
            decision.reservations.append(
                f"前三名 Learner 提案跨度为 {spread:.1f}，需要更多数据验证"
            )

        # ── 构建推理说明 ──
        decision.reasoning = (
            f"基于 {len(readings)} 个 Learner 的提案，"
            f"由 {top['learner_id']} 主导 (可信度 {top['credibility']:.2f})。"
            f"共识值 = {decision.consensus:.2f}，置信度 = {decision.confidence:.2f}。"
        )
        if decision.dissenting_view:
            decision.reasoning += f" 少数派观点: {decision.dissenting_view}。"

        # ── 给每个 Learner 的个性化反馈 ──
        for r in readings:
            deviation = abs(r["proposal"] - decision.consensus)
            if r is top:
                decision.learner_feedback[r["learner_id"]] = (
                    f"你的提案被采纳为主导意见。你最近的可信度为 {r['credibility']:.2f}。"
                )
            elif deviation < 2.0:
                decision.learner_feedback[r["learner_id"]] = (
                    f"你的提案 (偏差 {deviation:.1f}) 与共识接近，"
                    f"建议: 继续保持当前推理策略。"
                )
            else:
                direction = "偏高" if r["proposal"] > decision.consensus else "偏低"
                decision.learner_feedback[r["learner_id"]] = (
                    f"你的提案 {direction} {deviation:.1f}。你的 μ={r['mu']:.2f}，"
                    f"建议: {'缩小窗口关注近期趋势' if r['sigma'] < 5 else '加大窗口减少噪声'}。"
                )

        return decision

    # ──────────── 主入口: 一轮完整的深思熟虑 ────────────

    def deliberate(
        self,
        learners,
        chains,
        trust,
        current_obs: float,
    ) -> Decision:
        """
        母模块主持一轮"深思熟虑":

        1. 阅读所有 Learner 的提案
        2. 形成自己的判断
        3. 向 Learner 反馈
        4. 更新对每个 Learner 的印象
        5. 返回决策
        """
        # Step 1: 阅读
        readings = []
        for learner, chain in zip(learners, chains):
            trust_score = trust.get(learner.learner_id) if hasattr(trust, 'get') else 0.5
            reading = self._read_learner(learner, chain, trust_score)
            readings.append(reading)

        # Step 2: 判断
        decision = self._form_judgment(readings, current_obs)

        # Step 3: 反馈 — 通过 Learner 的 learn() 方法传递
        for learner, chain in zip(learners, chains):
            feedback = decision.learner_feedback.get(learner.learner_id, "")
            # 将反馈附加到 Learner 的内部状态（如果支持）
            if hasattr(learner, 'last_feedback'):
                learner.last_feedback = feedback

        # Step 4: 更新印象
        for r in readings:
            lid = r["learner_id"]
            old_imp = self.impressions.get(lid, {"trust_trend": [], "best_at": "unknown"})
            old_imp["trust_trend"].append(r["trust"])
            if len(old_imp["trust_trend"]) > 20:
                old_imp["trust_trend"] = old_imp["trust_trend"][-20:]
            # 判断 Learner 擅长什么：看最近 proposal 的方向
            recent_mu = r["mu"]
            if recent_mu > 2:
                old_imp["best_at"] = "detecting_highs"
            elif recent_mu < -2:
                old_imp["best_at"] = "detecting_lows"
            else:
                old_imp["best_at"] = "balanced"
            self.impressions[lid] = old_imp

        # Step 5: 记录
        self.decision_history.append(decision)
        self.decision_count += 1

        return decision

    def formulate_query(self, learners, function_learner=None) -> str:
        """
        v2.7: 自动生成搜索词。
        v2.8: 支持结构断层搜索策略。
        """
        # v2.8: 结构断层 → 搜规律而非最新值
        if function_learner is not None and function_learner.structure_gaps > 0:
            a, b = function_learner.theta[0], function_learner.theta[1]
            return (
                f"trend analysis linear model y={a:.2f}x+{b:.2f} "
                f"structure change detection latest data 2026"
            )

        # 常规: 从 Learner ScaleTracker 推断数据域
        avg_location = 0
        n = 0
        for l in learners:
            if hasattr(l, 'scale_tracker') and l.scale_tracker.n_obs > 0:
                avg_location += l.scale_tracker.location
                n += 1
        if n == 0:
            return "latest global data reading current value"

        avg_location /= n
        most_uncertain = max(learners, key=lambda l: l.belief.sigma)

        if 400 < avg_location < 450:
            domain = "Mauna Loa CO2 atmospheric concentration"
        elif avg_location > 1000:
            domain = "current value latest reading"
        elif avg_location < 1:
            domain = "latest measurement current reading"
        else:
            domain = "latest reading current data point"

        return (
            f"{domain} ppm weekly 2026 "
            f"(uncertainty:{most_uncertain.belief.sigma:.0f})"
        )

    def summary(self) -> dict:
        """返回母模块的自我认知摘要"""
        return {
            "total_decisions": self.decision_count,
            "impressions": {
                lid: {
                    "best_at": imp["best_at"],
                    "trust_trend": imp["trust_trend"][-5:] if imp["trust_trend"] else [],
                }
                for lid, imp in self.impressions.items()
            },
            "last_confidence": (
                self.decision_history[-1].confidence
                if self.decision_history else 0
            ),
        }
