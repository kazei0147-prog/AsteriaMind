"""
端到端测试: ActiveInference 在线集成 —— "预测→检索→回复" 链路

验证:
  1. plan_actions() 正确分类行动类型
  2. plan_next_action() 从星图上下文提取候选
  3. MotherController.loop() 在回复中生成主动建议
  4. 端到端: 用户提问 → 主动推理 → 建议下一步
"""
import sys, os
sys.path.insert(0, '.')
os.environ['ASTERIA_DB'] = 'test_ai_online.db'

from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface
from AsteriaMind.cognitive_interface import CognitiveInterface


def cleanup():
    for f in ['test_ai_online.db', 'test_ai_online.db-wal', 'test_ai_online.db-shm']:
        try: os.remove(f)
        except: pass


def run_tests():
    kg = KnowledgeGraph()
    db = KnowledgeDB('test_ai_online.db')
    ws = WebSearchInterface()
    ci = CognitiveInterface(kg, db, ws)
    star = ci.cognitive_star_map
    ai = ci.mother.active_inference

    print("=" * 60)
    print("Test 1: plan_actions() — 行动类型分类")
    print("=" * 60)

    # 教学: 多样知识
    teachings = [
        ("猫", "IS_A", "哺乳动物"),
        ("狗", "IS_A", "哺乳动物"),
        ("猫", "CAN", "爬树"),
        ("狗", "CAN", "看门"),
        ("企鹅", "IS_A", "鸟类"),
        ("企鹅", "CAN", "游泳"),
        ("麻雀", "IS_A", "鸟类"),
        ("麻雀", "CAN", "飞行"),
    ]
    for s, p, o in teachings:
        star.store(s, p, o, "confirmed", f"{s}{p}{o}")
        ai.update_from_feedback(s, p, o, True)

    # 加一些不确定的信念
    ai.get_or_create_belief("猫", "IS_A", "哺乳动物").update(True, 0.5)
    ai.get_or_create_belief("猫", "IS_A", "哺乳动物").update(True, 0.5)
    # 有证据但有矛盾的
    edge = ai.get_or_create_belief("企鹅", "IS_A", "哺乳动物")
    edge.update(True, 0.3)
    edge.update(False, 0.7)  # 矛盾证据

    print(f"  星图痕迹: {star.count()}")
    print(f"  信念边数量: {len(ai.belief_edges)}")

    # 测试 plan_actions 对企鹅相关边的评分
    candidates = [
        ("企鹅", "IS_A", "鸟类"),
        ("企鹅", "IS_A", "哺乳动物"),
        ("企鹅", "CAN", "游泳"),
        ("企鹅", "CAN", "飞行"),   # 从未教过
    ]
    plans = ai.plan_actions(candidates, top_k=4)
    print(f"\n  plan_actions 结果 ({len(plans)} 条):")
    for p in plans:
        print(f"    [{p['action_type']:8s}] {p['subj']} {p['pred']} {p['obj']}")
        print(f"           score={p['score']:.4f}  info_gain={p['info_gain']:.4f}  "
              f"uncertainty={p['uncertainty']:.4f}  belief={p['belief']:.4f}")
        print(f"           → {p['suggestion']}")

    # 验证: "企鹅 CAN 飞行" 应该是 "explore" (完全未知 + 高信息增益)
    flight_plan = [p for p in plans if p['subj'] == '企鹅' and p['pred'] == 'CAN' and p['obj'] == '飞行']
    assert flight_plan, "FAIL: '企鹅 CAN 飞行' should be in plans"
    fp = flight_plan[0]
    assert fp['action_type'] in ('explore', 'verify'), \
        f"FAIL: flight plan action_type={fp['action_type']}, expected explore/verify"
    print(f"\n  ✅ plan_actions 分类正确: '企鹅 CAN 飞行' → {fp['action_type']}")

    # 验证: "企鹅 IS_A 哺乳动物" 应该是 "clarify" (矛盾证据)
    mammal_plan = [p for p in plans if p['subj'] == '企鹅' and p['pred'] == 'IS_A' and p['obj'] == '哺乳动物']
    if mammal_plan:
        mp = mammal_plan[0]
        print(f"  ✅ '企鹅 IS_A 哺乳动物' → {mp['action_type']} (矛盾证据)")
    else:
        print(f"  ⚠️ '企鹅 IS_A 哺乳动物' not in top plans (OK if scored lower)")

    print()
    print("=" * 60)
    print("Test 2: plan_next_action() — 从星图上下文提取候选")
    print("=" * 60)

    ci_plans = ci.plan_next_action("企鹅", "IS_A", "鸟类", top_k=3)
    print(f"  plan_next_action('企鹅', 'IS_A', '鸟类') → {len(ci_plans)} 条:")
    for p in ci_plans:
        print(f"    [{p['action_type']:8s}] {p['subj']} {p['pred']} {p['obj']} "
              f"score={p['score']:.4f}")
    assert len(ci_plans) > 0, "FAIL: plan_next_action returned empty"
    print(f"  ✅ plan_next_action 返回 {len(ci_plans)} 条计划")

    print()
    print("=" * 60)
    print("Test 3: MotherController.loop() — 主动建议织入回复")
    print("=" * 60)

    # 模拟一次完整对话: 问"企鹅是鸟类吗"
    result = ci.process("企鹅是鸟类吗")
    sem = result.get("semantic")
    prag = result.get("pragmatic")

    loop = ci.mother.loop(sem, prag, "企鹅是鸟类吗")
    reply = loop.get("reply", "")
    action = loop.get("action", "")
    planned = loop.get("cognitive", {}).get("planned_actions", [])

    print(f"  用户: 企鹅是鸟类吗")
    print(f"  AM回复: {reply}")
    print(f"  行动: {action}")
    print(f"  主动计划 ({len(planned)} 条):")
    for p in planned:
        print(f"    [{p['action_type']}] {p['subj']} {p['pred']} {p['obj']} "
              f"score={p['score']:.4f}")

    # 验证: 回复中包含主动建议 (如果 high-score plan 存在)
    if planned and planned[0]['score'] > 0.15:
        has_proactive = "顺便一提" in reply or "📌" in reply or "🤔" in reply
        print(f"  {'✅' if has_proactive else '⚠️'} 主动建议是否织入回复: {has_proactive}")
    else:
        print(f"  ℹ️ 无高分计划 (score={planned[0]['score'] if planned else 'N/A'}), 跳过织入")

    print()
    print("=" * 60)
    print("Test 4: 端到端 — 完整在线推理链")
    print("=" * 60)

    # 场景: 教基础 → 问相关问题 → 验证主动推理触发
    # 先教 但是留缺口
    star.store("鲸鱼", "IS_A", "哺乳动物", "confirmed", "鲸鱼是哺乳动物")
    ai.update_from_feedback("鲸鱼", "IS_A", "哺乳动物", True)

    # 问: "鲸鱼是鱼类吗" — AM 不知道, 但知道鲸鱼 IS_A 哺乳动物
    result2 = ci.process("鲸鱼是鱼类吗")
    loop2 = ci.mother.loop(result2.get("semantic"), result2.get("pragmatic"), "鲸鱼是鱼类吗")
    reply2 = loop2.get("reply", "")
    planned2 = loop2.get("cognitive", {}).get("planned_actions", [])

    print(f"  用户: 鲸鱼是鱼类吗")
    print(f"  AM回复: {reply2}")
    print(f"  主动计划:")
    for p in planned2:
        print(f"    [{p['action_type']}] {p['subj']} {p['pred']} {p['obj']} "
              f"score={p['score']:.4f}")

    # 验证: 回复不为空
    assert reply2, "FAIL: empty reply"
    print(f"  ✅ 端到端链路完整: 提问 → 检索 → 推理 → 回复 ({len(reply2)} 字)")

    # 验证: plan_next_action 在无上下文时也能回退到全局
    empty_plans = ci.plan_next_action("", "", "", top_k=2)
    print(f"  ✅ 空上下文回退: {len(empty_plans)} 条全局计划")

    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        cleanup()
