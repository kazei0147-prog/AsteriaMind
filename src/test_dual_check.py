# -*- coding: utf-8 -*-
"""
test_dual_check.py — ID-018 belief_check 双向判读验证

方向 A (白盒→黑盒): 命名边验证向量近邻 — 黑盒是否贴合白盒 (黑盒质量)
方向 B (黑盒→白盒): 向量强相关验证命名边 — 黑盒新涌现是否被白盒沉淀
                      (白盒缺口/陈旧候选 — 白盒可被黑盒推翻)

运行: python test_dual_check.py
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1
    print(f"{'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail and not cond else ""))

class FakeSM:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute("CREATE TABLE directed_edges(source TEXT, target TEXT, relation TEXT, weight REAL, confidence REAL, evidence_count INTEGER, last_update REAL, energy REAL)")

class FakeVS:
    """控制近邻: 企鹅≈鸟类(已有边) / 海豚≈鲸鱼(缺口) / 火星≈太阳(缺口)"""
    def _load(self): return self
    def neighbors(self, w, top_k=10):
        table = {
            "企鹅": [("鸟类", 0.95), ("南极", 0.90)],
            "海豚": [("鲸鱼", 0.93), ("哺乳动物", 0.88)],
            "火星": [("行星", 0.92), ("太阳", 0.80)],
        }
        return table.get(w, [])[:top_k]
    def _pair_sim(self, a, b): return 0.9
    _words = set()

from AsteriaMind.concept_layer import ConceptLayer

print("=" * 60)
print("ID-018: belief_check 双向判读")
sm = FakeSM()
sm.conn.execute("INSERT INTO directed_edges VALUES('企鹅','鸟类','IS_A',1,1.0,1,0,1.0)")
sm.conn.execute("INSERT INTO directed_edges VALUES('火星','行星','IS_A',1,1.0,1,0,1.0)")
sm.conn.execute("INSERT INTO directed_edges VALUES('海豚','鳍','HAS',1,1.0,1,0,1.0)")
cl = ConceptLayer(sm)
cl._vector = FakeVS()

# 方向 A
a = cl.belief_check(sample=20)
check("方向A: 白盒验黑盒 consistency 正常", a["consistency"] >= 0.5, f"{a}")
check("方向A: 企鹅≈鸟类 在向量近邻 (命中)", a["hits"] >= 2, f"{a}")

# 方向 B
b = cl.emergence_check(sample=15, sim_threshold=0.7)
pairs = [p["pair"] for p in b["emergent_pairs"]]
check("方向B: 识别海豚≈鲸鱼 涌现缺口", any("海豚≈鲸鱼" == p for p in pairs), f"{pairs}")
check("方向B: 识别火星≈太阳 涌现缺口", any("火星≈太阳" == p for p in pairs), f"{pairs}")
check("方向B: 排除已有边 企鹅≈鸟类", not any("企鹅≈鸟类" == p for p in pairs), f"{pairs}")
check("方向B: 排除已有边 火星≈行星", not any("火星≈行星" == p for p in pairs), f"{pairs}")

# 双向汇总
d = cl.dual_check(sample=20)
check("双向汇总: verdict level 有效", d["verdict"]["level"] in ("normal","warning","critical"), f"{d['verdict']}")
check("双向汇总: 方向A/B 都在", "direction_a_whitebox_to_blackbox" in d
      and "direction_b_blackbox_to_whitebox" in d)

print("=" * 60)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(0 if FAIL == 0 else 1)
