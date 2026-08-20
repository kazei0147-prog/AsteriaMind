"""
ArgumentGate — 白盒论证闸门 (AsteriaMind v3.9, ID-024①)

v2.0 ArgumentEvaluator (old/argument.py 归档) 回归主链路, 为候选知识时代重铸:
  v2.0: 数值共识 — ReasoningChain.strength() 排序, 选 proposal_value
  v3.9: 知识论证 — 候选边 (subj, relation, target) 的论证强度竞争

链路位置: 涌现候选之后 (query_edges + 推理链 + 意图加权), 输出之前 (compose)
双职:
  ① 回答选答案 — 多候选论证竞争, 谁站得住脚谁上位 (不是谁 salience 高谁上位)
  ② 白盒质检   — 反证检查: 被更强反边压制的候选除名 (主动拒绝, v3.0 哲学回归)

论证强度 (一条边的"论证"由五要素构成):
  strength = 0.35 * 支持度   (salience, 检索管线综合分)
           + 0.15 * 能量     (energy, 推理链验证挣回过 = 被现实碰过)
           + 0.20 * 证据数   (evidence_count 对数归一, 独立支持次数)
           + 0.15 * 确信度   (confidence, 历史反馈均值)
           + 0.15 * 直接性   (直接边=1.0, 两跳推理=0.6 — 继承 v2.0 "最佳论证"思想)

差距判据 (继承 v2.0 agreement_threshold=0.3, 知识域调低):
  gap = strength[0] - strength[1]
  gap > 0.15 → 明显赢家 (single): 输出以冠军为首
  gap ≤ 0.15 → 势均力敌 (tie): 并列保留, 让语言层并列叙述

质检 (反证压制):
  NOT 边 (NOT_IS_A/NOT_CAN/NOT_CAUSES) 与候选同 (subj, target) 且
  反边强度 > 1.15 × 候选强度 → 候选除名, 理由入 audit
  两跳 inferred 候选被任何直接反边命中 → 除名 (推论不与直接证据对抗)

不可自指 (ID-024③ A 层纪律在回答侧的体现):
  闸门只消费外部锚 (星图既有证据), 不产出自证 — audit 只记录, 不加分
"""

import math

_NEG_OF = {
    "IS_A": "NOT_IS_A", "CAN": "NOT_CAN", "CAUSES": "NOT_CAUSES",
    "HAS": "NOT_HAS", "EATS": "NOT_EATS",
}
_NEG_RELS = set(_NEG_OF.values())

# 除名后的候选去向: 不进叙事 (被更强论证压制), 但留 audit 供证据链展示


class ArgumentGate:
    """论证闸门 — 候选竞争 + 白盒质检。无状态, 可热插拔。"""

    GAP_THRESHOLD = 0.15      # 差距判据: > 此值为明显赢家 (继承 v2.0 agreement_threshold)
    SUPPRESS_RATIO = 1.15     # 反边强度 > 1.15 × 候选 → 压制

    def __init__(self, star_map=None):
        self.star_map = star_map

    # ── 论证强度 ──
    def _edge_strength(self, e: dict, max_salience: float) -> float:
        # salience 批内相对归一: 论证是比较级 — 强者是比出来的, 不是绝对分
        salience = (float(e.get("salience") or 0.5)
                    / max(max_salience, 1e-6))
        energy = min(1.0, float(e.get("energy") or 1.0) / 2.0)
        confidence = float(e.get("confidence") or 0.5)
        # 直接性: 两跳推理候选 (reasoning_chain 注入, 带 path) 论证弱一档
        path = e.get("path") or []
        directness = 0.6 if len(path) >= 3 else 1.0
        return (0.35 * min(1.0, salience)
                + 0.15 * energy
                + 0.15 * min(1.0, confidence)
                + 0.15 * directness)

    def _evidence_factor(self, subj: str, target: str) -> float:
        """独立支持次数 → 对数归一 (10 次支持 ≈ 0.85, 1 次 = 0.4)"""
        if not self.star_map:
            return 0.4
        try:
            row = self.star_map.conn.execute(
                "SELECT MAX(evidence_count) FROM directed_edges "
                "WHERE source=? AND target=? AND relation NOT IN "
                "('co_text','NOT_IS_A','NOT_CAN','NOT_CAUSES','NOT_HAS','NOT_EATS')",
                (subj, target)).fetchone()
            n = float(row[0] or 0)
        except Exception:
            return 0.4
        if n <= 0:
            return 0.0
        return min(1.0, 0.4 + 0.45 * min(1.0, math.log10(n + 1) / math.log10(11)))

    def _edge_evidence(self, subj: str, target: str, relation: str) -> float:
        """边证据强度: weight × confidence × energy (同单位比较, 不混检索相关性)"""
        if not self.star_map:
            return 0.0
        try:
            row = self.star_map.conn.execute(
                "SELECT weight, COALESCE(confidence,0.5), COALESCE(energy,1.0) "
                "FROM directed_edges WHERE source=? AND target=? AND relation=?",
                (subj, target, relation)).fetchone()
        except Exception:
            return 0.0
        if not row:
            return 0.0
        return float(row[0] or 1) * float(row[1] or 0.5) * float(row[2] or 1.0)

    # ── 主入口 ──
    def evaluate(self, subject: str, edges: list[dict],
                 top_k: int = 6) -> tuple[list[dict], dict]:
        """
        候选竞争 + 质检。

        返回: (排序后的 edges, audit)
          audit = {mode: single|tie, gap, eliminated: [{edge, reason}], top_strength}
        """
        if not edges:
            return edges, {"mode": "empty", "gap": 0.0, "eliminated": [],
                           "top_strength": 0.0}

        eliminated = []

        # ── 质检: 反证压制 ──
        survivors = []
        for e in edges:
            rel = e.get("relation", "")
            neg_rel = _NEG_OF.get(rel)
            target = e.get("target", "")
            suppressed = False
            if neg_rel and target:
                cand_ev = self._edge_evidence(subject, target, rel)
                neg = self._edge_evidence(subject, target, neg_rel)
                # 推论 (inferred) 不与直接反边对抗 — 直接除名
                if e.get("inferred") and neg > 0:
                    eliminated.append({
                        "edge": f"{subject} {rel} {target}",
                        "reason": f"推论被直接反边 {neg_rel} 否决",
                    })
                    suppressed = True
                elif neg > self.SUPPRESS_RATIO * max(cand_ev, 0.1):
                    eliminated.append({
                        "edge": f"{subject} {rel} {target}",
                        "reason": f"被更强反边 {neg_rel} 压制 "
                                  f"(反边证据 {neg:.2f} > {self.SUPPRESS_RATIO}×候选 {cand_ev:.2f})",
                    })
                    suppressed = True
            if not suppressed:
                survivors.append(e)

        # ── 竞争: 论证强度排序 ──
        max_salience = max((float(e.get("salience") or 0.5)
                            for e in survivors), default=1.0)
        for e in survivors:
            e["argument_strength"] = round(
                self._edge_strength(e, max_salience)
                + 0.20 * self._evidence_factor(subject, e.get("target", "")), 3)
        survivors.sort(key=lambda x: -x["argument_strength"])

        gap = 0.0
        if len(survivors) >= 2:
            gap = survivors[0]["argument_strength"] - survivors[1]["argument_strength"]
        mode = ("single" if (len(survivors) < 2 or gap > self.GAP_THRESHOLD)
                else "tie")

        audit = {
            "mode": mode,
            "gap": round(gap, 3),
            "eliminated": eliminated,
            "top_strength": survivors[0]["argument_strength"] if survivors else 0.0,
        }
        return survivors[:top_k], audit
