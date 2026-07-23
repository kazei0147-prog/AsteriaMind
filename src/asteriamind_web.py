"""
AsteriaMind Web Chat — 浏览器交互窗口 (v3.2)

单文件实现: HTTP 服务器 + 聊天 HTML + AM 后端。

启动: python asteriamind_web.py
访问: http://localhost:8866

不需要 Flask/Django——纯 Python 内置 http.server。
"""
import http.server, json, re, time, os, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from collections import deque

# ── 持久对话记忆 (SQLite 后端, 不限长度) ──
CONV_MEMORY = None  # ConversationMemory instance, late init

SNAPSHOT_PATH = "kg_snapshot_latest.json"


def _auto_export():
    """每次学习后自动导出 JSON——让仪表盘能刷新看到最新状态"""
    import json as _json
    data = []
    for r in kg.relations:
        data.append({
            "subject": r.subject, "predicate": r.predicate, "object": r.object,
            "alpha": r.belief.alpha, "beta": r.belief.beta,
            "confidence": r.confidence, "source": getattr(r, 'source', 'web'),
        })
    with open(SNAPSHOT_PATH, 'w', encoding='utf-8') as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)

sys.path.insert(0, str(Path(__file__).parent))

from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.hypothesis_template import TemplateRegistry, _builtin_templates
from AsteriaMind.math_reasoner import MathReasoner
from AsteriaMind.skill_library import build_default_skills
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface
from AsteriaMind.conversation_memory import ConversationMemory
from AsteriaMind.intent_layer import IntentLayer, IntentHypothesis

# ── AM 初始化 ──
kg = KnowledgeGraph()
db = KnowledgeDB("asteriamind.db")
CONV_MEMORY = ConversationMemory(db)
reg = TemplateRegistry()
for t in _builtin_templates(): reg.register(t)
skill_lib = build_default_skills()
mr = MathReasoner()
web_search = WebSearchInterface()
intent_layer = IntentLayer(kg, db)

