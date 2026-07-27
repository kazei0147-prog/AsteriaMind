"""
端到端测试: MetaReasoning 反映射闭环

验证:
  1. SessionReflector 正确捕获反馈信号
  2. 自我评估生成准确的诊断
  3. MetaCognition 权重从反馈中学习
  4. MotherController.loop() 处理上轮反馈
  5. 端到端: 多轮对话 → 反馈 → 反思 → 评估
"""
import sys, os
sys.path.insert(0, '.')
os.environ['ASTERIA_DB'] = 'test_reflection.db'

from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface
from AsteriaMind.cognitive_interface import CognitiveInterface
from AsteriaMind.reflection import SessionReflector, FeedbackSignal


def cleanup():
    for f in ['test_reflection.db', 'test_reflection.db-wal', 'test_reflection.db-shm']:
        try: os.remove(f)
        except: pass


def run_tests():
    kg = KnowledgeGraph()
    db = KnowledgeDB('test_reflection.db')
    ws = WebSearchInterface()
    ci = CognitiveInterface(kg, db, ws)

    print("=" * 60)
    print("Test 1: SessionReflector — 反馈信号捕获")
    print("=" * 60)

    reflector = SessionReflector("test_session")

    # 记录一轮对话
    reflector.record_exchange(
        question="猫是什么",
        answer="猫是一种哺乳动物",
        confidence=0.7,
        action="info_request",
        modules={"semantic": 1.0, "meta_cognition": 1.0},
    )

    # 模拟用户下一轮输入 — 纠正
    fb1 = reflector.capture_feedback("不对，猫是猫科动物")
    print(f"  纠正信号: {fb1}")
    assert fb1["signal"] == FeedbackSignal.CORRECTION, \
        f"FAIL: expected CORRECTION, got {fb1['signal']}"
    assert fb1["was_correct"] == False
    print(f"  ✅ 纠正反馈捕获正确")

    # 再一轮
    reflector.record_exchange(
        question="企鹅是什么",
        answer="企鹅是一种鸟类",
        confidence=0.8,
        action="info_request",
        modules={"semantic": 1.0, "meta_cognition": 1.0},
    )
    fb2 = reflector.capture_feedback("对的，企鹅是鸟类")
    print(f"  肯定信号: {fb2}")
    assert fb2["signal"] == FeedbackSignal.EXPLICIT_POSITIVE, \
        f"FAIL: expected POSITIVE, got {fb2['signal']}"
    assert fb2["was_correct"] == True
    print(f"  ✅ 肯定反馈捕获正确")

    # 追问 (共享关键词)
    reflector.record_exchange(
        question="狗是哺乳动物吗",
        answer="对——狗是一种哺乳动物",
        confidence=0.75,
        action="info_request",
        modules={"semantic": 1.0, "meta_cognition": 1.0},
    )
    fb3 = reflector.capture_feedback("那汪汪汪呢")
    print(f"  追问信号: {fb3}")
    # 追问应该算弱正面(至少没纠正)
    assert fb3["was_correct"] == True or fb3["signal"] == FeedbackSignal.ENGAGEMENT
    print(f"  ✅ 追问反馈捕获正确")

    # 话题转移
    reflector.record_exchange(
        question="麻雀是什么",
        answer="麻雀是一种鸟类",
        confidence=0.85,
        action="info_request",
        modules={"semantic": 1.0, "meta_cognition": 1.0},
    )
    fb4 = reflector.capture_feedback("今天天气怎么样")
    print(f"  转移信号: {fb4}")
    assert fb4["signal"] == FeedbackSignal.DISENGAGEMENT
    assert fb4["was_correct"] == False
    print(f"  ✅ 话题转移反馈捕获正确")

    reflector.close_session()

    print()
    print("=" * 60)
    print("Test 2: 自我评估生成")
    print("=" * 60)

    assessment = reflector.generate_self_assessment()
    print(f"  会话: {assessment['session_id']}")
    print(f"  总轮数: {assessment['total_exchanges']}")
    print(f"  准确率: {assessment['accuracy']:.0%}")
    print(f"  确认: {assessment['confirmed']}  纠正: {assessment['corrected']}")
    print(f"  状态: {assessment['status']}")
    print(f"  摘要: {assessment['summary'][:80]}...")

    assert assessment["total_exchanges"] == 4
    assert assessment["corrected"] >= 1  # 至少猫那一轮被纠正
    assert assessment["status"] in ("healthy", "needs_improvement")

    if assessment["suggestions"]:
        print(f"  改进建议 ({len(assessment['suggestions'])} 条):")
        for s in assessment["suggestions"]:
            print(f"    [{s['priority']}] {s['message'][:80]}")

    lessons = reflector.get_lessons_for_next_session()
    print(f"\n  下次会话教训: accuracy={lessons['accuracy']:.0%}, "
          f"overconfidence_warning={lessons['overconfidence_warning']}")
    print(f"  ✅ 自我评估生成正确")

    print()
    print("=" * 60)
    print("Test 3: MetaCognition 权重学习")
    print("=" * 60)

    mc = ci.mother.meta_cognition
    print(f"  初始权重 (semantic): {mc.get_module_weight('semantic'):.2f}")

    # 模拟多轮反馈: semantic 模块 5 次正确
    for _ in range(5):
        mc.learn_from_reflection("semantic", True)
    print(f"  5次正确后: {mc.get_module_weight('semantic'):.2f}")
    assert mc.get_module_weight("semantic") > 1.0, \
        f"FAIL: weight should be > 1.0 after correct feedback"

    # pragmatic 模块 3 次错误
    for _ in range(3):
        mc.learn_from_reflection("pragmatic", False)
    print(f"  pragmatic 3次错误后: {mc.get_module_weight('pragmatic'):.2f}")
    assert mc.get_module_weight("pragmatic") < 1.0, \
        f"FAIL: weight should be < 1.0 after errors"

    # 测试加权投票
    signals = {
        "semantic": {"action": "info_request", "confidence": 0.7},
        "pragmatic": {"action": "fact_learn", "confidence": 0.6},
    }
    result = mc.arbitrate(signals)
    print(f"  裁决: {result['action']} (conf={result['confidence']:.0%})")
    print(f"  使用权重: {result['weights_used']}")
    # semantic 权重高 → info_request 应胜出
    assert result["action"] == "info_request", \
        f"FAIL: expected info_request to win with higher weight"
    print(f"  ✅ 权重学习正确影响裁决结果")

    print()
    print("=" * 60)
    print("Test 4: MotherController — 反馈闭环集成")
    print("=" * 60)

    # 使用 CognitiveInterface 的会话管理
    reflector2 = ci.start_reflection_session("test_loop")

    # 第一轮: 无上轮反馈
    result1 = ci.process("猫是哺乳动物吗")
    loop1 = ci.mother.loop(
        result1.get("semantic"), result1.get("pragmatic"),
        "猫是哺乳动物吗", {})
    print(f"  轮1 回复: {loop1['reply'][:60]}...")
    print(f"  轮1 reflection_ctx: {bool(loop1.get('reflection_ctx'))}")
    assert loop1.get("reflection_ctx"), "FAIL: missing reflection_ctx"
    assert loop1.get("was_correct_last") is None, \
        "FAIL: first round should have no prev feedback"
    print(f"  ✅ 首轮正确 (无上轮反馈)")

    # 第二轮: 传入上轮上下文 + 模拟用户纠正
    ctx2 = loop1["reflection_ctx"]
    ctx2["pending_feedback"] = {
        "signal": FeedbackSignal.CORRECTION,
        "detail": "用户: 不对", "was_correct": False,
    }
    result2 = ci.process("猫是猫科动物")  # 纠正输入
    loop2 = ci.mother.loop(
        result2.get("semantic"), result2.get("pragmatic"),
        "猫是猫科动物", ctx2)
    print(f"  轮2 回复: {loop2['reply'][:60]}...")
    print(f"  轮2 was_correct_last: {loop2.get('was_correct_last')}")
    assert loop2.get("was_correct_last") == False, \
        "FAIL: should detect previous was wrong"
    print(f"  ✅ 反馈闭环正确传递 (纠正→学习)")

    # 第三轮: 传入上轮上下文 + 肯定
    ctx3 = loop2["reflection_ctx"]
    ctx3["pending_feedback"] = {
        "signal": FeedbackSignal.EXPLICIT_POSITIVE,
        "detail": "用户: 对的", "was_correct": True,
    }
    result3 = ci.process("企鹅是鸟类")
    loop3 = ci.mother.loop(
        result3.get("semantic"), result3.get("pragmatic"),
        "企鹅是鸟类", ctx3)
    print(f"  轮3 回复: {loop3['reply'][:60]}...")
    print(f"  轮3 was_correct_last: {loop3.get('was_correct_last')}")
    assert loop3.get("was_correct_last") == True, \
        "FAIL: should detect previous was correct"
    print(f"  ✅ 反馈闭环正确传递 (肯定→学习)")

    # 结束会话 → 自我评估
    assessment2 = ci.end_reflection_session("test_loop")
    print(f"\n  会话评估: accuracy={assessment2.get('accuracy',0):.0%}")
    print(f"  权重学习结果: {ci.mother.meta_cognition.get_all_weights()}")

    print()
    print("=" * 60)
    print("Test 5: CognitiveInterface 会话管理")
    print("=" * 60)

    r3 = ci.start_reflection_session("manual_session")
    print(f"  开始会话: {r3.session_id}")
    assert ci._active_session_id == "manual_session"

    # 快速问答序列
    ci.mother.reflector.record_exchange("A是B吗", "对——A是B", 0.8, "info_request",
        {"semantic": 1.0, "meta_cognition": 1.0})
    fb5 = ci.capture_feedback("对", "manual_session")
    print(f"  反馈捕获: {fb5['signal']}")

    ci.mother.reflector.record_exchange("C是D吗", "C是D", 0.9, "info_request",
        {"semantic": 1.0, "meta_cognition": 1.0})
    fb6 = ci.capture_feedback("不对，C不是D", "manual_session")
    print(f"  反馈捕获: {fb6['signal']}")

    mid_assessment = ci.get_session_reflection("manual_session")
    print(f"  中期评估 (2轮): accuracy={mid_assessment.get('accuracy',0):.0%} "
          f"(应为50%: 1对1错)")

    # 结束
    final = ci.end_reflection_session("manual_session")
    print(f"  最终评估: accuracy={final.get('accuracy',0):.0%}")
    print(f"  总轮数: {final.get('total_exchanges',0)}")
    print(f"  ✅ 会话管理完整")

    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        cleanup()
