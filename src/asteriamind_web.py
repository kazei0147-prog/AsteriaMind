"""
AsteriaMind Web Chat — 浏览器交互窗口 (v3.2)

单文件实现: HTTP 服务器 + 聊天 HTML + AM 后端。

启动: python asteriamind_web.py
访问: http://localhost:8866

不需要 Flask/Django——纯 Python 内置 http.server。
"""
import sys
# ★ Windows GBK 陷阱: emoji (🧠) 在 GBK 下编码崩 → 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import http.server, json, re, time, os
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
# v3.6: TemplateRegistry/Old imports stubbed — legacy template path deprecated
class TemplateRegistry:
    templates = []
    def register(self, t): self.templates.append(t)
def _builtin_templates(): return []

from AsteriaMind.math_reasoner import MathReasoner
from AsteriaMind.skill_library import build_default_skills
from AsteriaMind.knowledge_db import KnowledgeDB
from AsteriaMind.falsification import WebSearchInterface, SearxNGSearch
from AsteriaMind.conversation_memory import ConversationMemory
from AsteriaMind.cognitive_interface import CognitiveInterface
from AsteriaMind.module_registry import REGISTRY

# ── AM 初始化 ──
import os, json
SEARXNG_URL = os.environ.get("SEARXNG_URL", "")
try:
    with open("asteria_config.json", "r") as f:
        SEARXNG_URL = SEARXNG_URL or json.load(f).get("searxng_url", "")
except Exception: pass

kg = KnowledgeGraph()
db = KnowledgeDB("asteriamind.db")
CONV_MEMORY = ConversationMemory(db)
reg = TemplateRegistry()
for t in _builtin_templates(): reg.register(t)
skill_lib = build_default_skills()
mr = MathReasoner()

if SEARXNG_URL:
    print(f"  🔍 使用 SearXNG: {SEARXNG_URL}")
    web_search = WebSearchInterface(search_fn=SearxNGSearch(SEARXNG_URL).search)
else:
    web_search = WebSearchInterface()
ci = CognitiveInterface(kg, db, web_search)

# ★ v3.8: 对话语料回流器 — 用户的话 = 她该学的说话方式
from AsteriaMind.conversation_replay import ConversationReplay
_REPLAY = ConversationReplay("asteriamind.db")

# ★ 跨请求状态 (HTTP 每请求新建 Handler, 实例状态会丢, 必须用全局)
_last_strategy = ""
_last_text = ""
_last_intent = ""
_last_subj = ""
_last_rel = ""
_last_verb = ""
_last_action = ""
_last_evidence = None  # ★ v3.6: 最近一次回答的证据链
_LM_CACHE = None       # ★ v3.7: 统计语言模型单例 (她自己的句式池)


def _speak_with_own_language(subj: str, edges: list) -> str:
    """★ v3.7: 统计语言生成 — 从她读过的句子采样句式, 不写模板

    edges: query_edges 返回的边 (含 relation/target/salience)
    返回: 自然语言; 骨架池无匹配/模块被卸载时返回 "" (模板兜底)
    """
    try:
        from AsteriaMind.module_registry import REGISTRY
        lang = REGISTRY.get("language")
        if lang is None:
            return ""  # 语言模块被卸载 → 模板兜底
        edge_dicts = [{"source": subj, "relation": e["relation"],
                       "target": e["target"]}
                      for e in edges[:5]]
        return lang.run(edge_dicts, max_sent=4)
    except Exception as e:
        print(f"统计语言生成失败: {e}")
        return ""

# 从 DB 恢复已有知识
for r in db.query():
    kg.add(r["subject"], r["predicate"], r["object"], confidence=r["confidence"])

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AsteriaMind — 对话</title>
<style>
/* ── 主题变量: 暗色(默认) / 浅色 ── */
:root{
  --bg:#0d1117; --bg-grad:radial-gradient(1200px 600px at 70% -10%, rgba(31,111,235,.13), transparent 60%), radial-gradient(900px 500px at 0% 110%, rgba(163,113,247,.09), transparent 55%);
  --panel:#161b22; --panel2:#21262d; --border:#30363d;
  --text:#e6edf3; --text2:#c9d1d9; --muted:#8b949e; --faint:#484f58;
  --accent:#58a6ff; --accent-soft:rgba(88,166,255,.14);
  --user:#238636; --user-hover:#2ea043; --user-text:#fff;
  --am:#21262d; --am-border:#30363d;
  --danger:#f85149; --warn:#d29922; --ok:#3fb950; --violet:#a371f7; --cyan:#39c5cf;
  --shadow:0 10px 30px rgba(0,0,0,.35);
  --radius:14px;
}
html[data-theme="light"]{
  --bg:#f6f8fa; --bg-grad:radial-gradient(1200px 600px at 70% -10%, rgba(9,105,218,.08), transparent 60%), radial-gradient(900px 500px at 0% 110%, rgba(130,80,223,.06), transparent 55%);
  --panel:#fff; --panel2:#f6f8fa; --border:#d0d7de;
  --text:#1f2328; --text2:#24292f; --muted:#57606a; --faint:#8c959f;
  --accent:#0969da; --accent-soft:rgba(9,105,218,.1);
  --user:#1f883d; --user-hover:#2ea043; --user-text:#fff;
  --am:#fff; --am-border:#d0d7de;
  --danger:#cf222e; --warn:#9a6700; --ok:#1a7f37; --violet:#8250df; --cyan:#0e7490;
  --shadow:0 10px 30px rgba(140,149,159,.16);
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{background:var(--bg);background-image:var(--bg-grad);background-attachment:fixed;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;flex-direction:column;height:100vh;height:100dvh;overflow:hidden}
button{font-family:inherit;cursor:pointer}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:1px}

/* ── 顶栏 ── */
#header{background:var(--panel);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:10px 14px;display:flex;align-items:center;gap:10px;flex-shrink:0;z-index:30}
#header .logo{display:flex;align-items:center;gap:8px;min-width:0}
#header .orb{width:10px;height:10px;background:var(--ok);border-radius:50%;animation:pulse 2s infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 var(--ok)}50%{opacity:.45;box-shadow:0 0 0 5px transparent}}
#header h1{font-size:15px;color:var(--text);font-weight:650;white-space:nowrap}
#header h1 span{color:var(--accent)}
#header .sub{color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#nav{display:flex;gap:2px;margin-left:auto;background:var(--panel2);padding:3px;border-radius:10px;border:1px solid var(--border)}
#nav a{display:flex;align-items:center;gap:5px;text-decoration:none;color:var(--muted);font-size:12px;padding:6px 10px;border-radius:8px;transition:all .15s;min-height:34px}
#nav a:hover{color:var(--text);background:var(--bg)}
#nav a.active{color:var(--accent);background:var(--accent-soft);font-weight:600}
#header .tools{display:flex;gap:4px;align-items:center}
.ibtn{display:flex;align-items:center;justify-content:center;width:38px;height:38px;min-height:38px;border-radius:10px;border:1px solid var(--border);background:var(--panel2);color:var(--muted);transition:all .15s;flex-shrink:0}
.ibtn:hover{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}
.ibtn.danger:hover{color:var(--danger);border-color:var(--danger);background:rgba(248,81,73,.08)}

/* ── 聊天区 ── */
#chat{flex:1;overflow-y:auto;padding:18px 14px;display:flex;flex-direction:column;gap:10px;-webkit-overflow-scrolling:touch}
#chat-inner{width:100%;max-width:760px;margin:0 auto;display:flex;flex-direction:column;gap:10px}
.msg{max-width:82%;padding:10px 14px;border-radius:var(--radius);font-size:14px;line-height:1.65;animation:slideIn .25s ease;word-break:break-word;position:relative}
@keyframes slideIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.msg .meta{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.msg .badge{font-size:10px;font-weight:700;letter-spacing:.5px;padding:2px 7px;border-radius:6px;line-height:1.4}
.b-user{background:rgba(63,185,80,.15);color:var(--ok)}
.b-am{background:var(--accent-soft);color:var(--accent)}
.b-err{background:rgba(248,81,73,.12);color:var(--danger)}
.b-learn{background:rgba(163,113,247,.14);color:var(--violet)}
.b-conf{background:rgba(248,81,73,.12);color:var(--danger)}
.b-fuzzy{background:rgba(57,197,207,.12);color:var(--cyan)}
.b-idle{background:rgba(139,148,158,.12);color:var(--muted)}
.msg .ts{margin-left:auto;font-size:10px;color:var(--faint)}
.msg.user{align-self:flex-end;background:var(--user);color:var(--user-text);border-bottom-right-radius:6px;box-shadow:var(--shadow)}
.msg.user .badge{background:rgba(255,255,255,.2);color:var(--user-text)}
.msg.user .ts{color:rgba(255,255,255,.65)}
.msg.am{align-self:flex-start;background:var(--am);border:1px solid var(--am-border);border-bottom-left-radius:6px;box-shadow:var(--shadow)}
.msg.error{align-self:flex-start;background:var(--am);border:1px solid var(--danger);border-bottom-left-radius:6px}
.msg.error .text{color:var(--danger)}
.msg code{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:1px 5px;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.msg pre{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px;overflow-x:auto;margin:6px 0;font-size:12.5px;line-height:1.5}
.msg pre code{background:none;border:none;padding:0}
.msg a{color:var(--accent);text-decoration:none}
.msg a:hover{text-decoration:underline}
.msg .li{display:block;padding-left:2px}
.copybtn{position:absolute;top:8px;right:8px;width:28px;height:28px;border-radius:7px;border:1px solid var(--border);background:var(--bg);color:var(--muted);display:none;align-items:center;justify-content:center;padding:0}
.msg.am:hover .copybtn{display:flex}
.copybtn:hover{color:var(--accent);border-color:var(--accent)}

/* 打字指示器 */
.msg.typing .dots{display:flex;gap:5px;padding:4px 2px}
.msg.typing .dots span{width:7px;height:7px;border-radius:50%;background:var(--muted);animation:bounce 1.2s infinite}
.msg.typing .dots span:nth-child(2){animation-delay:.15s}
.msg.typing .dots span:nth-child(3){animation-delay:.3s}
@keyframes bounce{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-5px);opacity:1}}

/* ── 快捷提示 ── */
#chips{flex-shrink:0;padding:8px 14px 0;display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
#chips::-webkit-scrollbar{display:none}
.chip{flex-shrink:0;min-height:34px;padding:6px 13px;border-radius:18px;border:1px solid var(--border);background:var(--panel2);color:var(--muted);font-size:12.5px;transition:all .15s;white-space:nowrap}
.chip:hover{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}

/* ── 输入区 ── */
#input-area{background:var(--panel);border-top:1px solid var(--border);padding:12px 14px calc(12px + env(safe-area-inset-bottom));flex-shrink:0}
#input-wrap{width:100%;max-width:760px;margin:0 auto;display:flex;align-items:flex-end;gap:8px;background:var(--bg);border:1px solid var(--border);border-radius:16px;padding:6px 6px 6px 14px;transition:border-color .2s, box-shadow .2s}
#input-wrap:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
#msg-input{flex:1;background:transparent;border:none;outline:none;color:var(--text);font-size:16px;line-height:1.5;resize:none;max-height:120px;padding:7px 0;font-family:inherit}
#msg-input::placeholder{color:var(--faint)}
#send-btn{display:flex;align-items:center;justify-content:center;width:44px;height:44px;min-height:44px;border-radius:12px;border:none;background:var(--user);color:var(--user-text);transition:all .15s;flex-shrink:0}
#send-btn:hover{background:var(--user-hover)}
#send-btn:disabled{opacity:.4;cursor:not-allowed}

/* ── 状态栏 ── */
#stats{background:var(--panel);border-top:1px solid var(--border);padding:6px 14px calc(6px + env(safe-area-inset-bottom));font-size:11px;color:var(--faint);display:flex;gap:16px;flex-wrap:wrap;flex-shrink:0}
#stats .cnt{color:var(--muted)}

