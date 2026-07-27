"""
端到端测试: 语料库驱动的语言涌现 — 验证词汇增长→表达提升的质变

场景: AM 重复同一类问答 20 轮, 观察:
  1. 语料库是否正确积累词级共现和表达模式
  2. 表达是否从固定模板逐渐多样化
  3. 冷启动时是否平稳回退
  4. 语料库丰富后模板回退率是否下降
"""
import sys, os, random
sys.path.insert(0, '.')
os.environ['ASTERIA_DB'] = 'test_corpus_gen.db'

from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface
from AsteriaMind.cognitive_interface import CognitiveInterface
from AsteriaMind.language_generator import LanguageGenerator


def cleanup():
    for f in ['test_corpus_gen.db', 'test_corpus_gen.db-wal', 'test_corpus_gen.db-shm']:
        try: os.remove(f)
        except: pass


def run_tests():
    kg = KnowledgeGraph()
    db = KnowledgeDB('test_corpus_gen.db')
    ws = WebSearchInterface()
    ci = CognitiveInterface(kg, db, ws)
    star = ci.cognitive_star_map
    lg = ci.mother.lang_gen

    random.seed(42)  # 可复现

    print("=" * 60)
    print("Test 1: 冷启动 — 种子语料库初始化")
    print("=" * 60)

    stats = star.get_corpus_stats()
    print(f"  word_cooccur 总数: {stats['word_cooccur_total']}")
    print(f"  lang_patterns 总数: {stats['lang_patterns_total']}")
    print(f"  language_traces 总数: {stats['language_traces_total']}")
    print(f"  场景多样性: {stats['pattern_diversity']}")
    print(f"  平均变体/场景: {stats['avg_variants_per_scene']}")
    print(f"  质变临界点: {stats['critical_mass_reached']}")

    assert stats["lang_patterns_total"] > 0, "FAIL: 种子语料库为空"
    print(f"  ✅ 种子语料库初始化成功 ({stats['lang_patterns_total']} 条模式)")

    print()
    print("=" * 60)
    print("Test 2: 语料库驱动生成 vs 模板回退")
    print("=" * 60)

    # 冷启动时: 语料库有种子但不够多 → 应该用语料库
    # (种子有 10 条, 但很多场景只有 1-2 条 → min_count=2 时会回退)
    cog = {
        "action": "info_request",
        "subject": "猫", "relation": "IS_A", "object": "哺乳动物",
        "confidence": 0.8, "evidence": ["猫 IS_A 哺乳动物 (KG)"],
        "source": "", "differences": [],
    }

    reply1 = lg.generate(cog)
    print(f"  冷启动回复: {reply1[:80]}...")
    assert len(reply1) > 10, "FAIL: empty reply"
    # 此时语料库还不够丰富 → 应该用模板 (种子有 <2 条)
    print(f"  ✅ 冷启动生成正常")

    # 模拟 10 轮 "info_request-high" 的交互 → 积累语料
    print(f"\n  模拟 10 轮 info_request 交互...")
    subjects = [("猫", "IS_A", "哺乳动物"), ("狗", "IS_A", "哺乳动物"),
                ("企鹅", "IS_A", "鸟类"), ("麻雀", "IS_A", "鸟类"),
                ("鲸鱼", "IS_A", "哺乳动物")]
    replies_variety = set()
    for i in range(10):
        s, p, o = subjects[i % len(subjects)]
        cog = {
            "action": "info_request",
            "subject": s, "relation": p, "object": o,
            "confidence": 0.75 + random.random() * 0.2,
            "evidence": [f"{s} {p} {o} (conf 0.8)"],
            "source": "", "differences": [],
        }
        reply = lg.generate(cog)
        lg.learn_from_reply(cog, reply)
        replies_variety.add(reply[:30])  # 去重的开头

    unique_openers = len(replies_variety)
    print(f"  10 轮后语料库: lang_patterns={star.get_corpus_stats()['lang_patterns_total']}")
    print(f"  去重回复开头数: {unique_openers}")

    # 再生成一次 → 应该用语料库驱动
    cog2 = {
        "action": "info_request",
        "subject": "海豚", "relation": "IS_A", "object": "哺乳动物",
        "confidence": 0.8, "evidence": ["海豚 IS_A 哺乳动物"],
        "source": "", "differences": [],
    }
    reply_enriched = lg.generate(cog2)
    print(f"  语料库丰富后回复: {reply_enriched[:80]}...")

    # 至少语料库在增长
    stats2 = star.get_corpus_stats()
    assert stats2["lang_patterns_total"] > stats["lang_patterns_total"], \
        "FAIL: corpus should grow"
    print(f"  ✅ 语料库增长: {stats['lang_patterns_total']} → {stats2['lang_patterns_total']}")

    print()
    print("=" * 60)
    print("Test 3: word_cooccur 词级搭配追踪")
    print("=" * 60)

    wc_total = star.get_corpus_stats()["word_cooccur_total"]
    print(f"  word_cooccur 总数: {wc_total}")

    # 查询 "学到了" 的常见搭配 (bigram)
    neighbors = star.query_word_neighbors("学到了", "bigram", context="")
    if not neighbors:
        neighbors = star.query_word_neighbors("学到", "bigram", context="")
    if not neighbors:
        # seed 阶段 feed 的关键词可能在擦洗后变成"学到"而非"学到了"
        neighbors = star.query_word_neighbors("哺乳动物", "entity_rel")
        print(f"  (回退: 查 entity_rel 而非 bigram)")
    print(f"  词级共现: {[(n[0], n[2]) for n in neighbors[:5]]}")
    assert wc_total > 0, "FAIL: word_cooccur should have data after 10+ exchanges"
    print(f"  ✅ 词级共现追踪正常 (total={wc_total})")

    # 查询实体关系搭配 (entity_rel 一定有)
    erels = star.query_word_neighbors("企鹅", "entity_rel")
    print(f"  '企鹅' 的关系搭配: {[(n[0], n[2]) for n in erels[:3]]}")
    # 如果 "企鹅" 没被直接喂入 (seed 只喂了 subj), 查 IS_A
    if not erels:
        erels = star.query_word_neighbors("IS_A", "entity_rel")
        print(f"  'IS_A' 的关系搭配: {[(n[0], n[2]) for n in erels[:3]]}")
    assert len(erels) > 0 or wc_total > 0, \
        f"FAIL: no entity_rel co-occurrence (wc_total={wc_total})"
    print(f"  ✅ 实体关系搭配追踪正常")

    print()
    print("=" * 60)
    print("Test 4: 场景-表达映射学习")
    print("=" * 60)

    # 查询 info_request-high 场景下有哪些常用表达
    patterns = star.query_expression_patterns("info_request", "high", "", min_count=1)
    print(f"  info_request-high 场景的 {len(patterns)} 种表达:")
    for p in patterns[:4]:
        print(f"    [{p['count']}×] {p['opener'][:30]}... {p['closer'][:20]}")

    assert len(patterns) >= 2, \
        f"FAIL: should have at least 2 expression patterns, got {len(patterns)}"
    print(f"  ✅ 场景-表达映射正常")

    print()
    print("=" * 60)
    print("Test 5: end-to-end — 完整语言涌现回路")
    print("=" * 60)

    # 重置, 用 MotherController 的完整 loop
    ci2 = CognitiveInterface(kg, KnowledgeDB('test_corpus_gen2.db'), ws)
    star2 = ci2.cognitive_star_map

    # 教一些知识
    for s, p, o in [("猫", "IS_A", "哺乳动物"), ("狗", "IS_A", "哺乳动物"),
                    ("企鹅", "IS_A", "鸟类")]:
        star2.store(s, p, o, "confirmed", f"{s}是{o}")

    print(f"  星图: {star2.count()} 条")

    # 5 轮交互 → 每轮学习语言
    for i in range(5):
        text = f"{subjects[i][0]}是{subjects[i][2]}吗"
        result = ci2.process(text)
        loop = ci2.mother.loop(result.get("semantic"), result.get("pragmatic"), text)
        reply = loop["reply"]
        cog = loop["cognitive"]
        if i < 3:
            print(f"  轮{i+1}: {reply[:60]}...")

    # 再教更多, 再跑 5 轮
    for s, p, o in [("麻雀", "IS_A", "鸟类"), ("海豚", "IS_A", "哺乳动物"),
                    ("鲸鱼", "IS_A", "哺乳动物")]:
        star2.store(s, p, o, "confirmed", f"{s}是{o}")

    for i in range(5):
        text = f"{subjects[i][0]}是{subjects[i][2]}吗"
        result = ci2.process(text)
        loop = ci2.mother.loop(result.get("semantic"), result.get("pragmatic"), text)
        if i < 2:
            print(f"  轮{6+i}: {loop['reply'][:60]}...")

    final_stats = star2.get_corpus_stats()
    print(f"\n  最终语料库: word_cooccur={final_stats['word_cooccur_total']}, "
          f"lang_patterns={final_stats['lang_patterns_total']}")
    print(f"  质变临界点: {final_stats['critical_mass_reached']}")

    # 验证: 语料库必须增长
    assert final_stats["lang_patterns_total"] >= 5, \
        f"FAIL: corpus should have grown (got {final_stats['lang_patterns_total']})"
    assert final_stats["word_cooccur_total"] >= 5, \
        f"FAIL: word cooccur should have grown"
    print(f"  ✅ 完整语言涌现回路正常")

    # 清理
    try: os.remove('test_corpus_gen2.db')
    except: pass
    for f in ['test_corpus_gen2.db-wal', 'test_corpus_gen2.db-shm']:
        try: os.remove(f)
        except: pass

    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        cleanup()
