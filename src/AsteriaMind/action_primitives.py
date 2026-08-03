"""
ActionPrimitives — 动作原语学习器 (AsteriaMind v3.6)

把"动词"从模板匹配升级为可学习绑定:
  "查一下星体" → 动词[查] → search_action → 宾语[星体]
  "算一下2+2"  → 动词[算] → math_action  → 表达式[2+2]
  "教我企鹅是鸟类" → 动词[教] → teach_action → 事实[企鹅是鸟类]

两层:
  词义层 (星图): 动词的语义关系 (查~搜索~检索 联想)
  动作层 (本模块): 动词 → 可执行动作 绑定, 靠反馈学习

冷启动: 种子绑定表 (先验)
自举:   反馈 → P(动作|动词) 更新 → 联想泛化到新动词
"""

import re

# 冷启动种子: 动词 → 动作 (先验, 学够了统计覆盖)
SEED_BINDINGS = {
    "查": "search", "搜索": "search", "搜": "search", "找": "search",
    "查找": "search", "查询": "search", "检索": "search", "看看": "search",
    "算": "math", "计算": "math",
    "教": "teach", "学": "teach", "记住": "teach", "记": "teach",
    "讲": "explain", "介绍": "explain", "说说": "explain", "解释": "explain",
}

# 动作动词提取模式: 动词 + 修饰语(一下/一) + 宾语
VERB_PATTERNS = [
    r'(查|搜|搜索|查找|查询|检索)一?下?[:：]?\s*(.+)',
    r'(算|计算)一?下?[:：]?\s*(.+)',
    r'(教|教教|教一下|学)我?\s*(.+)',
    r'(讲|介绍|说说|解释)一?下?[:：]?\s*(.+)',
    r'^(帮我|给我|请|麻烦)?(搜索|搜一下|查一下|查找|查询|检索)[：:\s]*(.+)',
]

# 修饰/语气词: 不参与动作, 但说明意图强度
_MODIFIERS = ('一下', '一', '个', '点', '点儿', '看看', '试试')


class ActionPrimitives:
    def __init__(self, star_map):
        self.star_map = star_map
        self._ensure_table()

    def _ensure_table(self):
        self.star_map.conn.execute(
            "CREATE TABLE IF NOT EXISTS action_bindings("
            "verb TEXT, action TEXT, correct INTEGER DEFAULT 0, "
            "total INTEGER DEFAULT 0, PRIMARY KEY(verb, action))")

    # ── 动词提取 ──
    @staticmethod
    def extract(text: str) -> tuple[str | None, str]:
        """提取 (动词, 宾语). 无动词 → (None, 原文本)"""
        for pat in VERB_PATTERNS:
            m = re.search(pat, text)
            if m:
                verb = m.group(1)
                target = m.group(2).strip()
                # 去修饰语 + 疑问词
                for mod in _MODIFIERS:
                    target = target.replace(mod, '')
                for junk in ('吗', '么', '呢', '吧', '呀'):
                    target = target.replace(junk, '')
                target = target.strip(' ，。？！：:')
                return verb, target
        return None, text

    # ── 预测: 动词 → 动作 ──
    def predict(self, verb: str | None) -> str | None:
        """统计预测 + 种子先验 + 联想泛化"""
        if not verb:
            return None
        # 1. 统计 (反馈学到的)
        rows = self.star_map.conn.execute(
            "SELECT action, correct, total FROM action_bindings "
            "WHERE verb=? AND total>0 ORDER BY correct*1.0/total DESC LIMIT 1",
            (verb,)).fetchone()
        if rows:
            action = rows[0]
            # 置信度足够才用统计, 否则回退种子
            if rows[2] >= 3 and rows[1] / rows[2] >= 0.6:
                return action
        # 2. 种子先验
        if verb in SEED_BINDINGS:
            return SEED_BINDINGS[verb]
        # 3. 联想泛化: 不认识动词 → co_text 关联已知动词
        known = [v for v in SEED_BINDINGS if len(v) >= 2]
        best_verb, best_energy = None, 0.0
        for kv in known:
            e = self.star_map.conn.execute(
                "SELECT energy FROM directed_edges "
                "WHERE source=? AND target=? AND relation='co_text' LIMIT 1",
                (verb, kv)).fetchone()
            energy = e[0] if e else 0.0
            if energy > best_energy:
                best_energy, best_verb = energy, kv
        if best_verb and best_energy >= 0.2:
            return SEED_BINDINGS[best_verb]
        return None

    # ── 反馈学习 ──
    def learn(self, verb: str, action: str, correct: bool):
        if not verb:
            return
        delta = 1 if correct else 0
        self.star_map.conn.execute(
            "INSERT OR IGNORE INTO action_bindings(verb,action,correct,total) "
            "VALUES(?,?,0,0)", (verb, action))
        self.star_map.conn.execute(
            "UPDATE action_bindings SET correct=correct+?, total=total+1 "
            "WHERE verb=? AND action=?", (delta, verb, action))
        self.star_map.conn.commit()

    def summary(self) -> dict:
        rows = self.star_map.conn.execute(
            "SELECT verb, action, correct, total FROM action_bindings "
            "WHERE total>0 ORDER BY total DESC LIMIT 10").fetchall()
        return {"learned_bindings": len(rows),
                "examples": [{"verb": r[0], "action": r[1],
                              "correct": r[2], "total": r[3]} for r in rows]}
