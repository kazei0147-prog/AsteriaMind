"""真机验证: 真实 ddgs 搜索 → ActiveLearner 提取 → 星图入库 (不 mock)"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.cognitive_star_map import CognitiveStarMap
from AsteriaMind.active_learner import ActiveLearner
from AsteriaMind.falsification import WebSearchInterface

star_map = CognitiveStarMap(":memory:")
web_search = WebSearchInterface()  # 默认 search_fn → _default_web_search → ddgs

print("── 1. 底层搜索接口直测 ──")
rs = web_search.search("鸵鸟是什么动物", max_results=3)
for r in rs[:3]:
    print(f"  [{r.source_credibility}] {r.title[:40]} | {r.snippet[:60]}")
assert not any("(search://" in r.url for r in rs), "仍是占位符!"
print("  ✅ 真实结果, 无占位符\n")

print("── 2. learn_relation 在线学习闭环 ──")
learner = ActiveLearner(star_map=star_map, web_search=web_search)
result = learner.learn_relation("鸵鸟", "IS_A", "鸟类")
print(f"  learned={result.get('learned')} source={result.get('source')}")
for f in (result.get('facts') or []):
    print(f"    学到: {f['subj']} {f['pred']} {f['obj']}")

print("\n── 3. 星图入库验证 ──")
rows = list(star_map.conn.execute(
    "SELECT DISTINCT subj, pred, obj FROM cognitive_traces WHERE subj='鸵鸟'"))
for r in rows:
    print(f"  {r[0]} {r[1]} {r[2]}")
print(f"  星图总痕迹: {star_map.count()}")
ok = len(rows) > 0 and (result.get('learned') or 0) >= 0
print("\n✅ 搜索→提取→入库 闭环打通" if rows else "\n⚠️ 入库为空, 需人工核查提取逻辑")
