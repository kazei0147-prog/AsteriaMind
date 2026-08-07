"""
SpontaneousSpeaker — 自发发言器 (AsteriaMind v3.7)

她"想说什么就说什么": 从内部状态收集值得说的话,
  不等用户输入, 主动把想法说出口。

核心转变:
  之前: 输出 = f(输入)      (响应器, 无输入就沉默)
  现在: 输出 = f(内部状态)  (认知体, 有想法就表达)

想法来源 (全部是内部状态, 不是外部输入):
  1. 刚学到的知识 (cognitive_traces 最新 confirmed) — 分享欲
  2. 发现的矛盾   (CAN↔NOT_CAN 并存)               — 质疑欲
  3. 高熵实体     (知识模糊, 想搞懂)                — 求知欲
  4. 概念缺口     (词表有语义位置, 星图不认识)      — 探索欲

克制参数: 不刷屏, 有节流, 有队列上限 — 有想法的前提是有分寸
"""

import time
import sqlite3

# ── 克制参数 ──
_MIN_INTERVAL = 90      # 两次自发发言最短间隔 (秒) — 不喋喋不休
_MAX_PENDING = 4        # 队列上限 — 不刷屏
_FRESH_WINDOW = 1800    # 只对 30 分钟内的新知识有分享欲


class SpontaneousSpeaker:
    def __init__(self, star_map, critic=None, concept=None):
        self.star_map = star_map
        self.critic = critic
        self.concept = concept
        # ★ 独立只读连接: 不共享 star_map.conn (后台线程在它上面写会卡死同连接读)
        import sqlite3 as _sq
        try:
            _p = star_map.conn.execute("PRAGMA database_list").fetchone()
            _db = _p[2] if _p else "asteriamind.db"
        except Exception:
            _db = "asteriamind.db"
        self._ro = _sq.connect(_db, timeout=8, check_same_thread=False)
        self._ro.execute("PRAGMA busy_timeout = 8000")
        self._pending = []          # 待推送: [(text, kind, ts)]
        self._last_spoke = 0
        self._said_ids: set[int] = set()   # 说过的痕迹 id (防重复)
        self.total_spoken = 0       # 总共说了多少次 (统计用)

    # ── 想法收集: 扫描内部状态 ──
    def collect_thoughts(self, limit=4) -> list[dict]:
        thoughts = []
        now = time.time()

        # 1. 刚学到的知识 (最高优先 — 分享欲)
        try:
            rows = self._ro.execute(
                "SELECT id, subj, pred, obj, feedback, timestamp "
                "FROM cognitive_traces "
                "WHERE feedback IN ('confirmed','corrected') "
                "ORDER BY timestamp DESC LIMIT 10").fetchall()
            for rid, s, p, o, fb, ts in rows:
                if rid in self._said_ids:
                    continue
                if not ts or now - ts > _FRESH_WINDOW:
                    continue
                if not s or not o or len(s) < 1 or len(o) < 1:
                    continue
                thoughts.append({
                    "priority": 8, "kind": "learned",
                    "trace_id": rid, "source": s,
                    "relation": p or "IS_A", "target": o,
                    "feedback": fb,
                })
        except Exception:
            pass

        # 2. 发现的矛盾 (质疑欲 — 她对自己的知识有疑问)
        #    轻量版: 先取 CAN 边 (部分索引 idx_named_rel, 几十条),
        #    再匹配对应 NOT_CAN — 避免 1100 万行 JOIN 全表卡死
        try:
            for r in self._ro.execute(
                "SELECT a.source, a.target, a.weight, "
                "COALESCE(b.weight, 0) "
                "FROM directed_edges a "
                "LEFT JOIN directed_edges b "
                "  ON b.source = a.source AND b.target = a.target "
                "  AND b.relation = 'NOT_CAN' "
                "WHERE a.relation = 'CAN' AND a.weight > 1 "
                "AND b.rowid IS NOT NULL "
                "LIMIT 3").fetchall():
                src, tgt, wa, wb = r
                key = f"conflict_{src}_{tgt}"
                if key in self._said_ids:
                    continue
                winner = "CAN" if wa >= wb else "NOT_CAN"
                thoughts.append({
                    "priority": 7, "kind": "conflict",
                    "trace_id": key, "source": src,
                    "relation": f"{'能' if winner=='CAN' else '不能'}",
                    "target": tgt,
                    "can_w": wa, "not_w": wb,
                })
        except Exception:
            pass

        # 3. 高熵实体 (求知欲 — 轻量版: 最近学过的实体, Python 算熵)
        #    避免 critic.scan_uncertain 的 1100 万行 GROUP BY 卡死
        if self.critic:
            try:
                import math
                from collections import Counter
                recent = [r[0] for r in self._ro.execute(
                    "SELECT DISTINCT subj FROM cognitive_traces "
                    "WHERE feedback='confirmed' "
                    "ORDER BY timestamp DESC LIMIT 40").fetchall()]
                for ent in recent[:20]:
                    rels = [r[0] for r in self._ro.execute(
                        "SELECT relation FROM directed_edges WHERE source=? "
                        "AND relation IN ('IS_A','CAN','NOT_CAN','HAS',"
                        "'EATS','LIVES_IN')", (ent,)).fetchall()]
                    if len(rels) < 3:
                        continue
                    cnt = Counter(rels)
                    total = sum(cnt.values())
                    h = -sum((c / total) * math.log2(c / total)
                             for c in cnt.values()) / math.log2(6)
                    if h > 0.75:
                        key = f"fuzzy_{ent}"
                        if key in self._said_ids:
                            continue
                        thoughts.append({
                            "priority": 5, "kind": "fuzzy",
                            "trace_id": key, "source": ent,
                            "entropy": round(h, 2),
                        })
                        break
            except Exception:
                pass

        # 4. 概念缺口 (探索欲 — 词表有位置, 星图不认识)
        if self.concept:
            try:
                vocab = self.concept.vocab()
                named = set(r[0] for r in self._ro.execute(
                    "SELECT DISTINCT source FROM directed_edges "
                    "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS',"
                    "'EATS','LIVES_IN')").fetchall())
                gaps = [w for w in vocab
                        if w not in named and len(w) >= 2][:12]
                import random
                random.seed(int(now))
                picked = random.sample(gaps, min(2, len(gaps)))
                for w in picked:
                    key = f"gap_{w}"
                    if key in self._said_ids:
                        continue
                    thoughts.append({
                        "priority": 4, "kind": "gap",
                        "trace_id": key, "source": w,
                        "similar_to": w[:2],
                    })
            except Exception:
                pass

        thoughts.sort(key=lambda x: -x["priority"])
        return thoughts[:limit]

    # ── 表达: 把想法说成话 ──
    def express(self, thought: dict) -> tuple[str, str]:
        """返回 (发言文本, 发言类型标签)
        知识内容优先用她的骨架池表达 (她自己的句式),
        元认知框架 (我刚了解到/我发现) 用简单连接 — 这部分骨架池还没有素材
        """
        kind = thought["kind"]
        try:
            if kind == "learned":
                # 知识内容本身走统计语言 (骨架池采样)
                content = self._speak_edges([
                    {"source": thought["source"],
                     "relation": thought["relation"],
                     "target": thought["target"]}])
                return (f"我刚了解到，{content}", "learned")
            if kind == "conflict":
                return (f"我发现自己的知识里有个矛盾："
                        f"「{thought['source']}」到底{thought['relation']}"
                        f"「{thought['target']}」？我还没想明白。", "conflict")
            if kind == "fuzzy":
                return (f"其实我对「{thought['source']}」一直没太大把握，"
                        f"它在我的知识里挺模糊的，有机会我想搞清楚。", "fuzzy")
            if kind == "gap":
                return (f"我注意到「{thought['source']}」这个词我好像听说过"
                        f"（有点像「{thought['similar_to']}」），"
                        f"但我还不认识它。", "gap")
        except Exception:
            pass
        return ("", kind)

    # ── 骨架池表达 (复用统计语言模型, 跟回答同一个嘴) ──
    _LM = None

    def _speak_edges(self, edges):
        if SpontaneousSpeaker._LM is None:
            from AsteriaMind.language_model import LanguageModel
            lm = LanguageModel()
            lm.mine(min_count=1)
            SpontaneousSpeaker._LM = lm
        text = SpontaneousSpeaker._LM.speak(edges, max_sent=1)
        return text if text else f"{edges[0]['source']} {edges[0]['relation']} {edges[0]['target']}"

    # ── 队列 ──
    def tick(self, force: bool = False) -> int:
        """后台循环调用: 收集想法 → 节流 → 表达 → 入队
        返回本次说出几条 (0 = 没有想说的/没到时间)
        """
        now = time.time()
        if not force and now - self._last_spoke < _MIN_INTERVAL:
            return 0
        thoughts = self.collect_thoughts(limit=2)
        for th in thoughts:
            text, kind = self.express(th)
            if not text:
                continue
            self._pending.append({"text": text, "kind": kind, "ts": now})
            if len(self._pending) > _MAX_PENDING:
                self._pending.pop(0)
            self._said_ids.add(th["trace_id"])
            self._last_spoke = now
            self.total_spoken += 1
            return 1
        return 0

    def drain(self) -> list[dict]:
        """前端取走全部未读发言"""
        out, self._pending = self._pending, []
        return [{"text": x["text"], "kind": x["kind"]} for x in out]
