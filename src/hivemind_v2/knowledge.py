"""
Knowledge Core — AsteriaMind 的脑内世界 (v3.0-alpha)

三个基本元素:
  Entity   — 概念: "线性函数", "y=2x+5", "导数"
  Relation — 关系: IS_A, HAS_PROPERTY, DERIVATIVE_OF, DEPENDS_ON
  Belief   — 每个关系的置信度 (复用 Bayesian 哲学)

核心操作:
  add_knowledge()    — 加入一条带置信度的关系
  query()            — 问: "y=2x+5 的导数是什么?"
  detect_gaps()      — 发现: "斜率这个概念只和线性函数有一条关系, 不够"
  detect_conflicts() — 发现: "两条关系互相矛盾"
  validate()         — 用外部验证更新置信度
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import math


@dataclass
class Relation:
    """一条知识: subject --[predicate]--> object"""
    subject: str
    predicate: str
    object: str
    confidence: float = 0.5          # Bayesian 置信度 [0, 1]
    evidence_count: int = 1           # 被验证次数
    source: str = "inferred"          # "observed" | "inferred" | "external"

    def key(self) -> str:
        return f"{self.subject}--[{self.predicate}]-->{self.object}"


class KnowledgeGraph:
    """AsteriaMind 的脑内世界"""

    def __init__(self):
        self.relations: list[Relation] = []
        self._entity_index: dict[str, list[Relation]] = {}  # subject → relations

    # ── 写入 ──

    def add(self, subject: str, predicate: str, object: str,
            confidence: float = 0.5, source: str = "observed"):
        """加入一条知识"""
        # 检查是否已存在 (更新而非重复)
        for r in self.relations:
            if r.subject == subject and r.predicate == predicate and r.object == object:
                # 贝叶斯更新
                old_n = r.evidence_count
                r.evidence_count += 1
                r.confidence = (r.confidence * old_n + confidence) / r.evidence_count
                return r

        rel = Relation(subject=subject, predicate=predicate, object=object,
                       confidence=confidence, source=source)
        self.relations.append(rel)
        self._entity_index.setdefault(subject, []).append(rel)
        return rel

    def learn_from(self, relations: list[tuple]):
        """批量学习: [(subject, predicate, object, confidence), ...]"""
        for item in relations:
            if len(item) == 4:
                self.add(*item)
            else:
                self.add(*item[:3])

    # ── 查询 ──

    def query(self, subject: str, predicate: str = None) -> list[Relation]:
        """问: 和 subject 相关的关系。可选过滤 predicate"""
        results = []
        for r in self.relations:
            if r.subject == subject:
                if predicate is None or r.predicate == predicate:
                    results.append(r)
            # 反向查: object 也匹配
            elif r.object == subject:
                if predicate is None or r.predicate == predicate:
                    results.append(r)
        return sorted(results, key=lambda r: -r.confidence)

    def ask(self, question: str) -> Optional[str]:
        """自然语言式查询: "y=2x+5 的导数是什么?"
        返回最佳答案字符串。"""
        # 简单 NLP: "X 的 Y 是什么?"
        parts = question.replace("的", " ").replace("是什么", "").strip().split()
        if len(parts) >= 2:
            subject = parts[0]
            predicate = parts[1]
            results = self.query(subject, predicate)
            if results:
                best = results[0]
                return f"{best.object} (置信度 {best.confidence:.2f})"
        return None

    # ── 推理 ──

    def infer(self) -> list[Relation]:
        """简单传递推理: A→B 且 B→C → A→C (最多一跳)"""
        new_relations = []
        for r1 in self.relations:
            for r2 in self.relations:
                if r1.object == r2.subject and r1.predicate == r2.predicate:
                    inferred = Relation(
                        subject=r1.subject,
                        predicate=r1.predicate,
                        object=r2.object,
                        confidence=min(r1.confidence, r2.confidence) * 0.8,
                        source="inferred",
                    )
                    # 避免重复
                    if not any(n.subject == inferred.subject
                               and n.predicate == inferred.predicate
                               and n.object == inferred.object
                               for n in self.relations + new_relations):
                        new_relations.append(inferred)
        self.relations.extend(new_relations)
        for nr in new_relations:
            self._entity_index.setdefault(nr.subject, []).append(nr)
        return new_relations

    # ── 诊断 ──

    def detect_gaps(self, min_relations: int = 2) -> list[str]:
        """发现知识缺口: 哪些实体只有很少的关系?"""
        gaps = []
        all_subjects = set(r.subject for r in self.relations) | set(r.object for r in self.relations)
        for entity in all_subjects:
            rel_count = sum(1 for r in self.relations
                           if r.subject == entity or r.object == entity)
            if rel_count < min_relations:
                gaps.append(f"{entity} (仅 {rel_count} 条关系, 需要更多知识)")
        return gaps

    def detect_conflicts(self) -> list[Tuple[Relation, Relation]]:
        """发现矛盾: 同一 subject-predicate 有两个不同 object"""
        conflicts = []
        seen = {}
        for r in self.relations:
            key = (r.subject, r.predicate)
            if key in seen:
                existing = seen[key]
                if existing.object != r.object:
                    conflicts.append((existing, r))
            else:
                seen[key] = r
        return conflicts

    def most_uncertain(self, n: int = 5) -> list[Relation]:
        """返回最不确定的 N 条关系 → 供 Curiosity 选择探索目标"""
        return sorted(self.relations, key=lambda r: r.confidence)[:n]

    # ── 验证 ──

    def validate(self, subject: str, predicate: str, object: str, correct: bool):
        """外部验证: 正确→置信度↑, 错误→置信度↓"""
        for r in self.relations:
            if r.subject == subject and r.predicate == predicate and r.object == object:
                if correct:
                    r.confidence = min(1.0, r.confidence + 0.2 * (1 - r.confidence))
                else:
                    r.confidence = max(0.01, r.confidence * 0.5)
                return r
        return None

    # ── 导出 ──

    def summary(self) -> dict:
        return {
            "n_entities": len(set(r.subject for r in self.relations) | set(r.object for r in self.relations)),
            "n_relations": len(self.relations),
            "avg_confidence": sum(r.confidence for r in self.relations) / max(1, len(self.relations)),
            "gaps": self.detect_gaps(),
            "conflicts": len(self.detect_conflicts()),
            "most_uncertain": [(r.key(), round(r.confidence, 2)) for r in self.most_uncertain(3)],
        }

    def dump(self) -> str:
        """可读的知识图谱"""
        lines = []
        for r in sorted(self.relations, key=lambda x: -x.confidence):
            bar = "█" * int(r.confidence * 10) + "░" * (10 - int(r.confidence * 10))
            src = {"observed": "👁", "inferred": "🧠", "external": "📡"}.get(r.source, "?")
            lines.append(f"  {src} {r.subject:20s} --[{r.predicate:15s}]--> {r.object:20s}  [{bar}] {r.confidence:.2f}")
        return "\n".join(lines)