# 从 DB 恢复已有知识
for r in db.query():
    kg.add(r["subject"], r["predicate"], r["object"], confidence=r["confidence"])

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AsteriaMind — 对话</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui;display:flex;flex-direction:column;height:100vh}
#header{background:#161b22;padding:12px 16px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:8px}
#header h1{font-size:16px;color:#58a6ff}
#header .dot{width:8px;height:8px;background:#3fb950;border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:80%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.5;animation:slideIn .3s}
@keyframes slideIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.msg.user{align-self:flex-end;background:#238636;color:#fff}
.msg.am{align-self:flex-start;background:#21262d;border:1px solid #30363d}
.msg.error{align-self:flex-start;background:#490202;border:1px solid #f85149;color:#f85149}
.msg .meta{font-size:11px;color:#8b949e;margin-bottom:4px}
.msg.am .meta{color:#58a6ff}
#input-area{background:#161b22;padding:12px 16px;border-top:1px solid #30363d;display:flex;gap:8px}
#input-area input{flex:1;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 14px;color:#c9d1d9;font-size:14px;outline:none}
#input-area input:focus{border-color:#58a6ff}
#input-area button{background:#238636;color:white;border:none;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:14px}
#input-area button:hover{background:#2ea043}
#stats{background:#161b22;padding:8px 16px;border-top:1px solid #30363d;display:flex;gap:16px;font-size:12px;color:#8b949e}
.hint{font-size:11px;color:#484f58;margin-top:4px}
</style>
</head>
<body>
<div id="header"><span class="dot"></span><h1>AsteriaMind v3.2</h1><span style="color:#8b949e;font-size:12px">自然语言对话</span></div>
<div id="chat">
  <div class="msg am"><div class="meta">🧠 AM</div>你好！我是 AsteriaMind。你可以：
  <br>· 告诉我事实：<i>地球是行星</i>
  <br>· 问我问题：<i>咖啡能让人清醒吗</i>
  <br>· 让我算数：<i>2+3×5 等于多少</i>
  <br>· 叫我搜索：<i>查一下黑洞</i></div>
</div>
<div id="input-area">
  <input id="msg-input" placeholder="说点什么..." autofocus onkeydown="if(event.key==='Enter')send()">
  <button onclick="send()">发送</button>
</div>
<div id="stats">数据库: ... | 模板: 6 | 模块就绪</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('msg-input');
const stats = document.getElementById('stats');

function addMsg(text, cls, meta) {
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    div.innerHTML = (meta ? '<div class="meta">' + meta + '</div>' : '') + text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

async function send() {
    const msg = input.value.trim();
    if (!msg) return;
    addMsg(msg, 'user', '💬 你');
    input.value = '';
    input.disabled = true;
    try {
        const res = await fetch('/api/talk', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: msg})
        });
        const data = await res.json();
        addMsg(data.reply, data.error ? 'error' : 'am', '🧠 AM' + (data.action ? ' · ' + data.action : ''));
        if (data.stats) stats.textContent = data.stats;
    } catch(e) {
        addMsg('连接失败: ' + e.message, 'error', '⚠ 错误');
    }
    input.disabled = false;
    input.focus();
}
</script>
</body>
</html>"""


class AMHandler(http.server.BaseHTTPRequestHandler):
    """AM 的 HTTP 请求处理器"""

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        """静默日志"""
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/dashboard":
            self._serve_dashboard()
        elif self.path == "/api/stats":
            self._json({"stats": db.stats(), "relations": db.count()})
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            if self.path == "/api/talk":
                self._handle_talk()
            elif self.path == "/api/learn":
                self._handle_learn()
            else:
                self.send_error(404)
        except Exception as e:
            print(f"[ERROR] {e}")
            self.send_error(500, str(e))

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(CHAT_HTML.encode('utf-8'))

    def _serve_dashboard(self):
        """简单仪表盘——实时 KG 数据"""
        rels = db.query()[:100]
        nodes = set()
        html_parts = ['<h2>KG Dashboard (实时)</h2><ul>']
        for r in rels:
            nodes.add(r['subject']); nodes.add(r['object'])
            color = '#3fb950' if r['confidence'] > 0.7 else '#d29922' if r['confidence'] > 0.4 else '#f85149'
            html_parts.append(
                f'<li><span style="color:{color}">'
                f'{r["subject"]} --[{r["predicate"]}]--> {r["object"]}'
                f'</span> ({r["confidence"]:.0%})</li>'
            )
        html_parts.append(f'</ul><p>节点: {len(nodes)} | 关系: {len(rels)}</p>')
        html_parts.append('<meta http-equiv="refresh" content="5">')  # 每5秒刷新
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("".join(html_parts).encode('utf-8'))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _handle_talk(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._json({"reply": "空请求", "error": True})
                return
            body = self.rfile.read(length)
            data = json.loads(body.decode('utf-8'))
            text = data.get("text", "").strip()
            if not text:
                self._json({"reply": "请说点什么", "error": True})
                return

            # ── 持久对话上下文 ──
            sid = self.client_address[0]
            topic = self._extract_topic(text)
            CONV_MEMORY.add(sid, "user", text, topic)
            context_str = CONV_MEMORY.get_context_string(sid, text)

            reply, action = self._process(text, context=context_str)

            CONV_MEMORY.add(sid, "am", reply, topic)

            self._json({
                "reply": reply, "action": action,
                "stats": f"数据库: {db.count()} 条关系 | 模板: {len(reg.templates)} 个",
            })
        except Exception as e:
            self._json({"reply": f"内部错误: {e}", "error": True})

    def _handle_learn(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            subj, pred, obj = body.get("s"), body.get("p"), body.get("o")
            conf = body.get("c", 0.7)
            if not all([subj, pred, obj]):
                self._json({"reply": "格式: {s,p,o,c}", "error": True})
                return
            kg.add(subj, pred, obj, confidence=conf)
            db.add_relation(subj, pred, obj, conf, source="web")
            self._json({"reply": f"学会了: {subj} --[{pred}]--> {obj}"})
        except Exception as e:
            self._json({"reply": f"错误: {e}", "error": True})

    def _extract_topic(self, text: str) -> str:
        """从一句话提取核心话题词"""
        # 去问号/语气词
        clean = text.rstrip('?？吗').strip()
        # "你了解X吗" → X
        m = re.search(r'(?:了解|知道|懂|认识)(.+)', clean)
        if m: return m.group(1).strip()
        # "X是什么" → X
        m = re.search(r'(.+)是什么', clean)
        if m: return m.group(1).strip()
        # 纯名词
        if re.match(r'^[\u4e00-\u9fff\w]{2,10}$', clean):
            return clean
        # 取最后一个有意义的词
        words = re.findall(r'[\u4e00-\u9fff\w]{2,}', clean)
        for w in words:
            if w not in ('什么','吗','可以','怎么','如何','为什么','了解','知道'):
                return w
        return ""

    def _process(self, text: str, context: str = None) -> tuple[str, str]:
        """
        ── 意图理解层 ──
        不再是 if-else 路由链。
        输入 → IntentLayer.understand() → 意图假说 → 认知系统查询 → 动态回复
        """
        # 命令路由 (learnw/readcn/answer — 这些是元操作, 保留)
        if text.startswith(('learnw ', 'readcn ', 'answer ', '以后我')):
            return self._process_legacy(text)

        # IntentLayer: 语义→假说→评分→选择
        intent = intent_layer.understand(text)

        # fact_learn: 先存 KG
        if intent.type == "fact_learn":
            self._store_from_intent(intent)
            return (f"✅ 学会了: {intent.parsed or intent.text}", "learn_fact")

        # math: 调用 math skill
        if intent.type == "math":
            m = skill_lib.best_match(text)
            if m:
                r = m.execute(text, kg)
                if r.get("success"):
                    return (f"🧮 {r.get('result')}", "math")
            return ("❓ 这题我算不出来", "math_fail")

        # 意图→认知系统→回复
        reply = intent_layer.execute(intent)
        return (reply, intent.type)

    def _store_from_intent(self, intent: IntentHypothesis):
        """从意图假说提取三元组存入 KG"""
        text = intent.text
        # X是Y
        m = re.search(r'([\u4e00-\u9fff\w]{1,15})是([\u4e00-\u9fff\w]{1,20})', text)
        if m and m.group(1) not in ('这','那','它','你','我'):
            kg.add(m.group(1), "IS_A", m.group(2), confidence=0.7)
            db.add_relation(m.group(1), "IS_A", m.group(2), 0.7, source="intent")
        # X会Y
        m = re.search(r'([\u4e00-\u9fff\w]{1,15})(?:会|能)([\u4e00-\u9fff\w]{1,20})', text)
        if m and m.group(1) not in ('这','那','它','你','我'):
            kg.add(m.group(1), "CAUSES", m.group(2), confidence=0.6)
            db.add_relation(m.group(1), "CAUSES", m.group(2), 0.6, source="intent")
        # X绕Y
        m = re.search(r'([\u4e00-\u9fff\w]{1,10})(?:围绕|绕)([\u4e00-\u9fff\w]{1,10})', text)
        if m and m.group(1) not in ('这','那','它'):
            kg.add(m.group(1), "ORBITS", m.group(2), confidence=0.7)
            db.add_relation(m.group(1), "ORBITS", m.group(2), 0.7, source="intent")
        _auto_export()

        # ── 0. 教学命令路由 (优先级最高) ──
        # learnw <词> [同义词 <词>]
        if text.startswith('learnw '):
            parts = text[7:].strip().split(None, 2)
            if len(parts) == 1:
                return self._cmd_learn_word(parts[0])
            elif len(parts) >= 3 and parts[1] == '同义词':
                return self._cmd_synonym(parts[0], parts[2])
        # readcn <文本>
        if text.startswith('readcn '):
            return self._cmd_read_cn(text[7:].strip())
        # answer <词> <解释>
        if text.startswith('answer '):
            parts = text[7:].strip().split(None, 1)
            if len(parts) >= 2:
                return self._cmd_answer(parts[0], parts[1])
        # 以后我<条件>你就<行为> (个性化教学)
        m = re.search(r'^以后我(?:说|)?(.+?)你就(.+)$', text)
        if m:
            condition, action = m.group(1).strip(), m.group(2).strip()
            # 清理: "说再见"→"再见", "夸你"→"夸"
            condition = re.sub(r'^(说|讲|叫)', '', condition)
            kg.add(condition, "REPLIES_WITH", action, confidence=0.9)
            db.add_relation(condition, "REPLIES_WITH", action, 0.9, source="user_preference")
            _auto_export()
            return (f"✅ 记住了: 以后你说 '{condition}' 我就回 '{action}'", "learn_pref")

        # ── 1. 数学优先: 含数字+运算符或明确求值词 ──
        if re.search(r'\d\s*[\+\-\*/\^]\s*\d', text) or any(kw in text for kw in ['等于多少', '算一下', '是多少等于']):
            m = skill_lib.best_match(text)
            if m:
                r = m.execute(text, kg)
                if r.get("success"):
                    return (f"🧮 计算结果: {r.get('result')}", "math")
            return ("❓ 这数学题我看不懂", "math_fail")

        # ── 2. 命令/请求/对话——不该学 ──
        if any(text.startswith(p) for p in ['请', '帮我', '可以', '能帮', '请帮', '我想', '我要', '给我', '试试']):
            if '搜索' in text or '查' in text or '找' in text:
                query = text.replace('请', '').replace('帮我', '').replace('可以', '').replace('试试', '')
                query = re.sub(r'(搜索|查一下|查|找一下|找|关于)', '', query).strip()
                results = web_search.search(query)
                if results:
                    return (f"🔍 搜索 '{query}':\n" + "\n".join(
                        f"  · {r.title}: {r.snippet[:80]}" for r in results[:3]), "search")
                return (f"🔍 我没有真实搜索能力 (需要联网)。试试告诉我: '{query} 是 什么'?", "search_fail")
            if '退出' in text or '再见' in text:
                return ("好的, 随时回来 👋", "bye")
            return ("好的, 我在听。有什么想告诉我的吗?", "ack")

        # ── 3. 元语句/对话——不该学 ──
        if any(text.startswith(p) for p in ['你', '您', '我', '我们', '咱', '它', '他', '她', '为什么', '怎么', '请问', '谢谢', '感谢']):
            if '你' in text and ('吗' in text or '?' in text or '？' in text or '吧' in text):
                return self._conversational_reply(text, context)
            # 问候语: 优先查偏好, 不再硬编码单一回复
            greeting_keywords = ['你好', 'hello', 'hi', '嗨', '您好', '早上好', '晚上好', 'hey', '在吗', '在不在', '早上', '晚安']
            if any(kw in text for kw in greeting_keywords):
                for r in kg.relations:
                    if r.predicate == "REPLIES_WITH" and ("招呼" in r.subject or "你好" in r.subject or "您好" in r.subject or "greeting" in r.subject.lower()):
                        return (r.object, "pref_reply")
                # 无偏好 → 丰富的默认回复池
                replies = [
                    "你好! 我是 AsteriaMind 🌻 今天想聊什么?",
                    "嗨! 我在呢。告诉我有趣的事?",
                    "早上好呀~ 有什么想和我说的?",
                    "在呢! 说吧, 我听着。",
                ]
                return (replies[hash(text) % len(replies)], "greeting")
            if '谢谢' in text or '感谢' in text:
                for r in kg.relations:
                    if r.predicate == "REPLIES_WITH" and ("谢" in r.subject or "thank" in r.subject.lower()):
                        return (r.object, "pref_reply")
                return (["不客气 🙂", "没事, 应该的!", "随时为你效劳~"][hash(text) % 3], "thanks")
            # 闲聊口语: 提前拦截, 别让它们落到事实解析
            if any(w in text for w in ('真的假的', '哈哈哈', '哈哈', '笑死', '😂', '好吧', '嗯嗯', '哦哦', '好的', '行吧', '知道了')):
                return self._conversational_reply(text, context)
            # 其他元语句: 对话回复, 不强学
            return self._conversational_reply(text, context)

        # ── 4. 问题——查 KG (中英文, 在事实学习之前!) ──
        tl = text.lower().strip()
        is_cn_q = ('?' in text or '？' in text or '吗' in text or '是什么' in text or '是谁' in text
                   or text.startswith('什么') or text.startswith('谁'))
        is_en_q = (tl.startswith(('what', 'who', 'how', 'where', 'when', 'why'))
                   or tl.startswith(('is ', 'are ', 'can ', 'does ', 'do ', 'could ', 'would '))
                   or 'tell me what' in tl or 'tell me who' in tl)
        if is_cn_q or is_en_q:
            return self._handle_question(text)

        # ── 5. 事实陈述——多句型解析 (去掉了 ^ 开头限制!) ──
        learned = []  # 本轮学到的所有事实

        # ── KG 词性扩展: 英语句子用 KG 里学的词性来解析 ──
        en_words = text.lower().split() if any(ord(c) < 128 for c in text[:20]) else []
        for w in en_words:
            wtype = self._lookup_word_type(w)
            if wtype:
                if "copula" in wtype.lower() or "linking" in wtype.lower():
                    idx = text.lower().find(w)
                    if idx > 0:
                        subj = text[:idx].strip()
                        obj = text[idx + len(w):].strip()
                        for art in ('a ', 'an ', 'the '):
                            if obj.lower().startswith(art):
                                obj = obj[len(art):].strip()
                        if subj and obj:
                            kg.add(subj, "IS_A", obj, confidence=0.7)
                            db.add_relation(subj, "IS_A", obj, 0.7, source="kg_grammar")
                            _auto_export()
                            return (f"✅ Learned: {subj} is a {obj} (KG词性: {w} IS copula_verb)", "learn_fact")
                if "auxiliary" in wtype.lower() or "ability" in wtype.lower():
                    idx = text.lower().find(w)
                    if idx > 0:
                        subj = text[:idx].strip()
                        obj = text[idx + len(w):].strip()
                        if subj and obj:
                            kg.add(subj, "CAN", obj, confidence=0.6)
                            db.add_relation(subj, "CAN", obj, 0.6, source="kg_grammar")
                            _auto_export()
                            return (f"✅ Learned: {subj} can {obj} (KG词性: {w} IS auxiliary_verb)", "learn_can")
                if "relation" in wtype.lower() or "action" in wtype.lower():
                    idx = text.lower().find(w)
                    if idx > 0:
                        subj = text[:idx].strip()
                        obj = text[idx + len(w):].strip()
                        pred = w.upper()
                        if subj:
                            if not obj:
                                obj = w  # 不及物动词: 宾语=动词本身
                                pred = "DOES"
                            kg.add(subj, pred, obj, confidence=0.7)
                            db.add_relation(subj, pred, obj, 0.7, source="kg_grammar")
                            _auto_export()
                            return (f"✅ Learned: {subj} {pred} {obj} (KG词性: {w})", "learn_fact")

        # 先按中文分隔符拆句: 逗号/分号/句号/也/和/还/然后
        clauses = re.split(r'[，,；;。]|(?<=[\u4e00-\u9fff])(?:也|还|和|然后|而且)(?=[\u4e00-\u9fff])', text)
        clauses = [c.strip() for c in clauses if len(c.strip()) >= 4]

        if not clauses:
            clauses = [text]

        for clause in clauses:
            if len(clause) < 4:
                continue

            # 句型1: "X是Y的Z"
            m = re.search(r'([\u4e00-\u9fff\w]{1,10})是([\u4e00-\u9fff\w]{1,10})的([\u4e00-\u9fff\w]{1,10})', clause)
            if m:
                subj, owner, rel = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                if subj not in ('这', '那', '这个', '那个', '它', '他', '她', '我', '你'):
                    kg.add(subj, f"HAS_{rel.upper()}", owner, confidence=0.7)
                    db.add_relation(subj, f"HAS_{rel.upper()}", owner, 0.7, source="web")
                    learned.append(f"{subj}的{rel}是{owner}")
                    continue

            # 句型2: "X是Y" (简单 IS_A)
            m = re.search(r'([\u4e00-\u9fff\w]{1,15})是([\u4e00-\u9fff\w]{1,20})', clause)
            if m:
                subj, obj = m.group(1).strip(), m.group(2).strip()
                if subj in ('这', '那', '这个', '那个', '它', '他', '她', '我', '你', '什么', '怎么'):
                    continue
                kg.add(subj, "IS_A", obj, confidence=0.7)
                db.add_relation(subj, "IS_A", obj, 0.7, source="web")
                learned.append(f"{subj}是一种{obj}")
                self._infer_transitive(subj, obj)
                continue

            # 句型3: "X围绕Y环绕" / "X绕Y转"
            m = re.search(r'([\u4e00-\u9fff\w]{1,8})(?:围绕|绕着|绕)([\u4e00-\u9fff\w]{1,8})(?:环绕|运行|运动|转|转动)?', clause)
            if m:
                subj, obj = m.group(1).strip(), m.group(2).strip()
                if subj not in ('这', '那', '它'):
                    kg.add(subj, "ORBITS", obj, confidence=0.7)
                    db.add_relation(subj, "ORBITS", obj, 0.7, source="web")
                    learned.append(f"{subj}绕{obj}运行")
                    continue

            # 句型4: "X属于Y"
            m = re.search(r'([\u4e00-\u9fff\w]{1,10})(?:属于|属于于)([\u4e00-\u9fff\w]{1,15})', clause)
            if m:
                subj, obj = m.group(1).strip(), m.group(2).strip()
                kg.add(subj, "BELONGS_TO", obj, confidence=0.7)
                db.add_relation(subj, "BELONGS_TO", obj, 0.7, source="web")
                learned.append(f"{subj}属于{obj}")
                continue

            # 句型5: "X会/能/导致Y" — 先查 KG 词性再决定是因果还是能力
            m = re.search(r'([\u4e00-\u9fff\w]{1,15})(会|能|可以|导致|引起|产生)([\u4e00-\u9fff\w]{1,20})', clause)
            if m:
                subj, connector, obj = m.group(1).strip(), m.group(2), m.group(3).strip()
                if subj in ('这', '那', '它', '他', '她', '你', '我'): continue

                # ── 查 KG: 这个词是什么词性？ ──
                is_ability = False
                for r in kg.relations:
                    if r.subject == connector and r.predicate in ("MEANS", "IS_A"):
                        if "助动词" in r.object or "能力" in r.object or "不是因果关系" in r.object:
                            is_ability = True
                            break

                if is_ability and connector in ("会", "能", "可以"):
                    # 能力句: X CAN Y, 非因果!
                    kg.add(subj, "CAN", obj, confidence=0.6)
                    db.add_relation(subj, "CAN", obj, 0.6, source="web")
                    learned.append(f"{subj}有{obj}的能力 (从KG词性推断)")
                else:
                    kg.add(subj, "CAUSES", obj, confidence=0.6)
                    db.add_relation(subj, "CAUSES", obj, 0.6, source="web")
                    learned.append(f"{subj}会导致{obj}")
                continue

        if learned:
            _auto_export()
            if len(learned) == 1:
                return (f"✅ 学会了: {learned[0]}", "learn_fact")
            else:
                return (f"✅ 从这段话里学会了 {len(learned)} 条知识:\n" + "\n".join(f"  · {l}" for l in learned), "learn_multi")

        # ── 5.5: 什么都没匹配到 → 尝试理解 (语义搜索) ──
        # 查向量层是否有语义相似的已知概念
        if len(text) >= 3:
            hints = []
            for r in kg.relations:
                if r.subject in text or text[:3] in r.subject:
                    hints.append(f"'{r.subject}' --[{r.predicate}]--> '{r.object}'")
            if hints:
                return (f"不太确定你要表达的关系, 但我联想到:\n" + "\n".join(f"  · {h}" for h in hints[:3]), "semantic_hint")

        # ── 6. 默认: 对话回复 ──
        return self._conversational_reply(text, context)

    def _cmd_learn_word(self, word: str) -> tuple[str, str]:
        """learnw: 学习一个词"""
        # 已存在?
        for r in kg.relations:
            if r.subject == word and r.predicate in ("IS_A", "MEANS", "HAS_MEANING"):
                return (f"✅ 我知道 '{word}': {r.object} (置信度 {r.confidence:.0%})", "known")
        # 搜网络
        if web_search:
            results = web_search.search(f"{word} 定义", max_results=1)
            for r in results:
                if r.snippet and len(r.snippet) > 10:
                    kg.add(word, "MEANS", r.snippet[:100], confidence=0.5)
                    db.add_relation(word, "MEANS", r.snippet[:100], 0.5, source="web_search")
                    _auto_export()
                    return (f"✅ 从网络学了: {word} → {r.snippet[:60]}...", "learn_web")
        # 存为未知
        kg.add(word, "IS_UNKNOWN", "true", confidence=0.3)
        db.add_relation(word, "IS_UNKNOWN", "true", 0.3, source="pending")
        _auto_export()
        return (f"❓ 不太确定 '{word}' 的意思。用 'answer {word} <解释>' 教我?", "pending")

    def _cmd_synonym(self, word_a: str, word_b: str) -> tuple[str, str]:
        """learnw A 同义词 B"""
        kg.add(word_a, "IS_SYNONYM", word_b, confidence=0.8)
        db.add_relation(word_a, "IS_SYNONYM", word_b, 0.8, source="user_taught")
        kg.add(word_b, "IS_SYNONYM", word_a, confidence=0.8)
        db.add_relation(word_b, "IS_SYNONYM", word_a, 0.8, source="user_taught")
        _auto_export()
        return (f"✅ 同义词: {word_a} ↔ {word_b}", "learn_synonym")

    def _cmd_read_cn(self, text: str) -> tuple[str, str]:
        """readcn: 分词 + 不认识就学"""
        import re as _re
        # 中文分词: 字/双字/三字
        unknown = []
        # 清除标点
        # 清理
        clean = _re.sub(r'[，。！？、；：""''（）\\s]', '', text)
        # 提取双字词
        pairs = [clean[i:i+2] for i in range(len(clean)-1)]
        seen = set()
        for w in pairs[:30]:
            if w in seen: continue
            seen.add(w)
            # 查 KG 是否认识
            known = False
            for r in kg.relations:
                if r.subject == w and r.predicate in ("IS_A", "MEANS", "HAS_MEANING"):
                    known = True
                    break
            if not known:
                kg.add(w, "APPEARED_IN", text[:30], confidence=0.3)
                db.add_relation(w, "APPEARED_IN", text[:30], 0.3, source="readcn")
                unknown.append(w)
        _auto_export()
        if unknown:
            return (f"📖 从中文字串中发现了 {len(unknown)} 个陌生词: {', '.join(unknown[:8])}\n"
                    f"用 'learnw <词>' 一个个学, 或 'answer <词> <解释>' 直接教", "read_cn")
        return (f"📖 这些词我都认识 ✅", "read_cn")

    def _cmd_answer(self, word: str, meaning: str) -> tuple[str, str]:
        """answer: 用户直接教"""
        kg.add(word, "MEANS", meaning, confidence=0.85)
        db.add_relation(word, "MEANS", meaning, 0.85, source="user_taught")
        # 如果之前标记为 UNKNOWN, 清除
        _auto_export()
        return (f"✅ 学会了: {word} → {meaning[:50]}", "learn_answer")

    def _infer_transitive(self, subj: str, obj: str) -> str:
        """传递推理: 已知 A IS_A B, 刚学 B IS_A C → 推出 A IS_A C"""
        # 查: 谁 IS_A subj? (即底层实体)
        lower = []
        for r in kg.relations:
            if r.predicate == "IS_A" and r.object == subj:
                lower.append(r)
        for r in lower:
            kg.add(r.subject, "IS_A", obj, confidence=min(0.7, r.confidence * 0.9))
            db.add_relation(r.subject, "IS_A", obj, min(0.7, r.confidence * 0.9), source="inferred")
            _auto_export()
            return f"{r.subject} 也是一种 {obj} (因为 {r.subject} IS_A {subj} ∧ {subj} IS_A {obj})"
        # 反向: 刚学 A IS_A B, 已知 B IS_A C → 推出 A IS_A C
        for r in kg.relations:
            if r.predicate == "IS_A" and r.subject == obj:
                kg.add(subj, "IS_A", r.object, confidence=min(0.7, r.confidence * 0.9))
                db.add_relation(subj, "IS_A", r.object, min(0.7, r.confidence * 0.9), source="inferred")
                _auto_export()
                return f"{subj} 也是一种 {r.object} (因为 {subj} IS_A {obj} ∧ {obj} IS_A {r.object})"
        return ""

    def _handle_question(self, text: str) -> tuple[str, str]:
        """问题处理——KG查询 + 传递推理"""
        # 句型1: "X的Y是什么" (必须在 "X是什么" 之前!)
        m = re.search(r'^(.{1,6})的(.{1,8})(?:是什么|是什么？|是什么\?|属于什么)', text)
        if m:
            entity, prop = m.group(1).strip(), m.group(2).strip()
            found = kg.query(subject=entity)
            if found:
                lines = [f"  · {r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})"
                         for r in found[:5]]
                # 推理: 如果 entity 有 ORBITS 关系, 且 "环绕" IS_A prop → 传递推理
                if prop == "运动方式" or prop == "移动方式":
                    orbit = [r for r in kg.relations if r.subject == entity and r.predicate == "ORBITS"]
                    if orbit:
                        motion_type = [r for r in kg.relations if r.subject == "环绕" and r.predicate == "IS_A"]
                        if motion_type:
                            lines.append(f"  🔗 推理: {entity} 的 {prop} 是 {motion_type[0].object} (因为 {entity} ORBITS {orbit[0].object} ∧ 环绕 IS_A {motion_type[0].object})")
                return ("\n".join(lines), "kg_query")

        # 句型2: "X是什么" / "X属于什么"
        m = re.search(r'^([\u4e00-\u9fff\w]{1,15})(?:是什么|是什么？|是什么\?|属于什么|属于啥|是什么东西)', text)
        if m:
            subj = m.group(1).strip()
            found = kg.query(subject=subj)
            if found:
                lines = [f"  · {r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})"
                         for r in found[:5]]
                return (f"关于 '{subj}' 我知道:\n" + "\n".join(lines), "kg_query")

        # 通用问题 — 中文 + 英文词
        skip_words = {'什么','是什么','吗','可以','怎么','如何','为什么',
                      'what','who','how','where','when','why','is','are',
                      'can','does','do','a','an','the','tell','me','you','of','to','i'}
        for kw in re.findall(r'[\u4e00-\u9fff\w]{2,}', text.replace("?", "").replace("？", "")):
            if kw.lower() in skip_words: continue
            found = kg.query(subject=kw)
            if found:
                lines = [f"  · {r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})"
                         for r in found[:5]]
                return (f"关于 '{kw}' 我知道:\n" + "\n".join(lines), "kg_query")
        # 英文单字查询
        for w in text.lower().rstrip('?').split():
            if len(w) <= 2 or w in ('what','who','how','where','when','why','is','are','can','does','do','a','an','the','tell','me','you','of','to','i'): continue
            for r in kg.relations:
                if r.subject.lower() == w:
                    return (f"{r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})", "kg_query")
        return (f"我不确定。试试告诉我: '{text[:15]}' 是什么?", "unknown")

    def _lookup_word_type(self, word: str) -> str:
        """查 KG: 这个词是什么词性？"""
        for r in kg.relations:
            if r.subject == word and r.predicate in ("MEANS", "IS_A"):
                return r.object
        return ""

    def _conversational_reply(self, text: str, context: str = "") -> tuple[str, str]:
        """对话回复——从 KG 取身份, 用上下文增强"""
        # 代词解析: 从上下文中提取最近话题
        resolved = text
        if context:
            topics = re.findall(r'Topic chain: (.+)', context)
            if topics:
                last = topics[0].split('→')[-1].strip()
                for w in ('它', '他', '她'):
                    if w in text and last and last not in ('它','他','她'):
                        resolved_text = text.replace(w, last)
                        return self._process(resolved_text, context=None)

        # 偏好优先
        for r in kg.relations:
            if r.predicate == "REPLIES_WITH":
                if r.subject in text:
                    return (r.object, "pref_reply")
                for ch in re.findall(r'[\u4e00-\u9fff]{2,}', text):
                    if ch in r.subject and len(ch) >= 2:
                        return (r.object, "pref_reply")

        # 同义词
        for r in kg.relations:
            if r.predicate == "IS_SYNONYM" and r.subject in text:
                for r2 in kg.relations:
                    if r2.subject == r.object and r2.predicate == "MEANS":
                        return (f"💡 '{r.subject}' = '{r.object}' → {r2.object}", "synonym")

        # 能力查询 + 自我介绍 (上下文匹配之前!)
        if any(p in text for p in ('你会什么', '你能做什么', '你都会啥', '你会干啥', '你的能力', '你会哪些')):
            return ("我可以: 学事实 (X是Y) / 解答提问 / 做数学 / 记偏好 / 推理知识链。你想让我学什么?", "capabilities")
        if any(p in text for p in ('你是谁', '你叫什么', '你的名字', '怎么称呼', '啥名字', '叫什么名字')):
            name = "AsteriaMind"
            role = "一个正在进化的认知系统"
            # KG 里有教的自我介绍吗？
            for r in kg.relations:
                if r.predicate == "MEANS" and r.subject in ("我", "my_name", "自我介绍"):
                    name = r.object
                if r.subject == "我":
                    if r.predicate == "IS_A":
                        role = r.object
            replies = [
                f"我叫 {name}, {role} 🧠 是你在培养的 AI。",
                f"我是 {name}呀~ {role}。你教什么我就学什么!",
                f"{name} 就是我! {role}, 还在不断成长。",
            ]
            return (replies[hash(text) % len(replies)], "intro")

        # 问候
        if any(w in text for w in ('你好', 'hello', 'hi', '嗨', '您好', '早安', '早上好', '晚上好')):
            replies = ["你好呀~ 🌻", "嗨! 我在呢。", "你好! 今天想聊什么?", "在呢! 说吧~"]
            return (replies[hash(text) % len(replies)], "greeting")

        # 感谢
        if '谢谢' in text or '感谢' in text:
            return (["不客气 🙂", "没事!", "随时效劳~", "嘿嘿, 应该的"][hash(text) % 4], "thanks")

        # 轻量对话反馈
        if any(w in text for w in ('真的假的', '哈哈哈', '哈哈', '笑死', '😂')):
            return (["😄 真的!", "哈哈哈, 是吧!", "笑什么笑, 我很认真的!"][hash(text) % 3], "laugh")
        if any(w in text for w in ('好吧', '嗯嗯', '哦哦', '嗯', '好')):
            return (["嗯!", "好的~", "继续说吧!"][hash(text) % 3], "ack")

        # ── 知识缺口: "你了解X吗"/"你知道X吗"/"X是什么" ──
        import re as _re
        m = _re.search(r'(?:了解|知道|懂|认识)(.+)', text)
        if m:
            topic = m.group(1).strip().rstrip('吗?？') or text
            for r in kg.relations:
                if r.subject in topic or topic in r.object:
                    return (f"我知道一点: {r.subject} --[{r.predicate}]--> {r.object}", "kg_hint")
            return (f"我还不太了解「{topic}」😅 你能教我吗? 比如 '{topic}是X'", "knowledge_gap")

        # 纯名词——先查上下文是不是同一个话题
        if _re.match(r'^[\u4e00-\u9fff\w]{2,10}$', text):
            for r in kg.relations:
                if r.subject == text:
                    return (f"我知道 {text}: {r.predicate} {r.object}", "kg_hint")
            # 上下文指代: 仅当输入极短 (<8字) 且出现在近期对话中
            if context and len(text) <= 8 and text in context:
                return (f"嗯, 我们刚聊到这个呢。继续说吧?", "context_match")
            return (f"「{text}」? 还不太了解呢。你能教我吗?", "knowledge_gap")

        # 兜底——不再是一句死话
        defaults = [
            "我记下了。试试更具体地说? 比如 '太阳是恒星'",
            "嗯嗯。想告诉我什么知识吗?",
            "收到! 你可以教我任何事 😊",
            "好的, 我在听! 想让我学什么?",
        ]
        return (defaults[hash(text) % len(defaults)], "casual")


if __name__ == "__main__":
    port = 8866
    print(f"\n╔══════════════════════════════╗")
    print(f"║  🧠 AsteriaMind Web Chat    ║")
    print(f"║  http://localhost:{port}       ║")
    print(f"║  Ctrl+C 退出                 ║")
    print(f"╚══════════════════════════════╝")
    print(f"  💾 {db.count()} 条已有知识")
    server = http.server.HTTPServer(("127.0.0.1", port), AMHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  👋 再见")
        server.shutdown()
