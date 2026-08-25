"""ID-024②③ 双路径蒸馏 + A/B 双层治理测试"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.cognitive_star_map import CognitiveStarMap
from AsteriaMind.argument_gate import ArgumentGate
from AsteriaMind.memory_consolidation import MemoryConsolidation

passed = 0

# ── T1: 双路径分岔 — 教→A / 学→B ──
star = CognitiveStarMap(":memory:")
star.store("鸵鸟", "IS_A", "鸟类", "confirmed", "鸵鸟是鸟类", source="teach")
star.store("蛇", "IS_A", "爬行动物", "confirmed", "搜索提取", source="learn")
t1a = star.conn.execute(
    "SELECT tier FROM directed_edges WHERE source='鸵鸟' AND relation='IS_A'").fetchone()[0]
t1b = star.conn.execute(
    "SELECT tier FROM directed_edges WHERE source='蛇' AND relation='IS_A'").fetchone()[0]
assert t1a == "A", f"教应进 A 层: {t1a}"
assert t1b == "B", f"学应进 B 层: {t1b}"
print(f"T1 双路径分岔 ✓  教→{t1a} / 学→{t1b}")
passed += 1

# ── T2: query_edges 带出 tier ──
edges = star.query_edges("鸵鸟", "鸵鸟是什么", space="belief")
assert edges and edges[0]["tier"] == "A", f"查询应带 tier: {edges}"
print(f"T2 查询带出 tier ✓  {edges[0]['target']} tier={edges[0]['tier']}")
passed += 1

# ── T3: B→A 四锚升级 (锚1: 用户 confirmed ≥ 3 次) ──
star2 = CognitiveStarMap(":memory:")
for _ in range(3):
    star2.store("企鹅", "IS_A", "鸟类", "confirmed", "语料涌现", source="learn")
mc = MemoryConsolidation(star2)
r = mc.consolidate()
t3 = star2.conn.execute(
    "SELECT tier FROM directed_edges WHERE source='企鹅' AND relation='IS_A'").fetchone()[0]
assert t3 == "A", f"confirmed×3 应升级 A: {t3}"
assert r["promoted_to_a"] >= 1, f"promoted 应 ≥1: {r}"
print(f"T3 B→A 升级 ✓  promoted={r['promoted_to_a']} 企鹅→{t3}")
passed += 1

# ── T4: A 层保护 — B 层反边不压制 A 层边 ──
star3 = CognitiveStarMap(":memory:")
star3.store("X", "IS_A", "Y", "confirmed", "用户教", source="teach")   # A 层, weight=1
for _ in range(10):
    star3.store("X", "NOT_IS_A", "Y", "confirmed", "搜索反证", source="learn")  # B 层, weight=10
gate = ArgumentGate(star3)
cand = [{"source": "X", "relation": "IS_A", "target": "Y",
         "salience": 0.5, "energy": 1.0, "confidence": 0.8}]
_, aud = gate.evaluate("X", [dict(c) for c in cand])
assert len(aud["eliminated"]) == 0, f"A 层边不应被 B 层反边压制: {aud['eliminated']}"
# 对照组: B 层候选会被 B 层反边压制
star3b = CognitiveStarMap(":memory:")
for _ in range(1):
    star3b.store("X", "IS_A", "Y", "confirmed", "搜索", source="learn")  # B, weight=1
for _ in range(10):
    star3b.store("X", "NOT_IS_A", "Y", "confirmed", "搜索反证", source="learn")  # B, weight=10
gate_b = ArgumentGate(star3b)
_, aud_b = gate_b.evaluate("X", [dict(c) for c in cand])
assert len(aud_b["eliminated"]) == 1, f"B 层候选应被压制: {aud_b['eliminated']}"
print(f"T4 A 层保护 ✓  A 层免疫 B 反边 / B 层对照被压制")
passed += 1

# ── T5: A→B 降级 — A 层非终身制, 矛盾调和败者降级 ──
star4 = CognitiveStarMap(":memory:")
star4.store("X", "IS_A", "Y", "confirmed", "用户教", source="teach")   # A, weight=1
for _ in range(10):
    star4.store("X", "NOT_IS_A", "Y", "confirmed", "强反证", source="learn")  # B, weight=10
mc4 = MemoryConsolidation(star4)
mc4.consolidate()
t5 = star4.conn.execute(
    "SELECT tier FROM directed_edges WHERE source='X' AND relation='IS_A'").fetchone()[0]
assert t5 == "B", f"矛盾调和败者应降级 B: {t5}"
print(f"T5 A→B 降级 ✓  被强反证调和的 A 层边 → {t5}")
passed += 1

# ── T6: 增长模型 W(t) 快照 ──
g = r.get("growth", {})
assert "W" in g and "tier_a" in g and "tier_b" in g, f"growth 快照缺字段: {g}"
assert g["W"] >= 1 and g["tier_a"] + g["tier_b"] == g["W"], f"tier 分布应等于 W: {g}"
print(f"T6 增长快照 ✓  W={g['W']} A={g['tier_a']} B={g['tier_b']}")
passed += 1

print(f"\n✅ 双路径+A/B 双层 {passed}/6 通过")