/* ── 确认弹窗 ── */
#modal{position:fixed;inset:0;z-index:99;background:rgba(1,4,9,.55);display:none;align-items:center;justify-content:center;padding:20px}
#modal.show{display:flex}
#modal .box{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:22px;max-width:340px;width:100%;box-shadow:var(--shadow);animation:pop .2s ease}
@keyframes pop{from{transform:scale(.94);opacity:0}to{transform:scale(1);opacity:1}}
#modal h3{font-size:15px;margin-bottom:8px;color:var(--text)}
#modal p{font-size:13px;color:var(--muted);line-height:1.6;margin-bottom:18px}
#modal .actions{display:flex;gap:10px;justify-content:flex-end}
#modal button{min-height:42px;padding:0 18px;border-radius:10px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13.5px;font-weight:600;transition:all .15s}
#modal button:hover{background:var(--bg)}
#modal button.danger{background:var(--danger);border-color:var(--danger);color:#fff}
#modal button.danger:hover{background:#da3633}

/* ── 移动端 ── */
@media (max-width:640px){
  #header{flex-wrap:wrap;gap:8px;padding:8px 10px}
  #header .sub{display:none}
  #nav{order:10;width:100%;justify-content:center}
  #nav a{flex:1;justify-content:center}
  .msg{max-width:92%}
  #chat{padding:12px 10px}
  #chips{padding:6px 10px 0}
  #input-area{padding:8px 10px calc(8px + env(safe-area-inset-bottom))}
  .copybtn{display:flex;opacity:.6}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
}
</style>
</head>
<body>
<div id="header">
  <div class="logo"><span class="orb"></span><h1>AsteriaMind <span>v3.2</span></h1></div>
  <span class="sub">自然语言对话 · 自发学习</span>
  <div id="nav">
    <a href="/" class="active"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>对话</a>
    <a href="/graph"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>能量视图</a>
    <a href="/galaxy"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10A10 10 0 0 1 2 12 10 10 0 0 1 12 2z"/></svg>知识星系</a>
  </div>
  <div class="tools">
    <button class="ibtn" id="theme-btn" title="切换深浅主题" onclick="toggleTheme()"></button>
    <button class="ibtn" title="导出聊天记录备份" onclick="exportChat()"></button>
    <button class="ibtn" title="导入聊天记录恢复" onclick="importFile.click()"></button>
    <button class="ibtn danger" title="清空对话记录" onclick="askClear()"></button>
  </div>
</div>
<div id="chat"><div id="chat-inner"></div></div>
<div id="chips">
  <button class="chip" onclick="fill('企鹅是一种鸟类')">教我知识</button>
  <button class="chip" onclick="fill('咖啡能让人清醒吗？')">问我问题</button>
  <button class="chip" onclick="fill('2+3×5 等于多少')">让我算数</button>
  <button class="chip" onclick="fill('查一下黑洞')">叫我搜索</button>
  <button class="chip" onclick="fill('蛇会飞吗？')">考考她</button>
</div>
<div id="input-area">
  <div id="input-wrap">
    <textarea id="msg-input" placeholder="说点什么…（Enter 发送 / Shift+Enter 换行）" rows="1"></textarea>
    <button id="send-btn" onclick="send()" title="发送"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
  </div>
</div>
<div id="stats"><span class="cnt" id="msg-count"></span><span id="backend-stats">连接中…</span></div>
<div id="modal"><div class="box">
  <h3>清空对话记录？</h3>
  <p id="modal-desc">将删除本地保存的全部消息，此操作不可恢复。建议先导出备份。</p>
  <div class="actions"><button onclick="closeModal()">取消</button><button class="danger" onclick="doClear()">确认清空</button></div>
</div></div>
<input type="file" id="importFile" accept=".json,application/json" hidden>
<script>
const chat = document.getElementById('chat-inner');
const input = document.getElementById('msg-input');
const statsEl = document.getElementById('backend-stats');
const countEl = document.getElementById('msg-count');
const sendBtn = document.getElementById('send-btn');
const LS_KEY = 'wb_amchat_msgs';
const TH_KEY = 'wb_amchat_theme';
let msgs = [];
let sending = false;
let typingEl = null;

/* ── 主题 ── */
const ICONS = {
  moon: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  sun: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  dl: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
  trash: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
};
function renderThemeBtn(){
  const btn = document.getElementById('theme-btn');
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  btn.innerHTML = dark ? ICONS.sun : ICONS.moon;  /* 显示"目标", 点击切换 */
}
function initTheme(){
  let t = localStorage.getItem(TH_KEY);
  if(!t) t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  renderThemeBtn();
}
function toggleTheme(){
  const t = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem(TH_KEY, t);
  renderThemeBtn();
}
(function(){  /* 工具按钮图标 */
  const tools = document.querySelectorAll('#header .tools .ibtn');
  tools[1].innerHTML = ICONS.dl;
  tools[2].innerHTML = ICONS.up;
  tools[3].innerHTML = ICONS.trash;
})();

/* ── 渲染: 轻量 Markdown (先转义再渲染, 防注入) ── */
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function renderMD(s){
  s = esc(s);
  s = s.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/^[-•]\s+(.+)$/gm, '<span class="li">• $1</span>');
  return s.replace(/\n/g, '<br>');
}
const KIND_META = {
  user:{badge:'b-user', label:'你'},
  am:{badge:'b-am', label:'AM'},
  error:{badge:'b-err', label:'错误'},
  learned:{badge:'b-learn', label:'AM 分享'},
  conflict:{badge:'b-conf', label:'AM 质疑'},
  fuzzy:{badge:'b-fuzzy', label:'AM 求知'},
  idle:{badge:'b-idle', label:'AM 自语'}
};
function fmtTime(ts){
  const d = new Date(ts);
  return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);
}
function addMsgEl(m){
  const div = document.createElement('div');
  const k = KIND_META[m.kind] || KIND_META.idle;
  const isUser = m.kind === 'user';
  div.className = 'msg ' + (m.kind==='error' ? 'error' : isUser ? 'user' : 'am');
  const body = (m.kind==='user') ? esc(m.text).replace(/\n/g,'<br>') : renderMD(m.text);
  div.innerHTML = '<div class="meta"><span class="badge '+k.badge+'">'+k.label+'</span><span class="ts">'+fmtTime(m.ts||Date.now())+'</span></div>'
    + '<div class="text">'+body+'</div>'
    + (isUser ? '' : '<button class="copybtn" title="复制" onclick="copyMsg(this)"></button>');
  const cp = div.querySelector('.copybtn');
  if(cp) cp.innerHTML = ICONS.copy || '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  chat.appendChild(div);
  return div;
}
function copyMsg(btn){
  const text = btn.closest('.msg').querySelector('.text').innerText;
  navigator.clipboard.writeText(text).then(()=>{
    const old = btn.innerHTML; btn.innerHTML = '<span style="font-size:10px;color:var(--ok)">✓</span>';
    setTimeout(()=>{btn.innerHTML = old;}, 1200);
  });
}
function scrollBottom(){ const c = document.getElementById('chat'); c.scrollTop = c.scrollHeight; }
function push(m){ msgs.push(m); save(); addMsgEl(m); scrollBottom(); updateCount(); }
function updateCount(){ countEl.textContent = '本地记录 ' + msgs.length + ' 条'; }

/* ── 持久化 ── */
function save(){ try{ localStorage.setItem(LS_KEY, JSON.stringify(msgs)); }catch(e){} }
function load(){
  try{
    const raw = localStorage.getItem(LS_KEY);
    if(raw){ const arr = JSON.parse(raw); if(Array.isArray(arr)) msgs = arr; }
  }catch(e){ msgs = []; }
  if(!msgs.length){
    msgs = [{role:'am', kind:'am', ts:Date.now(), text:'你好！我是 AsteriaMind — 一个会自己学习的认知系统。你可以：\n- 告诉我事实：**企鹅是一种鸟类**\n- 问我问题：*咖啡能让人清醒吗？*\n- 让我算数：`2+3×5 等于多少`\n- 叫我搜索：**查一下黑洞**\n\n她会自发学习、质疑和分享，不用你一直喂。'}];
    save();
  }
  msgs.forEach(addMsgEl);
  scrollBottom(); updateCount();
}

/* ── 发送 ── */
async function send(){
  const msg = input.value.trim();
  if(!msg || sending) return;
  push({role:'user', kind:'user', text:msg, ts:Date.now()});
  input.value = ''; autoGrow();
  sending = true; sendBtn.disabled = true;
  showTyping();
  const t0 = Date.now();
  try{
    const res = await fetch('/api/talk', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: msg})
    });
    const data = await res.json();
    await new Promise(r=>setTimeout(r, Math.max(0, 500-(Date.now()-t0))));
    hideTyping();
    push({role:'am', kind: data.error ? 'error' : 'am', text: data.reply, ts:Date.now()});
    if(data.stats) statsEl.textContent = data.stats;
  }catch(e){
    hideTyping();
    push({role:'am', kind:'error', text:'连接失败: ' + e.message, ts:Date.now()});
  }
  sending = false; sendBtn.disabled = false;
  input.focus();
}
function showTyping(){
  typingEl = document.createElement('div');
  typingEl.className = 'msg am typing';
  typingEl.innerHTML = '<div class="meta"><span class="badge b-am">AM</span></div><div class="dots"><span></span><span></span><span></span></div>';
  chat.appendChild(typingEl); scrollBottom();
}
function hideTyping(){ if(typingEl){ typingEl.remove(); typingEl = null; } }
function autoGrow(){
  input.style.height = 'auto';
  input.style.height = Math.min(120, input.scrollHeight) + 'px';
}
function fill(t){ input.value = t; autoGrow(); input.focus(); }

