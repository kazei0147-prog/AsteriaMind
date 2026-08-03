"""
IntentLearner — 意图统计学习器 (AsteriaMind v3.6)

替代正则猜意图:
  正则 = 先验 (冷启动)
  统计 = 从用户反馈中学 P(意图|关键词)

数据流:
  用户问句 → 提取关键词 → 系统用某意图回答
  → 用户反馈 (对/不对) → 更新 P(意图|关键词)
  → 下次相同句式 → 概率最高的意图胜出

表: intent_feedback(keyword, intent, correct, total)
预测: score(intent) = Σ correct/total 取最高
无数据 → 回退正则
"""

import re

# 先验正则 (冷启动用, 统计学够了就让位)
PRIOR_PATTERNS = {
    "NOT_CAN":  [r'不会', r'不能', r'无法', r'是不是不会'],
    "CAN":      [r'会\b', r'能\b', r'可以', r'会不会', r'能不能', r'擅长'],
    "IS_A":     [r'是什么', r'什么是', r'属于什么', r'属于'],
    "HAS":      [r'有什么', r'有哪些', r'具有什么', r'拥有'],
    "EATS":     [r'吃', r'捕食', r'以.*为食'],
    "LIVES_IN": [r'在哪里', r'住哪里', r'生活在哪里', r'栖息'],
}

# 意图关键词 (提取用)
KEYWORDS = ['不会', '不能', '无法', '会', '能', '可以', '是什么', '什么是',
            '属于', '有什么', '有哪些', '具有', '吃', '捕食', '在哪里',
            '生活在哪里', '栖息', '怎么回事', '怎么', '为什么', '会不会',
            '能不能', '擅长']


class IntentLearner:
    def __init__(self, star_map):
        self.star_map = star_map
        self._ensure_table()

    def _ensure_table(self):
        self.star_map.conn.execute(
            "CREATE TABLE IF NOT EXISTS intent_feedback("
            "keyword TEXT, intent TEXT, correct INTEGER DEFAULT 0, "
            "total INTEGER DEFAULT 0, PRIMARY KEY(keyword, intent))")

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        return [kw for kw in KEYWORDS if kw in text]

    @staticmethod
    def _infer_prior(text: str) -> str:
        """正则先验 — 冷启动"""
        for intent, pats in PRIOR_PATTERNS.items():
            for p in pats:
                if re.search(p, text):
                    return intent
        return "ASK"

    def learn(self, text: str, intent_used: str, correct: bool):
        """用户反馈 → 更新统计"""
        kws = self._extract_keywords(text)
        if not kws:
            return
        delta = 1 if correct else 0
        for kw in kws:
            self.star_map.conn.execute(
                "INSERT OR IGNORE INTO intent_feedback(keyword,intent,correct,total) "
                "VALUES(?,?,0,0)", (kw, intent_used))
            self.star_map.conn.execute(
                "UPDATE intent_feedback SET correct=correct+?, total=total+1 "
                "WHERE keyword=? AND intent=?", (delta, kw, intent_used))
        self.star_map.conn.commit()

    def predict(self, text: str) -> str:
        """统计预测 — 无数据回退正则"""
        kws = self._extract_keywords(text)
        if not kws:
            return self._infer_prior(text)
        scores: dict[str, float] = {}
        support = 0
        for kw in kws:
            rows = self.star_map.conn.execute(
                "SELECT intent, correct, total FROM intent_feedback "
                "WHERE keyword=? AND total>0", (kw,)).fetchall()
            for intent, correct, total in rows:
                scores[intent] = scores.get(intent, 0) + correct / total
                support += 1
        if support >= 2:  # 至少 2 条经验才覆盖先验
            if scores:
                return max(scores, key=scores.get)
        return self._infer_prior(text)

    def summary(self) -> dict:
        rows = self.star_map.conn.execute(
            "SELECT keyword, COUNT(DISTINCT intent), SUM(total) "
            "FROM intent_feedback GROUP BY keyword ORDER BY SUM(total) DESC LIMIT 10").fetchall()
        return {"learned_patterns": len(rows),
                "examples": [{"keyword": r[0], "intents": r[1], "count": r[2]} for r in rows]}
