"""
端到端测试: 真实 Web 搜索 → 知识同化 → 回答
完全对齐 web 入口的调用链路: process() → mother.loop()
"""
import sys, os, warnings
warnings.filterwarnings('ignore')

# 确保能 import duckduckgo_search (装在 venv 里)
venv_site = 'C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Lib/site-packages'
if venv_site not in sys.path:
    sys.path.insert(0, venv_site)

sys.path.insert(0, '.')

from AsteriaMind.cognitive_interface import CognitiveInterface
from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface, _default_web_search

# 用临时 db
db_path = 'test_websearch_e2e.db'
if os.path.exists(db_path):
    os.remove(db_path)

kg = KnowledgeGraph()
db = KnowledgeDB(db_path)
ws = WebSearchInterface()
ci = CognitiveInterface(kg, db, ws)

print("=" * 60)
print("端到端测试: 真实 Web 搜索")
print("=" * 60)

# Step 0: 先直接测试 _default_web_search
print("\n--- Step 0: 直接测试 _default_web_search ---")
raw = _default_web_search("企鹅 分类 鸟类", max_results=3)
print(f"  返回 {len(raw)} 条结果")
for i, r in enumerate(raw[:2]):
    print(f"  [{i+1}] title: {r.title[:60]}")
    print(f"      snippet: {r.snippet[:120]}")
    print(f"      credibility: {r.source_credibility}")

# Step 1: 教基础知识 (走 mother.loop 的 fact_learn 分支)
print("\n--- Step 1: 教基础知识 ---")
teach_inputs = ["猫是哺乳动物", "狗是哺乳动物", "鸟有羽毛"]
for text in teach_inputs:
    result = ci.process(text)
    loop = ci.mother.loop(result.get("semantic"), result.get("pragmatic"), text)
    print(f"  教: {text}")
    print(f"  AM: {loop.get('reply', '')[:80]}")

star_count = ci.cognitive_star_map.count()
print(f"\n  星图当前: {star_count} 条认知痕迹")

# Step 2: 问未知问题 — 应触发在线学习
print("\n--- Step 2: 问未知问题 (触发在线学习) ---")
query = "企鹅是哺乳动物吗"
print(f"  用户: {query}")

result = ci.process(query)
loop = ci.mother.loop(result.get("semantic"), result.get("pragmatic"), query)
reply = loop.get("reply", "")
cognitive = loop.get("cognitive", {})
print(f"  AM 回复: {reply}")
print(f"  认知结构:")
print(f"    subject: {cognitive.get('subject', '')}")
print(f"    relation: {cognitive.get('relation', '')}")
print(f"    object: {cognitive.get('object', '')}")
print(f"    confidence: {cognitive.get('confidence', 0)}")
print(f"    source: {cognitive.get('source', '')}")
print(f"    evidence: {cognitive.get('evidence', [])}")

star_count_after = ci.cognitive_star_map.count()
print(f"\n  星图更新后: {star_count_after} 条 (增加 {star_count_after - star_count})")

# Step 3: 再问一次 — 应从已学知识回答
print("\n--- Step 3: 再问一次 (应从已学知识回答) ---")
result2 = ci.process(query)
loop2 = ci.mother.loop(result2.get("semantic"), result2.get("pragmatic"), query)
print(f"  AM 回复: {loop2.get('reply', '')}")
cognitive2 = loop2.get("cognitive", {})
print(f"    confidence: {cognitive2.get('confidence', 0)}")
print(f"    source: {cognitive2.get('source', '')}")
print(f"    evidence: {cognitive2.get('evidence', [])}")

# 清理
db.close()
for ext in ['', '-wal', '-shm']:
    p = db_path + ext
    if os.path.exists(p):
        try:
            os.remove(p)
        except:
            pass

print("\n" + "=" * 60)
print("端到端测试完成")
print("=" * 60)
