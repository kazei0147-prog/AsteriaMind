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

# ★ v3.7: 完整概念词表缓存 (word_vectors) — 长词优先提取主语
_VOCAB_CACHE = None
_QUERY_WORDS = frozenset(
    '什么 怎么 哪里 为什么 是不是 会不会 如何 多少 哪些 什么样 是否 为什么'
    '是什么 什么是 有什么 有哪些 怎么样 怎么回事 什么时候'.split())


def _get_vocab(star_map):
    """向量词表 → 集合 (模块级缓存, 完整概念词优先匹配)"""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is None:
        _VOCAB_CACHE = set()
        try:
            for (w,) in star_map.conn.execute(
                    "SELECT word FROM word_vectors").fetchall():
                if len(w) >= 2:
                    _VOCAB_CACHE.add(w)
        except Exception:
            pass
    return _VOCAB_CACHE


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
    # ★ v3.9 F16: 因果问句 (瓶颈一: CAUSES 元逻辑) — 强因果词才归 CAUSES,
    #   "为什么"是弱因果 (可能问否定/能力原因, 如"为什么不会飞"→NOT_CAN), 不抢占
    if re.search(r'(?:导致|引起|造成|引发|是因为|什么原因|为何会|怎么会导致)', text):
        return "CAUSES"
    # ★ v3.9 ID-004: 相反关系 ("热和什么相反" → OPPOSITE)
    if re.search(r'(?:相反|对立|相对|反义词)', text):
        return "OPPOSITE"
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
        subject = ""  # ★ 先初始化, 供 context 块引用 ★

        # ── 0.5. 从 context 读"你"指代谁 ──
        if context and not subject:
            # 用户的上一句话
            um = re.search(r'\[user\]:\s*(.+)', context)
            if um:
                prev_q = um.group(1)
                prev_subj = self._extract_subject(re.sub(r'[^\u4e00-\u9fff]', '', prev_q))
                if prev_subj:
                    self.last_subject = prev_subj
                    self.last_relation = _infer_relation(prev_q)

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

        # ── 2.5 该不该搜? 对话性短句 → 不搜 ──
        if len(clean) <= 3:
            return ActionPlan("CLARIFY", subject or clean, search_query=clean)
        # 纯追问/元对话
        if re.match(r'^(什么|怎么|为啥|为什么|是吗|真的|好吧|行|嗯|额|啊|唉|这|那)$', clean):
            return ActionPlan("CLARIFY", subject or clean, search_query=clean)

        # ── 3. 星图中查 — 有直接边吗? ──
        named_count = self._count_named_edges(subject)
        if named_count >= 2:
            return ActionPlan("DIRECT", subject, relation_hints=[rel_hint])

        # ★ v3.8: 只有 1 条边时, 先试推理链 — "三角龙" 只有 IS_A 恐龙
        #   但 恐龙 IS_A 爬行动物 → 能推两跳 → 值得 DIRECT 回答
        if named_count == 1 and rel_hint == "IS_A":
            try:
                from AsteriaMind.reasoning_chain import ReasoningChain
                if not hasattr(self, "_rc") or self._rc is None:
                    self._rc = ReasoningChain(self.star_map)
                chain = self._rc.infer(subject, top_k=2)
                if any(r["hops"] >= 2 for r in chain):
                    return ActionPlan("DIRECT", subject,
                                      relation_hints=[rel_hint])
            except Exception:
                pass

        # ★ v3.9 ID-004: 单条边但正好问的是这条关系 → 直接答
        #   元常识实体只有 1 条边 (天上下雨 CAUSES 地面湿), named_count>=2
        #   永远达不到 → 全落 SEARCH。问"导致什么"且确有 CAUSES 边 → DIRECT
        if named_count == 1:
            single_rel = self.star_map.conn.execute(
                "SELECT relation FROM directed_edges WHERE source=? "
                "AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS',"
                "'EATS','LIVES_IN','ORBITS','CAUSES','NOT_CAUSES','OPPOSITE') "
                "ORDER BY (tier='A') DESC LIMIT 1", (subject,)).fetchone()
            if single_rel:
                sr = single_rel[0]
                # 因果/反因果同域: 问"导致什么" → NOT_CAUSES 边也可答
                #   (吃辣椒 NOT_CAUSES 感冒 → 答"不会导致感冒")
                if sr == rel_hint or \
                   (rel_hint == "CAUSES" and sr == "NOT_CAUSES") or \
                   (rel_hint == "NOT_CAUSES" and sr == "CAUSES"):
                    return ActionPlan("DIRECT", subject,
                                      relation_hints=[rel_hint])

        # ── 3.5 类群概念检查: X 被多个实体 IS_A 指向 → 问"X是什么"答 X 本身 ──
        #    "甲壳动物是什么" → 甲壳动物被螃蟹/龙虾/虾归类 → SEARCH 查定义
        #    而不是反推成成员 (答虾) — REVERSE 只适合属性词 (羽毛→鸟类)
        if rel_hint == "IS_A" and self._count_in_is_a(subject) >= 2:
            return ActionPlan("SEARCH", subject, relation_hints=[rel_hint],
                              search_query=subject)

        # ── 4. 无直接边 — 尝试反向推理 ──
        reversed_sources = self._find_reverse_sources(subject)
        if reversed_sources:
            # 用最可能的源实体做主词
            best_source = reversed_sources[0]
            return ActionPlan("REVERSE", best_source,
                              relation_hints=[rel_hint],
                              search_query=f"{subject}(来自{best_source})")

        # ── 4.5. co_text 联想 — 谁跟 subject 经常共现? ──
        if self.star_map.co_conn:
            for row in self.star_map.co_conn.execute(
                "SELECT target, energy FROM directed_edges "
                "WHERE source=? AND relation='co_text' "
                "ORDER BY energy DESC LIMIT 10",
                (subject,)).fetchall():
                neighbor, energy = row
                # 邻居在命名DB有边 → 借用它的知识
                named = self.star_map.conn.execute(
                    "SELECT 1 FROM directed_edges WHERE source=? "
                    "AND relation IN ('IS_A','CAN','HAS','NOT_CAN') LIMIT 1",
                    (neighbor,)).fetchone()
                if named:
                    return ActionPlan("DIRECT", neighbor,
                                      relation_hints=[rel_hint],
                                      search_query=f"{subject}(共现→{neighbor})")

        # ── 5. 完全陌生 — 上网查 ──
        return ActionPlan("SEARCH", "", search_query=clean)

    def _extract_subject(self, text: str) -> str:
        """提取实体 — 完整概念词优先 (甲壳动物 ≠ 动物)

        ★ v3.9 ID-004 修复: 命名边 source 匹配**优先于**向量词表 —
          此前向量词表在 w=2 命中"天上"碎片, 抢在 4 字命名边"天上下雨"之前,
          导致元常识实体提取成残片。白盒确定知识优先, 黑盒词表补充。
        """
        clean = re.sub(r'[^\u4e00-\u9fff]', '', text)
        NAMED_SQL = ("SELECT COUNT(*) FROM directed_edges WHERE source=? "
                     "AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS',"
                     "'EATS','LIVES_IN','ORBITS','CAUSES','NOT_CAUSES','OPPOSITE')")
        # ① 命名边 source 句首匹配 (白盒确定知识, 主语通常在句首)
        #    "热和什么相反" → "热"; "天上下雨会导致什么" → "天上下雨"
        for w in range(min(8, len(clean)), 0, -1):
            kw = clean[:w]
            if kw and kw not in _QUERY_WORDS:
                c = self.star_map.conn.execute(NAMED_SQL, (kw,)).fetchone()
                if c and c[0] > 0:
                    return kw
        # ② 向量词表最长匹配 (黑盒完整概念 — "甲壳动物" 在词表,
        #    优先于句中"动物"碎片)
        vocab = _get_vocab(self.star_map)
        if vocab:
            for w in range(min(8, len(clean)), 1, -1):
                for i in range(len(clean) - w + 1):
                    kw = clean[i:i + w]
                    if kw in vocab and kw not in _QUERY_WORDS:
                        return kw
        # ③ 命名边 source 全滑动 (句中实体兜底)
        for w in range(min(8, len(clean)), 0, -1):
            for i in range(len(clean) - w + 1):
                kw = clean[i:i + w]
                if kw in _QUERY_WORDS:
                    continue
                c = self.star_map.conn.execute(NAMED_SQL, (kw,)).fetchone()
                if c and c[0] > 0:
                    return kw
        # 回退: 取前 3 个汉字
        if len(clean) >= 2:
            return clean[:3]
        return ""

    def _count_named_edges(self, subject: str) -> int:
        return self.star_map.conn.execute(
            "SELECT COUNT(*) FROM directed_edges WHERE source=? "
            "AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS','EATS','LIVES_IN','ORBITS','CAUSES','NOT_CAUSES','OPPOSITE')",
            (subject,)).fetchone()[0]

    def _count_in_is_a(self, subject: str) -> int:
        """IS_A 入度: 被多少实体归类 (类群概念信号)"""
        return self.star_map.conn.execute(
            "SELECT COUNT(*) FROM directed_edges WHERE target=? "
            "AND relation='IS_A'", (subject,)).fetchone()[0]

    def _find_reverse_sources(self, target: str) -> list[str]:
        """反推: 谁指向 target?"""
        rows = self.star_map.conn.execute(
            "SELECT DISTINCT source FROM directed_edges WHERE target=? "
            "AND relation IN ('IS_A','HAS','CAN','LIVES_IN') LIMIT 3",
            (target,)).fetchall()
        return [r[0] for r in rows]
