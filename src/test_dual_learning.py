"""
双循环学习测试 — 验证在线学习 + 离线学习
"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.cognitive_star_map import CognitiveStarMap
from AsteriaMind.active_learner import ActiveLearner
from AsteriaMind.active_inference import ActiveInferenceEngine
from AsteriaMind.dream_module import DreamModule
from AsteriaMind.offline_learner import OfflineLearner
from AsteriaMind.falsification import WebSearchInterface, WebResult

# ── 1. 创建星图 (内存数据库) ──
star_map = CognitiveStarMap(":memory:")

# 先存一些已有知识
star_map.store("猫", "IS_A", "哺乳动物", "confirmed", "猫是哺乳动物")
star_map.store("狗", "IS_A", "哺乳动物", "confirmed", "狗是哺乳动物")
star_map.store("猫", "CAN", "喵", "confirmed", "猫会喵")
star_map.store("海豚", "IS_A", "哺乳动物", "confirmed", "海豚是哺乳动物")
print(f"初始星图: {star_map.count()} 条认知痕迹\n")

# ── 2. Mock web search (模拟真实搜索结果) ──
def mock_search(query, max_results=5):
    results = []
    if "企鹅" in query:
        results.append(WebResult(
            query=query, url="https://example.com/penguin",
            title="企鹅 - 维基百科",
            snippet="企鹅是鸟类，不是哺乳动物。企鹅属于鸟纲，是会游泳但不会飞的鸟类。",
            source_credibility=0.7
        ))
    if "哺乳动物" in query and ("特征" in query or "定义" in query):
        results.append(WebResult(
            query=query, url="https://example.com/mammal",
            title="哺乳动物特征",
            snippet="哺乳动物是胎生、哺乳的动物。猫是哺乳动物，狗是哺乳动物。鸟类不是哺乳动物。",
            source_credibility=0.6
        ))
    if "鸟类" in query and "特征" in query:
        results.append(WebResult(
            query=query, url="https://example.com/bird",
            title="鸟类特征",
            snippet="鸟类是卵生动物，有羽毛。企鹅是鸟类。",
            source_credibility=0.6
        ))
    return results

web_search = WebSearchInterface(search_fn=mock_search)

# ── 3. 创建 ActiveLearner ──
learner = ActiveLearner(star_map=star_map, web_search=web_search)

# ── 4. 测试在线学习 ──
print("=" * 50)
print("在线学习测试: 企鹅 IS_A 哺乳动物?")
print("=" * 50)
result = learner.learn_relation("企鹅", "IS_A", "哺乳动物")
print(f"  learned={result.get('learned')}")
print(f"  source={result.get('source')}")
if result.get('facts'):
    print(f"  学到 {len(result['facts'])} 条知识:")
    for f in result['facts']:
        print(f"    {f['subj']} {f['pred']} {f['obj']}")
elif result.get('pending'):
    print(f"  → 搜索未找到，已加入提问队列")
print()

# ── 5. 验证星图更新 ──
print("=" * 50)
print("星图验证: 企鹅相关知识")
print("=" * 50)
similar = star_map.query_similar(subj="企鹅", top_k=5)
for s in similar:
    print(f"  {s['subj']} {s['pred']} {s['obj']} (sim={s['similarity']:.2f}, fb={s['feedback']})")
if not similar:
    print("  (无)")
print(f"  星图总痕迹: {star_map.count()}")
print()

# ── 6. 测试离线学习 ──
print("=" * 50)
print("离线学习测试: AM 闲时自主学习")
print("=" * 50)
ai = ActiveInferenceEngine(star_map)
dream = DreamModule(star_map)
offline = OfflineLearner(
    star_map=star_map,
    active_inference=ai,
    dream_module=dream,
    active_learner=learner,
)
offline_result = offline.run_cycle()
print(f"  proposals={offline_result['proposals']}")
print(f"  winners={offline_result['winners']}")
print(f"  learned={offline_result['learned']}")
print(f"  skipped={offline_result['skipped']}")
print()

# ── 7. OfflineLearner summary ──
print("=" * 50)
print("OfflineLearner 汇总")
print("=" * 50)
summary = offline.summary()
print(f"  total_runs: {summary['total_runs']}")
print(f"  total_learned: {summary['total_learned']}")
bc = summary.get('budget_contest', {})
print(f"  budget_contest: total={bc.get('total_contests',0)}, random_wins={bc.get('random_wins',0)}")
print()

# ── 8. 最终星图状态 ──
print("=" * 50)
print(f"最终星图: {star_map.count()} 条认知痕迹")
print("=" * 50)
for row in star_map.conn.execute("SELECT subj, pred, obj, feedback FROM cognitive_traces"):
    print(f"  {row[0]} {row[1]} {row[2]} [{row[3]}]")

print("\n✅ 双循环学习测试完成")
