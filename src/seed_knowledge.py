"""
AsteriaMind 冷启动种子脚本 — 常识图谱灌入

不依赖 web。直接通过 spread_write + directed_edges 批量灌入结构化知识。
建立"基础电网"——让 NPMI 和能量扩散有足够的节点和边来运作。
"""
import sys, time, os
sys.path.insert(0, os.path.dirname(__file__))

from AsteriaMind.cognitive_star_map import CognitiveStarMap, _incr_directed

# ── 常识三元组: subj →[pred]→ obj ──
# 分成清晰的概念层次，方便 NPMI 找到真正的因果边

SEED_TRIPLES = [
    # === 天文 ===
    ("地球", "IS_A", "行星"), ("火星", "IS_A", "行星"), ("金星", "IS_A", "行星"),
    ("月球", "ORBITS", "地球"), ("月球", "IS_A", "卫星"),
    ("太阳", "IS_A", "恒星"), ("地球", "ORBITS", "太阳"),
    ("火星", "ORBITS", "太阳"),

    # === 生物分类 ===
    ("动物", "IS_A", "生物"), ("植物", "IS_A", "生物"),
    ("哺乳动物", "IS_A", "动物"), ("鸟类", "IS_A", "动物"),
    ("爬行动物", "IS_A", "动物"), ("鱼类", "IS_A", "动物"),
    ("猫", "IS_A", "哺乳动物"), ("狗", "IS_A", "哺乳动物"),
    ("海豚", "IS_A", "哺乳动物"), ("鲸鱼", "IS_A", "哺乳动物"),
    ("人类", "IS_A", "哺乳动物"), ("蝙蝠", "IS_A", "哺乳动物"),
    ("企鹅", "IS_A", "鸟类"), ("麻雀", "IS_A", "鸟类"),
    ("鹰", "IS_A", "鸟类"), ("鸽子", "IS_A", "鸟类"),
    ("蛇", "IS_A", "爬行动物"), ("蜥蜴", "IS_A", "爬行动物"),
    ("乌龟", "IS_A", "爬行动物"), ("鳄鱼", "IS_A", "爬行动物"),
    ("鲨鱼", "IS_A", "鱼类"), ("金鱼", "IS_A", "鱼类"),

    # === 能力 ===
    ("企鹅", "CAN", "游泳"), ("企鹅", "NOT_CAN", "飞行"),
    ("麻雀", "CAN", "飞行"), ("狗", "CAN", "游泳"),
    ("猫", "CAN", "爬树"), ("蝙蝠", "CAN", "飞行"),
    ("鹰", "CAN", "飞行"), ("鸽子", "CAN", "飞行"),
    ("海豚", "CAN", "游泳"), ("鲸鱼", "CAN", "���泳"),
    ("人类", "CAN", "思考"),

    # === 特征 ===
    ("哺乳动物", "HAS", "恒温"), ("哺乳动物", "HAS", "毛发"),
    ("鸟类", "HAS", "羽毛"), ("鸟类", "HAS", "卵生"),
    ("爬行动物", "HAS", "变温"), ("鱼类", "HAS", "鳃"),
    ("哺乳动物", "HAS", "胎生"),

    # === 层级分类 (IS_A链) ===
    ("猫", "HAS", "胡须"), ("狗", "HAS", "嗅觉"),
    ("蛇", "CAN", "蜕皮"), ("蛇", "NOT_CAN", "咀嚼"),
    ("太阳", "IS_A", "恒星"), ("木星", "IS_A", "行星"),
    ("土星", "IS_A", "行星"), ("土星", "HAS", "光环"),
    ("火星", "HAS", "红色"), ("金星", "HAS", "高温"),

    # === 地理 ===
    ("亚洲", "IS_A", "大洲"), ("中国", "IS_A", "亚洲"),
    ("日本", "IS_A", "亚洲"), ("美国", "IS_A", "北美洲"),
    ("太平洋", "IS_A", "海洋"), ("大西洋", "IS_A", "海洋"),

    # === AI / 系统概念 ===
    ("AI", "IS_A", "人工智能"), ("人工智能", "IS_A", "技术"),
    ("Python", "IS_A", "编程语言"), ("机器学习", "IS_A", "AI"),
    ("深度学习", "IS_A", "机器学习"),
]

# ── 偏常识文本 (用 spread_write 灌入共现网) ──
SEED_TEXTS = [
    "企鹅是一种不会飞的鸟类，生活在南极。它们擅长游泳，以鱼类和磷虾为食。",
    "海豚和鲸鱼属于哺乳动物，不是鱼类。它们用肺呼吸，胎生哺乳。",
    "蝙蝠是唯一能够飞行的哺乳动物。它们倒挂着睡觉，用回声定位导航。",
    "月球围绕地球旋转，是地球唯一的天然卫星。月球的引力引起地球的潮汐。",
    "太阳是一个恒星，位于太阳系的中心。所有行星都围绕太阳旋转。",
    "猫和狗都是人类常见的宠物。它们都属于哺乳动物，有毛发，恒温。",
    "蛇和蜥蜴是爬行动物，冷血变温，需要晒太阳来调节体温。",
    "AI是人工智能的缩写。机器学习和深度学习是AI的重要分支。",
    "火星是红色的行星，因为表面含有大量氧化铁。科学家在研究火星上是否存在过生命。",
    "鲨鱼属于鱼类，用鳃呼吸。海豚虽然生活在水中，但属于哺乳动物。",
]


def seed_star_map(db_path: str = "asteriamind.db"):
    """灌入所有种子数据到星图"""
    ts = time.time()
    star = CognitiveStarMap(db_path)
    cur = star.conn.cursor()

    # ── 1. 三元组 → cognitive_traces + directed_edges ──
    triples_added = 0
    for subj, pred, obj in SEED_TRIPLES:
        star.store(subj, pred, obj, "confirmed",
                    f"种子知识: {subj} {pred} {obj}")
        # 额外提升有向边权重 (种子知识应该更可靠)
        _incr_directed(cur, subj, obj, pred, "confirmed", ts)
        _incr_directed(cur, subj, obj, pred, "confirmed", ts)
        triples_added += 1

    # ── 2. 常识文本 → spread_write 共现网 ──
    for text in SEED_TEXTS:
        star.spread_write(text)

    star.conn.commit()
    print(f"种子灌入完成: {triples_added} 三元组 + {len(SEED_TEXTS)} 段文本")
    print(f"星图节点: {star.count()} 条, "
          f"有向边: {cur.execute('SELECT COUNT(*) FROM directed_edges').fetchone()[0]} 条, "
          f"共现: {cur.execute('SELECT COUNT(*) FROM co_occurrence').fetchone()[0]} 条")
    return star


if __name__ == "__main__":
    seed_star_map()
