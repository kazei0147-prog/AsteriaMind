"""
SeedCognition — 认知层种子包: 理论锚点 + AM 自我认知 (AsteriaMind v3.9 F13/F16)

来源: 2026-08-15~18 与用户的认知讨论 (登记册 ID-022/ID-023 的结晶)
  - 语言层双锚点: Levelt 言语产生模型 + 语义网络 (Collins/Firth)
  - AM 自我认知: 黑盒/白盒/验证回路/共情层 — F16 立场层的雏形种子

设计原则 (与用户哲学一致):
  - 只喂"确认过的知识" (L3 一次性手术刀, 克制) — 每条都是讨论验证过的
  - 自我认知边让 AM 能回答"你是什么/黑盒是什么" — 白盒先立骨架, 黑盒慢慢跟上
  - 数量少而精: ~30 条认知锚点 >> 百万共现边

用法:
  python seed_cognition.py            # 喂入 + 汇报
"""

import sys
sys.path.insert(0, '.')

# ── 理论锚点 (语言/认知科学) — 来自 ID-022 双锚点 ──
SEED_THEORY = [
    # Levelt 言语产生模型 (1989)
    ("Levelt", "IS_A", "心理语言学家"),
    ("Levelt", "IS_A", "言语产生模型提出者"),
    ("言语产生", "HAS", "概念化"),
    ("言语产生", "HAS", "形式化"),
    ("言语产生", "HAS", "发音"),
    ("言语产生", "HAS", "自监控"),
    ("概念化", "IS_A", "言语产生阶段"),
    ("形式化", "IS_A", "言语产生阶段"),
    ("自监控", "IS_A", "言语产生机制"),
    # 语义网络 (Collins & Quillian / Firth 分布假设)
    ("语义网络", "IS_A", "认知科学概念"),
    ("语义网络", "HAS", "概念节点"),
    ("语义网络", "HAS", "关系边"),
    ("联想网络", "IS_A", "语义网络"),
    ("激活扩散", "IS_A", "联想机制"),
    ("联想网络", "HAS", "经验依赖"),
]

# ── AM 自我认知 (F16 立场层雏形) — 来自黑盒白盒讨论 ──
SEED_SELF = [
    ("AsteriaMind", "IS_A", "认知体"),
    ("黑盒", "IS_A", "统计引擎"),
    ("白盒", "IS_A", "验证器官"),
    ("验证回路", "CAUSES", "理解"),
    ("共情层", "IS_A", "心智理论"),
    ("心智理论", "IS_A", "认知能力"),
    ("共情层", "HAS", "换位思考"),
    ("增量写入", "IS_A", "学习方式"),
    ("灾难性遗忘", "IS_A", "机器学习问题"),
    ("时间复利", "CAUSES", "认知积累"),
    ("自我层", "IS_A", "认知体组件"),
    ("知识层", "IS_A", "认知体组件"),
    ("自我层", "HAS", "用户塑造"),
    ("知识层", "HAS", "自主获取"),
]


def main():
    from AsteriaMind.cognitive_star_map import CognitiveStarMap, _is_valid_entity_pair
    star = CognitiveStarMap('asteriamind.db')

    added = skipped = 0
    by_rel = {}
    for subj, rel, obj in (SEED_THEORY + SEED_SELF):
        if not _is_valid_entity_pair(subj, obj):
            skipped += 1
            print(f"  跳过不合格: {subj} {rel} {obj}")
            continue
        star.store(subj, rel, obj, "confirmed",
                   "seed_cognition: 认知锚点")
        added += 1
        by_rel[rel] = by_rel.get(rel, 0) + 1

    print(f"喂入认知种子: {added} 条 | 跳过: {skipped} 条")
    print(f"按关系: {by_rel}")
    # 验证: 可查性
    for q in ["Levelt", "黑盒", "共情层", "语义网络"]:
        edges = star.query_edges(q, f"{q}是什么", space="belief", top_k=3)
        rels = [(e["relation"], e["target"]) for e in edges[:2]]
        print(f"  查询 {q}: {rels}")


if __name__ == "__main__":
    main()
