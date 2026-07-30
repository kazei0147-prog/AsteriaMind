"""
HumanReview + ProvenanceGuard — 异步人类审核 + 来源防篡改 (AsteriaMind v3.1)

防护哲学: 不怕被喂假数据, 就怕看不出来被喂了假数据。

两层防护:
  1. ProvenanceGuard: 每条知识记录完整来源链, 不可逆
  2. HumanReview: 异步审核接口, 管理员可纠正但不覆盖历史
"""
import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional
from AsteriaMind.knowledge import KnowledgeGraph


# ═══════════════ 1. 来源防篡改 ═══════════════

@dataclass
class ProvenanceRecord:
    """一条知识的完整来源链——不可逆, 不可删除"""
    relation_key: str
    first_observed: float          # 首次记录时间
    source_chain: list[dict]       # [{time, source, action, evidence}]
    review_count: int = 0
    last_reviewed: float = 0.0
    review_history: list[dict] = field(default_factory=list)

    @property
    def source_diversity(self) -> float:
        """来源多样性: 越高越好 (防止单一来源垄断)"""
        sources = set(s.get("source", "") for s in self.source_chain)
        return min(1.0, len(sources) / 5)

    @property
    def trust_score(self) -> float:
        """
        来源可信度评分:
          + 来源多样 (多个独立源)
          + 时间跨度长 (不是短期内密集注入的)
          + 有人审核过
        """
        diversity = self.source_diversity
        time_span = (time.time() - self.first_observed) / 86400  # 天数
        age_bonus = min(1.0, time_span / 30)  # 30 天以上满分
        review_bonus = min(0.3, self.review_count * 0.1)
        return min(1.0, diversity * 0.4 + age_bonus * 0.3 + review_bonus + 0.1)


class ProvenanceGuard:
    """
    来源卫士: 每条知识有完整的出生证明和成长记录。

    不被管理员直接篡改——只追加, 不重写。
    """

    def __init__(self):
        self.records: dict[str, ProvenanceRecord] = {}

    def record_add(self, key: str, source: str, confidence: float):
        if key not in self.records:
            self.records[key] = ProvenanceRecord(
                relation_key=key, first_observed=time.time(),
                source_chain=[],
            )
        self.records[key].source_chain.append({
            "time": time.time(), "source": source,
            "action": "added", "confidence": confidence,
        })

    def record_verify(self, key: str, source: str, correct: bool):
        if key not in self.records:
            return
        self.records[key].source_chain.append({
            "time": time.time(), "source": source,
            "action": "verified" if correct else "falsified",
        })

    def record_review(self, key: str, reviewer: str, verdict: str, reason: str):
        if key not in self.records:
            return
        self.records[key].review_count += 1
        self.records[key].last_reviewed = time.time()
        self.records[key].review_history.append({
            "time": time.time(), "reviewer": reviewer,
            "verdict": verdict, "reason": reason,
        })

    def audit(self, key: str) -> Optional[dict]:
        """审查一条知识的来源: 谁说的? 什么时候? 有人审核过吗?"""
        rec = self.records.get(key)
        if not rec:
            return None
        return {
            "key": key,
            "age_days": round((time.time() - rec.first_observed) / 86400, 1),
            "source_count": len(rec.source_chain),
            "unique_sources": len(set(s["source"] for s in rec.source_chain if "source" in s)),
            "diversity": round(rec.source_diversity, 2),
            "trust": round(rec.trust_score, 2),
            "reviewed": rec.review_count > 0,
            "last_review": rec.last_reviewed,
            "flag": self._flag(rec),
        }

    def _flag(self, rec: ProvenanceRecord) -> List[str]:
        """自动标记: 这条知识需要警惕吗?"""
        flags = []
        if rec.source_diversity < 0.2 and len(rec.source_chain) > 5:
            flags.append("单源风险: 所有证据来自同一源头")
        if rec.review_count == 0 and len(rec.source_chain) > 10:
            flags.append("未经审核: 有大量证据但无人验证")
        if (time.time() - rec.first_observed) < 3600 and len(rec.source_chain) > 20:
            flags.append("注入异常: 短时间内密集添加, 可能是批量攻击")
        return flags


