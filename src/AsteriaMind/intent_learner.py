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

# 先验正则 (冷启动用, 统计学够了就让位) — 注意: 汉字间没有 \b 边界!
# F14 (v3.9): 扩展复杂意图 — 对比 / 假设 / 反事实 (U-03 方案 B, 本期 MVP)
# 顺序纪律: 复杂意图(长句)必须先于基本意图(单关键词) — 否则 "如果企鹅会飞会怎样"
#   里的 "会" 会被 CAN 抢走, 反事实永远不命中
PRIOR_PATTERNS = {
    # ── F14 复杂意图 (长句优先) ──
    "COUNTERFACTUAL": [  # 反事实: 与已知事实相反的条件假设
        r'如果.{0,8}(?:会怎样|会怎么样|怎么样|会如何|会有什么后果)',
        r'(?:假如|假设).{0,8}(?:会怎样|会怎么样|会如何)',
        r'要不是|如果不是|要不是.{0,6}(?:就|会)',
        r'要是.{0,8}(?:就好了|该多好|就惨了)',
    ],
    "HYPOTHESIS": [      # 假设: 一般条件推理 (如果X就Y / 假设X会Y)
        r'假设.{0,12}',
        r'假如.{0,12}',
        r'如果.{0,10}(?:就|那么|那)',
        r'要是.{0,8}(?:会|能|就)',
        r'设想.{0,10}(?:会|能)',
    ],
    "COMPARE": [         # 对比: 两者或多者差异 (复用 intent_layer 的 COMPARE 剖面)
        r'(?:和|与|跟|同).{1,8}(?:比|比较|相比|对比)',
        r'(?:区别|差异|不同|差别|异同|谁更|哪个更|哪个好|孰优)',
        r'哪个.{1,6}(?:更|最|好|适合)',
        r'比.{1,6}(?:好|强|大|快|高|多)',
    ],
    # ── 基本意图 (单关键词) ──
    "NOT_CAN":  [r'不会', r'不能', r'无法', r'是不是不会'],
    "CAN":      [r'会不会', r'能不能', r'会(?!不会)', r'能(?!不能)', r'可以', r'擅长'],
    "IS_A":     [r'是什么', r'什么是', r'属于什么', r'属于'],
    "HAS":      [r'有什么', r'有哪些', r'具有什么', r'拥有'],
    "EATS":     [r'吃', r'捕食', r'以.*为食'],
    "LIVES_IN": [r'在哪里', r'住哪里', r'生活在哪里', r'栖息'],
}

# 意图关键词 (提取用)
KEYWORDS = ['不会', '不能', '无法', '会', '能', '可以', '是什么', '什么是',
            '属于', '有什么', '有哪些', '具有', '吃', '捕食', '在哪里',
            '生活在哪里', '栖息', '怎么回事', '怎么', '为什么', '会不会',
            '能不能', '擅长',
            # ── F14 复杂意图关键词 ──
            '如果', '假如', '要是', '假设', '设想', '要不是', '如果不是',
            '会怎样', '会怎么样', '会如何',
            '比较', '相比', '对比', '区别', '差异', '不同', '差别', '异同',
            '哪个', '谁更', '哪个更']


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
