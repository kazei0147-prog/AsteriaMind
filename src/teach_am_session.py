"""
AM 综合教学会话 — 验证全链路: 学习→检索→反思→语料库涌现

不依赖特定数据库，纯 HTTP API 驱动。
"""
import urllib.request, json, time, sys

BASE = "http://127.0.0.1:8866"
HEADERS = {"Content-Type": "application/json"}

def talk(text):
    """发送一条消息给 AM"""
    req = urllib.request.Request(
        f"{BASE}/api/talk",
        data=json.dumps({"text": text}).encode('utf-8'),
        headers=HEADERS,
    )
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read().decode('utf-8'))
    return data

def reflect():
    """获取当前会话的自我评估"""
    resp = urllib.request.urlopen(f"{BASE}/api/reflect")
    return json.loads(resp.read().decode('utf-8'))

def health():
    """获取系统健康报告"""
    resp = urllib.request.urlopen(f"{BASE}/api/health")
    return json.loads(resp.read().decode('utf-8'))


def run_session():
    print("=" * 65)
    print("🧠 AsteriaMind 教学会话 — 全链路验证")
    print("=" * 65)

    # ══════════════════════════════════
    # Phase 1: 教学基础
    # ══════════════════════════════════
    print("\n📖 Phase 1: 教基础知识")
    print("-" * 45)

    lessons = [
        "猫是哺乳动物",
        "狗是哺乳动物",
        "企鹅是鸟类",
        "麻雀会飞行",
        "企鹅会游泳",
        "海豚是哺乳动物",
        "鲸鱼是哺乳动物",
    ]
    for lesson in lessons:
        r = talk(lesson)
        cog = r.get("cognitive", {})
        print(f"  教「{lesson}」")
        print(f"    → {r['reply'][:60]}...")
        time.sleep(0.3)

    # ══════════════════════════════════
    # Phase 2: 询问 (触发在线学习)
    # ══════════════════════════════════
    print("\n🔍 Phase 2: 查询 — 触发在线搜索学习")
    print("-" * 45)

    queries = [
        "企鹅是哺乳动物吗",
        "麻雀是哺乳动物吗",
        "鲸鱼是鱼类吗",
    ]
    for q in queries:
        r = talk(q)
        cog = r.get("cognitive", {})
        source = cog.get("source", "")
        planned = cog.get("planned_actions", [])

        print(f"  问「{q}」")
        print(f"    → {r['reply'][:80]}...")
        print(f"    source={source}")

        # 主动推理
        if planned:
            top = planned[0]
            print(f"    💡 主动计划: [{top.get('action_type')}] {top.get('subj')} {top.get('pred','')} {top.get('obj','')}")

        # 反馈信号
        fb = r.get("prev_feedback", {})
        if fb and fb.get("signal") != "no_session":
            print(f"    📋 上轮反馈: {fb.get('signal')} (correct={fb.get('was_correct')})")

        time.sleep(1.5)  # DuckDuckGo 频率限制

    # ══════════════════════════════════
    # Phase 3: 纠正 — 触发反思闭环
    # ══════════════════════════════════
    print("\n🔧 Phase 3: 故意说错 → 纠正 → 观察反思")
    print("-" * 45)

    # AM 说"猫是鸟类" (故意错误)
    r1 = talk("猫是鸟类")
    print(f"  教错误知识「猫是鸟类」→ {r1['reply'][:60]}...")

    # 下一轮纠正
    r2 = talk("不对，猫是哺乳动物，不是鸟类")
    cog = r2.get("cognitive", {})
    fb = r2.get("prev_feedback", {})
    was_correct = r2.get("last_feedback", {})

    print(f"  纠正「不对，猫是哺乳动物」→ {r2['reply'][:60]}...")
    print(f"  上轮反馈信号: {fb.get('signal')}")
    print(f"  上轮是否正确: {fb.get('was_correct')}")

    # 再问
    r3 = talk("猫是鸟类吗")
    print(f"  再问「猫是鸟类吗」→ {r3['reply'][:80]}...")
    time.sleep(1)

    # ══════════════════════════════════
    # Phase 4: 观察反思 + 语料库
    # ══════════════════════════════════
    print("\n📊 Phase 4: 会话反思 + 系统健康")
    print("-" * 45)

    # 自我评估
    assessment = reflect()
    print(f"  会话评估:")
    print(f"    会话ID: {assessment.get('session_id', 'N/A')[:20]}...")
    print(f"    总轮数: {assessment.get('total_exchanges', 0)}")
    print(f"    准确率: {assessment.get('accuracy', 0):.0%}")
    print(f"    确认: {assessment.get('confirmed', 0)}  纠正: {assessment.get('corrected', 0)}")
    print(f"    状态: {assessment.get('status', 'N/A')}")

    if assessment.get("suggestions"):
        print(f"    改进建议:")
        for s in assessment["suggestions"]:
            print(f"      [{s.get('priority','')}] {s.get('message','')[:80]}")

    # 模块权重
    weights = assessment.get("module_weights", {})
    if weights:
        print(f"    模块权重:")
        for mod, w in weights.items():
            print(f"      {mod}: 准确率={w.get('accuracy',0):.0%} 权重={w.get('weight',0):.2f}")

    # 系统健康
    h = health()
    print(f"\n  系统健康:")
    print(f"    状态: {h.get('status', 'N/A')}")
    print(f"    平均误差: {h.get('avg_error', 0):.4f}")
    print(f"    星图痕迹: {h.get('star_map_traces', 0)}")
    mc_weights = h.get("meta_cognition_weights", {})
    if mc_weights:
        print(f"    MetaCognition 学习权重:")
        for mod, w in mc_weights.items():
            print(f"      {mod}: 准确率={w.get('accuracy',0):.1%} 权重={w.get('weight',0):.2f} (样本={w.get('evidence',0)})")

    # 语料库统计
    print(f"\n  语料库:")
    print(f"    表达模式: {assessment.get('lang_patterns_total', 'N/A')}")
    print(f"    词级共现: {assessment.get('word_cooccur_total', 'N/A')}")
    div = assessment.get("pattern_diversity", {})
    if div:
        rich_count = sum(1 for v in div.values() if v.get("rich"))
        print(f"    丰富场景: {rich_count}/{len(div)}")
        for scene, stats in div.items():
            if stats.get("rich"):
                print(f"      {scene}: {stats['unique_openers']} 种开头 × {stats['total_patterns']} 条")

    print("\n" + "=" * 65)
    print("✅ 全链路验证完成")
    print("=" * 65)


if __name__ == "__main__":
    try:
        run_session()
    except urllib.error.URLError as e:
        print(f"❌ 连接失败: {e}")
        print("请先启动: cd D:\\AM\\HiveMind_repo\\src && python asteriamind_web.py")
        sys.exit(1)
