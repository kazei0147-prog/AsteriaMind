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

# ── AM 初始化 ──
kg = KnowledgeGraph()
db = KnowledgeDB("asteriamind.db")
reg = TemplateRegistry()
for t in _builtin_templates(): reg.register(t)
skill_lib = build_default_skills()
mr = MathReasoner()
web_search = WebSearchInterface()

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
            reply, action = self._process(text)
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

    def _process(self, text: str) -> tuple[str, str]:
        """处理自然语言——命令路由 + 意图分类"""

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

        # ── 英文模式: ASCII 占比 > 60% → 走英文解析 ──
        ascii_count = sum(1 for c in text if ord(c) < 128)
        if ascii_count > len(text) * 0.6:
            return self._process_en(text)

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
        if any(text.startswith(p) for p in ['你', '您', '我', '我们', '咱', '为什么', '怎么', '请问', '谢谢', '感谢']):
            if '你' in text and ('吗' in text or '?' in text or '？' in text or '吧' in text):
                return self._conversational_reply(text)
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
                return ("不客气 🙂", "thanks")
            # 其他元语句: 对话回复, 不强学
            return self._conversational_reply(text)

        # ── 4. 问题——查 KG (在事实学习之前!) ──
        if '?' in text or '？' in text or '吗' in text or '是什么' in text or '是谁' in text or text.startswith('什么') or text.startswith('谁'):
            return self._handle_question(text)

        # ── 5. 事实陈述——多句型解析 (去掉了 ^ 开头限制!) ──
        learned = []  # 本轮学到的所有事实

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
        return self._conversational_reply(text)

    def _process_en(self, text: str) -> tuple[str, str]:
        """English parsing — space-delimited, less ambiguous"""
        t = text.strip()
        tl = t.lower()

        # ── Questions (CHECED FIRST, before any fact pattern) ──
        is_question = ('?' in t or tl.startswith(('what', 'who', 'how', 'where', 'when', 'why'))
                       or tl.startswith('is ') or tl.startswith('are ')
                       or tl.startswith('can ') or tl.startswith('does ')
                       or tl.startswith('do ') or 'tell me what' in tl or 'tell me who' in tl
                       or tl.startswith('could ') or tl.startswith('would '))

        if is_question:
            # Clean up
            clean = t.rstrip('?.!').lower()
            words = [w for w in clean.split() if w not in
                     ('what', 'who', 'is', 'are', 'a', 'an', 'the', 'can', 'you',
                      'tell', 'me', 'of', 'does', 'do', 'how', 'where', 'when', 'why',
                      'could', 'would', 'please', 'to')]
            for w in words:
                for r in kg.relations:
                    if r.subject.lower() == w:
                        return (f"{r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})", "en_query")
            return ("I don't know that yet. Try teaching me!", "en_unknown")

        m = re.search(r'(\w[\w\s]{0,30}?)\s+is\s+(?:a\s+|an\s+)?(\w[\w\s]{0,30}?)$', t, re.I)
        if m:
            subj, obj = m.group(1).strip(), m.group(2).strip()
            if subj.lower() in ('it', 'this', 'that', 'he', 'she', 'i', 'you'): return ("I'm listening!", "en_ack")
            kg.add(subj, "IS_A", obj, confidence=0.7)
            db.add_relation(subj, "IS_A", obj, 0.7, source="en")
            _auto_export()
            return (f"Got it: {subj} is a {obj}", "learn_fact")

        m = re.search(r'(\w[\w\s]{0,30}?)\s+can\s+(\w[\w\s]{0,30}?)$', t, re.I)
        if m:
            subj, obj = m.group(1).strip(), m.group(2).strip()
            kg.add(subj, "CAN", obj, confidence=0.6)
            db.add_relation(subj, "CAN", obj, 0.6, source="en")
            _auto_export()
            return (f"Got it: {subj} can {obj}", "learn_can")

        for pat, pred in [
            (r'(\w[\w\s]{0,30}?)\s+causes?\s+(\w[\w\s]{0,30}?)$', 'CAUSES'),
            (r'(\w[\w\s]{0,30}?)\s+orbits?\s+(\w[\w\s]{0,30}?)$', 'ORBITS'),
            (r'(\w[\w\s]{0,30}?)\s+belongs?\s+to\s+(\w[\w\s]{0,30}?)$', 'BELONGS_TO'),
            (r'(\w[\w\s]{0,30}?)\s+includes?\s+(\w[\w\s]{0,30}?)$', 'INCLUDES'),
        ]:
            m = re.search(pat, t, re.I)
            if m:
                subj, obj = m.group(1).strip(), m.group(2).strip()
                kg.add(subj, pred, obj, confidence=0.7)
                db.add_relation(subj, pred, obj, 0.7, source="en")
                _auto_export()
                return (f"Got it: {subj} {pred} {obj}", "learn_fact")

        return ("I heard you. Try: 'cat is animal' / 'bird can fly'?", "en_casual")

    def _conversational_reply(self, text: str) -> tuple[str, str]:
        """对话回复——用户教的偏好优先, 再默认"""
        # 1. 查用户教的偏好 — 词级匹配 (避免"你"字符误匹配)
        for r in kg.relations:
            if r.predicate == "REPLIES_WITH":
                pref = r.subject
                # 精确: 偏好词出现在文本中, 或文本词出现在偏好中(双字以上)
                if pref in text:
                    return (r.object, "pref_reply")
                # 反向: 文本中的2字以上词在偏好里
                for ch in re.findall(r'[\u4e00-\u9fff]{2,}', text):
                    if ch in pref and len(ch) >= 2:
                        return (r.object, "pref_reply")
        # 2. 同义词展开
        for r in kg.relations:
            if r.predicate == "IS_SYNONYM" and r.subject in text:
                for r2 in kg.relations:
                    if r2.subject == r.object and r2.predicate == "MEANS":
                        return (f"💡 '{r.subject}' 就是 '{r.object}' → {r2.object}", "synonym")
        # 3. 默认
        if '你好' in text or 'hello' in text.lower():
            return ("你好! 有什么想告诉我的吗?", "greeting")
        if '你是谁' in text or '你叫什么' in text:
            return (["我是 AsteriaMind, 一个不断进化的认知系统 🧠", "我叫 AsteriaMind! 是你在培养的 AI。", "我是你一手带大的 AsteriaMind 呀~"][hash(text) % 3], "intro")
        if '你能做什么' in text or '你会什么' in text:
            return ("我可以: 学习事实 / 回答提问 / 做数学题 / 搜索信息 / 自己进化。试试告诉我点什么?", "capabilities")
        if '怎么用' in text or '如何用' in text:
            return ("很简单: 'X是Y' 教事实, 'X会Y吗' 问问题, '2+3=?' 算数学, 'learnw X' 学单词, 'readcn 文本' 读中文", "howto")
        # 默认: 多样化提示
        defaults = [
            "我记下了。试试更具体地说? 比如 '鸟是动物' 或 '太阳会发光'",
            "嗯嗯。想告诉我什么知识吗?",
            "收到! 你可以教我任何事 😊",
        ]
        return (defaults[hash(text) % len(defaults)], "casual")

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

        # 通用问题
        for kw in re.findall(r'[\u4e00-\u9fff\w]{2,}', text.replace("?", "").replace("？", "")):
            if kw in ("什么", "是什么", "吗", "可以", "怎么", "如何", "为什么"): continue
            found = kg.query(subject=kw)
            if found:
                lines = [f"  · {r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})"
                         for r in found[:5]]
                return (f"关于 '{kw}' 我知道:\n" + "\n".join(lines), "kg_query")
        return (f"我不确定。试试告诉我: '{text[:6] if len(text)>6 else text}' 是什么?", "unknown")


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
