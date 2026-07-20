"""
Knowledge Core — AsteriaMind 的脑内世界 (v3.0)

核心理念:
  不是存一堆"苹果 是 水果"的死数据。
  而是: 每个关系有自己的 Bayesian 信念(alpha/beta),
       有反证据记录、有时间戳、有上下文标签。
       系统可以追问"你多确定?"、"什么时候验证的?"、
       "什么情况下不对?"、"你最近是越来越确信还是越来越动摇?"

三个基本元素:
  Entity   — 概念: "线性函数", "y=2x+5", "导数"
  Relation — 带贝叶斯信念的有向关系
  Evidence — 支持/反证据链 (每条关系有自己的证据谱)

核心操作:
  observe_support()   — "又看到了一次, 更确定了"
  observe_counter()   — "等等, 这次不是这样, 在 X 语境下它是 Y"
  query()             — "y=2x+5 的导数是什么?"
  growth_trend()      — "这条知识最近是稳定了还是在动摇?"
  detect_staleness()  — "这条知识上次验证是 3 天前, 该复查了"
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CounterEvidence:
    """一条反证据: 在什么语境下, 这条关系不成立"""
    alternative: str              # 替代解释
    context: str = ""             # 语境描述
    weight: float = 0.5           # 这条反证据的分量
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class Belief:
    """
    用 Beta(α, β) 表示一个信念。

    α = 支持证据的累积分
    β = 反对证据的累积分

    置信度 = α / (α+β)     (Beta 分布均值)
    不确定性 = α·β / ((α+β)² · (α+β+1))  (Beta 方差)
    """
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def confidence(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    @property
    def evidence_total(self) -> float:
        return self.alpha + self.beta

    @property
    def uncertainty(self) -> float:
        total = self.alpha + self.beta
        if total <= 1:
            return 0.25
        return (self.alpha * self.beta) / (total * total * (total + 1))

    @property
    def is_strong(self) -> bool:
        return self.confidence > 0.85 and self.evidence_total > 5

    @property
    def is_contested(self) -> bool:
        return self.beta > 0 and self.beta > self.alpha * 0.2

    def observe_support(self, weight: float = 1.0):
        self.alpha += weight

    def observe_against(self, weight: float = 0.5):
        self.beta += weight

    def summary(self) -> str:
        pct = self.confidence * 100
        if self.is_strong:
            return f"稳固 ({pct:.0f}%, 证据 {self.evidence_total:.0f} 条)"
        elif self.is_contested:
            return f"动摇 ({pct:.0f}%, 反证据 {self.beta:.1f} 条)"
        else:
            return f"待验证 ({pct:.0f}%)"


@dataclass
class Relation:
    """
    一条知识: subject --[predicate]--> object

    不是死数据, 是活的 Bayesian 信念:
      - belief: 贝叶斯信念 (alpha/beta)
      - counter_evidence: 什么情况下这条关系不成立
      - first_observed / last_verified: 时间戳 (检测陈旧)
      - source: 从哪里来的
    """
    subject: str
    predicate: str
    object: str
    belief: Belief = field(default_factory=Belief)
    counter_evidence: List[CounterEvidence] = field(default_factory=list)
    first_observed: float = 0.0
    last_verified: float = 0.0
    source: str = "observed"

    def __post_init__(self):
        if self.first_observed == 0.0:
            self.first_observed = time.time()
        if self.last_verified == 0.0:
            self.last_verified = self.first_observed

    @property
    def confidence(self) -> float:
        return self.belief.confidence

    @property
    def uncertainty(self) -> float:
        return self.belief.uncertainty

    @property
    def is_stale(self) -> bool:
        """超过 24 小时未验证 → 陈旧"""
        return (time.time() - self.last_verified) > 86400

    def key(self) -> str:
        return f"{self.subject}--[{self.predicate}]-->{self.object}"

    def growth_trend(self) -> str:
        """
        成长趋势:
          "consolidated"  — 证据充分, 无人质疑
          "stable"        — 持续观察, 稳定
          "contested"     — 有反证据, 信念在摇摆
          "uncertain"     — 证据太少, 不确定
          "stale"         — 太久没验证
        """
        if self.is_stale:
            return "stale"
        if self.belief.is_strong:
            return "consolidated"
        if self.belief.is_contested:
            return "contested"
        if self.belief.evidence_total > 3:
            return "stable"
        return "uncertain"

    def observe(self, correct: bool, weight: float = 1.0,
                context: str = "", alternative: str = ""):
        """
        观察到一次验证:
          correct=True  → 增加 α (更自信)
          correct=False → 增加 β + 记录反证据语境
        """
        if correct:
            self.belief.observe_support(weight)
        else:
            self.belief.observe_against(weight)
            if alternative or context:
                self.counter_evidence.append(CounterEvidence(
                    alternative=alternative,
                    context=context,
                    weight=weight,
                ))
        self.last_verified = time.time()


# ═══════════════════ 知识图谱 ═══════════════════

class KnowledgeGraph:
    """AsteriaMind 的脑内世界"""

    def __init__(self):
        self.relations: list[Relation] = []
        self._index: dict[str, list[Relation]] = {}

    # ── 写入 ──

    def add(self, subject: str, predicate: str, object: str,
            confidence: float = 0.5, source: str = "observed") -> Relation:
        """加入一条知识 (带初始置信度)"""
        alpha = max(0.1, confidence * 10)  # 置信度 → Beta prior
        beta = max(0.1, (1 - confidence) * 10)

        # 已存在? → 合并证据
        for r in self.relations:
            if r.subject == subject and r.predicate == predicate and r.object == object:
                r.belief.alpha += alpha
                r.belief.beta = max(0.1, (r.belief.beta + beta) / 2)
                r.last_verified = time.time()
                return r

        rel = Relation(
            subject=subject, predicate=predicate, object=object,
            belief=Belief(alpha=alpha, beta=beta), source=source,
        )
        self.relations.append(rel)
        self._index.setdefault(subject, []).append(rel)
        return rel

    def learn_from(self, relations: list[tuple]):
        """批量学习"""
        for item in relations:
            if len(item) == 4:
                self.add(*item)
            else:
                self.add(*item[:3])

    # ── 验证 ──

    def observe(self, subject: str, predicate: str, object: str,
                correct: bool, weight: float = 1.0,
                context: str = "", alternative: str = "") -> Optional[Relation]:
        """用一次观察更新一条关系的信念"""
        for r in self.relations:
            if r.subject == subject and r.predicate == predicate and r.object == object:
                r.observe(correct, weight, context, alternative)
                return r
        return None

    # ── 查询 ──

    def query(self, subject: str, predicate: str = None) -> list[Relation]:
        results = []
        for r in self.relations:
            if r.subject == subject:
                if predicate is None or r.predicate == predicate:
                    results.append(r)
            elif r.object == subject:
                if predicate is None:
                    results.append(r)
        return sorted(results, key=lambda r: -r.confidence)

    def ask(self, question: str) -> Optional[dict]:
        """自然语言查询, 返回 {'answer', 'confidence', 'trend', 'n_counter'}"""
        parts = question.replace("的", " ").replace("是什么", "").strip().split()
        if len(parts) >= 2:
            results = self.query(parts[0], parts[1])
            if results:
                best = results[0]
                return {
                    "answer": best.object,
                    "confidence": round(best.confidence, 3),
                    "trend": best.growth_trend(),
                    "evidence": f"α={best.belief.alpha:.1f} β={best.belief.beta:.1f}",
                    "n_counter": len(best.counter_evidence),
                    "verified_ago": f"{(time.time()-best.last_verified)/3600:.1f}h",
                }
        return None

    # ── 推理 ──

    def infer(self) -> list[Relation]:
        """传递推理 A→B 且 B→C → A→C"""
        new_relations = []
        for r1 in self.relations:
            for r2 in self.relations:
                if r1.object == r2.subject and r1.predicate == r2.predicate:
                    combined_alpha = min(r1.belief.alpha, r2.belief.alpha) * 0.8
                    combined_beta = max(r1.belief.beta, r2.belief.beta) * 1.2
                    inferred = Relation(
                        subject=r1.subject, predicate=r1.predicate, object=r2.object,
                        belief=Belief(alpha=combined_alpha, beta=combined_beta),
                        source="inferred",
                    )
                    if not any(n.subject == inferred.subject
                               and n.predicate == inferred.predicate
                               and n.object == inferred.object
                               for n in self.relations + new_relations):
                        new_relations.append(inferred)
        self.relations.extend(new_relations)
        for nr in new_relations:
            self._index.setdefault(nr.subject, []).append(nr)
        return new_relations

    # ── 诊断 ──

    def detect_gaps(self, min_relations: int = 2) -> list[str]:
        gaps = []
        entities = set()
        for r in self.relations:
            entities.add(r.subject)
            entities.add(r.object)
        for e in entities:
            n = sum(1 for r in self.relations if r.subject == e or r.object == e)
            if n < min_relations:
                gaps.append(f"{e} (仅 {n} 条关系)")
        return gaps

    def detect_conflicts(self) -> list[Tuple[Relation, Relation]]:
        """同一 subject-predicate 有多个不同 object → 矛盾"""
        conflicts = []
        seen: dict[tuple, Relation] = {}
        for r in self.relations:
            key = (r.subject, r.predicate)
            if key in seen:
                if seen[key].object != r.object:
                    conflicts.append((seen[key], r))
            else:
                seen[key] = r
        return conflicts

    def detect_staleness(self, max_hours: float = 24) -> list[Relation]:
        """太久没验证的知识"""
        now = time.time()
        return [r for r in self.relations
                if (now - r.last_verified) > max_hours * 3600]

    def most_uncertain(self, n: int = 5) -> list[Relation]:
        return sorted(self.relations, key=lambda r: r.confidence)[:n]

    def growth_report(self) -> list[dict]:
        """每条关系的成长状态"""
        return [{
            "key": r.key(),
            "confidence": round(r.confidence, 3),
            "alpha": round(r.belief.alpha, 1),
            "beta": round(r.belief.beta, 1),
            "trend": r.growth_trend(),
            "n_counter": len(r.counter_evidence),
            "is_stale": r.is_stale,
        } for r in self.relations]

    # ── 导出 ──

    def summary(self) -> dict:
        entities = len(set(r.subject for r in self.relations) | set(r.object for r in self.relations))
        consolidated = sum(1 for r in self.relations if r.growth_trend() == "consolidated")
        contested = sum(1 for r in self.relations if r.growth_trend() == "contested")
        stale = sum(1 for r in self.relations if r.is_stale)
        return {
            "entities": entities,
            "relations": len(self.relations),
            "consolidated": consolidated,
            "contested": contested,
            "stale": stale,
            "avg_confidence": round(
                sum(r.confidence for r in self.relations) / max(1, len(self.relations)), 3),
        }

    def dump(self) -> str:
        lines = []
        for r in sorted(self.relations, key=lambda x: -x.confidence):
            bar = "█" * int(r.confidence * 10) + "░" * (10 - int(r.confidence * 10))
            trend = {"consolidated": "🟢", "stable": "🔵", "contested": "🟡",
                     "uncertain": "⚪", "stale": "⏳"}.get(r.growth_trend(), "?")
            ce = f" 反证×{len(r.counter_evidence)}" if r.counter_evidence else ""
            lines.append(
                f"  {trend} {r.subject:20s} --[{r.predicate:15s}]--> {r.object:20s}  "
                f"[{bar}] {r.confidence:.2f}  {r.belief.summary()}{ce}"
            )
        return "\n".join(lines)
