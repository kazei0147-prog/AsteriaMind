"""
ActiveInferenceLayer — 主动推理增强 (AsteriaMind v3.2)

基于 Friston 自由能原理的认知架构增强。

核心概念在 AM 中的映射:
  Generative Model   → CognitiveStarMap (预测用户反馈)
  Prior Belief       → 边的当前信念 Beta(α, β)
  Posterior          → 贝叶斯更新后的信念
  Prediction Error   → 预测反馈 vs 实际反馈的 KL 散度
  Precision          → 信念的确定程度 (1/方差)
  Free Energy        → 惊讶度 + 复杂度 — 系统要最小化的量
  Active Inference   → 选择能最大程度降低不确定性的行动

不是被动更新——是主动选择该问什么。
"""
import math, time
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class BeliefEdge:
    """一条边的贝叶斯信念——Beta 分布"""
    subject: str
    predicate: str
    object: str
    # Beta(α, β): α=成功次数+1, β=失败次数+1
    alpha: float = 1.0    # 默认 Beta(1,1)=均匀分布
    beta_param: float = 1.0
    # 元数据
    total_evidence: int = 0
    prediction_errors: list[float] = field(default_factory=list)  # 历史预测误差
    last_update: float = 0.0
    # ★ v3.9 F17 (瓶颈三): 该边是否曾被 F15 预测想法源"预测过"
    #   预测被后续 confirmed 验证 → 挣回能量 (内在奖励, 可证伪)
    predicted: bool = False

    @property
    def mean(self) -> float:
        """信念期望值 = α/(α+β)"""
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def precision(self) -> float:
        """精确度 = α+β (越高越确定)"""
        return self.alpha + self.beta_param

    @property
    def uncertainty(self) -> float:
        """不确定性 = 1/precision"""
        p = self.precision
        return 1.0 / p if p > 0 else 1.0

    @property
    def variance(self) -> float:
        """方差 = αβ / ((α+β)²(α+β+1))"""
        a, b = self.alpha, self.beta_param
        total = a + b
        return (a * b) / (total * total * (total + 1)) if total > 0 else 0.25

    def update(self, observed_confirmed: bool, weight: float = 1.0):
        """
        贝叶斯更新: 观察到一个确认/纠正事件。

        确认 → α += weight
        纠正 → β += weight
        """
        if observed_confirmed:
            self.alpha += weight
        else:
            self.beta_param += weight
        self.total_evidence += 1
        self.last_update = time.time()

    def predict(self) -> tuple[bool, float]:
        """预测: 下一个观测会是 confirmed 还是 corrected? 置信度? """
        return self.mean > 0.5, self.mean

    def free_energy(self) -> float:
        """
        自由能 = 惊讶度 + 复杂度。

        对于 Beta 分布:
          - 惊讶度 ∝ -log(p(observation|belief))
          - 复杂度 ∝ KL(Beta(α,β) || Beta(1,1))  ← 距离先验的距离
        """
        # 复杂度: KL 散度 vs 均匀先验 Beta(1,1)
        a, b = self.alpha, self.beta_param
        if a < 0.01 or b < 0.01:
            return 10.0  # 极端情况

        # KL(Beta(a,b) || Beta(1,1)) 解析近似
        # 复杂度: 距离无信息先验的距离
        complexity = 0.0
        if a > 1:
            complexity += (a - 1) ** 2 / (2 * max(a, 0.1))
        if b > 1:
            complexity += (b - 1) ** 2 / (2 * max(b, 0.1))

        # 惊讶度: 预测误差的历史平均
        surprise = 0.0
        if self.prediction_errors:
            surprise = sum(abs(e) for e in self.prediction_errors[-5:]) / min(len(self.prediction_errors), 5)

        return complexity + surprise * 0.5

    def expected_information_gain(self) -> float:
        """
        信息增益期望——如果我去验证这条边，能减少多少不确定性？

        高不确定性 + 高精度潜力 = 高信息增益
        """
        return self.uncertainty * math.log(self.precision + 1)


