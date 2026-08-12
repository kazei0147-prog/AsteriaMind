"""
intake_purifier.py — 汲取净化器 (候选 → 筛选 → 沉淀)

两个汲取口统一治理 (用户: 两个汲取口都有污染, 特别是网上学):
  网上学 (搜索): snippet → 句式提取三元组 → 冲突检查 → 只存事实
    不再 spread_write 全文 — 那是污染 700 万 co_text 联想层的元凶
    搜索结果里的广告词/导航词/废话不再进星图
  人工灌 (教学): 问句过滤 ("X是Y吗"是提问不是教学) → 质量门 → 存储

哲学: 汲取是感觉, 净化是海马体, 星图是长期记忆
"""

import re

from AsteriaMind.corpus_miner import PATTERNS
from AsteriaMind.cognitive_star_map import _is_valid_entity_pair

# 问句标记: "鸟类有乳腺吗" → 不是教学
_QUESTION_RE = re.compile(r"[吗么呢]$|^(?:是不是|会不会|能不能|有没有|是否|请问|你知道|你知道)")
# 关系反对映射 (冲突检查用)
# ★ v3.9 F16: 加入 CAUSES↔NOT_CAUSES (瓶颈一: 因果元逻辑 — 防因果边自相矛盾)
_OPPOSITE = {"IS_A": "NOT_IS_A", "CAN": "NOT_CAN", "NOT_CAN": "CAN",
             "HAS": "NOT_HAS", "EATS": "NOT_EATS", "CAUSES": "NOT_CAUSES",
             "NOT_CAUSES": "CAUSES"}


class IntakePurifier:
    """汲取净化器: 两个汲取口共用"""

    def __init__(self, star_map):
        self.star_map = star_map

    # ── 网上汲取: 提取事实, 不扩散全文 ──
    def ingest_web(self, word: str, title: str, snippet: str) -> dict:
        """搜索结果 → 句式提取 → 冲突检查 → 只存事实

        返回: {extracted, stored, rejected, note}
        """
        result = {"extracted": [], "stored": [], "rejected": [], "note": ""}
        text = f"{title}。{snippet}"
        for pat, rel, gs, go in PATTERNS:
            for m in re.finditer(pat, text):
                s, o = m.group(gs).strip(), m.group(go).strip()
                if not _is_valid_entity_pair(s, o):
                    continue
                # 主语必须是查询词或其子串 (防提取到别的实体)
                if not (s == word or word in s or s in word):
                    continue
                triple = (s, rel, o)
                if triple in result["extracted"]:
                    continue
                result["extracted"].append(triple)
                # 冲突检查: 新事实和已有正反对 → 拒绝
                if self._conflicts(s, rel, o):
                    result["rejected"].append((*triple, "conflict"))
                    result["note"] = f"「{s} {rel} {o}」与现有知识冲突, 已拒绝"
                    continue
                # 同类边已存在 → 合并 (不重复存)
                if self._exists(s, rel, o):
                    continue
                self.star_map.store(s, rel, o, "confirmed",
                                    f"web_intake: {word}")
                result["stored"].append(triple)
        return result

    def _conflicts(self, s: str, rel: str, o: str) -> bool:
        """新事实与现有知识冲突? (如已有 蛇 NOT_CAN 咀嚼, 搜到 蛇 CAN 咀嚼)"""
        if rel in _OPPOSITE:
            return bool(self.star_map.conn.execute(
                "SELECT 1 FROM directed_edges WHERE source=? AND relation=? "
                "AND target=? LIMIT 1", (s, _OPPOSITE[rel], o)).fetchone())
        return False

    def _exists(self, s: str, rel: str, o: str) -> bool:
        return bool(self.star_map.conn.execute(
            "SELECT 1 FROM directed_edges WHERE source=? AND relation=? "
            "AND target=? LIMIT 1", (s, rel, o)).fetchone())

    # ── 人工教学: 问句过滤 + 质量门 ──
    def ingest_teach(self, subj: str, rel: str, obj: str) -> tuple:
        """教学输入净化

        返回: (True, 'ok') 或 (False, 原因)
        """
        if _QUESTION_RE.search(subj) or _QUESTION_RE.search(obj):
            return False, "这像是问句不是教学——教我用 'X 是 Y' 格式"
        if not _is_valid_entity_pair(subj, obj):
            return False, "实体不合格 (太短/虚词/残片)"
        # 用户明确教学 → 高置信直接存
        self.star_map.store(subj, rel, obj, "confirmed", "teach_intake")
        return True, "ok"
