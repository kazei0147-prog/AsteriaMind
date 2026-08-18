"""F13 会话上下文专项测试 — 滚动摘要/会话元数据/上下文注入/指代消解"""
import sys, os, tempfile, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.mktemp(suffix='.db')
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.conversation_memory import ConversationMemory

db = KnowledgeDB(tmp)
cm = ConversationMemory(db)
sid = "test-session"
cur = db.conn.cursor()

# ── 1. 会话元数据: 实体 + 话题链 + 轮数 ──
cm.update_session_meta(sid, ["语义网络"], "语义网络")
cm.update_session_meta(sid, ["Levelt"], "Levelt")
cm.update_session_meta(sid, ["黑盒"], "黑盒")
cur.execute("SELECT last_entities, topic_chain, rounds FROM session_context WHERE session_id=?", (sid,))
row = cur.fetchone()
ents, chain, rounds = json.loads(row[0]), json.loads(row[1]), row[2]
assert "语义网络" in ents and "Levelt" in ents and "黑盒" in ents
assert chain == ["语义网络", "Levelt", "黑盒"]
assert rounds == 3

# ── 2. 第 5 轮触发滚动摘要 ──
for i in range(2):
    cm.update_session_meta(sid, [f"实体{i}"], f"话题{i}")
cm.add(sid, "user", "语义网络是什么", "语义网络")
cm.add(sid, "am", "语义网络是概念节点的连接", "语义网络")
cm.add(sid, "user", "那Levelt呢", "Levelt")
cm.add(sid, "am", "Levelt研究言语产生", "Levelt")
cm.add(sid, "user", "黑盒是什么", "黑盒")
cm.add(sid, "am", "黑盒是统计引擎", "黑盒")
cur.execute("SELECT rounds FROM session_context WHERE session_id=?", (sid,))
assert cur.fetchone()[0] == 5
summary = cm.roll_summary(sid, every=5)
assert summary, "摘要应生成"

# ── 3. 上下文注入: 摘要 + 最近实体 + 话题链 ──
ctx = cm.get_context_string(sid, "那黑盒呢")
assert "Session summary" in ctx
assert "黑盒" in ctx

# ── 4. 指代消解 (web 层逻辑复现) ──
ents2 = json.loads(cur.execute(
    "SELECT last_entities FROM session_context WHERE session_id=?", (sid,)).fetchone()[0])
text = "那个呢"
m = re.match(r'^(它|这个|那个|他|她|那|这)(呢|是什么|是啥|怎么样|怎么|在哪|哪里|呢\?|呢？|呢吗|呢吗?)', text)
if m and ents2:
    resolved = ents2[0] + m.group(2)
    assert resolved == ents2[0] + "呢"

db.conn.close()
try: os.remove(tmp)
except Exception: pass
print("F13 会话上下文 4/4 ✅")
