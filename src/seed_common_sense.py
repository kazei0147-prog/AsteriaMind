"""
SeedCommonSense — 元常识种子包: CAUSES 因果骨架 (AsteriaMind v3.9 F16)

瓶颈一 (常识缺口 vs 组合爆炸): 共现是稀疏的, 常识是稠密的。
靠 co_text 自然增长永远补不齐"天上下雨地面会湿"这类基础因果常识,
所以直接注入结构化元关系种子 — 让因果/矛盾/时序元逻辑骨架先立起来。

三类元关系:
  CAUSES       A 导致 B        (因果: 反事实意图/预测的基础)
  NOT_CAUSES   A 不会导致 B    (反因果: 防止"运动→变瘦"类过度归因)
  OPPOSITE     A 与 B 相反     (矛盾: 批判者/矛盾调和的显式骨架)

设计原则 (与用户哲学一致):
  - 只喂"能被未来验证"的常识, 不喂意见 (黑盒涌现/白盒筛选)
  - 冲突检查仍走净化器 _OPPOSITE (CAUSES↔NOT_CAUSES 自动拦截矛盾教学)
  - 数量少而精: 初期几十条因果常识 + 几组相反概念, 性价比 >> 百万共现边

用法:
  python seed_common_sense.py            # 喂入 + 汇报
"""

import sys
sys.path.insert(0, '.')

# ── 因果常识包: (原因, CAUSES, 结果) — 公开常识, 无版权问题 ──
SEED_CAUSES = [
    # ═══ 自然现象因果 ═══
    ("天上下雨", "CAUSES", "地面变湿"),
    ("气温降到零度以下", "CAUSES", "水结冰"),
    ("水结冰", "CAUSES", "体积膨胀"),
    ("阳光照射", "CAUSES", "植物进行光合作用"),
    ("强烈地震", "CAUSES", "房屋倒塌"),
    ("火山喷发", "CAUSES", "岩浆流出"),
    ("台风登陆", "CAUSES", "狂风暴雨"),
    ("空气污染", "CAUSES", "呼吸系统疾病"),
    ("温室效应", "CAUSES", "全球变暖"),
    ("冰川融化", "CAUSES", "海平面上升"),
    ("过度捕捞", "CAUSES", "渔业资源枯竭"),
    ("森林砍伐", "CAUSES", "水土流失"),
    ("水土流失", "CAUSES", "土壤贫瘠"),
    ("燃烧化石燃料", "CAUSES", "二氧化碳排放"),
    ("二氧化碳增多", "CAUSES", "温室效应"),
    # ═══ 生物因果 ═══
    ("缺少水分", "CAUSES", "植物枯萎"),
    ("长期营养不良", "CAUSES", "身体虚弱"),
    ("病毒感染", "CAUSES", "发烧"),
    ("充足睡眠", "CAUSES", "精力恢复"),
    ("规律运动", "CAUSES", "增强体质"),
    ("吃了变质食物", "CAUSES", "食物中毒"),
    ("花粉进入鼻腔", "CAUSES", "过敏反应"),
    ("体温过高", "CAUSES", "中暑"),
    ("身体缺水", "CAUSES", "口渴"),
    ("缺乏维生素C", "CAUSES", "坏血病"),
    # ═══ 物理/日常因果 ═══
    ("用力推门", "CAUSES", "门打开"),
    ("断开电源", "CAUSES", "电器停止工作"),
    ("按下开关", "CAUSES", "灯亮起来"),
    ("充电", "CAUSES", "电池电量增加"),
    ("碰撞", "CAUSES", "物体受损"),
    ("加热", "CAUSES", "温度升高"),
    ("剧烈摩擦", "CAUSES", "产生热量"),
    ("高处坠落", "CAUSES", "受伤"),
    ("努力学习", "CAUSES", "成绩提升"),
    ("拖延", "CAUSES", "任务堆积"),
]

# ── 反因果 (防过度归因) ──
SEED_NOT_CAUSES = [
    ("吃辣椒", "NOT_CAUSES", "感冒"),
    ("穿厚衣服", "NOT_CAUSES", "发烧"),
    ("下雨", "NOT_CAUSES", "气温升高"),
    ("熬夜", "NOT_CAUSES", "长高"),
]

# ── 相反概念对 (OPPOSITE 显式矛盾骨架) ──
SEED_OPPOSITES = [
    ("白天", "OPPOSITE", "黑夜"),
    ("热", "OPPOSITE", "冷"),
    ("干燥", "OPPOSITE", "潮湿"),
    ("上升", "OPPOSITE", "下降"),
    ("增加", "OPPOSITE", "减少"),
    ("打开", "OPPOSITE", "关闭"),
    ("开始", "OPPOSITE", "结束"),
    ("前进", "OPPOSITE", "后退"),
    ("静止", "OPPOSITE", "运动"),
    ("膨胀", "OPPOSITE", "收缩"),
    ("生", "OPPOSITE", "死"),
    ("快乐", "OPPOSITE", "悲伤"),
    ("强", "OPPOSITE", "弱"),
    ("快", "OPPOSITE", "慢"),
    ("高", "OPPOSITE", "低"),
]


def main():
    from AsteriaMind.cognitive_star_map import CognitiveStarMap, _is_valid_entity_pair
    star = CognitiveStarMap('asteriamind.db')

    added = skipped = 0
    by_rel = {}
    for subj, rel, obj in (SEED_CAUSES + SEED_NOT_CAUSES + SEED_OPPOSITES):
        if not _is_valid_entity_pair(subj, obj):
            skipped += 1
            continue
        star.store(subj, rel, obj, "confirmed",
                   "seed_common_sense: 元常识骨架")
        added += 1
        by_rel[rel] = by_rel.get(rel, 0) + 1

    print(f"喂入元常识: {added} 条 | 跳过: {skipped} 条")
    print(f"按关系: {by_rel}")
    named = star.conn.execute(
        "SELECT COUNT(*) FROM directed_edges "
        "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN','CAUSES','NOT_CAUSES','OPPOSITE')"
    ).fetchone()[0]
    print(f"知识层命名边总数 (含元关系): {named}")


if __name__ == "__main__":
    main()