class ActiveInferenceEngine:
    """
    主动推理引擎——不是被动接收反馈，是主动选择行动。

    功能:
      1. 维护 CognitiveStarMap 的贝叶斯信念层
      2. 计算每条边的自由能 + 信息增益
      3. 选择最小化自由能的行动 (该问什么问题 / 该验证什么假说)
    """

    def __init__(self, star_map=None):
        self.star_map = star_map
        self.belief_edges: dict[str, BeliefEdge] = {}  # key = "subj::pred::obj"

    def _edge_key(self, subj: str, pred: str, obj: str) -> str:
        return f"{subj}::{pred}::{obj}"

    def get_or_create_belief(self, subj: str, pred: str, obj: str) -> BeliefEdge:
        """获取或创建一条信念边"""
        key = self._edge_key(subj, pred, obj)
        if key not in self.belief_edges:
            self.belief_edges[key] = BeliefEdge(subj, pred, obj)
        return self.belief_edges[key]

    def update_from_feedback(self, subj: str, pred: str, obj: str, confirmed: bool):
        """
        收到用户反馈 → 贝叶斯更新对应边的信念。
        """
        edge = self.get_or_create_belief(subj, pred, obj)
        # 预测 vs 实际
        predicted, _ = edge.predict()
        error = abs(float(confirmed) - float(predicted))
        edge.prediction_errors.append(error)
        # 贝叶斯更新
        edge.update(confirmed)
        # ★ v3.9 F17 (瓶颈三): 预测被验证 → 内在挣回能量
        #   该边曾被 F15 预测想法源"预测过" + 本次确认 → 挣回 (预测兑现)
        #   设计原则 (可证伪): 预测可被未来证据推翻, 不是自我表扬
        if confirmed and edge.predicted and self.star_map:
            try:
                self.star_map.restore_energy(subj, obj, 0.08)
            except Exception:
                pass
            edge.predicted = False  # 一次预测兑现一次奖励
        # 同步写入星图
        if self.star_map:
            self.star_map.store(
                subj, pred, obj,
                "confirmed" if confirmed else "corrected",
                f"{subj}{pred}{obj}"
            )

    def perceive(self, subj: str, pred: str, obj: str) -> dict:
        """
        感知: 查询一条边的当前信念状态。

        返回: { belief, precision, uncertainty, free_energy }
        """
        edge = self.get_or_create_belief(subj, pred, obj)
        return {
            "belief": edge.mean,
            "prediction": edge.predict()[0],
            "precision": edge.precision,
            "uncertainty": edge.uncertainty,
            "free_energy": edge.free_energy(),
            "evidence_count": edge.total_evidence,
        }

    def choose_action(self, candidate_edges: list[tuple] = None,
                      top_k: int = 3) -> list[tuple]:
        """
        BudgetContest — 主动推理 + 成本约束。

        Score = (uncertainty_reduction × importance) / interaction_cost

        不是"哪个信息增益最大"
        而是"哪个行动性价比最高"
        """
        if candidate_edges is None:
            if self.star_map:
                candidate_edges = []
                for row in self.star_map.conn.execute(
                    "SELECT subj, pred, obj FROM cognitive_traces GROUP BY subj, pred, obj"
                ):
                    candidate_edges.append((row[0], row[1], row[2]))

        if not candidate_edges:
            return []

        scored = []
        for subj, pred, obj in candidate_edges:
            edge = self.get_or_create_belief(subj, pred, obj)
            ig = edge.expected_information_gain()
            fe = edge.free_energy()

            # 行动成本: 不确定的边需要更多交互轮次验证
            cost = 1.0 + edge.uncertainty * 3.0

            # 重要度: 共现次数多的边更重要
            importance = math.log(edge.precision + 2)

            # BudgetContest 得分
            score = (ig * importance) / cost

            scored.append((subj, pred, obj, ig, fe, score, edge.uncertainty, edge.mean))

        scored.sort(key=lambda x: -x[5])
        return [(s[0], s[1], s[2], s[3], s[5]) for s in scored[:top_k]]

    def most_uncertain_edges(self, top_k: int = 5) -> list[dict]:
        """
        找出 AM 最不确定的边——应该主动向用户确认。
        """
        edges = []
        for key, edge in self.belief_edges.items():
            if edge.total_evidence > 0:  # 有数据但不确定的
                edges.append({
                    "subj": edge.subject, "pred": edge.predicate, "obj": edge.object,
                    "uncertainty": edge.uncertainty,
                    "mean": edge.mean,
                    "free_energy": edge.free_energy(),
                    "evidence": edge.total_evidence,
                })
        edges.sort(key=lambda e: -e["uncertainty"])
        return edges[:top_k]

    def plan_actions(self, candidate_edges: list[tuple] = None,
                     top_k: int = 3) -> list[dict]:
        """
        Active Inference 行动规划 —— 不是"哪个得分高"，
        而是"下一步该做什么"。

        用 choose_action() 的 BudgetContest 评分，映射为可执行的行动类型:

          Action Type    Condition                          Example
          ─────────────────────────────────────────────────────────
          "verify"       高不确定性 + 有证据但矛盾             向用户确认
          "explore"      高信息增益 + 低证据                   搜索网络
          "suggest"      中高置信度 + 有证据                   主动告知相关知识
          "clarify"      极高不确定性 + 有证据                 请求用户澄清
          "observe"      低证据 + 低信息增益                   静默观察

        返回 list[dict]:
          { action_type, suggestion, subj, pred, obj,
            score, info_gain, uncertainty, belief, evidence_count }
        """
        scored = self.choose_action(candidate_edges, top_k=max(top_k * 2, 5))
        if not scored:
            return []

        plans = []
        for subj, pred, obj, info_gain, score in scored:
            edge = self.get_or_create_belief(subj, pred, obj)
            uncertainty = edge.uncertainty
            mean = edge.mean
            evidence = edge.total_evidence

            # ── 行动分类 ──
            if uncertainty > 0.75 and evidence >= 2:
                # 有证据但极不确定 → 证据可能矛盾, 需要澄清
                action_type = "clarify"
                suggestion = f"核实「{subj} {pred} {obj}」——证据不一致"
            elif uncertainty > 0.55 and evidence >= 1:
                # 有证据但仍不确定 → 主动验证
                action_type = "verify"
                suggestion = f"确认「{subj}」是否「{pred} {obj}」"
            elif evidence == 0 and info_gain > 0.15:
                # 完全未知 + 信息增益高 → 探索
                action_type = "explore"
                suggestion = f"探索「{subj}」的「{pred}」关系"
            elif mean > 0.6 and evidence >= 2:
                # 高置信 + 有证据 → 可主动分享
                action_type = "suggest"
                suggestion = f"可告知: {subj} {pred} {obj}"
            elif evidence == 0 and info_gain <= 0.15:
                # 未知且收益低 → 静默观察
                action_type = "observe"
                suggestion = f"静默观察「{subj} {pred} {obj}」"
            else:
                # 默认: 中等不确定性 → 验证
                action_type = "verify"
                suggestion = f"验证「{subj} {pred} {obj}」"

            plans.append({
                "subj": subj, "pred": pred, "obj": obj,
                "action_type": action_type,
                "suggestion": suggestion,
                "score": round(score, 4),
                "info_gain": round(info_gain, 4),
                "uncertainty": round(uncertainty, 4),
                "belief": round(mean, 4),
                "evidence_count": evidence,
            })

        # 按得分降序
        plans.sort(key=lambda p: -p["score"])
        return plans[:top_k]
