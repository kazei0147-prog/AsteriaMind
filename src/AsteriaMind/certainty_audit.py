"""
CertaintyAudit — 高置信度信念的自检 (AsteriaMind v3.1)

不是"我不确定的去查查"——那是 Curiosity。
而是"我太确定的, 是不是有盲区?"——这是智力上的谦卑。
"""
from dataclasses import dataclass


@dataclass
class AuditFinding:
    """对一条稳固信念的压力测试结果"""
    relation_key: str
    confidence: float
    risk_level: str          # low | medium | high
    reasons: list[str]       # 为什么这条信念可能有盲区
    recommended_action: str  # 建议怎么做


class CertaintyAudit:
    """
    扫描已稳固 (consolidated) 的信念, 寻找结构性盲区。

    触发条件 (不是人手动调的, 是自动的):
      - 某个信念的 evidence_total 很高但 counter_evidence 几乎为零
      - 某个信念的所有证据来自单一来源
      - 某个信念的生成条件太窄 (没在不同语境下测试过)
    """

    def audit(self, kg) -> list[AuditFinding]:
        findings = []

        for r in kg.relations:
            if not r.belief.is_strong:
                continue  # 只看高置信度的

            risks = []
            actions = []

            # 风险1: 无反证 / 单源偏信
            sources = set()
            for ce in r.counter_evidence:
                ctx = ce.get("context", "")
                if "来源:" in ctx:
                    src = ctx.split("来源:")[-1].split("|")[0].strip()
                    if src:
                        sources.add(src)
            # 如果没有 counter_evidence → 更可疑 (没有试图找反面证据)
            if len(r.counter_evidence) == 0:
                risks.append("无反证: 从未被质疑过——可能是真, 也可能是没人去找反面证据")
                actions.append("设计一个会暴露反设场景的实验")
            elif len(sources) <= 1 and r.belief.evidence_total > 10:
                risks.append(f"来源单一: 证据集中在同一上下文")
                actions.append("从不同语境采集新数据交叉验证")

            # 风险2: 太高置信度的底层信念 — 如果错了, 后果严重
            if r.confidence > 0.9 and r.belief.evidence_total > 20:
                # 查它是不是其他信念的依赖基础
                dependents = [r2 for r2 in kg.relations
                              if r.subject in r2.key() or r.object in r2.key()]
                if len(dependents) > 3:
                    risks.append(f"结构关键: {len(dependents)} 条其他关系依赖此信念, 如果出错影响面大")
                    actions.append("做一次针对性验证, 确认基础信念仍然成立")

            # 风险3: 只有关联性证据, 没有因果证据
            has_causal = ("CAUSES" in r.predicate or "因果" in str(r.belief))
            has_correlation_only = (
                "CORRELATED" in r.predicate
                and r.belief.evidence_total > 15
                and len(r.counter_evidence) == 0
            )
            if has_correlation_only:
                risks.append("相关非因果: 高度相关但未验证因果关系——可能是共同原因")
                actions.append("设计共因排除实验")

            if risks:
                risk = "high" if len(risks) >= 2 else "medium"
                findings.append(AuditFinding(
                    relation_key=r.key(),
                    confidence=r.confidence,
                    risk_level=risk,
                    reasons=risks,
                    recommended_action="; ".join(actions),
                ))

        return sorted(findings,
                      key=lambda f: {"high": 0, "medium": 1, "low": 2}[f.risk_level])

    def summarize(self, kg) -> str:
        findings = self.audit(kg)
        if not findings:
            return "未发现高置信度信念的结构性盲区。"

        lines = [f"对 {len(findings)} 条稳固信念做了压力测试:"]
        for f in findings[:5]:
            icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}[f.risk_level]
            lines.append(f"  {icon} [{f.risk_level.upper()}] {f.relation_key} (信 {f.confidence:.2f})")
            for reason in f.reasons:
                lines.append(f"      ⚠ {reason}")
            lines.append(f"      → {f.recommended_action}")
        return "\n".join(lines)

    def act_on_findings(self, kg, engine=None) -> list[dict]:
        """
        不只是诊断——对每条高风险发现, 生成对应的探索行动。
        """
        findings = self.audit(kg)
        actions = []

        for f in findings:
            if f.risk_level not in ("high", "medium"):
                continue

            subject = f.relation_key.split("--[")[0].strip()

            if "无反证" in str(f.reasons):
                kg.add(f"{subject}_falsification_test", "SEEKS_DISPROOF_OF",
                       f.relation_key, confidence=0.3, source="certainty_audit")
                actions.append({
                    "finding": f.relation_key,
                    "action": "falsification_targeted",
                    "detail": "创建了反证搜寻标记, 接下来 explore 会优先验证",
                })

            if "相关非因果" in str(f.reasons):
                kg.add(f.relation_key, "NEEDS_CAUSAL_VALIDATION", "共因排除实验",
                       confidence=0.6, source="certainty_audit")
                actions.append({
                    "finding": f.relation_key,
                    "action": "causal_validation_queued",
                    "detail": "标记为需要因果验证",
                })

        return actions
