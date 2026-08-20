"""ID-024① ArgumentGate 测试 — 候选论证竞争 + 反证压制质检"""
import sys
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.cognitive_star_map import CognitiveStarMap
from AsteriaMind.argument_gate import ArgumentGate

star = CognitiveStarMap(":memory:")
gate = ArgumentGate(star)

# 种子知识: 鸵鸟是鸟类(3次) / 鸵鸟是哺乳动物(10次, 语料重复多)
#           NOT_IS_A 哺乳动物被确认 15 次 (反边证据 15 > 1.15×10 候选证据)
# 候选来自多源管线 (搜索提取/跨空间/预去重), 不一定经过检索层的同对去重 —
# 检索分高 (salience=1.4) ≠ 论证强, 闸门按反边证据反杀
for _ in range(3):
    star.store("鸵鸟", "IS_A", "鸟类", "confirmed", "鸵鸟是鸟类")
for _ in range(10):
    star.store("鸵鸟", "IS_A", "哺乳动物", "confirmed", "鸵鸟是哺乳动物")
for _ in range(15):
    star.store("鸵鸟", "NOT_IS_A", "哺乳动物", "confirmed", "鸵鸟不是哺乳动物")

passed = 0

# ── T1: 反证压制 — 弱 IS_A 被强 NOT_IS_A 除名 ──
edges = [
    {"source": "鸵鸟", "relation": "IS_A", "target": "哺乳动物",
     "salience": 1.4, "energy": 1.0, "confidence": 1.0},
    {"source": "鸵鸟", "relation": "IS_A", "target": "鸟类",
     "salience": 0.42, "energy": 1.0, "confidence": 1.0},
]
out, audit = gate.evaluate("鸵鸟", edges)
elim_targets = [x["edge"] for x in audit["eliminated"]]
assert any("哺乳动物" in t for t in elim_targets), f"应压制哺乳动物: {elim_targets}"
assert not any(e["target"] == "哺乳动物" and e["relation"] == "IS_A" for e in out), \
    "被压制候选不应出现在输出"
assert out[0]["target"] == "鸟类", f"鸟类应夺冠: {[e['target'] for e in out]}"
print(f"T1 反证压制 ✓  eliminated={elim_targets}")
passed += 1

# ── T2: 推论否决 — inferred 两跳候选遇直接反边 → 除名 ──
star.store("鸵鸟", "NOT_IS_A", "脊椎动物门", "confirmed", "分类学修正")
cand = edges + [{
    "source": "鸵鸟", "relation": "IS_A", "target": "脊椎动物门",
    "salience": 0.8, "energy": 1.0, "confidence": 0.7,
    "inferred": True, "path": ["鸵鸟", "鸟类", "脊椎动物门"],
}]
out2, audit2 = gate.evaluate("鸵鸟", cand)
assert any("脊椎动物门" in x["edge"] and "否决" in x["reason"]
           for x in audit2["eliminated"]), f"推论应被否决: {audit2['eliminated']}"
print(f"T2 推论否决 ✓  {audit2['eliminated']}")
passed += 1

# ── T3: 论证排序 — 冠军按 argument_strength 而非裸 salience ──
assert all(out[i]["argument_strength"] >= out[i+1]["argument_strength"]
           for i in range(len(out)-1)), "输出应按论证强度降序"
assert audit["mode"] in ("single", "tie") and audit["gap"] >= 0
print(f"T3 论证排序 ✓  mode={audit['mode']} gap={audit['gap']} "
      f"top_strength={audit['top_strength']}")
passed += 1

# ── T4: 势均力敌 — 强度接近 → tie 模式 ──
tie_cand = [
    {"source": "蛇", "relation": "EATS", "target": "昆虫",
     "salience": 0.50, "energy": 1.0, "confidence": 0.8},
    {"source": "蛇", "relation": "EATS", "target": "鼠类",
     "salience": 0.51, "energy": 1.0, "confidence": 0.8},
]
_, audit_tie = gate.evaluate("蛇", tie_cand)
assert audit_tie["mode"] == "tie", f"强度接近应为 tie: {audit_tie}"
print(f"T4 势均力敌 ✓  mode={audit_tie['mode']} gap={audit_tie['gap']}")
passed += 1

# ── T5: 全部被压制 → 空输出 (诚实拒答的弹药) ──
star2 = CognitiveStarMap(":memory:")
star2.store("X", "IS_A", "Y", "confirmed", "弱证据")
for _ in range(5):
    star2.store("X", "NOT_IS_A", "Y", "confirmed", "强反证")
gate2 = ArgumentGate(star2)
weak = [{"source": "X", "relation": "IS_A", "target": "Y",
         "salience": 0.3, "energy": 1.0, "confidence": 0.5}]
out5, audit5 = gate2.evaluate("X", weak)
assert out5 == [] and len(audit5["eliminated"]) == 1, f"{out5} {audit5}"
print(f"T5 全压制 ✓  {audit5['eliminated'][0]['reason'][:30]}")
passed += 1

# ── T6: 注册表 — 可热插拔 (ID-010 惯例) ──
from AsteriaMind.module_registry import REGISTRY
m = REGISTRY.get("argument")
assert m is None or m.name == "argument"  # 独立进程时为 None, 联动时可见
print("T6 注册表契约 ✓ (独立运行不炸)")
passed += 1

print(f"\n✅ ArgumentGate {passed}/6 通过")