/* ── 备份: 导出 / 导入 / 清空 ── */
function exportChat(){
  const blob = new Blob([JSON.stringify(msgs, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'am-chat-' + new Date().toISOString().slice(0,10) + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}
document.getElementById('importFile').addEventListener('change', function(){
  const f = this.files[0]; if(!f) return;
  const r = new FileReader();
  r.onload = () => {
    try{
      const arr = JSON.parse(r.result);
      if(!Array.isArray(arr)) throw new Error('不是数组');
      arr.forEach(m=>{ if(!m || typeof m.text !== 'string' || !m.kind) throw new Error('字段缺失'); });
      if(arr.length && !confirm('导入将覆盖当前 ' + msgs.length + ' 条记录，确定继续？')) return;
      msgs = arr; save(); chat.innerHTML = ''; msgs.forEach(addMsgEl); scrollBottom(); updateCount();
    }catch(e){ alert('备份文件格式不对: ' + e.message); }
    this.value = '';
  };
  r.readAsText(f);
});
function askClear(){
  document.getElementById('modal-desc').textContent = '将删除本地保存的 ' + msgs.length + ' 条消息，此操作不可恢复。建议先导出备份。';
  document.getElementById('modal').classList.add('show');
}
function closeModal(){ document.getElementById('modal').classList.remove('show'); }
function doClear(){
  msgs = []; save(); chat.innerHTML = ''; closeModal(); updateCount();
}
document.getElementById('modal').addEventListener('click', e=>{ if(e.target.id==='modal') closeModal(); });

/* ── 自发发言轮询 (v3.7 保留) ── */
async function pollUtterances(){
  try{
    const res = await fetch('/api/utterances');
    const data = await res.json();
    (data.utterances || []).forEach(u=>{
      const kind = ['learned','conflict','fuzzy'].indexOf(u.kind) >= 0 ? u.kind : 'idle';
      push({role:'am', kind:kind, text:u.text, ts:Date.now()});
    });
  }catch(e){ /* 静默, 下轮再试 */ }
}

/* ── 事件绑定 ── */
input.addEventListener('keydown', e=>{
  if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
input.addEventListener('input', autoGrow);

/* ── 启动 ── */
initTheme();
load();
setInterval(pollUtterances, 10000);
</script>
</body>
</html>"""


class AMHandler(http.server.BaseHTTPRequestHandler):
    """AM 的 HTTP 请求处理器 (v3.3: 反映射闭环)"""

    # ── v3.3: 会话跟踪 ──
    SESSIONS: dict[str, dict] = {}  # ip → {session_id, reflection_ctx, last_active}
    SESSION_TIMEOUT = 300  # 5 分钟超时

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
        elif self.path == "/graph":
            self._serve_graph_page()
        elif self.path == "/galaxy":
            self._serve_galaxy_page()
        elif self.path.startswith("/vendor/"):
            self._serve_vendor(self.path)
        elif self.path.startswith("/api/modules"):
            self._handle_modules()
        elif self.path == "/api/stats":
            ol_summary = ci.offline_learner.summary() if ci.offline_learner else {}
            self._json({
                "stats": db.stats(),
                "relations": db.count(),
                "dreams": {
                    "verification_rate": ol_summary.get("verification_rate", 0),
                    "total_runs": ol_summary.get("total_runs", 0),
                }
            })
        elif self.path == "/api/reflect":
            self._handle_reflect()
        elif self.path == "/api/utterances":
            # ★ v3.7: 自发发言 — 前端轮询拉取她"想说的话"
            try:
                uts = ci.speaker.drain() if hasattr(ci, 'speaker') else []
                self._json({"utterances": uts})
            except Exception as e:
                self._json({"utterances": [], "error": str(e)[:80]})
        elif self.path == "/api/health":
            self._handle_health()
        elif self.path == "/api/graph":
            self._handle_graph()
        elif self.path == "/api/evidence":
            self._json(_last_evidence if _last_evidence else
                       {"question": "暂无回答记录", "edges": []})
        elif self.path.startswith("/api/entity/"):
            import urllib.parse as _up
            entity = _up.unquote(self.path.split("/api/entity/")[1])
            self._handle_entity(entity)
        elif self.path == "/api/galaxy":
            self._handle_galaxy()
        elif self.path.startswith("/api/vector/"):
            import urllib.parse as _upv
            w = _upv.unquote(self.path.split("/api/vector/")[1])
            self._handle_vector(w)
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

    def _serve_vendor(self, path):
        """★ v3.8b: 本地静态库 (three.js 等) — 断网可用, 零外链"""
        import os as _os
        fname = _os.path.basename(path)
        fpath = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "vendor", fname)
        if not fname.endswith(".js") or not _os.path.isfile(fpath):
            self.send_error(404)
            return
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_graph_page(self):
        """★ v3.6: 知识能量视图 (③) — 星图热力仪表盘"""
        html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AM 知识能量视图</title>
<style>
body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px 24px calc(24px + env(safe-area-inset-bottom))}
#nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
#nav a{color:#8b949e;text-decoration:none;font-size:13px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:7px 14px;min-height:36px;display:inline-flex;align-items:center;transition:all .15s}
#nav a:hover{color:#58a6ff;border-color:#58a6ff}
#nav a.active{color:#58a6ff;background:rgba(88,166,255,.12);font-weight:600}
h1{font-size:20px;color:#58a6ff;margin:0 0 4px}
h2{font-size:14px;color:#8b949e;font-weight:400;margin:0 0 20px}
h3{font-size:14px;color:#58a6ff;margin:20px 0 10px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.bar{height:20px;border-radius:4px;margin:4px 0;display:flex;align-items:center;padding:0 8px;font-size:12px;color:#fff;white-space:nowrap;overflow:hidden}
.tag{display:inline-block;background:#21262d;border:1px solid #30363d;border-radius:4px;padding:2px 8px;margin:3px;font-size:12px}
.cold{color:#f85149}
.stat{display:inline-block;margin-right:24px;font-size:13px}
.stat b{font-size:20px;color:#58a6ff}
</style></head><body>
<div id="nav">
  <a href="/">← 对话</a>
  <a href="/graph" class="active">能量视图</a>
  <a href="/galaxy">知识星系</a>
</div>
<h1>🧠 AsteriaMind 知识能量视图</h1>
<h2>能量代谢 — 哪里热(活跃), 哪里冷(冬眠), 哪里新(成长)</h2>
<div class="card"><h3>🕸️ 实体浏览器 (点实体 → 星形展开 + 数据卡)</h3>
<div style="margin-bottom:8px"><input id="entInput" placeholder="输入实体名, 如 企鹅/蛇/鸟类" style="background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:6px 10px;width:220px">
<button onclick="exploreEntity()" style="background:#238636;border:none;color:#fff;border-radius:6px;padding:6px 14px;cursor:pointer">展开</button></div>
<div id="starMap" style="min-height:180px;position:relative"></div></div>
<div class="card"><div id="stats"></div></div>
<div class="card"><h3>🧊 冷边 (能量低, 需关注)</h3><div id="cold"></div></div>
<div class="card"><h3>🌱 新鲜边 (近24h 成长)</h3><div id="fresh"></div></div>
<div class="card"><h3>📊 关系分布</h3><div id="rel"></div></div>
<div class="card"><h3>🌫️ 熵云 (知识模糊区 — 越虚越不确定)</h3><div id="entropy"></div></div>
<div class="card"><h3>🕰️ 知识生长时间线 (她怎么长起来的)</h3><div id="timeline"></div></div>
<div class="card"><h3>🔗 最近回答的证据链 (她凭什么这么说)</h3><div id="evidence"></div></div>
<script>
async function load(){
  try{
    const r = await fetch('/api/graph');
    const d = await r.json();
    const s = d.stats;
    document.getElementById('stats').innerHTML =
      '<span class="stat">总边 <b>'+s.total_edges.toLocaleString()+'</b></span>'+
      '<span class="stat">命名边 <b>'+s.named_edges+'</b></span>'+
      '<span class="stat">冷边 <b class="'+(s.cold_count>0?'cold':'')+'">'+s.cold_count+'</b></span>';
    // maxE 仅供后续扩展用, 当前没有 hot 数据所以不需要
    document.getElementById('cold').innerHTML = d.cold.length ? d.cold.map(x=>
      '<span class="tag cold">'+x.source+' ['+x.relation+'] '+x.target+' E'+x.energy+'</span>').join('')
      : '<span style="color:#3fb950">✅ 无冷边 — 知识能量健康</span>';
    document.getElementById('fresh').innerHTML = d.fresh.length ? d.fresh.map(x=>
      '<span class="tag">'+x.source+' ['+x.relation+'] '+x.target+'</span>').join('')
      : '<span style="color:#8b949e">近24h 无新增</span>';
    // 删除 hot/assoc 渲染 (暂未启用以避免 GROUP BY 慢查询)
    document.getElementById('rel').innerHTML = d.relation_dist.map(x=>
      '<span class="tag">'+x.relation+' ×'+x.count+'</span>').join('');
    document.getElementById('entropy').innerHTML = (d.entropy_cloud||[]).length ? d.entropy_cloud.map(x=>{
      const blur = Math.min(3, Math.round((x.entropy-0.5)*6));  // 熵越高越模糊
      const red = Math.min(255, Math.round((x.entropy-0.5)*400));
      return '<span class="tag" style="color:rgb('+red+',80,80);filter:blur('+blur+'px)">'
        +x.entity+' H'+x.entropy+'</span>';
    }).join('') : '<span style="color:#3fb950">✅ 无高熵实体 — 知识清晰</span>';
    document.getElementById('timeline').innerHTML = (d.timeline||[]).length ? d.timeline.map(x=>
      '<div style="margin:2px 0;font-size:12px"><span style="color:#8b949e;display:inline-block;width:90px">'+x.time+'</span>'
      +'<span style="color:#58a6ff">'+x.subject+'</span> <span style="color:#d29922">['+x.relation+']</span> '
      +'<span>'+x.target+'</span> <span style="color:#8b949e">('+x.feedback+')</span></div>').join('')
      : '<span style="color:#8b949e">暂无记录</span>';
  }catch(e){ document.getElementById('stats').innerHTML='<span style="color:#f85149">加载失败: '+e+'</span>'; }
}
async function loadEvidence(){
  try{
    const r = await fetch('/api/evidence');
    const d = await r.json();
    if(!d.edges || !d.edges.length){ document.getElementById('evidence').innerHTML='<span style="color:#8b949e">还没回答过问题 — 去聊两句, 这里会显示她走了哪些边</span>'; return; }
    let html = '<div style="margin-bottom:8px">问: <b>'+d.question+'</b> &nbsp; 策略: '+d.strategy+' &nbsp; 意图: '+d.intent;
    if(d.uncertain) html += ' &nbsp; <span class="cold">⚠ 不确定 ('+d.uncertain.entropy.toFixed(2)+')</span>';
    html += '</div>';
    html += d.edges.map((e,i)=>{
      const w = 30 + Math.min(60, e.salience*40);
      return '<div style="margin:3px 0;padding:6px 10px;background:#21262d;border-radius:6px;border-left:3px solid '+(d.uncertain?'#f85149':'#3fb950')+';width:'+w+'%">'
        + '<span style="color:#58a6ff">'+d.subject+'</span> '
        + '<span style="color:#d29922">['+e.relation+']</span> '
        + '<span style="color:#e6edf3">'+e.target+'</span> '
        + '<span style="color:#8b949e;font-size:11px">E'+e.energy+'</span></div>';
    }).join('');
    document.getElementById('evidence').innerHTML = html;
  }catch(e){ document.getElementById('evidence').innerHTML='<span style="color:#f85149">证据链加载失败</span>'; }
}
load(); setInterval(load, 10000);
loadEvidence(); setInterval(loadEvidence, 10000);
async function exploreEntity(){
  const ent = document.getElementById('entInput').value.trim();
  if(!ent) return;
  try{
    const r = await fetch('/api/entity/'+encodeURIComponent(ent));
    const d = await r.json();
    const box = document.getElementById('starMap');
    const cx = 300, cy = 110;
    let html = '<div style="text-align:center;margin-bottom:6px"><span style="color:#58a6ff;font-size:16px;font-weight:500">'+d.entity+'</span>'
      +' <span style="color:#8b949e">熵 H'+d.entropy+'</span></div>';
    const rels = d.out_edges||[];
    rels.forEach((e,i)=>{
      const ang = (2*Math.PI*i)/Math.max(rels.length,1) - Math.PI/2;
      const x = cx + 130*Math.cos(ang), y = cy + 80*Math.sin(ang);
      const color = e.relation.indexOf('NOT')>=0 ? '#f85149' : '#3fb950';
      html += '<svg style="position:absolute;left:0;top:0;width:100%;height:100%" viewBox="0 0 600 220">'
        +'<line x1="'+cx+'" y1="'+cy+'" x2="'+x+'" y2="'+y+'" stroke="'+color+'" stroke-width="1.5" stroke-dasharray="'+(e.energy<0.5?'4 3':'none')+'"/>'
        +'<text x="'+(cx+x)/2+'" y="'+(cy+y)/2-4+'" fill="#d29922" font-size="11" text-anchor="middle">['+e.relation+']</text>'
        +'<circle cx="'+cx+'" cy="'+cy+'" r="18" fill="#1f6feb" stroke="#58a6ff" stroke-width="1"/>'
        +'<circle cx="'+x+'" cy="'+y+'" r="12" fill="#21262d" stroke="'+color+'" stroke-width="1" cursor="pointer" data-ent="'+e.target+'" onclick="exploreNode(this)"/>'
        +'<text x="'+x+'" y="'+y+'" fill="#e6edf3" font-size="10" text-anchor="middle" dominant-baseline="central">'+e.target+'</text>'
        +'</svg>';
    });
    if(rels.length) html += '<div style="position:absolute;left:0;top:180px;font-size:11px;color:#8b949e">点击外圈实体可继续展开 — 虚线=低能量边</div>';
    if(!rels.length) html += '<div style="color:#8b949e;text-align:center;padding:30px">「'+d.entity+'」还没有命名知识边 — 教教她吧</div>';
    box.innerHTML = html;
  }catch(e){ document.getElementById('starMap').innerHTML='<span style="color:#f85149">展开失败: '+e+'</span>'; }
}
function exploreNode(el){ document.getElementById('entInput').value = el.getAttribute('data-ent'); exploreEntity(); }
</script></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _serve_galaxy_page(self):
        """★ v3.8c: 知识星系 — three.js 3D 点阵星云 (本地组件, 零外链)

        银河系式扁平旋涡星云: 中心金核=分类中枢, 3条旋臂=普通实体
          发光圆点(亮度=能量/颜色=类型/大小=度数) + 3000背景星尘 + 缓慢自转
          点击恒星才展开局部链接(细发光管, ≤33条) → 永不拥挤
        """
        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AM 知识星系 · 3D 星云</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}
body{background:#04070f;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
#scene-container{position:fixed;inset:0}
#scene-container canvas{display:block}
#scene-container .label{position:absolute;pointer-events:none;font-size:13px;font-weight:600;color:#fff;text-shadow:0 0 8px rgba(0,0,0,.95),0 1px 3px #000;white-space:nowrap;transform:translate(-50%,-130%);background:rgba(4,7,15,.55);padding:2px 8px;border-radius:6px;border:1px solid rgba(255,255,255,.15);backdrop-filter:blur(3px)}
#scene-container .label.hub{color:#ffd76a;border-color:rgba(255,215,106,.4)}
a{color:#8b949e;text-decoration:none}
#info{position:fixed;top:14px;left:16px;z-index:10;font-size:13px;color:#8b949e;text-shadow:0 1px 6px rgba(0,0,0,.8);max-width:70vw}
#info b{color:#58a6ff}
#navs{position:fixed;top:40px;left:16px;z-index:10;display:flex;gap:6px;flex-wrap:wrap}
#navs a{font-size:12px;background:rgba(22,27,34,.85);border:1px solid #30363d;border-radius:7px;padding:6px 12px;min-height:32px;display:inline-flex;align-items:center;transition:all .15s;backdrop-filter:blur(6px)}
#navs a:hover{color:#58a6ff;border-color:#58a6ff}
#navs a.active{color:#58a6ff;background:rgba(88,166,255,.12);font-weight:600}
#search-wrap{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:12;width:min(320px,72vw)}
#search{width:100%;background:rgba(22,27,34,.85);border:1px solid #30363d;border-radius:12px;padding:10px 14px;color:#e6edf3;font-size:16px;outline:none;backdrop-filter:blur(8px);transition:border-color .2s}
#search::placeholder{color:#484f58}
#search:focus{border-color:#58a6ff}
#search-list{position:absolute;top:44px;left:0;right:0;background:rgba(22,27,34,.95);border:1px solid #30363d;border-radius:10px;display:none;max-height:220px;overflow-y:auto;backdrop-filter:blur(8px);z-index:13}
#search-list div{padding:8px 12px;font-size:13px;color:#8b949e;cursor:pointer;border-bottom:1px solid rgba(48,54,61,.5);display:flex;justify-content:space-between;gap:8px}
#search-list div:last-child{border-bottom:none}
#search-list div:hover{color:#58a6ff;background:rgba(88,166,255,.1)}
#tip{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);z-index:10;font-size:12px;color:#8b949e;background:rgba(13,17,23,.7);border:1px solid rgba(48,54,61,.6);padding:7px 16px;border-radius:20px;white-space:nowrap;backdrop-filter:blur(6px)}
#legend{position:fixed;left:16px;bottom:16px;z-index:10;font-size:11px;color:#8b949e;background:rgba(13,17,23,.72);border:1px solid rgba(48,54,61,.6);padding:9px 13px;border-radius:10px;backdrop-filter:blur(6px)}
#legend .row{display:flex;align-items:center;gap:7px;margin:3px 0}
#legend .dot{width:9px;height:9px;border-radius:50%}
#legend .sw{width:16px;height:3px;border-radius:2px}
#tooltip{position:fixed;z-index:20;background:rgba(22,27,34,.96);border:1px solid #30363d;border-radius:10px;padding:9px 13px;font-size:12px;pointer-events:none;display:none;box-shadow:0 8px 24px rgba(0,0,0,.5);max-width:250px}
#tooltip b{color:#58a6ff;font-size:13px}
#tooltip .ttm{color:#8b949e;font-size:11px;margin-top:3px}
#card{position:fixed;right:16px;top:14px;z-index:12;background:rgba(22,27,34,.95);border:1px solid #30363d;border-radius:12px;padding:14px 16px;min-width:230px;max-width:300px;display:none;font-size:13px;max-height:72vh;overflow-y:auto;box-shadow:0 10px 30px rgba(0,0,0,.5);backdrop-filter:blur(8px)}
#card h3{margin:0 0 4px;color:#58a6ff;font-size:15px;padding-right:18px}
#card .meta{color:#8b949e;font-size:11px;margin-bottom:8px}
#card .entropy{color:#f0883e;font-size:12px;margin-bottom:8px}
#card .rel{margin:4px 0;color:#e6edf3;font-size:12px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
#card .rel .r{display:inline-block;width:14px;height:14px;border-radius:3px;flex-shrink:0}
#card .rel .tgt{cursor:pointer}
#card .rel .tgt:hover{color:#58a6ff;text-decoration:underline}
#card .rel .e{color:#8b949e;font-size:10px;margin-left:auto}
#card .sec{margin-top:10px;border-top:1px solid #30363d;padding-top:8px;font-size:11px;color:#8b949e}
#card .tag{display:inline-block;background:rgba(139,148,158,.12);border:1px solid #30363d;border-radius:4px;padding:2px 7px;margin:3px 3px 0 0;font-size:11px;color:#8b949e;cursor:pointer}
#card .tag:hover{color:#58a6ff;border-color:#58a6ff}
#card .close{position:absolute;top:6px;right:8px;background:none;border:none;color:#8b949e;font-size:15px;cursor:pointer;padding:6px}
#card .close:hover{color:#e6edf3}
#load-tip{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:15;color:#8b949e;font-size:13px;display:none;text-align:center;line-height:1.8}
#load-tip .spin{width:26px;height:26px;border:2px solid #30363d;border-top-color:#58a6ff;border-radius:50%;margin:0 auto 12px;animation:rot .9s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
@media (max-width:640px){
  #card{left:10px;right:10px;top:auto;bottom:10px;max-height:46vh;min-width:0}
  #legend{display:none}
  #info{font-size:12px}
}
</style>
</head>
<body>
<div id="info">🌌 <b>AM 知识星系</b> · 3D 星云</div>
<div id="navs">
  <a href="/">← 对话</a>
  <a href="/graph">能量视图</a>
  <a href="/galaxy" class="active">知识星系</a>
</div>
<div id="search-wrap">
  <input id="search" placeholder="搜索恒星…" autocomplete="off">
  <div id="search-list"></div>
</div>
<div id="load-tip"><div class="spin"></div>正在展开星云…</div>
<div id="tooltip"></div>
<div id="card"><button class="close" onclick="hideCard()">✕</button><div id="card-body"></div></div>
<div id="scene-container"></div>
<div id="tip">拖拽旋转 · 滚轮/双指缩放 · 点击恒星展开链接 · 点空白收起</div>
<div id="legend">
  <div class="row"><span class="dot" style="background:#ffd76a"></span>中枢分类 (金核)</div>
  <div class="row"><span class="dot" style="background:#f0883e"></span>高熵 · 知识模糊</div>
  <div class="row"><span class="dot" style="background:#58a6ff"></span>正常实体 (蓝白)</div>
  <div class="row"><span class="sw" style="background:#3fb950"></span>IS_A 分类</div>
  <div class="row"><span class="sw" style="background:#58a6ff"></span>CAN 能力</div>
  <div class="row"><span class="sw" style="background:#f85149"></span>NOT_CAN 否定</div>
  <div class="row"><span class="sw" style="background:#d29922"></span>HAS 属性</div>
  <div class="row"><span class="sw" style="background:#a371f7"></span>EATS 捕食</div>
  <div class="row"><span class="sw" style="background:#f0883e"></span>LIVES_IN 栖息</div>
  <div class="row"><span class="sw" style="background:#39c5cf"></span>ORBITS 环绕</div>
</div>
<script src="/vendor/three.min.js"></script>
<script src="/vendor/OrbitControls.js"></script>
<script src="/vendor/CSS2DRenderer.js"></script>
<script>
const relColor = {'IS_A':'#3fb950','CAN':'#58a6ff','NOT_CAN':'#f85149','HAS':'#d29922','EATS':'#a371f7','LIVES_IN':'#f0883e','ORBITS':'#39c5cf','CAUSES':'#e34b4b'};
const container = document.getElementById('scene-container');
const tooltipEl = document.getElementById('tooltip');
const searchEl = document.getElementById('search');
const listEl = document.getElementById('search-list');
let nodes = [], byName = new Map(), hotSet = new Set();
let maxDeg = 1, maxE = 1;
let sel = null, selNode = null, selData = null, neighbors = new Set();
let hoverName = null;
let camAnim = null;

/* ── three.js 场景 ── */
let scene, camera, renderer, controls, labelRenderer;
let galaxyGroup, linksGroup, bgPoints;
let glowTex;
let cw = 0, ch = 0;
function hexToInt(h){ return parseInt(h.slice(1), 16); }
function makeGlowTexture(){
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.9)');
  grad.addColorStop(0.6, 'rgba(255,255,255,0.25)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.Texture(c);
  t.needsUpdate = true;
  return t;
}
function init3d(){
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x04070f);
  camera = new THREE.PerspectiveCamera(55, cw / ch, 1, 4000);
  camera.position.set(360, 240, 460);
  renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(cw, ch);
  container.appendChild(renderer.domElement);
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 30;
  controls.maxDistance = 1200;
  labelRenderer = new THREE.CSS2DRenderer();
  labelRenderer.domElement.style.position = 'absolute';
  labelRenderer.domElement.style.top = '0';
  labelRenderer.domElement.style.pointerEvents = 'none';
  container.appendChild(labelRenderer.domElement);
  galaxyGroup = new THREE.Group();
  linksGroup = new THREE.Group();
  galaxyGroup.add(linksGroup);
  scene.add(galaxyGroup);
  glowTex = makeGlowTexture();
  addBackgroundDust();
}
function addBackgroundDust(){
  const n = 3000;
  const pos = new Float32Array(n * 3);
  for(let i = 0; i < n; i++){
    const r = 420 + Math.random() * 900;
    const a = Math.random() * 6.283;
    const b = Math.acos(2 * Math.random() - 1);
    pos[i*3]   = r * Math.sin(b) * Math.cos(a);
    pos[i*3+1] = r * Math.cos(b) * 0.6;
    pos[i*3+2] = r * Math.sin(b) * Math.sin(a);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({color: 0x7788aa, size: 1.3, transparent: true, opacity: 0.55, sizeAttenuation: true, depthWrite: false});
  bgPoints = new THREE.Points(geo, mat);
  scene.add(bgPoints);
}
function gauss(){ return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5; }
/* ── 布局: 银河扁平旋涡 — 中心金核 + 3条旋臂 ── */
function layout(){
  const hubs = nodes.filter(n => n.hub);
  const stars = nodes.filter(n => !n.hub);
  const N = stars.length || 1;
  const R = 190;
  stars.forEach((n, i) => {
    const t = i / N;
    const arm = i % 3;
    const a = t * 13.8 + arm * 2.094;
    const r = R * Math.sqrt(t) * (0.8 + 0.2 * Math.sin(t * 40));
    n.pos = new THREE.Vector3(Math.cos(a) * r + gauss() * 8, gauss() * 13, Math.sin(a) * r + gauss() * 8);
  });
  const M = hubs.length || 1;
  hubs.forEach((n, i) => {
    const t = i / M;
    const a = t * 6.283 * 3 + (i % 5) * 0.15;
    const r = 34 * Math.sqrt(t) + 5;
    n.pos = new THREE.Vector3(Math.cos(a) * r, gauss() * 5, Math.sin(a) * r);
  });
}
/* ── 星点 Sprite ── */
function nodeColor(n){
  if(n.hub) return '#ffd76a';
  if(hotSet.has(n.entity)) return '#f0883e';
  return '#58a6ff';
}
function nodeSize(n){
  if(n.hub) return 9 + Math.min(13, n.edges * 0.55);
  return 3 + Math.min(8, 3.4 * Math.log2(1 + n.edges) / Math.log2(2 + maxDeg));
}
function buildStars(){
  nodes.forEach(n => {
    n.size = nodeSize(n);
    const mat = new THREE.SpriteMaterial({map: glowTex, color: hexToInt(nodeColor(n)), transparent: true, depthWrite: false, opacity: 1});
    const sp = new THREE.Sprite(mat);
    sp.position.copy(n.pos);
    sp.scale.set(n.size, n.size, 1);
    sp.userData.name = n.entity;
    n.sprite = sp;
    galaxyGroup.add(sp);
  });
}
/* ── 局部链接: 细发光管 ── */
function clearLinks(){
  while(linksGroup.children.length){
    const c = linksGroup.children.pop();
    if(c.geometry) c.geometry.dispose();
    if(c.material) c.material.dispose();
  }
}
function addTube(a, b, color){
  const dir = new THREE.Vector3().subVectors(b, a);
  const len = dir.length();
  if(len < 0.001) return;
  const geo = new THREE.CylinderGeometry(0.3, 0.3, len, 6, 1);
  const mat = new THREE.MeshBasicMaterial({color: color, transparent: true, opacity: 0.85});
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.copy(a).add(dir.clone().multiplyScalar(0.5));
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  linksGroup.add(mesh);
}
function buildLinks(d){
  clearLinks();
  if(!selNode) return;
  const edges = (d.out_edges || []).map(e => ({rel: e.relation, target: e.target}))
    .concat((d.in_edges || []).map(e => ({rel: e.relation, target: e.source})));
  edges.forEach(e => {
    const nn = byName.get(e.target);
    if(!nn) return;
    addTube(selNode.pos, nn.pos, hexToInt(relColor[e.rel] || '#888888'));
  });
}
/* ── 亮度: 选中时非邻居变暗 ── */
function updateBrightness(){
  nodes.forEach(n => {
    const m = n.sprite.material;
    if(sel){
      if(n.entity === sel){ m.opacity = 1; n.sprite.scale.set(n.size * 1.6, n.size * 1.6, 1); }
      else if(neighbors.has(n.entity)){ m.opacity = 1; n.sprite.scale.set(n.size * 1.25, n.size * 1.25, 1); }
      else { m.opacity = 0.14; }
    } else {
      m.opacity = 1;
      n.sprite.scale.set(n.size, n.size, 1);
    }
  });
}
/* ── CSS2D 标签 ── */
let labelObjs = [];
function clearLabels(){
  labelObjs.forEach(o => { scene.remove(o); if(o.element) o.element.remove(); });
  labelObjs = [];
}
function setLabel(name, hub){
  const el = document.createElement('div');
  el.className = 'label' + (hub ? ' hub' : '');
  el.textContent = name;
  const obj = new THREE.CSS2DObject(el);
  const n = byName.get(name);
  obj.position.copy(n.pos);
  scene.add(obj);
  labelObjs.push(obj);
}
/* ── 相机飞行 ── */
function flyTo(pos, dist){
  if(camAnim) cancelAnimationFrame(camAnim);
  const fromT = controls.target.clone();
  const fromP = camera.position.clone();
  const dir = new THREE.Vector3().subVectors(fromP, fromT).normalize();
  const toP = pos.clone().add(dir.multiplyScalar(dist));
  const t0 = performance.now(), D = 600;
  function step(tt){
    const k = Math.min(1, (tt - t0) / D);
    const e = 1 - Math.pow(1 - k, 3);
    controls.target.lerpVectors(fromT, pos, e);
    camera.position.lerpVectors(fromP, toP, e);
    controls.update();
    if(k < 1) camAnim = requestAnimationFrame(step); else camAnim = null;
  }
  camAnim = requestAnimationFrame(step);
}
/* ── 选中 / 数据卡 ── */
async function selectEntity(name){
  const n = byName.get(name);
  if(!n) return;
  sel = name; selNode = n; selData = null;
  neighbors = new Set([name]);
  clearLinks();
  updateBrightness();
  clearLabels();
  setLabel(name, n.hub);
  flyTo(n.pos, 130);
  try{
    const d = await (await fetch('/api/entity/' + encodeURIComponent(name))).json();
    selData = d;
    (d.out_edges || []).forEach(e => neighbors.add(e.target));
    (d.in_edges || []).forEach(e => neighbors.add(e.source));
    buildLinks(d);
    updateBrightness();
    showCard(d);
  }catch(e){}
}
function clearSel(){
  sel = null; selNode = null; selData = null; neighbors = new Set();
  clearLinks(); clearLabels(); updateBrightness(); hideCard();
}
function showCard(d){
  const body = document.getElementById('card-body');
  let h = '<h3>' + d.entity + '</h3>';
  h += '<div class="meta">出边 ' + (d.out_edges || []).length + ' · 入边 ' + (d.in_edges || []).length + ' · 熵 H' + d.entropy + '</div>';
  if(d.entropy > 0.5) h += '<div class="entropy">⚠ 知识模糊 — 她的理解还不确定</div>';
  (d.out_edges || []).forEach(e => {
    h += '<div class="rel"><span class="r" style="background:' + (relColor[e.relation] || '#888') + '"></span>['
      + e.relation + '] <span class="tgt" data-n="' + escAttr(e.target) + '" onclick="focusFromCard(this)">'
      + e.target + '</span><span class="e">E' + e.energy + '</span></div>';
  });
  if(!(d.out_edges || []).length) h += '<div style="color:#8b949e">还没有命名知识边 — 教教她吧</div>';
  h += '<div class="sec">语义邻居 (向量联想)</div><div id="vnei" style="margin-top:4px"></div>';
  body.innerHTML = h;
  document.getElementById('card').style.display = 'block';
  (async () => {
    try{
      const v = await (await fetch('/api/vector/' + encodeURIComponent(d.entity))).json();
      const box = document.getElementById('vnei');
      if(!box) return;
      if(v.neighbors && v.neighbors.length){
        box.innerHTML = v.neighbors.slice(0, 8).map(x =>
          '<span class="tag" onclick="focusFromTag(\'' + x.word.replace(/'/g, '') + '\')">' + x.word + ' ' + x.sim.toFixed(2) + '</span>').join('');
      } else box.innerHTML = '<span style="color:#8b949e">词表无此词 — 喂语料后会长出来</span>';
    }catch(e){ const box = document.getElementById('vnei'); if(box) box.innerHTML = '<span style="color:#8b949e">向量服务未启动</span>'; }
  })();
}
function escAttr(s){ return String(s).replace(/"/g, '&quot;'); }
function focusFromCard(el){ selectEntity(el.dataset.n); }
function focusFromTag(w){ selectEntity(w); }
function hideCard(){ document.getElementById('card').style.display = 'none'; }
function showTip(n, sx, sy){
  if(!n){ tooltipEl.style.display = 'none'; return; }
  tooltipEl.innerHTML = '<b>' + n.entity + '</b>' + (n.hub ? ' <span style="color:#ffd76a">★中枢</span>' : '')
    + '<div class="ttm">出边 ' + n.edges + ' · 能量 ' + n.energy.toFixed(1)
    + (hotSet.has(n.entity) ? ' · <span style="color:#f0883e">高熵</span>' : '') + '</div>'
    + '<div class="ttm" style="color:#484f58">点击展开链接</div>';
  tooltipEl.style.display = 'block';
  tooltipEl.style.left = Math.min(sx + 14, cw - 260) + 'px';
  tooltipEl.style.top = Math.min(sy + 14, ch - 90) + 'px';
}
/* ── 拾取与交互 ── */
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let isDragging = false, downX = 0, downY = 0, moved = false;
controls.addEventListener('start', () => { isDragging = true; });
controls.addEventListener('end', () => { isDragging = false; moved = false; });
function pick(e){
  pointer.x = (e.clientX / cw) * 2 - 1;
  pointer.y = -(e.clientY / ch) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(galaxyGroup.children.filter(c => c.isSprite), false);
  return hits.length ? hits[0].object.userData.name : null;
}
container.addEventListener('pointerdown', e => {
  downX = e.clientX; downY = e.clientY; moved = false;
});
container.addEventListener('pointermove', e => {
  if(!isDragging){
    const name = pick(e);
    if(name !== hoverName){
      hoverName = name;
      clearLabels();
      if(sel) setLabel(sel, byName.get(sel).hub);
      if(name && name !== sel){
        const n = byName.get(name);
        setLabel(name, n.hub);
        showTip(n, e.clientX, e.clientY);
      } else {
        tooltipEl.style.display = 'none';
      }
    }
  }
});
container.addEventListener('pointerup', e => {
  const dx = e.clientX - downX, dy = e.clientY - downY;
  if(Math.abs(dx) + Math.abs(dy) > 6){ moved = true; return; }
  const name = pick(e);
  if(name) selectEntity(name); else clearSel();
});
container.addEventListener('wheel', e => { /* OrbitControls 处理 */ }, {passive: false});
/* ── 搜索 ── */
searchEl.addEventListener('input', () => {
  const q = searchEl.value.trim();
  if(!q){ listEl.style.display = 'none'; return; }
  const hits = nodes.filter(n => n.entity.indexOf(q) >= 0).slice(0, 8);
  if(!hits.length){ listEl.style.display = 'none'; return; }
  listEl.innerHTML = hits.map(n =>
    '<div data-k="' + escAttr(n.entity) + '"><span>' + n.entity + '</span><span style="color:#484f58;font-size:10px">' + n.edges + '边</span></div>').join('');
  listEl.style.display = 'block';
  listEl.querySelectorAll('div').forEach(d => {
    d.onclick = () => { searchEl.value = ''; listEl.style.display = 'none'; selectEntity(d.dataset.k); };
  });
});
searchEl.addEventListener('keydown', e => {
  if(e.key === 'Enter'){
    const q = searchEl.value.trim();
    if(q){
      const n = nodes.find(x => x.entity === q) || nodes.filter(x => x.entity.indexOf(q) >= 0)[0];
      if(n){ searchEl.value = ''; listEl.style.display = 'none'; selectEntity(n.entity); }
    }
  }
  if(e.key === 'Escape'){ listEl.style.display = 'none'; searchEl.blur(); }
});
document.addEventListener('click', e => {
  if(!e.target.closest('#search-wrap')) listEl.style.display = 'none';
});
window.addEventListener('resize', () => {
  cw = container.clientWidth; ch = container.clientHeight;
  camera.aspect = cw / ch; camera.updateProjectionMatrix();
  renderer.setSize(cw, ch);
  labelRenderer.setSize(cw, ch);
});
/* ── 渲染循环 (3D 场景持续渲染, GPU 轻载) ── */
const clock = new THREE.Clock();
function animate(){
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  galaxyGroup.rotation.y += 0.0007;   /* 缓慢自转 */
  if(selNode){
    const pulse = 1 + 0.12 * Math.sin(performance.now() / 400);
    selNode.sprite.scale.set(selNode.size * 1.6 * pulse, selNode.size * 1.6 * pulse, 1);
  }
  nodes.forEach(n => {
    if(n.hub && !sel){
      const p = 1 + 0.1 * Math.sin(performance.now() / 500 + n.pos.x * 0.02);
      n.sprite.scale.set(n.size * p, n.size * p, 1);
    }
  });
  controls.update();
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}
/* ── 数据加载 ── */
async function load(){
  document.getElementById('load-tip').style.display = 'block';
  try{
    const gal = await (await fetch('/api/galaxy')).json();
    const gl = gal.nodes || gal;
    nodes = gl.map(g => ({entity: g.entity, edges: g.edges, energy: g.energy || 1, in_degree: g.in_degree || 0, hub: !!g.is_hub}));
    if(!nodes.length) throw new Error('星图还没有实体 — 先去聊几句吧');
    maxDeg = Math.max(1, ...nodes.map(n => n.edges));
    maxE = Math.max(0.0001, ...nodes.map(n => n.energy));
    try{
      const g2 = await (await fetch('/api/graph')).json();
      hotSet = new Set((g2.entropy_cloud || []).map(c => c.entity));
    }catch(e){}
    byName = new Map(nodes.map(n => [n.entity, n]));
    cw = container.clientWidth; ch = container.clientHeight;
    init3d();
    layout();
    buildStars();
    requestAnimationFrame(animate);
    document.getElementById('load-tip').style.display = 'none';
  }catch(e){
    document.getElementById('load-tip').innerHTML = '<div style="color:#f85149">星云加载失败: ' + e.message + '</div>';
  }
}
load();
</script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

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

            # ── v3.6: 简化的会话管理 (旧反映射管线已退役) ──
            sid = self.client_address[0]
            now = time.time()
            session = self.SESSIONS.get(sid)

            # 检查超时
            if session and (now - session.get("last_active", 0) > self.SESSION_TIMEOUT):
                session = None

            # 新会话
            if not session:
                session = {
                    "session_id": str(int(now)),
                    "last_active": now,
                    "exchange_count": 0,
                }
                self.SESSIONS[sid] = session

            # ── 短期记忆: 最近 4 轮对话 ★ ──
            topic = self._extract_topic(text)
            CONV_MEMORY.add(sid, "user", text, topic)
            # ★ v3.8: 对话语料实时回流 — 用户的话是她该学的说话方式
            try:
                _REPLAY.ingest(text)
            except Exception:
                pass
            # ★ v3.9 F18 (瓶颈二): 句间衔接统计 — 用上一轮用户话 + 本轮构成轮次对
            try:
                if "last_user_text" in session and session["last_user_text"]:
                    _REPLAY.learn_transition(session["last_user_text"], text)
            except Exception:
                pass
            session["last_user_text"] = text
            recent = CONV_MEMORY.get_recent(sid, n=4)
            short_mem = "\n".join(f"[{r['role']}]: {r['content'][:120]}" for r in recent)
            # 长记忆上下文
            context_str = CONV_MEMORY.get_context_string(sid, text)

            reply, action, cognitive = self._process(
                text, context=(short_mem + "\n---\n" + (context_str or "")))

            # ── 更新会话 ──
            session["last_active"] = now
            session["exchange_count"] += 1

            CONV_MEMORY.add(sid, "am", reply, topic)

            # ── 构建响应 (含反映射信息) ──
            resp_data = {
                "reply": reply, "action": action,
                "cognitive": cognitive,
                "stats": f"星图: {ci.mother.star_map.conn.execute('SELECT COUNT(*) FROM directed_edges').fetchone()[0]} 边",
            }

            # 如果刚结束了旧会话, 附带评估摘要
            if cognitive.get("was_correct_last") is not None:
                resp_data["last_feedback"] = {
                    "was_correct": cognitive["was_correct_last"],
                    "signal": cognitive.get("prev_feedback", {}).get("signal", ""),
                }

            # 附带上轮反馈信息
            if cognitive.get("prev_feedback"):
                resp_data["prev_feedback"] = cognitive["prev_feedback"]

            self._json(resp_data)
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

    def _handle_reflect(self):
        """v3.3: 获取当前会话的自我评估"""
        sid = self.client_address[0]
        session = self.SESSIONS.get(sid)
        if not session:
            self._json({"status": "no_session", "summary": "无活跃会话"})
            return
        assessment = ci.get_session_reflection(session.get("session_id", ""))
        # 附加权重信息
        assessment["module_weights"] = ci.mother.meta_cognition.get_all_weights()
        self._json(assessment)

    def _handle_health(self):
        """v3.3: 系统健康报告"""
        health = ci.mother.get_health()
        health["meta_cognition_weights"] = ci.mother.meta_cognition.get_all_weights()
        health["star_map_traces"] = ci.cognitive_star_map.count()
        self._json(health)

    def _handle_graph(self):
        """★ v3.6: 知识能量视图 (③) — 星图热力数据 (简化版)

        排除 GROUP BY 全表扫描 (700万 co_text 上 GROUP BY 慢)
        返回:
          cold:    低能量命名边 (无 GROUP BY, 快)
          fresh:   最近新增边 (无 GROUP BY)
          named_stats: 关系分布 (GROUP BY 限定命名边, 已加索引)
          totals:   星图总数
        """
        # 用专用连接, 不与后台线程争锁
        import sqlite3 as sqlite3_mod
        api_conn = sqlite3_mod.connect('D:/AM/HiveMind_repo/src/asteriamind.db')
        api_conn.execute('PRAGMA busy_timeout = 5000')
        conn = api_conn

        # 冷边: 命名边 + 低能量 (主键 (source,target,relation) 走索引快)
        cold = conn.execute(
            "SELECT source, relation, target, ROUND(COALESCE(energy,0),2) as e "
            "FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES') "
            "AND COALESCE(energy,1.0) < 0.4 "
            "ORDER BY e ASC LIMIT 10").fetchall()

        # 新鲜边: 命名边按 last_update DESC 走主键索引
        fresh = conn.execute(
            "SELECT source, relation, target FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES') "
            "ORDER BY last_update DESC LIMIT 10").fetchall()

        # 关系分布
        rel_dist = conn.execute(
            "SELECT relation, COUNT(*) FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN','NOT_IS_A') "
            "GROUP BY relation").fetchall()
        named_edges = sum(n for _, n in rel_dist)
        total_edges = conn.execute(
            "SELECT COUNT(*) FROM directed_edges").fetchone()[0]

        # ★ v3.6: 熵云 — 高熵实体 (知识模糊区)
        # 直接用 api_conn 计算, 不碰 ci.critic (它锁共享连接, 会死锁!)
        # 限 200 实体 (够用, 不再 5s+)
        entropy_cloud = []
        import math
        entities = api_conn.execute(
            "SELECT DISTINCT source FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES') LIMIT 200").fetchall()
        for (e,) in entities:
            rels = api_conn.execute(
                "SELECT relation, COUNT(*) FROM directed_edges "
                "WHERE source=? AND relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN') "
                "GROUP BY relation", (e,)).fetchall()
            if not rels:
                continue
            total = sum(n for _, n in rels)
            if total <= 1:
                continue
            h = 0.0
            for _, n in rels:
                p = n / total
                h -= p * math.log(p) if p > 0 else 0
            h_norm = h / math.log(6)
            if h_norm > 0.8:  # 熵阈值
                entropy_cloud.append({"entity": e, "entropy": round(h_norm, 2)})
        entropy_cloud.sort(key=lambda x: -x["entropy"])
        entropy_cloud = entropy_cloud[:12]

        # ★ v3.6: 时间演化 (②) — 知识怎么长出来的, 最近 30 条痕迹
        from AsteriaMind.cognitive_star_map import _is_valid_entity_pair
        timeline = []
        for subj, pred, obj, fb, ts in api_conn.execute(
            "SELECT subj, pred, obj, feedback, timestamp FROM cognitive_traces "
            "ORDER BY timestamp DESC LIMIT 60").fetchall():
            # 质量门过滤历史残片 (部分 IS_A 依赖于 这种)
            if not _is_valid_entity_pair(subj, obj):
                continue
            timeline.append({
                "time": time.strftime('%m-%d %H:%M', time.localtime(ts)) if ts else "?",
                "subject": subj, "relation": pred, "target": obj,
                "feedback": fb,
            })
            if len(timeline) >= 25:
                break
        api_conn.close()

        self._json({
            "cold": [{"source": s, "relation": r, "target": t, "energy": e}
                     for s, r, t, e in cold],
            "fresh": [{"source": s, "relation": r, "target": t}
                      for s, r, t in fresh],
            "relation_dist": [{"relation": r, "count": n} for r, n in rel_dist],
            "entropy_cloud": entropy_cloud,
            "timeline": timeline,
            "stats": {
                "total_edges": total_edges,
                "named_edges": named_edges,
                "cold_count": len(cold),
            },
        })

    def _handle_modules(self):
        """★ v3.7: 认知模块注册表 — 查看/开关 (门框, 人类现在就能操作)

        GET /api/modules                    → 全部模块状态
        GET /api/modules?toggle=critic&enabled=false → 卸载/禁用
        """
        from AsteriaMind.module_registry import REGISTRY
        import urllib.parse as _upm
        if "?" in self.path:
            qs = _upm.parse_qs(self.path.split("?", 1)[1])
            name = qs.get("toggle", [""])[0]
            enabled = qs.get("enabled", ["true"])[0] == "true"
            if name:
                ok = REGISTRY.toggle(name, enabled)
                self._json({"toggled": name, "enabled": enabled,
                            "ok": ok, **REGISTRY.health_report()})
                return
        self._json(REGISTRY.health_report())

    def _handle_galaxy(self):
        """★ v3.6: 星系视图数据 — 实体 + 能量 + 分类中枢 (自动涌现)

        返回: [{entity, edges, energy, in_degree, is_hub}, ...]
        中枢 = IS_A 被 ≥2 个实体指向的 target (行星/大洲/水果...)
        分类中枢不需要人工建 — 统计涌现, 学了知识自动长出来

        性能: temp 表预筛命名边 rowid (走部分索引), 聚合 15 倍提速
        """
        import sqlite3 as sqlite3_mod
        api_conn = sqlite3_mod.connect('D:/AM/HiveMind_repo/src/asteriamind.db')
        api_conn.execute('PRAGMA busy_timeout = 5000')

        NAMED = "('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN','NOT_IS_A')"

        # 预筛命名边 rowid → temp 表 (部分索引 313 行, 避免 700 万全扫)
        api_conn.execute(
            "CREATE TEMP TABLE _n AS SELECT rowid FROM directed_edges "
            "WHERE relation IN " + NAMED)
        # 实体 (source 维度): 出边数 + 能量
        rows = api_conn.execute(
            f"SELECT de.source, COUNT(*), ROUND(SUM(COALESCE(de.energy,1.0)),1) "
            f"FROM directed_edges de JOIN _n ON de.rowid=_n.rowid "
            f"GROUP BY de.source").fetchall()
        # 分类中枢: IS_A 被指向 ≥2 次 = 涌现的分类词
        hubs = api_conn.execute(
            "SELECT de.target, COUNT(*) FROM directed_edges de "
            "JOIN _n ON de.rowid=_n.rowid WHERE de.relation='IS_A' "
            "AND LENGTH(de.target)<=6 GROUP BY de.target "
            "HAVING COUNT(*) >= 2 ORDER BY COUNT(*) DESC LIMIT 40").fetchall()
        hub_map = {t: c for t, c in hubs}
        # IS_A 入度
        indeg = api_conn.execute(
            "SELECT de.target, COUNT(*) FROM directed_edges de "
            "JOIN _n ON de.rowid=_n.rowid WHERE de.relation='IS_A' "
            "GROUP BY de.target").fetchall()
        indeg_map = {t: c for t, c in indeg}
        api_conn.execute("DROP TABLE _n")
        api_conn.close()

        nodes = {}
        for s, n, e in rows:
            nodes[s] = {"entity": s, "edges": n, "energy": e,
                        "in_degree": indeg_map.get(s, 0),
                        "is_hub": s in hub_map}
        # 中枢词如果还没当过 source, 也加进星系 (分类节点必须可见)
        for t, c in hub_map.items():
            if t not in nodes:
                nodes[t] = {"entity": t, "edges": 0, "energy": 0.5,
                            "in_degree": c, "is_hub": True}
        out = sorted(nodes.values(),
                     key=lambda x: (x["edges"] + x["in_degree"] * 2,
                                    x["energy"]), reverse=True)
        node_list = out[:120]

        # ★ 全量连线: 节点之间的命名边 (群星漂浮 + 线连接)
        api_conn = sqlite3_mod.connect('D:/AM/HiveMind_repo/src/asteriamind.db')
        api_conn.execute('PRAGMA busy_timeout = 5000')
        api_conn.execute(
            "CREATE TEMP TABLE _n2 AS SELECT rowid FROM directed_edges "
            "WHERE relation IN " + NAMED)
        all_edges = api_conn.execute(
            f"SELECT de.source, de.relation, de.target "
            f"FROM directed_edges de JOIN _n2 ON de.rowid=_n2.rowid "
            f"WHERE de.source IN (SELECT source FROM directed_edges "
            f"JOIN _n2 ON directed_edges.rowid=_n2.rowid GROUP BY source) "
            f"AND LENGTH(de.source)<=6 AND LENGTH(de.target)<=6").fetchall()
        api_conn.execute("DROP TABLE _n2")
        api_conn.close()
        node_ids = {n["entity"] for n in node_list}
        edges = [{"source": s, "relation": r, "target": t}
                 for s, r, t in all_edges
                 if s in node_ids and t in node_ids]

        self._json({"nodes": node_list, "edges": edges})

    def _handle_vector(self, word: str):
        """★ v3.6: 向量空间 — 语义近邻 (黑盒联想层, 走概念层唯一入口)"""
        try:
            concept = REGISTRY.get("concept") or ci.concept
            ns = concept.run(word, 10)
            self._json({
                "word": word,
                "neighbors": [{"word": w, "sim": round(s, 3)} for w, s in ns],
            })
        except Exception as e:
            self._json({"word": word, "error": str(e)[:120],
                        "neighbors": []})

    def _handle_entity(self, entity: str):
        """★ v3.6: 实体详情 — 单个实体的关系网络 + 熵 + 能量

        /api/entity/<名字> → 混合图谱的"数据卡"
        """
        import sqlite3 as sqlite3_mod
        import math
        ent = entity.strip()
        api_conn = sqlite3_mod.connect('D:/AM/HiveMind_repo/src/asteriamind.db')
        api_conn.execute('PRAGMA busy_timeout = 5000')

        # 1. 命名边 (出边)
        out_edges = api_conn.execute(
            "SELECT relation, target, ROUND(COALESCE(energy,0),2), weight "
            "FROM directed_edges WHERE source=? "
            "AND relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN','NOT_IS_A') "
            "ORDER BY weight DESC LIMIT 15", (ent,)).fetchall()
        # 2. 入边 (谁指向它)
        in_edges = api_conn.execute(
            "SELECT source, relation, ROUND(COALESCE(energy,0),2) "
            "FROM directed_edges WHERE target=? "
            "AND relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN','NOT_IS_A') "
            "ORDER BY weight DESC LIMIT 10", (ent,)).fetchall()
        # 3. co_text 联想 (黑盒邻居)
        assoc = api_conn.execute(
            "SELECT target, ROUND(COALESCE(energy,0),2) FROM directed_edges "
            "WHERE source=? AND relation='co_text' ORDER BY energy DESC LIMIT 8",
            (ent,)).fetchall()
        # 4. 熵 (知识模糊度)
        rels = api_conn.execute(
            "SELECT relation, COUNT(*) FROM directed_edges "
            "WHERE source=? AND relation IN ('IS_A','CAN','NOT_CAN','HAS','CAUSES','EATS','LIVES_IN') "
            "GROUP BY relation", (ent,)).fetchall()
        entropy = 0.0
        total_n = sum(n for _, n in rels)
        if total_n > 1:
            h = 0.0
            for _, n in rels:
                p = n / total_n
                h -= p * math.log(p) if p > 0 else 0
            entropy = round(h / math.log(6), 2)
        api_conn.close()

        self._json({
            "entity": ent,
            "entropy": entropy,
            "out_edges": [{"relation": r, "target": t, "energy": e, "weight": w}
                          for r, t, e, w in out_edges],
            "in_edges": [{"source": s, "relation": r, "energy": e}
                         for s, r, e in in_edges],
            "assoc": [{"target": t, "energy": e} for t, e in assoc],
        })

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

    def _process(self, text: str, context: str = None) -> tuple[str, str, dict]:
        # ★ 跨请求状态必须在函数顶部声明 global (先声明, 后任何赋值)
        global _last_strategy, _last_text, _last_intent, _last_verb, _last_action
        global _last_subj, _last_rel
        """
        ── Cognitive Interface Layer ──
        Semantic → Pragmatic → Action → Mother v3 → 回复

        v3.3: 传入 reflection_ctx 支持反馈闭环
        """
        # ★ v3.6: 自指拦截 — 只对"你是谁/你会什么"这类自我认知问句 ★
        #   注意: "你知道铁是什么吗" 不是自指, 是问铁! 三种"你"要区分:
        #   ① 自我认知: 你是谁/你叫什么/你会什么/你能做什么 → self_ref
        #   ② 祈使:     你帮我查X/你能查一下X → 掉进动作原语
        #   ③ 指向提问: 你知道X吗/你觉得X吗 → 剥掉框架, 查X
        if text.startswith('你') and len(text) >= 3:
            if re.match(r'^你(?:是|叫)', text) or \
               re.match(r'^你(?:会|能|有|可以做|擅长)(?:什么|哪些|啥|什么能力|什么本事|做什么|哪些事)', text):
                # ① 真自指: 你是谁/你会什么/你能做什么
                text = re.sub(r'^你', '我', text)
                if ci.mother and ci.mother.star_map:
                    from AsteriaMind.language_generator import LanguageGenerator
                    from AsteriaMind.intent_layer import apply_intent_weight
                    intent = ci.intent_learner.predict(text) if hasattr(ci, 'intent_learner') else "ASK"
                    lg = LanguageGenerator(ci.mother.star_map)
                    edges = ci.mother.star_map.query_edges("我", text, space="belief")
                    if edges:
                        edges = apply_intent_weight(edges, intent)
                        act = [{"node": e["target"], "energy": e["salience"],
                                "triggers": [e["relation"]], "degree": 0} for e in edges[:8]]
                        narrative = lg._compose_narrative("我", act, [], intent=intent)
                        if narrative:
                            return (narrative, "self_ref", {"subject": "我"})
            elif re.match(r'^你知道', text):
                # ③ "你知道X吗" → 剥框架, 直接查 X
                m = re.match(r'^你知道(.+?)(?:吗|么|不)?$', text)
                if m:
                    text = m.group(1)
                    # 掉进正常管线 (ThinkNode 处理)

        # 命令: learnw/readcn/answer/偏好教学 (保留)
        if text.startswith(('learnw ', 'readcn ', 'answer ', '以后我')):
            return self._process_legacy(text)

        # ── ★ v3.6: 动作原语 — 动词理解 (查/算/教/讲) ★ ──
        if hasattr(ci, 'actions'):
            verb, target = ci.actions.extract(text)
            if verb:
                action = ci.actions.predict(verb)
                _last_verb, _last_action = verb, action
                if action == "search" and target:
                    if ci.active_learner and ci.active_learner.web_search:
                        try:
                            result = ci.active_learner.learn_word(target)
                            if result.get("known") and result.get("definition"):
                                return (f"🔍 查「{target}」：{result['definition'][:200]}",
                                        "search_learn", result)
                        except Exception:
                            pass
                    return (f"🤔 查「{target}」没找到可靠信息，你能教我吗？",
                            "search_gap", {})
                if action == "math" and re.search(r'\d', target):
                    m = skill_lib.best_match(target)
                    if m:
                        r = m.execute(target, kg)
                        if r.get("success"):
                            return (f"🧮 {r.get('result')}", "math", {})
                    return (f"🧮 我算不了「{target}」", "math_fail", {})
                if action == "teach" and target:
                    # 教我 X 是 Y → 汲取净化 (问句过滤 + 质量门) → 存星图
                    tm = re.match(r'(.+?)\s*(?:是|属于)\s*(.+)', target)
                    if tm:
                        try:
                            from AsteriaMind.intake_purifier import IntakePurifier
                            pur = IntakePurifier(ci.mother.star_map)
                            ok, msg = pur.ingest_teach(
                                tm.group(1).strip(), "IS_A",
                                tm.group(2).strip())
                        except Exception:
                            ok, msg = False, "教学失败"
                        if ok:
                            return (f"📖 学会了：{tm.group(1).strip()} 是 {tm.group(2).strip()}",
                                    "teach", {})
                        return (f"🤔 {msg}", "teach_reject", {})
                    return (f"🤔 想学「{target}」，但我不确定怎么记。"
                            f"试试 '教我 企鹅 是 鸟类' 这种格式？", "teach_unknown", {})

        # ── v3.5: 联网搜索 — 桥接到 ActiveLearner 学习管道 ──
        search_query = None
        for pat in (r'^搜索[：:\s]*(.+)', r'^帮我搜[：:\s]*(.+)', r'^查一下[：:\s]*(.+)',
                    r'^查查[：:\s]*(.+)', r'^搜一下[：:\s]*(.+)',
                    r'^search[：:\s]+(.+)', r'^帮我查[：:\s]*(.+)'):
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                search_query = m.group(1).strip()
                break
        if search_query and len(search_query) >= 2:
            result = ci.active_learner.learn_word(search_query)
            if result.get("known") and result.get("source") in ("web_search", "star_map"):
                return (f"🔍 搜索「{search_query}」: {result.get('definition', '')[:200]}",
                        "search_learn", {})
            elif result.get("pending"):
                return (f"🔍 关于「{search_query}」我没搜到可靠信息。你能教我吗?",
                        "search_gap", {})
            else:
                return (f"🔍 搜索了「{search_query}」，但需要更多上下文。试试教我?",
                        "search_uncertain", {})

        # 数学: 保留快速路径
        if re.search(r'\d\s*[\+\-\*/\^]\s*\d', text):
            m = skill_lib.best_match(text)
            if m:
                r = m.execute(text, kg)
                if r.get("success"):
                    return (f"🧮 {r.get('result')}", "math", {})

        # ★ v3.6: 短期记忆 + 元认知 + 代词解析 ★
        last_subj = ""
        if context:
            # 从上下文提取上一轮主语
            m = re.search(r'\[user\]:\s*(.+)', context)
            if m:
                prev_q = m.group(1)
                prev_clean = re.sub(r'[^\u4e00-\u9fff]', '', prev_q)
                for w in (3, 2):
                    for i in range(len(prev_clean) - w + 1):
                        kw = prev_clean[i:i+w]
                        c = ci.mother.star_map.conn.execute(
                            "SELECT COUNT(*) FROM directed_edges WHERE source=? OR target=?",
                            (kw, kw)).fetchone()
                        if c and c[0] > 1:
                            last_subj = kw; break
                    if last_subj: break
        # 元认知: 检测用户反馈 → 策略评分 + 意图学习 + 动作学习
        if re.search(r'(不对|错了|不是|不是这样|不对哦|错啦)', text):
            if ci.mother and hasattr(ci.mother, 'meta_cognition'):
                ci.mother.meta_cognition.learn_from_reflection(
                    _last_strategy, False)
            if hasattr(ci, 'intent_learner') and _last_text and _last_intent:
                ci.intent_learner.learn(_last_text, _last_intent, False)
            if hasattr(ci, 'actions') and _last_verb and _last_action:
                ci.actions.learn(_last_verb, _last_action, False)
            return ("🙏 明白了，我记下了，下次注意。", "feedback_negative", {})
        elif re.search(r'(说的对|正确|没错|是的|对呀|对的|说得对|没错没错|是的是的)', text):
            if ci.mother and hasattr(ci.mother, 'meta_cognition'):
                ci.mother.meta_cognition.learn_from_reflection(
                    _last_strategy, True)
            if hasattr(ci, 'intent_learner') and _last_text and _last_intent:
                ci.intent_learner.learn(_last_text, _last_intent, True)
            if hasattr(ci, 'actions') and _last_verb and _last_action:
                ci.actions.learn(_last_verb, _last_action, True)
            return ("😊 收到，我会记住的。", "feedback_positive", {})

        # 代词解析: 你/它/这/那 → 解析为主语
        if text.strip() in ('它','她','他','这','那','它们','她们','他们'):
            if last_subj:
                text = last_subj
            else:
                return ("请问你指的是？", "clarify", {})
        # 追问: "还有呢"/"为什么"/"那..." → 保持主语
        if re.match(r'^(还有|为什么|那|那么|这个|那个|这些)', text) and last_subj:
            text = f"{last_subj}{text}"

        clean = re.sub(r'[^\u4e00-\u9fff]', '', text)
        subj_candidate = ""

        # 打招呼 / 身份 → 直回
        if text in ('你好','您好','嗨','在吗','hello','hi','你是谁','你叫什么','你是谁啊'):
            return ("你好！我是 AsteriaMind——一个基于认知星图和能量扩散的学习系统。"
                    "你可以问我关于动物、植物、天文的问题，或者教我新知识。", "greeting", {})

        # ★ v3.6: 词义查询 — 'X是什么意思' → 查 symbol_star ★
        m = re.match(r'(.+?)是什么意思$', text)
        if m and ci.mother.star_map:
            word = m.group(1).strip()
            rows = ci.mother.star_map.conn.execute(
                "SELECT DISTINCT meaning FROM symbol_star WHERE symbol=? AND meaning!='' LIMIT 1",
                (word,)).fetchone()
            if rows:
                return (f"「{word}」：{rows[0]}", "define", {})
            return (f"🤔 我还没学过「{word}」的具体含义，你教教我？", "unknown", {})

        # ★ v3.6: ThinkNode — 问题理解 + 策略规划 ★
        if ci.mother.star_map:
            from AsteriaMind.think_node import ThinkNode
            tn = ThinkNode(ci.mother.star_map)
            # 注入持久化的短期记忆 (跨请求存活 — 模块级全局)
            tn.last_subject = _last_subj
            tn.last_relation = _last_rel
            plan = tn.plan(text, context or "")
            if plan.subject:
                _last_subj = plan.subject
                _last_rel = plan.relation_hints[0] if plan.relation_hints else ""

            if plan.strategy == "CLARIFY":
                q = plan.search_query or text
                if len(q) <= 2:
                    return (f"嗯？你说了「{q}」——我没太明白，多说一点？",
                            "clarify", {})
                return (f"🤔 「{q[:10]}」——我没太理解，能换个方式说说吗？",
                        "clarify", {})

            if plan.strategy == "SEARCH":
                # ★ v3.7: 向量类比推理优先 — 语义近亲 (走概念层唯一入口)
                try:
                    concept = REGISTRY.get("concept")
                    if concept is None:
                        concept = ci.concept
                    q = plan.search_query
                    for w, sim in concept.run(q, top_k=5):
                        if sim < 0.95:
                            break  # 相似度饱和噪声多 (小语料), 宁可不用不可乱用
                        # 近亲必须自己认识 (有命名知识可借)
                        rel_edges = ci.mother.star_map.query_edges(
                            w, text, space="belief", top_k=8)
                        if not rel_edges:
                            continue
                        best = max(rel_edges, key=lambda e: e.get("salience", 0))
                        rel_word = {"IS_A": "属于", "CAN": "能",
                                    "NOT_CAN": "不能", "HAS": "有",
                                    "EATS": "吃", "LIVES_IN": "生活在"}
                        rw = rel_word.get(best["relation"], best["relation"])
                        reply = (f"我没学过「{q[:8]}」，但它和「{w}」很像"
                                 f"（相似度 {sim:.2f}），而「{w}」{rw}"
                                 f"{best['target']}。我猜「{q[:8]}」大概也"
                                 f"{rw}{best['target']}——不过这是我猜的，"
                                 f"要是错了记得告诉我。")
                        return (reply, "vector_transfer",
                                {"similar_to": w, "sim": round(sim, 2),
                                 "borrowed": best})
                except Exception as e:
                    print(f"向量类比失败: {e}")
                # ★ v3.6: 软证据 — 其次问联想 (co_text 共现)
                soft = ci.mother.star_map.soft_evidence(plan.search_query, top_k=8)
                # ★ v3.7: 语义验证 — related 必须在查询词的向量近邻里
                #   co_text 共现 ≠ 语义相关 (语文课程~微积分 同文档共现)
                if soft:
                    try:
                        semantic = {w for w, _ in
                                    concept.run(plan.search_query, top_k=30)}
                        soft = [x for x in soft if x["related"] in semantic][:5]
                    except Exception:
                        pass
                if soft:
                    relates = "、".join(f"「{s['related']}」" for s in soft[:4])
                    reply = (f"我还不太确定「{plan.search_query[:8]}」具体是什么，"
                             f"但根据我读过的内容，它经常和 {relates} 一起出现。"
                             f"要我联网查一下吗？")
                    return (reply, "soft_association", {"evidence": soft})
                if ci.active_learner and ci.active_learner.web_search:
                    try:
                        result = ci.active_learner.learn_word(plan.search_query)
                        if result.get("known") and result.get("definition"):
                            return (f"🔍 我查了一下——{result['definition'][:200]}",
                                    "search_learn", result)
                    except Exception:
                        pass
                return (f"🤔 我还没学过关于「{text[:10]}」的知识。"
                        f"你可以教我——比如 '野狗 是 犬科动物' 或 '野狗 吃 小型动物'。",
                        "unknown", {})

            # DIRECT / REVERSE: 走叙事管线
            from AsteriaMind.language_generator import LanguageGenerator
            from AsteriaMind.intent_layer import apply_intent_weight
            subj = plan.subject
            intent = ci.intent_learner.predict(text) if hasattr(ci, 'intent_learner') else "ASK"
            lg = LanguageGenerator(ci.mother.star_map)

            if plan.strategy == "REVERSE":
                # ThinkNode 已反推: 羽毛 → 鸟类, 用鸟类查, 但加权匹配原问题
                edges = ci.mother.star_map.query_edges(subj, text, space="belief")
                # ★ CHAIN-4: 原问题关系高权重 → "会飞吗" → CAN 边加权 ★
                for e in edges:
                    if e["relation"] == plan.relation_hints[0]:
                        e["salience"] *= 2.0; e["energy"] *= 1.5
            else:
                edges = ci.mother.star_map.query_edges(subj, text, space="belief")

            if not edges:
                return (f"🤔 关于「{subj}」，我知道的还不多。你能教教我吗？",
                        "unknown", {})

            # ★ v3.8: 推理链 — IS_A 意图时补传递推理 (企鹅→鸟类→脊椎动物)
            #   已知的边不再重复, 只补两跳推理 (一跳 IS_A 已在 edges)
            if hasattr(ci, 'reasoning') and "IS_A" in (intent or ""):
                try:
                    known = {e["target"] for e in edges}
                    for r in ci.reasoning.infer(subj, top_k=3):
                        if r["hops"] < 2 or r["target"] in known:
                            continue
                        edges.append({
                            "source": subj, "relation": "IS_A",
                            "target": r["target"],
                            "salience": r["confidence"],
                            "energy": r["confidence"],
                            "inferred": True,
                            "path": r.get("path", []),
                        })
                except Exception:
                    pass

            edges = apply_intent_weight(edges, intent)
            # ★ v3.7: 统计语言生成 — 她自己的句式 (骨架池采样), 模板只兜底
            narrative = _speak_with_own_language(subj, edges)
            if not narrative:
                act = [{"node": e["target"], "energy": e["salience"],
                        "triggers": [e["relation"]], "degree": 0}
                       for e in edges[:8]]
                narrative = lg._compose_narrative(subj, act, [], intent=intent)
            # ★ v3.6: 批判者 — 熵高时诚实标注不确定性 (走注册表, 可卸载) ★
            critic_note = None
            if narrative:
                try:
                    critic_mod = REGISTRY.get("critic")
                    crit = critic_mod.run(subj) if critic_mod else None
                except Exception:
                    crit = ci.critic.check(subj) if hasattr(ci, 'critic') else None
                if crit:
                    critic_note = crit
                    narrative = crit["preface"] + narrative
            if narrative:
                _last_strategy = plan.strategy
                _last_text = text
                _last_intent = intent
                for e in edges[:3]:
                    ci.mother.star_map.restore_energy(subj, e["target"], 0.03)
                # ★ v3.6: 证据链 — 记录回答走了哪些边 (供 /api/evidence) ★
                global _last_evidence
                _last_evidence = {
                    "question": text,
                    "subject": subj,
                    "strategy": plan.strategy,
                    "intent": intent,
                    "uncertain": critic_note,
                    "edges": [{
                        "relation": e["relation"],
                        "target": e["target"],
                        "energy": e.get("energy", 0),
                        "salience": e.get("salience", 0),
                        "inferred": e.get("inferred", False),
                        "path": e.get("path", []),
                    } for e in edges[:6]],
                    "ts": time.time(),
                }
                # ★ v3.6: 自学习 — 每个成功回答更新自我认知 ★
                ci.mother.star_map.store("我", "CAN", "回答问题",
                    "confirmed", f"成功回答: {subj}({plan.strategy})")
                return (narrative, "narrative", {"subject": subj})

        # 回退: 星图不可用
        return (f"🤔 我还没学过关于「{text[:10]}」的知识。"
                f"你可以教我——比如 '野狗 是 犬科动物' 或 '野狗 吃 小型动物'。",
                "unknown", {})

    def _process_legacy(self, text: str) -> tuple[str, str]:
        """命令路由: learnw / readcn / answer / 偏好教学"""
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
    import threading

    # ★ v3.8: 启动时回放历史对话 → 语言史 (骨架池吸收对话句式)
    try:
        _r = _REPLAY.replay_history(limit=600)
        print(f"  💬 对话语料回放: {_r}")
    except Exception as e:
        print(f"  ⚠️ replay: {e}")

    # 后台记忆巩固线程: 每 120 秒跑一次
    def _consolidation_loop():
        while True:
            time.sleep(120)
            try:
                mc_result = ci.consolidate()
                print(f"\n  🌙 Memory Consolidation: "
                      f"clusters={mc_result.get('clusters_found',0)} "
                      f"contradictions={mc_result.get('contradictions_found',0)}")
            except Exception as e:
                print(f"\n  ⚠️ Consolidation error: {e}")

    threading.Thread(target=_consolidation_loop, daemon=True).start()

    # 后台离线学习线程: 状态感知的自我唤醒
    def _offline_learn_loop():
        last_cycle = time.time()
        wake_log: list[str] = []  # 唤醒原因记录

        def _should_wake() -> tuple[bool, str]:
            """状态感知唤醒: 不只定时, 也听系统自己的声音"""
            nonlocal last_cycle
            now = time.time()

            # 1. 保底定时 (2 分钟 — 更主动)
            if now - last_cycle >= 120:
                return True, "time_based"

            # 2. MetaReasoning: 高误差 → 需要学习
            try:
                health = ci.mother.meta_reasoning.get_system_health()
                if health.get("avg_error", 0) > 0.3:
                    return True, "health_high_error"
            except Exception:
                pass

            # 3. ActiveInference: 不确定边 > 0.4 → 立即验证
            try:
                uncertain = ci.mother.active_inference.most_uncertain_edges(top_k=3)
                for e in uncertain:
                    if e.get("uncertainty", 0) > 0.4:
                        return True, f"uncertain_{e['subj']}_{e['pred']}"
            except Exception:
                pass

            return False, ""

        while True:
            time.sleep(30)  # 轻量轮询, 30s 检查一次
            try:
                should, reason = _should_wake()
                if should:
                    # 记录唤醒原因
                    wake_log.append(f"{time.strftime('%H:%M:%S')} wake: {reason}")
                    if len(wake_log) > 20:
                        wake_log = wake_log[-20:]

                    result = ci.offline_learner.run_cycle()
                    last_cycle = time.time()

                    if result.get("proposals", 0) > 0:
                        print(f"\n  🔍 Offline Learning ({reason}): "
                              f"proposals={result['proposals']} "
                              f"winners={result['winners']} "
                              f"learned={result['learned']} "
                              f"skipped={result['skipped']}")

                    # ★ v3.7: 学完有想法 → 自发发言 (不等用户输入)
                    try:
                        if hasattr(ci, 'speaker'):
                            n = ci.speaker.tick()
                            if n > 0:
                                print(f"\n  💭 AM 自发发言: 说了 {n} 条")
                    except Exception as se:
                        print(f"  ⚠️ speaker error: {se}")
            except Exception as e:
                print(f"\n  ⚠️ Offline learning error: {e}")

    threading.Thread(target=_offline_learn_loop, daemon=True).start()

    # ── ★ v3.7: 自发发言循环 — 想说什么就说什么 ──
    # 独立线程, 不依赖 offline learning 是否跑成功
    def _speaker_loop():
        while True:
            try:
                if hasattr(ci, 'speaker'):
                    n = ci.speaker.tick()
                    if n > 0:
                        print(f"\n  💭 AM 自发发言: {n} 条")
            except Exception as e:
                print(f"  ⚠️ speaker loop error: {e}")
            time.sleep(45)

    threading.Thread(target=_speaker_loop, daemon=True).start()

    # ── ★ v3.7: RSS 送饭循环 — 每 6 小时自动喂语料 ──
    def _rss_loop():
        from AsteriaMind.rss_feeder import RSSFeeder
        import sqlite3 as _sq
        # 启动时先喂一次 (服务器起来就有饭)
        first = True
        while True:
            try:
                if not first:
                    time.sleep(6 * 3600)  # 6 小时一餐
                first = False
                feeder = RSSFeeder(star_map=ci.mother.star_map)
                stats = feeder.feed(max_items=20)
                if stats.get("new", 0) > 0:
                    print(f"\n  📡 RSS 送饭: 新喂 {stats['new']} 条 "
                          f"(源{stats['sources']} 重复{stats['dup']} "
                          f"失败{stats['errors']})")
                    # 喂完触发离线学习 (新词 → 概念缺口 → 她主动学)
                    try:
                        ci.offline_learner.run_cycle()
                    except Exception:
                        pass
            except Exception as e:
                print(f"  ⚠️ RSS feed error: {e}")
                time.sleep(1800)  # 失败半小时后重试

    threading.Thread(target=_rss_loop, daemon=True).start()

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