# ═══════════════ 2. 异步人类审核接口 ═══════════════

class HumanReviewInterface:
    """
    异步人类审核接口: 不是审批流, 是事后纠正机制。

    管理员操作:
      review <key> correct   → 确认这条知识正确
      review <key> wrong <原因> → 标记为错误, 高权重反证
      review <key> uncertain → 标记为待验证
      provenance <key>       → 查看完整来源链
    """

    def __init__(self, kg: KnowledgeGraph, guard: ProvenanceGuard = None):
        self.kg = kg
        self.guard = guard or ProvenanceGuard()

    def review_correct(self, key: str, reviewer: str = "admin"):
        """管理员确认: 这条知识是正确的"""
        rel = self._find(key)
        if not rel:
            return f"❌ 未找到知识: {key}"

        # 高权重支持证据
        self.kg.observe(rel.subject, rel.predicate, rel.object,
                        correct=True, weight=2.0,
                        context=f"管理员 {reviewer} 审核确认")
        self.guard.record_review(key, reviewer, "correct", "人工确认")
        return f"✅ 已确认: {key} (信任+2.0)"

    def review_wrong(self, key: str, reason: str, reviewer: str = "admin"):
        """管理员纠正: 这条知识是错误的"""
        rel = self._find(key)
        if not rel:
            return f"❌ 未找到知识: {key}"

        # 高权重反证 — 但不删除原纪录
        self.kg.observe(rel.subject, rel.predicate, rel.object,
                        correct=False, weight=2.0,
                        context=f"管理员 {reviewer} 审核纠正: {reason}",
                        alternative=f"人工审核判定为错误")
        self.guard.record_review(key, reviewer, "wrong", reason)
        return (f"❌ 已纠正: {key}\n"
                f"   原因: {reason}\n"
                f"   原记录保留, 反证权重 2.0 已加入")

    def review_uncertain(self, key: str, reviewer: str = "admin"):
        """管理员标记: 这条知识待验证"""
        rel = self._find(key)
        if not rel:
            return f"❌ 未找到知识: {key}"
        self.guard.record_review(key, reviewer, "uncertain", "标记为待验证")
        return f"❓ 已标记: {key} → 待验证"

    def provenance_report(self, key: str) -> str:
        """完整来源审查报告"""
        audit = self.guard.audit(key)
        if not audit:
            return f"❌ 未找到来源记录: {key}"

        rel = self._find(key)
        lines = [
            f"════════════════════════════════",
            f"📋 来源审查: {key}",
            f"   当前置信度: {rel.confidence:.2f} (α={rel.belief.alpha:.1f} β={rel.belief.beta:.1f})" if rel else "",
            f"   年龄: {audit['age_days']} 天  来源数: {audit['source_count']}",
            f"   来源多样性: {audit['diversity']}  综合可信度: {audit['trust']}",
        ]
        if audit["flag"]:
            lines.append(f"   ⚠️ 警告: {'; '.join(audit['flag'])}")

        # 时间线
        rec = self.guard.records.get(key)
        if rec and rec.source_chain:
            lines.append(f"   时间线:")
            for entry in rec.source_chain[-5:]:
                t = time.strftime("%m-%d %H:%M", time.localtime(entry["time"]))
                action = entry.get("action", "?")
                source = entry.get("source", "?")
                lines.append(f"     [{t}] {source}: {action}")

        if rec and rec.review_history:
            lines.append(f"   审核记录:")
            for entry in rec.review_history[-3:]:
                t = time.strftime("%m-%d %H:%M", time.localtime(entry["time"]))
                lines.append(f"     [{t}] {entry['reviewer']}: {entry['verdict']} — {entry['reason']}")

        return "\n".join(lines)

    def _find(self, key: str):
        for r in self.kg.relations:
            if r.key() == key:
                return r
        return None
