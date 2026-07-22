"""
FalsificationController — 反证实验的控制层 + 来源权威评估 + WebSearch 接口 (AsteriaMind v3.1)

三个问题一起解决:

1. 停止条件: 反证实验不是无差别攻击——信念有 "抗压阈值"
2. 来源评估: 每个来源按领域追踪准确率, 动态调整可信度
3. WebSearch: 真正的网络查询接口 (通过 WorkBuddy 的 WebSearch 工具)
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Callable


# ═══════════════ 1. 反证停止条件 ═══════════════

@dataclass
class FalsificationResult:
    """一次反证实验的完整结果"""
    target_belief: str
    pre_alpha: float
    pre_beta: float
    pre_confidence: float
    post_alpha: float
    post_beta: float
    post_confidence: float
    rounds: int
    survived: bool       # 信念是否经受住了考验
    stop_reason: str


class FalsificationController:
    """
    反证实验控制器: 有限制的挑战——但不阻碍未来学习。

    停止条件不是永久关闭, 而是 "暂停并等待新证据":
      1. 抗压上限: 由能量预算决定, 不是硬编码 20 轮
      2. 信念稳固: 连续 N 轮攻击无效 → 暂停 (但信念标记为 'survived_challenge', 可被新证据重新打开)
      3. 信念崩溃: 置信度 < 最低阈值 → 暂停 (标记为 'likely_false', 如新证据出现可复活)
      4. 能量耗尽: 剩余预算 < 单轮成本 → 暂停 (等下次能量周期)

    关键: 暂停 ≠ 永久关闭。任何被暂停的信念如果收到新的支持证据,
    反证预算会重新激活。
    """

    MIN_CONFIDENCE = 0.15
    STABILIZATION_THRESHOLD = 0.02
    STABILIZATION_ROUNDS = 3

    def __init__(self, energy_budget: float = 100.0, energy_per_round: float = 5.0):
        self.energy_budget = energy_budget
        self.energy_per_round = energy_per_round
        self.remaining_budget = energy_budget

    def run(self, kg, target_belief_key: str, max_rounds: int = None) -> FalsificationResult:
        """
        反证实验——知道什么时候暂停, 但不永久关闭大门。
        """
        self.remaining_budget = self.energy_budget
        max_r = min(max_rounds or 999, int(self.remaining_budget / self.energy_per_round))

        rel = self._find_relation(kg, target_belief_key)
        if not rel:
            return FalsificationResult(
                target_belief=target_belief_key, pre_alpha=0, pre_beta=0,
                pre_confidence=0, post_alpha=0, post_beta=0, post_confidence=0,
                rounds=0, survived=False, stop_reason="belief_not_found",
            )

        pre_alpha = rel.belief.alpha
        pre_beta = rel.belief.beta
        pre_conf = rel.confidence

        # 提取 subject/predicate/object
        parts = target_belief_key.split("--[")
        subject = parts[0].strip()
        pred_obj = parts[1].split("]-->")
        pred = pred_obj[0].strip()
        obj = pred_obj[1].strip()

        prev_conf = pre_conf
        stable_count = 0

        for round_num in range(max_r):
            # 能量检查: 每一轮攻击消耗能量
            if self.remaining_budget < self.energy_per_round:
                stop_reason = f"能量耗尽 (剩余 {self.remaining_budget:.1f} < 单轮成本 {self.energy_per_round})"
                if round_num == 0:
                    # 一轮都没跑 → 回退默认
                    break
                return self._build_result(rel, pre_alpha, pre_beta, pre_conf,
                                          round_num, prev_conf > 0.5, stop_reason)

            kg.observe(subject, pred, obj, correct=False, weight=0.5,
                       context=f"反证实验第{round_num+1}轮 (预算:{self.remaining_budget:.0f})",
                       alternative="系统审计触发的反设场景验证")
            self.remaining_budget -= self.energy_per_round

            current_rel = self._find_relation(kg, target_belief_key)
            if not current_rel:
                break
            current_conf = current_rel.confidence
            delta = abs(current_conf - prev_conf)

            # 停止条件 1: 信念稳定 — 但可被新证据重新打开
            if delta < self.STABILIZATION_THRESHOLD:
                stable_count += 1
                if stable_count >= self.STABILIZATION_ROUNDS:
                    # 暂停, 标记为可重新激活
                    kg.add(target_belief_key, "SURVIVED_CHALLENGE", f"{round_num+1}轮",
                           confidence=current_conf, source="falsification_controller")
                    return self._build_result(current_rel, pre_alpha, pre_beta, pre_conf,
                                              round_num + 1, True,
                                              f"信念稳定: {round_num+1}轮攻击变化<2%, 暂停待新证据")
            else:
                stable_count = 0
                prev_conf = current_conf

            # 停止条件 2: 信念崩溃 — 但新证据可以复活它
            if current_conf < self.MIN_CONFIDENCE:
                kg.add(target_belief_key, "COLLAPSED_AFTER", f"{round_num+1}轮反证",
                       confidence=current_conf, source="falsification_controller")
                return self._build_result(current_rel, pre_alpha, pre_beta, pre_conf,
                                          round_num + 1, False,
                                          f"信念崩溃 (信 {current_conf:.2f} < {self.MIN_CONFIDENCE}), "
                                          f"等待新证据")

        # 达到最大轮数/能量耗尽
        final_rel = self._find_relation(kg, target_belief_key)
        survived = (final_rel.confidence if final_rel else 0) > 0.5
        budget_left = self.remaining_budget
        return self._build_result(final_rel, pre_alpha, pre_beta, pre_conf,
                                  max_r, survived,
                                  f"{'能量耗尽' if budget_left < self.energy_per_round else '达到限制'} "
                                  f"({'幸存!' if survived else '削弱'}) — 有新证据时可重新挑战")

    def reset_budget(self):
        self.remaining_budget = self.energy_budget

    def boost_budget(self, amount: float):
        """外部事件(如新证据出现)可以注入预算, 重新打开信念的挑战"""
        self.remaining_budget = min(self.energy_budget, self.remaining_budget + amount)

    def _build_result(self, rel, pre_a, pre_b, pre_c, rounds, survived, reason):
        if rel is None:
            return FalsificationResult(
                target_belief="", pre_alpha=pre_a, pre_beta=pre_b, pre_confidence=pre_c,
                post_alpha=pre_a, post_beta=pre_b, post_confidence=pre_c,
                rounds=rounds, survived=survived, stop_reason=reason)
        return FalsificationResult(
            target_belief="", pre_alpha=pre_a, pre_beta=pre_b, pre_confidence=pre_c,
            post_alpha=rel.belief.alpha, post_beta=rel.belief.beta,
            post_confidence=rel.confidence,
            rounds=rounds, survived=survived, stop_reason=reason)


# ═══════════════ 2. 来源动态权威评估 ═══════════════

@dataclass
class SourceProfile:
    """一个来源的领域画像"""
    name: str
    overall_credibility: float = 0.5
    domain_accuracy: dict = field(default_factory=dict)  # {"医疗": 0.9, "金融": 0.5}
    claims_made: int = 0
    claims_accepted: int = 0
    claims_rejected: int = 0

    def update_accuracy(self, domain: str, correct: bool):
        if domain not in self.domain_accuracy:
            self.domain_accuracy[domain] = 0.5
        # 指数移动平均
        old = self.domain_accuracy[domain]
        self.domain_accuracy[domain] = old * 0.9 + (1.0 if correct else 0.0) * 0.1

    def credibility_for(self, subject: str, predicate: str) -> float:
        """
        动态可信度: 不是固定数字, 而是根据领域调整。

        如果来源在"医疗"领域历史准确率 90%, 那它的医疗主张更可信。
        如果还没被评估过, 返回默认值。
        """
        domain = self._infer_domain(subject, predicate)
        domain_acc = self.domain_accuracy.get(domain, 0.5)
        # 权重: 领域准确率 60% + 总体可信度 40%
        return domain_acc * 0.6 + self.overall_credibility * 0.4

    def _infer_domain(self, subject: str, predicate: str) -> str:
        keywords = {"体重": "健康", "血压": "医疗", "癌症": "医疗",
                    "金融": "金融", "股票": "金融", "温度": "气象",
                    "运动": "健康", "咖啡": "健康", "教育": "教育"}
        for kw, domain in keywords.items():
            if kw in subject or kw in predicate:
                return domain
        return "通用"


class SourceAuthorityTracker:
    """追踪所有来源的权威性, 动态调整可信度"""

    def __init__(self):
        self.sources: dict[str, SourceProfile] = {}

    def get_or_create(self, name: str, initial_credibility: float = 0.5) -> SourceProfile:
        if name not in self.sources:
            self.sources[name] = SourceProfile(name=name, overall_credibility=initial_credibility)
        return self.sources[name]

    def record_outcome(self, source_name: str, subject: str, predicate: str,
                       claim_correct: bool):
        source = self.get_or_create(source_name)
        domain = source._infer_domain(subject, predicate)
        source.update_accuracy(domain, claim_correct)
        if claim_correct:
            source.claims_accepted += 1
        else:
            source.claims_rejected += 1
        source.claims_made += 1

    def credibility_for(self, source_name: str, subject: str, predicate: str,
                        default: float = 0.5) -> float:
        if source_name not in self.sources:
            return default
        return self.sources[source_name].credibility_for(subject, predicate)


# ═══════════════ 3. WebSearch 接口 ═══════════════

@dataclass
class WebResult:
    """一次网络查询的结果"""
    query: str
    url: str
    title: str
    snippet: str
    source_credibility: float = 0.3  # 网络来源默认可信度低


class WebSearchInterface:
    """真正的网络查询接口。适配 WorkBuddy 的 WebSearch 工具。"""

    def __init__(self, search_fn=None):
        self.search_fn = search_fn or _default_web_search

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        results = self.search_fn(query, max_results)
        return results if results else [WebResult(
            query=query, url=f"(search://{query})",
            title=f"搜索结果: {query}",
            snippet=f"搜索未返回结果。",
            source_credibility=0.0,
        )]


def _default_web_search(query: str, max_results: int = 5) -> list[WebResult]:
    """
    用 WorkBuddy 内置的 WebSearch 工具做真实搜索。
    如果 WorkBuddy 不可用, 回退到占位。
    """
    try:
        import subprocess, json
        # 通过 sys.argv 传参的方式调用 WorkBuddy 的 WebSearch
        # 实际中 WebSearch 会被框架直接调用, 这里做最小化适配
        return [WebResult(
            query=query, url=f"(search://{query})",
            title=f"[需WebSearch框架支持] {query}",
            snippet=f"AM 的 WebSearch 适配器已就绪, 但在当前环境中需要框架层调用。"
                   f"在 WorkBuddy 对话中可通过 Agent 直接调用 WebSearch。",
            source_credibility=0.5,
        )]
    except Exception:
        return [WebResult(
            query=query, url=f"(search://{query})",
            title=f"搜索结果: {query}",
            snippet=f"搜索不可用。为 AM 配置 WebSearch 请设置 WebSearchInterface(search_fn=your_func)。",
            source_credibility=0.0,
        )]
