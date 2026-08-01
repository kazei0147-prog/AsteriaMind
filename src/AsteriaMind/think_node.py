"""
ThinkNode — 问题理解与查询策略规划 (AsteriaMind v3.6)

从 HM 2.0 Orchestrator 演化而来:
  预热 → 多假说生成 → 辩论 → 验证 → 聚合
  
简化为:
  分析问题 → 选策略 → 执行 → 通过现有管线回答

策略:
  DIRECT:    subject 在星图有直接命名边 → query_edges
  REVERSE:   subject 无直接边 → reason_about 反推
  SEARCH:    subject 完全陌生 → web_search
  CLARIFY:   代词/追问 → 解析后重试
"""

import re


class ActionPlan:
    """ThinkNode 的决策输出"""
    def __init__(self, strategy: str, subject: str = "",
                 relation_hints: list[str] = None, search_query: str = ""):
        self.strategy = strategy
        self.subject = subject
        self.relation_hints = relation_hints or []
        self.search_query = search_query or subject

    def __repr__(self):
        return (f"ActionPlan(strategy={self.strategy}, subject={self.subject}, "
                f"hints={self.relation_hints}, search={self.search_query})")


# ── 可以回答"什么"的问题类型 ──
ASK_PATTERNS = {
    "CAN":     r'(?:会|能|可以|擅长|会不会|能不能)([^吗呀呢]+?)[吗呢呀]?[？?]?$',
    "NOT_CAN": r'(?:不会|不能|无法|是不是不会)([^吗呀呢]+?)[吗呢呀]?[？?]?$',
    "IS_A":    r'是什么',
    "HAS":     r'有(?:什么|哪些|没有)',
    "EATS":    r'(?:吃|以..为食)',
    "LIVES":   r'(?:在哪里|住哪里|生活在哪里|栖息在哪里)',
    "DEFINE":  r'(?:什么是|介绍一下|介绍)',
}


def _infer_relation(text: str) -> str:
    """从问句推断在问什么关系"""
    if re.search(r'(?:不会|不能|无法|是不是不会)', text):
        return "NOT_CAN"
    if re.search(r'(?:会|能|可以|擅长|会不会|能不能)', text):
        return "CAN"
    if re.search(r'(?:是什么|什么是|属于什么)', text):
        return "IS_A"
    if re.search(r'(?:有什么|有哪些|具有什么)', text):
        return "HAS"
    if re.search(r'(?:吃|捕食|以..为食)', text):
        return "EATS"
    if re.search(r'(?:在哪里|住哪里|生活在哪里)', text):
        return "LIVES_IN"
    return "IS_A"


class ThinkNode:
    """问题理解核心: 分析 → 规划 → 返回执行策略"""

    def __init__(self, star_map):
        self.star_map = star_map
        self.last_subject = ""
        self.last_relation = ""

    def plan(self, text: str, context: str = "") -> ActionPlan:
        """
        输入: 用户问题 + 对话上下文
        输出: ActionPlan — 告诉执行层: 找什么、怎么找
        """
        clean = text.strip()

        # ── 0. 代词 + 追问检测 ──
        if clean in ('它', '她', '他', '这', '那', '它们', '他们', '她们'):
            if self.last_subject:
                return ActionPlan("DIRECT", self.last_subject,
                                  relation_hints=[self.last_relation])
            return ActionPlan("CLARIFY", "", search_query=clean)

        follow_match = re.match(r'^(还有|为什么|那|那么|这个|那个|这些)(.+)', clean)
        if follow_match and self.last_subject:
            suffix = follow_match.group(2)
            return ActionPlan("DIRECT", self.last_subject,
                              relation_hints=[self.last_relation])

        # ── 1. 提取主语 ──
        subject = self._extract_subject(clean)
        if not subject:
            return ActionPlan("CLARIFY", "", search_query=clean)

        # ── 2. 推断在问什么关系 ──
        rel_hint = _infer_relation(clean)
        self.last_subject = subject
        self.last_relation = rel_hint

        # ── 3. 星图中查 — 有直接边吗? ──
        named_count = self._count_named_edges(subject)
        if named_count >= 2:
            return ActionPlan("DIRECT", subject, relation_hints=[rel_hint])

        # ── 4. 无直接边 — 尝试反向推理 ──
        reversed_sources = self._find_reverse_sources(subject)
        if reversed_sources:
            # 用最可能的源实体做主词
            best_source = reversed_sources[0]
            return ActionPlan("REVERSE", best_source,
                              relation_hints=[rel_hint],
                              search_query=f"{subject}(来自{best_source})")

        # ── 5. 完全陌生 — 上网查 ──
        return ActionPlan("SEARCH", "", search_query=clean)

    def _extract_subject(self, text: str) -> str:
        """滑动窗口提取实体 (1-3字)"""
        clean = re.sub(r'[^\u4e00-\u9fff]', '', text)
        for w in (3, 2, 1):
            for i in range(len(clean) - w + 1):
                kw = clean[i:i+w]
                if kw in ('什么', '怎么', '哪里', '为什么', '是不是', '会不会'):
                    continue
                c = self.star_map.conn.execute(
                    "SELECT COUNT(*) FROM directed_edges WHERE (source=? OR target=?) "
                    "AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS','EATS','LIVES_IN','ORBITS')",
                    (kw, kw)).fetchone()
                if c and c[0] > 0:
                    return kw
        # 回退: 取前 3 个汉字
        if len(clean) >= 2:
            return clean[:3]
        return ""

    def _count_named_edges(self, subject: str) -> int:
        return self.star_map.conn.execute(
            "SELECT COUNT(*) FROM directed_edges WHERE source=? "
            "AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS','EATS','LIVES_IN','ORBITS')",
            (subject,)).fetchone()[0]

    def _find_reverse_sources(self, target: str) -> list[str]:
        """反推: 谁指向 target?"""
        rows = self.star_map.conn.execute(
            "SELECT DISTINCT source FROM directed_edges WHERE target=? "
            "AND relation IN ('IS_A','HAS','CAN','LIVES_IN') LIMIT 3",
            (target,)).fetchall()
        return [r[0] for r in rows]
