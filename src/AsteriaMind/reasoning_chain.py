"""
ReasoningChain — 推理链 (AsteriaMind v3.8)

把分散的知识串成推理路径 — "思考"的核心能力:
  企鹅 IS_A 鸟类 ∧ 鸟类 IS_A 脊椎动物 → 企鹅 IS_A 脊椎动物

现状: 回答管线只有 直接查边(DIRECT) / 反推(REVERSE) / 联想借知识
  缺: 多跳传递 — 两段知识之间没有桥

设计:
  IS_A 严格传递 (属于的属于 = 属于)
  CAN / HAS / EATS 不传递 (能吃昆虫 ≠ 它的类能吃昆虫)
  只推 IS_A — 语义最稳的传递关系

置信度:
  一跳 0.9 (直接证据)
  两跳 0.9 × 0.8 = 0.72 (链式衰减, 越多跳越不确定)

冲突检查: 链上出现 NOT_IS_A → 停 (企鹅 NOT_IS_A 哺乳动物 → 不再向上推)
"""

import sqlite3

_NAMED = "('IS_A','NOT_IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN')"


class ReasoningChain:
    def __init__(self, star_map):
        self.star_map = star_map

    def infer(self, subject: str, max_hops: int = 2,
              top_k: int = 4) -> list[dict]:
        """从 subject 沿 IS_A 链推理

        返回: [{target, path: [A,B,C], confidence, hops}]
          hops=1: 直接 IS_A 边 (企鹅 → 鸟类)
          hops=2: 传递推理 (企鹅 → 鸟类 → 脊椎动物)
        """
        if not subject:
            return []
        results = []
        seen = set()

        # ── 一跳: 直接 IS_A 边 ──
        one_hop = self.star_map.conn.execute(
            "SELECT target, COALESCE(confidence, 0.5) "
            "FROM directed_edges "
            "WHERE source=? AND relation='IS_A' "
            "AND target NOT IN ('?','') AND target != ? "
            "ORDER BY COALESCE(confidence,0.5) DESC LIMIT 5",
            (subject, subject)).fetchall()
        for tgt, conf in one_hop:
            conf = float(conf or 0.5)
            if tgt in seen:
                continue
            seen.add(tgt)
            results.append({
                "target": tgt, "path": [subject, tgt],
                "confidence": max(0.5, conf), "hops": 1,
            })

        # ── 两跳: 传递推理 (只对一跳的 target 再向上追) ──
        if max_hops >= 2:
            for tgt, conf in one_hop:
                # 冲突检查: subject NOT_IS_A tgt 的上游 → 不推
                conflict = self.star_map.conn.execute(
                    "SELECT 1 FROM directed_edges "
                    "WHERE source=? AND relation='NOT_IS_A' AND target=? LIMIT 1",
                    (subject, tgt)).fetchone()
                if conflict:
                    continue
                two_hop = self.star_map.conn.execute(
                    "SELECT target, COALESCE(confidence, 0.5) "
                    "FROM directed_edges "
                    "WHERE source=? AND relation='IS_A' "
                    "AND target NOT IN ('?','') AND target != ? "
                    "LIMIT 3", (tgt, subject)).fetchall()
                for t2, c2 in two_hop:
                    if t2 == subject or t2 in seen:
                        continue
                    seen.add(t2)
                    results.append({
                        "target": t2, "path": [subject, tgt, t2],
                        "confidence": max(0.5, float(conf or 0.5)) * 0.8,
                        "hops": 2,
                    })

        results.sort(key=lambda x: -x["confidence"])
        return results[:top_k]

    def chain_text(self, r: dict) -> str:
        """推理链转描述: 企鹅 → 鸟类 → 脊椎动物"""
        path = r.get("path", [])
        if len(path) >= 3:
            return f"{path[0]}属于{path[1]}，而{path[1]}属于{path[2]}"
        if len(path) == 2:
            return f"{path[0]}属于{path[1]}"
        return ""
