# -*- coding: utf-8 -*-
"""
test_bottlenecks.py — 三前瞻瓶颈验证 (AsteriaMind v3.9)

瓶颈一 (常识缺口): CAUSES/OPPOSITE 元关系打通 belief 查询链路
瓶颈二 (单句骨架池): dialogue_transitions 句间衔接统计
瓶颈三 (能量闭环): 三个内在奖励 (推理链自洽 / 预测被验证 / 有效信息量)

运行: python test_bottlenecks.py
"""
import sys, os, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1
    print(f"{'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail and not cond else ""))

TMP = tempfile.mktemp(suffix='.db')

# ─────────── 瓶颈一: CAUSES / OPPOSITE 元关系 ───────────
print("=" * 60)
print("瓶颈一: CAUSES / OPPOSITE 元关系")
from AsteriaMind.cognitive_star_map import CognitiveStarMap, _is_valid_entity_pair
star = CognitiveStarMap(TMP)
star._ensure_table()
star.store("天上下雨", "CAUSES", "地面变湿", "confirmed", "test")
star.store("水结冰", "CAUSES", "体积膨胀", "confirmed", "test")
star.store("热", "OPPOSITE", "冷", "confirmed", "test")

edges = star.query_edges("天上下雨", "天上下雨导致什么", space="belief")
check("CAUSES 在 belief 空间可查", any(e["relation"]=="CAUSES" for e in edges),
      f"{[(e['relation'],e['target']) for e in edges]}")
edges2 = star.query_edges("热", "热和什么相反", space="belief")
check("OPPOSITE 在 belief 空间可查", any(e["relation"]=="OPPOSITE" for e in edges2),
      f"{[(e['relation'],e['target']) for e in edges2]}")

from AsteriaMind.intake_purifier import _OPPOSITE
check("CAUSES↔NOT_CAUSES 冲突映射", _OPPOSITE["CAUSES"]=="NOT_CAUSES")
from AsteriaMind.language_model import _REL_LOOKUP
check("骨架池因果关系词", _REL_LOOKUP["导致"]=="CAUSES")
from AsteriaMind.think_node import _infer_relation
check("因果问句识别", _infer_relation("什么导致全球变暖")=="CAUSES")
check("弱因果不抢占否定", _infer_relation("为什么企鹅不会飞")=="NOT_CAN")
check("质量门仍生效", _is_valid_entity_pair("因此","鸟类")==False)

# ─────────── 瓶颈二: 句间衔接统计 ───────────
print("=" * 60)
print("瓶颈二: dialogue_transitions 句间衔接")
conn = sqlite3.connect(TMP)
conn.execute("CREATE TABLE IF NOT EXISTS language_traces(id INTEGER PRIMARY KEY AUTOINCREMENT, sentence TEXT, subj TEXT, pred TEXT, obj TEXT, timestamp REAL, sentence_type TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS conversation_log(id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT)")
conn.commit()
from AsteriaMind.conversation_replay import ConversationReplay
rp = ConversationReplay(TMP)
rp.learn_transition("企鹅会飞吗？", "企鹅不会飞")
rp.learn_transition("企鹅会飞吗？", "企鹅不会飞")
rp.learn_transition("不对，企鹅不会飞", "你说得对")
stats = rp.transition_stats()
check("轮次对计数正确", stats["total_transitions"]==3, f"{stats}")
check("重复轮次对 count=2", stats["top"][0]["count"]==2, f"{stats}")
check("prev_intent 分类", ConversationReplay._prev_intent("企鹅会飞吗")=="question"
      and ConversationReplay._prev_intent("不对，你错了")=="negate")
for r, c in [("user","海豚是什么"),("user","海豚会飞吗")]:
    conn.execute("INSERT INTO conversation_log(role,content) VALUES(?,?)", (r,c))
conn.commit()
res = rp.replay_history(limit=600)
check("回放批量学轮次对", rp.transition_stats()["total_transitions"]>3, f"{res}")

# ─────────── 瓶颈三: 能量内在奖励 ───────────
print("=" * 60)
print("瓶颈三: 能量内在奖励 (可证伪性原则)")
star.store("企鹅", "IS_A", "鸟类", "confirmed", "t")
star.store("鸟类", "IS_A", "脊椎动物", "confirmed", "t")
e1 = star.conn.execute("SELECT energy FROM directed_edges WHERE source='企鹅' AND target='鸟类'").fetchone()[0]
from AsteriaMind.reasoning_chain import ReasoningChain
rc = ReasoningChain(star)
res = rc.infer("企鹅")
e2 = star.conn.execute("SELECT energy FROM directed_edges WHERE source='企鹅' AND target='鸟类'").fetchone()[0]
check("奖励1 推理链自洽挣回", e2 > e1, f"{e1:.3f}→{e2:.3f}")

from AsteriaMind.active_inference import ActiveInferenceEngine
ai = ActiveInferenceEngine(star)
be = ai.get_or_create_belief("海豚", "IS_A", "哺乳动物")
be.predicted = True
ai.update_from_feedback("海豚", "IS_A", "哺乳动物", True)
e4 = star.conn.execute("SELECT energy FROM directed_edges WHERE source='海豚' AND target='哺乳动物'").fetchone()[0]
check("奖励2 预测被验证挣回", e4 > 0 and be.predicted==False, f"energy={e4}")

from AsteriaMind.offline_learner import OfflineLearner
class FakeAL:
    def learn_relation(self, s, p, o):
        star.store(s, p, o, "confirmed", "fake_al"); return {"learned": True}
class P1:
    query = "金星 IS_A 行星"; learner_id = "l1"; uncertainty_source = "gap"
class P2:
    query = "火星 IS_A 行星"; learner_id = "l2"; uncertainty_source = "gap"
class FakeAI:
    def update_from_feedback(self, *a): pass
ol = OfflineLearner(star_map=star, active_learner=FakeAL(), active_inference=FakeAI())
star.store("火星", "IS_A", "行星", "confirmed", "t")
e_mar = star.conn.execute("SELECT energy FROM directed_edges WHERE source='火星' AND target='行星'").fetchone()[0]
ol._execute_learning(P1())
e_ven = star.conn.execute("SELECT energy FROM directed_edges WHERE source='金星' AND target='行星'").fetchone()[0]
check("奖励3a 新增知识挣回", e_ven > 0, f"{e_ven}")
ol._execute_learning(P2())
e_mar2 = star.conn.execute("SELECT energy FROM directed_edges WHERE source='火星' AND target='行星'").fetchone()[0]
check("奖励3b 重复知识不挣回", abs(e_mar2-e_mar)<1e-9, f"{e_mar}→{e_mar2}")

# ─────────── 汇总 ───────────
try:
    star.conn.close(); star._writer.close(); conn.close()
    os.remove(TMP)
except Exception:
    pass
print("=" * 60)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(0 if FAIL == 0 else 1)
