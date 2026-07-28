"""
CognitiveStarMap — 统一星图 v3 (共现引擎 + 语言涌现)

v3: 统计共近代替代字符哈希。
认知痕迹 → 自动构建共现矩阵 → 稀疏向量 → 相似检索。
认知 + 语言痕迹共存于同一空间，同时检索。
"""
import time, math, sqlite3, struct, re
from typing import Optional


# ═══════════════════════════════════════
#  共现向量引擎
# ═══════════════════════════════════════

def _build_cooccur_from_traces(conn: sqlite3.Connection):
    """从 cognitive_traces 构建/升级共现表"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='co_occurrence'")
    if cur.fetchone():
        # 检查是否需要升级 schema (old: count only, new: weight/confidence/evidence/last_update)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(co_occurrence)")}
        if "confidence" not in cols:
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN confidence REAL DEFAULT 1.0")
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN evidence_count INTEGER DEFAULT 1")
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN last_update REAL DEFAULT 0")
            # 从已有 count 初始化
            cur.execute("UPDATE co_occurrence SET evidence_count=count, confidence=1.0, last_update=0")
            conn.commit()
        return

    cur.execute("""
        CREATE TABLE co_occurrence (
            entity_a TEXT NOT NULL,
            entity_b TEXT NOT NULL,
            weight INTEGER DEFAULT 1,
            confidence REAL DEFAULT 1.0,
            evidence_count INTEGER DEFAULT 1,
            last_update REAL DEFAULT 0,
            PRIMARY KEY (entity_a, entity_b)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS directed_edges (
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            relation TEXT DEFAULT '',
            weight INTEGER DEFAULT 1,
            confidence REAL DEFAULT 1.0,
            evidence_count INTEGER DEFAULT 1,
            last_update REAL DEFAULT 0,
            PRIMARY KEY (source, target, relation)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_de_source ON directed_edges(source)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_de_target ON directed_edges(target)")
    for row in cur.execute("SELECT subj, pred, obj, feedback FROM cognitive_traces"):
        subj, pred, obj = (row[0] or "").strip(), (row[1] or "").strip(), (row[2] or "").strip()
        fb = row[3] or "confirmed"
        _incr_cooccur(cur, subj, pred, fb, time.time())
        _incr_cooccur(cur, subj, obj, fb, time.time())
        _incr_cooccur(cur, pred, obj, fb, time.time())
        # 有向边: 保留三元组方向
        _incr_directed(cur, subj, obj, pred, fb, time.time())
    conn.commit()


DECAY_LAMBDA = 0.01  # 衰减系数: 越大遗忘越快


def _incr_cooccur(cur, a: str, b: str, feedback: str = "confirmed", ts: float = 0):
    """更新边权: weight+1, confidence 根据反馈调整, evidence_count+1"""
    if not a or not b or a == b:
        return
    if a > b:
        a, b = b, a
    conf_boost = 1.0 if feedback == "confirmed" else (0.3 if feedback == "corrected" else 0.5)
    ts = ts or time.time()
    cur.execute(
        "INSERT INTO co_occurrence(entity_a,entity_b,weight,confidence,evidence_count,last_update) "
        "VALUES(?,?,1,?,1,?) "
        "ON CONFLICT(entity_a,entity_b) DO UPDATE SET "
        "weight=weight+1, "
        "confidence=(confidence*evidence_count+?)/(evidence_count+1), "
        "evidence_count=evidence_count+1, "
        "last_update=?",
        (a, b, conf_boost, ts, conf_boost, ts))


def _incr_directed(cur, source: str, target: str, relation: str = "",
                    feedback: str = "confirmed", ts: float = 0):
    """有向边: source →[relation]→ target, 保留方向和关系类型"""
    if not source or not target or source == target:
        return
    conf_boost = 1.0 if feedback == "confirmed" else (0.3 if feedback == "corrected" else 0.5)
    ts = ts or time.time()
    cur.execute(
        "INSERT INTO directed_edges(source,target,relation,weight,confidence,evidence_count,last_update) "
        "VALUES(?,?,?,1,?,1,?) "
        "ON CONFLICT(source,target,relation) DO UPDATE SET "
        "weight=weight+1, "
        "confidence=(confidence*evidence_count+?)/(evidence_count+1), "
        "evidence_count=evidence_count+1, "
        "last_update=?",
        (source, target, relation, conf_boost, ts, conf_boost, ts))


def _effective_weight(row) -> float:
    """动态边权: weight × confidence × time_decay"""
    weight = row[0] if isinstance(row, tuple) else row["weight"]
    conf = row[1] if isinstance(row, tuple) else row["confidence"]
    last_up = row[2] if isinstance(row, tuple) else row["last_update"]
    decay = math.exp(-DECAY_LAMBDA * (time.time() - (last_up or 0)) / 86400)
    return float(weight) * float(conf) * float(decay)


def _directed_vector(conn, entity: str, direction: str = "out",
                      pmi_threshold: float = -0.5) -> dict[str, float]:
    """
    有向向量 + PMI 过滤。

    PMI(x,y) = log(P(x,y) / P(x)P(y))
    NPMI = PMI / -log(P(x,y))

    只保留 NPMI > 0.2 的边—过滤掉偶然共现噪声。
    "蛇 →[ORBITS]→ 地球" (w=1, rare) → PMI < 0 → 被过滤
    "月球→[ORBITS]→地球" (w=5, frequent) → PMI > 2 → 保留

    direction='out': entity → target 的出边
    direction='in':  source → entity 的入边
    direction='both': 出+入
    """
    vec = {}
    total_weight = conn.execute(
        "SELECT COALESCE(SUM(weight), 1) FROM directed_edges").fetchone()[0] + 1e-6

    for col, entity_col, dir_weight in (
        ("target", "source", 1.0),
        ("source", "target", 0.8),
    ):
        if direction == "out" and col == "source":
            continue
        if direction == "in" and col == "target":
            continue
        query = f"SELECT {col}, weight, confidence, last_update, relation FROM directed_edges WHERE {entity_col}=?"
        for row in conn.execute(query, (entity,)):
            neighbor, weight, conf, last_up, rel = row
            w = _effective_weight((weight, conf, last_up))
            if w < 1.5:  # 边太弱, 跳过 PMI 计算
                continue

            # ── PMI 计算 ──
            # P(x,y) = edge_weight / total
            # P(x)   = source_degree / total
            # P(y)   = target_degree / total
            p_xy = w / total_weight
            if p_xy <= 0:
                continue

            if col == "target":
                src_deg = conn.execute(
                    "SELECT SUM(weight) FROM directed_edges WHERE source=?",
                    (entity,)).fetchone()[0] or 1
                tgt_deg = conn.execute(
                    "SELECT SUM(weight) FROM directed_edges WHERE target=?",
                    (neighbor,)).fetchone()[0] or 1
            else:
                src_deg = conn.execute(
                    "SELECT SUM(weight) FROM directed_edges WHERE source=?",
                    (neighbor,)).fetchone()[0] or 1
                tgt_deg = conn.execute(
                    "SELECT SUM(weight) FROM directed_edges WHERE target=?",
                    (entity,)).fetchone()[0] or 1

            p_x = src_deg / total_weight
            p_y = tgt_deg / total_weight

            if p_x * p_y <= 0:
                continue
            pmi = math.log(p_xy / (p_x * p_y))
            npmi = pmi / (-math.log(p_xy)) if p_xy > 0 else 0

            # ── NPMI 作为边权重系数 ──
            # NPMI < 0  → 硬裁剪 (偶然共现, 不导电)
            # NPMI ~ 0  → 极弱传导
            # NPMI > 0.4 → 强因果/逻辑边
            npmi = pmi / (-math.log(p_xy)) if p_xy > 0 else 0

            if npmi < 0:  # 硬裁剪: 负 NPMI → 噪声边, 直接丢弃
                continue

            key = neighbor  # 目标实体为键 (蛇, 不是 IS_A)
            # 返回 (有效权重, NPMI, relation) — 三元元组
            edge_w = w * dir_weight
            prev = vec.get(key, (0, 0, ""))
            vec[key] = (max(prev[0], edge_w), npmi, prev[2] or rel)

    return vec
    """动态边权: weight × confidence × time_decay"""
    weight = row[0] if isinstance(row, tuple) else row["weight"]
    conf = row[1] if isinstance(row, tuple) else row["confidence"]
    last_up = row[2] if isinstance(row, tuple) else row["last_update"]
    decay = math.exp(-DECAY_LAMBDA * (time.time() - (last_up or 0)) / 86400)  # 按天衰减
    return float(weight) * float(conf) * float(decay)


def _entity_vector(conn, entity: str) -> dict[str, float]:
    """单实体共现向量——用有效权重"""
    vec = {}
    now = time.time()
    decay_factor = math.exp(-DECAY_LAMBDA * now / 86400)
    for row in conn.execute(
        "SELECT entity_b, weight, confidence, last_update FROM co_occurrence WHERE entity_a=? "
        "UNION ALL SELECT entity_a, weight, confidence, last_update FROM co_occurrence WHERE entity_b=?",
        (entity, entity)):
        w = _effective_weight(row[1:])  # row[0] 是实体名, row[1:]= weight,confidence,last_update
        if w > 0.01:
            vec[row[0]] = w
    return vec


def _query_vector(conn, subj: str, obj: str, pred: str = "") -> dict[str, float]:
    """组合查询向量"""
    vec: dict[str, float] = {}
    for e in (subj, obj, pred):
        if e:
            for k, v in _entity_vector(conn, e).items():
                vec[k] = vec.get(k, 0.0) + v
    return vec


def _sparse_cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    """稀疏向量余弦相似度"""
    if not v1 or not v2:
        return 0.0
    dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in set(v1) & set(v2))
    n1 = math.sqrt(sum(v * v for v in v1.values()))
    n2 = math.sqrt(sum(v * v for v in v2.values()))
    return dot / (n1 * n2) if n1 * n2 > 0 else 0.0


# ═══════════════════════════════════════
#  CognitiveStarMap
# ═══════════════════════════════════════

class CognitiveStarMap:
    """统一星图——共现向量 + 语言涌现"""

    def __init__(self, db_path: str = "asteriamind.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()
        _build_cooccur_from_traces(self.conn)

    def _ensure_table(self):
        c = self.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='language_traces'")
        if not c.fetchone():
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cognitive_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    pattern TEXT NOT NULL, feedback TEXT NOT NULL,
                    timestamp REAL
                );
                CREATE TABLE IF NOT EXISTS language_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sentence TEXT NOT NULL,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    cognitive_id INTEGER, pattern_type TEXT DEFAULT '', timestamp REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ct_pattern ON cognitive_traces(pattern);
                CREATE INDEX IF NOT EXISTS idx_lt_pattern ON language_traces(pattern_type);
            """)
        # v3.4: 自动迁移 — 确保新表存在
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='word_cooccur'")
        if not c.fetchone():
            c.executescript("""
                CREATE TABLE IF NOT EXISTS word_cooccur (
                    word_a TEXT NOT NULL,
                    word_b TEXT NOT NULL,
                    category TEXT NOT NULL,
                    context TEXT DEFAULT '',
                    weight REAL DEFAULT 1.0,
                    count INTEGER DEFAULT 1,
                    last_update REAL,
                    PRIMARY KEY (word_a, word_b, category, context)
                );
                CREATE INDEX IF NOT EXISTS idx_wc_ctx ON word_cooccur(category, context);

                CREATE TABLE IF NOT EXISTS lang_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    confidence_bucket TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    opener TEXT NOT NULL,
                    body_template TEXT NOT NULL,
                    closer TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    last_update REAL
                );
                CREATE INDEX IF NOT EXISTS idx_lp_action ON lang_patterns(action_type, confidence_bucket);
            """)
        # v3.5: 自动迁移 — sentence_type 列
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='language_traces'")
        if c.fetchone():
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(language_traces)")}
            if "sentence_type" not in cols:
                c.execute("ALTER TABLE language_traces ADD COLUMN sentence_type TEXT DEFAULT 'unknown'")
        # v3.5: 自动迁移 — directed_edges 表
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='directed_edges'")
        if not c.fetchone():
            c.execute("""
                CREATE TABLE IF NOT EXISTS directed_edges (
                    source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT DEFAULT '',
                    weight INTEGER DEFAULT 1, confidence REAL DEFAULT 1.0,
                    evidence_count INTEGER DEFAULT 1, last_update REAL DEFAULT 0,
                    PRIMARY KEY (source, target, relation)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_de_source ON directed_edges(source)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_de_target ON directed_edges(target)")
            # 从现有 cognitive_traces 回填
            for row in c.execute("SELECT subj, pred, obj, feedback FROM cognitive_traces"):
                s, p, o = (row[0] or "").strip(), (row[1] or "").strip(), (row[2] or "").strip()
                if s and o and p:
                    _incr_directed(c, s, o, p, row[3] or "confirmed", time.time())
        self.conn.commit()

    @staticmethod
    def _language_pattern(sentence: str) -> str:
        if '属于' in sentence: return 'X属于Y'
        if '会' in sentence and '吗' in sentence: return 'X会Y吗'
        if '是' in sentence and '吗' in sentence: return 'X是Y吗'
        if '会' in sentence: return 'X会Y'
        if '绕' in sentence: return 'X绕Y'
        if '是' in sentence: return 'X是Y'
        if '吗' in sentence: return '问句'
        return '陈述'

    @staticmethod
    def _tag_sentence_type(sentence: str) -> str:
        """
        v3.5: 推断句子来源类型。

        conversational: 对话式 — 有语气词、反问、简短
        encyclopedic:  百科式 — 长句、定义性、书面语
        title:         标题式 — 极短、无谓语
        """
        s = sentence.strip()
        # 标题: 无标点 + 极短 + 无谓词
        if len(s) <= 8 and not any(k in s for k in ('是', '会', '能', '有', '属于')):
            return "title"
        # 对话: 语气词开头或结尾
        dialog_markers = ('嗯', '对', '不', '那', '所以', '但是', '可是', '其实', '哈哈')
        if any(s.startswith(m) for m in dialog_markers):
            return "conversational"
        if s.rstrip().endswith(('吗', '呢', '吧', '？', '?', '！', '!')):
            return "conversational"
        if len(s) <= 20 and ('你' in s or '我' in s):
            return "conversational"
        # 百科: 长句 + 定义性
        if len(s) > 15 or any(k in s for k in ('特征', '定义', '属于', '具有', '分为')):
            return "encyclopedic"
        if len(s) > 25:
            return "encyclopedic"
        return "unknown"

    def _cooccur_neighbors(self, entities: list[str], top_k: int = 20) -> set[str]:
        """
        低频准备: 从共现表快速捞出相关实体。

        "哺乳动物" → [猫, 狗, 海豚, 蝙蝠, ...]
        不在每次检索时扫全表，只激活局部子图。
        """
        neighbors = set(e for e in entities if e)
        cur = self.conn.cursor()
        for e in entities:
            if not e: continue
            for sql, col in (
                ("SELECT entity_b FROM co_occurrence WHERE entity_a=? "
                 "ORDER BY weight*confidence DESC LIMIT ?", 0),
                ("SELECT entity_a FROM co_occurrence WHERE entity_b=? "
                 "ORDER BY weight*confidence DESC LIMIT ?", 0),
            ):
                for row in cur.execute(sql, (e, top_k)):
                    if row[col] and row[col] != e:
                        neighbors.add(row[col])
        return neighbors

    def _indexed_scan(self, qv: dict, activated: set[str]) -> list:
        """
        高频局部激活: 只在相关实体的认知痕迹中计算相似度。

        WHERE subj IN (...) OR obj IN (...) → 子图扫描。
        """
        if not activated:
            return []
        placeholders = ",".join("?" * len(activated))
        params = list(activated) + list(activated)
        sql = (f"SELECT id,subj,pred,obj,pattern,feedback FROM cognitive_traces "
               f"WHERE subj IN ({placeholders}) OR obj IN ({placeholders})")
        res = []
        for row in self.conn.execute(sql, params):
            tv = _query_vector(self.conn, row[1], row[3], row[2])
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                res.append({"id": row[0], "subj": row[1], "pred": row[2],
                            "obj": row[3], "pattern": row[4], "feedback": row[5],
                            "similarity": sim})
        res.sort(key=lambda x: x["similarity"], reverse=True)
        return res

    def store(self, subj: str, pred: str, obj: str,
              feedback: str = "confirmed", text: str = "") -> int:
        """存入认知痕迹 + 语言痕迹 + 更新共现"""
        subj = (subj or "").strip()
        pred = (pred or "").strip()
        obj = (obj or "").strip()
        pattern = f"{subj[:8]}::{pred}::{obj[:8]}"
        cur = self.conn.execute(
            "INSERT INTO cognitive_traces(subj,pred,obj,pattern,feedback,timestamp) "
            "VALUES(?,?,?,?,?,?)",
            (subj, pred, obj, pattern, feedback, time.time()))
        cog_id = cur.lastrowid
        if text:
            lt = self._language_pattern(text)
            stype = self._tag_sentence_type(text)
            self.conn.execute(
                "INSERT INTO language_traces"
                "(sentence,subj,pred,obj,cognitive_id,pattern_type,sentence_type,timestamp) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (text, subj, pred, obj, cog_id, lt, stype, time.time()))
        # 更新共现边权
        ts = time.time()
        _incr_cooccur(self.conn.cursor(), subj, pred, feedback, ts)
        _incr_cooccur(self.conn.cursor(), subj, obj, feedback, ts)
        _incr_cooccur(self.conn.cursor(), pred, obj, feedback, ts)
        # 有向边: subj →[pred]→ obj (保留方向和关系类型)
        _incr_directed(self.conn.cursor(), subj, obj, pred, feedback, ts)
        self.conn.commit()
        return cog_id

    def query_similar(self, text: str = "", subj: str = "", pred: str = "",
                      obj: str = "", top_k: int = 5) -> list:
        """共现索引检索 —— 低频准备 + 高频局部激活"""
        qv = _query_vector(self.conn, subj, obj, pred)
        activated = self._cooccur_neighbors([subj, obj, pred])
        return self._indexed_scan(qv, activated)[:top_k]

    def predict_feedback(self, text: str = "", subj: str = "", pred: str = "",
                         obj: str = "") -> tuple[str, float, list]:
        """共现索引预测 —— 只在激活子图中运算"""
        qv = _query_vector(self.conn, subj, obj, pred)
        activated = self._cooccur_neighbors([subj, obj, pred])
        similar = self._indexed_scan(qv, activated)[:10]
        if not similar:
            return ("unknown", 0.0, [])
        fc = {"confirmed": 0.0, "corrected": 0.0}
        for s in similar:
            fc[s["feedback"]] = fc.get(s["feedback"], 0.0) + s["similarity"]
        total = sum(fc.values()) or 1
        if fc.get("confirmed", 0) > fc.get("corrected", 0) * 1.5:
            return ("confirmed", fc["confirmed"] / total, similar)
        if fc.get("corrected", 0) > fc.get("confirmed", 0) * 1.5:
            return ("corrected", fc["corrected"] / total, similar)
        return ("unknown", 0.5, similar)

    # ═══════════════════════════════════════
    #  v3.5: 滑动窗口 + 能量扩散激活 (Spreading Activation)
    # ═══════════════════════════════════════

    def _sliding_window(self, text: str) -> list[str]:
        """
        把输入文本切为重叠滑动窗口。
        "你知道森蚺吗" → ["你知道", "知道森", "道森蚺", "森蚺吗", "你知道森", "道森蚺吗"]
        不需要知道哪个是实体——全丢进去让网络自己判断。
        """
        chunks = []
        clean = re.sub(r'[^\u4e00-\u9fff\w]', '', text)  # 去标点
        if not clean:
            return []
        for width in (2, 3, 4):
            for i in range(len(clean) - width + 1):
                chunk = clean[i:i + width]
                chunks.append(chunk)
        return chunks

    def spread_activate(self, text: str, top_k: int = 8,
                          gamma: float = 0.3) -> list[dict]:
        """
        能量扩散激活 + 胜者通吃 (WTA) + 侧向抑制。

        v3.5 final:
          γ=0.3 steep decay — 防止远跳噪声污染焦点
          WTA — 最高能节点独占，次要节点能量 ×0.3 抑制
          自锚节点 — "你/AI" 类词触发自我概念锚定

        只有网络本身存在的连接才能传导能量。
        """
        from collections import defaultdict

        chunks = self._sliding_window(text)
        if not chunks:
            return []

        activation: dict[str, float] = defaultdict(float)
        activated_by: dict[str, set] = defaultdict(set)

        # ── Layer 0: 精确匹配 (优先有向边 + NPMI 过滤) ──
        matched = set()
        for chunk in chunks:
            vec = _directed_vector(self.conn, chunk, "out")
            is_directed = bool(vec)
            if not vec:
                vec = _entity_vector(self.conn, chunk)  # 回退无向共现
            if not vec:
                continue
            matched.add(chunk)
            for node, val in vec.items():
                w, npmi = (val[0], val[1]) if isinstance(val, tuple) else (val, 1.0)
                activation[node] += w
                activated_by[node].add(chunk)

        if not matched:
            return self._anchor_activation(text)

        # ── Layer 1: 单跳扩散 (γ × sigmoid(NPMI)) ──
        gamma = 0.3
        layer0_candidates = {
            node for node, energy in activation.items() if energy > 1.0
        }
        for node in layer0_candidates:
            vec = _directed_vector(self.conn, node, "out")
            if not vec:
                vec = _entity_vector(self.conn, node)
            for neighbor, val in vec.items():
                if neighbor in activation:
                    continue
                w, npmi = (val[0], val[1]) if isinstance(val, tuple) else (val, 1.0)
                # 动态衰减: γ × sigmoid(NPMI)
                decay = gamma * (1.0 / (1.0 + math.exp(-5.0 * (npmi - 0.3))))
                activation[neighbor] = w * decay
                activated_by[neighbor].add(f"{node}(h1)")

        # ── Layer 2: 双跳 (γ² × sigmoid²) ──
        layer1_candidates = {
            node for node, energy in activation.items()
            if energy > 3.0 and node not in layer0_candidates
        }
        for node in layer1_candidates:
            vec = _directed_vector(self.conn, node, "out")
            if not vec:
                vec = _entity_vector(self.conn, node)
            for neighbor, val in vec.items():
                if neighbor in activation:
                    continue
                w, npmi = (val[0], val[1]) if isinstance(val, tuple) else (val, 1.0)
                decay = gamma * gamma * (1.0 / (1.0 + math.exp(-5.0 * (npmi - 0.3))))
                activation[neighbor] = w * decay
                activated_by[neighbor].add(f"{node}(h2)")

        # ── 过滤谓词标签 ──
        _skip = {"IS_A", "CAN", "BELONGS_TO", "NOT_IS_A",
                 "CAUSES", "ORBITS", "HAS", "IS_TOPIC", "UNPARSED"}
        for node in list(activation.keys()):
            if node in _skip:
                del activation[node]
            else:
                degree = self._node_degree(node)
                if degree > 50: activation[node] *= 0.2
                elif degree > 20: activation[node] *= 0.5

        if not activation:
            return []

        # ── WTA: 胜者通吃 + 侧向抑制 ──
        sorted_items = sorted(activation.items(), key=lambda x: -x[1])
        winner = sorted_items[0]
        # 冠军能量增强
        activation[winner[0]] *= 1.5
        # 其他节点能量抑制
        for i in range(1, len(sorted_items)):
            node = sorted_items[i][0]
            activation[node] *= 0.3

        # 重新排序
        sorted_nodes = sorted(activation.items(), key=lambda x: -x[1])[:top_k]

        return [{
            "node": node,
            "energy": round(energy, 4),
            "triggers": list(activated_by.get(node, set())),
            "degree": self._node_degree(node),
        } for node, energy in sorted_nodes if energy > 0.01]

    def _anchor_activation(self, text: str) -> list[dict]:
        """
        自锚节点: 当共现网零激活时，检查输入是否触发自我概念。

        "你是谁" → 激活 [AI, 助手, AsteriaMind]
        "你叫什么" → 激活 [AI]
        """
        # 自我概念锚定词
        self_markers = {'你', 'AI', '谁', '叫什么', '什么是', '你是谁',
                        'what', 'are', 'you', 'who'}
        text_clean = re.sub(r'[^\u4e00-\u9fff\w]', '', text)
        text_set = set(text_clean)

        if not (text_set & self_markers):
            return []

        # 自锚节点基底能量
        anchors = [
            {"node": "AI", "energy": 0.5, "triggers": ["self_anchor"], "degree": 0},
            {"node": "助手", "energy": 0.4, "triggers": ["self_anchor"], "degree": 0},
            {"node": "AsteriaMind", "energy": 0.3, "triggers": ["self_anchor"], "degree": 0},
        ]
        return [a for a in anchors if any(m in text_set for m in self_markers)]

    def _node_degree(self, entity: str) -> int:
        """节点的总连接度 (cognitive_traces + co_occurrence)"""
        degree = 0
        try:
            for row in self.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE subj=? OR obj=?",
                (entity, entity)):
                degree += row[0]
            for row in self.conn.execute(
                "SELECT COUNT(*) FROM co_occurrence WHERE entity_a=? OR entity_b=?",
                (entity, entity)):
                degree += row[0]
        except Exception:
            pass
        return degree

    def spread_write(self, text: str, energy_boost: float = 1.0):
        """
        从搜索结果中直接增强共现连接，而不是硬提取三元组。

        "森蚺...是世上最大的蛇之一，生活在南美洲"
          → 高频实词: 森蚺、巨型、蛇、南美洲
          → 两两建强连接 (co_occurrence weight++)
        """
        # 提取高频中文实词 (2-4 字)
        words = list(set(re.findall(r'[\u4e00-\u9fff]{2,4}', text)))
        if len(words) < 2:
            return

        cur = self.conn.cursor()
        ts = time.time()
        # 两两共现: 同时出现在同一段文本中的词 → 边权+1
        for i in range(len(words)):
            for j in range(i + 1, len(words)):
                a, b = words[i], words[j]
                if a == b: continue
                _incr_cooccur(cur, a, b, "confirmed", ts)
                # 有向边: 同段文本内双向弱连接 (relation=co_text)
                _incr_directed(cur, a, b, "co_text", "confirmed", ts)
                _incr_directed(cur, b, a, "co_text", "confirmed", ts)
        self.conn.commit()

    def emergent_reply(self, text: str, subj: str, pred: str, obj: str) -> dict:
        """共现 + 语言统一检索 → 涌现回复"""
        pf, conf, ev = self.predict_feedback(text, subj, pred, obj)
        qv = _query_vector(self.conn, subj, obj, pred)
        activated = self._cooccur_neighbors([subj, obj, pred])
        lang = []
        placeholders = ",".join("?" * len(activated))
        sql = (f"SELECT sentence,pattern_type,subj,obj FROM language_traces "
               f"WHERE subj IN ({placeholders}) OR obj IN ({placeholders})")
        for row in self.conn.execute(sql, list(activated) + list(activated)):
            tv = _query_vector(self.conn, row[2], row[3], "")
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                lang.append({"sentence": row[0], "pattern": row[1],
                             "subj": row[2], "obj": row[3], "similarity": sim})
        lang.sort(key=lambda x: x["similarity"], reverse=True)
        lang = lang[:3]
        reply = self._assemble(pf, conf, ev, lang)
        return {"predicted": pf, "confidence": conf, "evidence": ev,
                "language": lang, "reply": reply}

    def _assemble(self, predicted: str, confidence: float,
                  evidence: list, language: list) -> str:
        if not evidence:
            return f"我还不太了解 (置信{confidence:.0%})。你能教我吗?"
        nearest = evidence[0]
        if predicted == "confirmed" and confidence > 0.3:
            return f"对——就像「{nearest['subj']} {nearest['pred']} {nearest['obj']}」一样。(置信{confidence:.0%})"
        if predicted == "corrected" and confidence > 0.3:
            return f"不对——「{nearest['subj']} {nearest['pred']} {nearest['obj']}」曾被纠正过。"
        return f"还不太确定 (置信{confidence:.0%})"

    # ═══════════════════════════════════════
    #  v3.4: 语料库驱动的语言涌现
    # ═══════════════════════════════════════

    def learn_word_cooccur(self, word_a: str, word_b: str,
                           category: str, context: str = ""):
        """v3.4: 记录词级共现——每次生成回复后喂入"""
        if not word_a or not word_b or word_a == word_b:
            return
        if word_a > word_b:
            word_a, word_b = word_b, word_a
        ts = time.time()
        self.conn.execute(
            "INSERT INTO word_cooccur(word_a,word_b,category,context,weight,count,last_update) "
            "VALUES(?,?,?,?,1.0,1,?) "
            "ON CONFLICT(word_a,word_b,category,context) DO UPDATE SET "
            "count=count+1, weight=weight+1.0, last_update=?",
            (word_a, word_b, category, context, ts, ts))
        self.conn.commit()

    def query_word_neighbors(self, word: str, category: str,
                             context: str = "", top_k: int = 8) -> list[tuple]:
        """
        v3.4: 查询与某词最常共现的词。

        例如: query_word_neighbors("学到了", "bigram", "fact_learn")
              → [("✅", 15), ("📌", 8), ("💡", 5), ...]
        """
        rows = []
        # 先精确匹配 context
        for sql, params in (
            ("SELECT word_b, weight, count FROM word_cooccur "
             "WHERE word_a=? AND category=? AND context=? "
             "ORDER BY weight DESC LIMIT ?",
             (word, category, context, top_k)),
            ("SELECT word_a, weight, count FROM word_cooccur "
             "WHERE word_b=? AND category=? AND context=? "
             "ORDER BY weight DESC LIMIT ?",
             (word, category, context, top_k)),
        ):
            for row in self.conn.execute(sql, params):
                rows.append((row[0], row[1], row[2]))
        # 如果没有 context 匹配，回退到同一 category 的全部
        if not rows and context:
            for sql, params in (
                ("SELECT word_b, weight, count FROM word_cooccur "
                 "WHERE word_a=? AND category=? "
                 "ORDER BY weight DESC LIMIT ?",
                 (word, category, top_k)),
                ("SELECT word_a, weight, count FROM word_cooccur "
                 "WHERE word_b=? AND category=? "
                 "ORDER BY weight DESC LIMIT ?",
                 (word, category, top_k)),
            ):
                for row in self.conn.execute(sql, params):
                    rows.append((row[0], row[1], row[2]))
        rows.sort(key=lambda r: -r[1])
        return rows[:top_k]

    def learn_expression_pattern(self, action_type: str, confidence_bucket: str,
                                  source: str, opener: str, body_template: str,
                                  closer: str):
        """v3.4: 记录一个语言表达模式"""
        ts = time.time()
        # 检查是否已存在类似模式
        existing = self.conn.execute(
            "SELECT id, count FROM lang_patterns "
            "WHERE action_type=? AND confidence_bucket=? AND source=? "
            "AND opener=? AND closer=?",
            (action_type, confidence_bucket, source, opener, closer)
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE lang_patterns SET count=count+1, body_template=?, last_update=? "
                "WHERE id=?",
                (body_template, ts, existing[0]))
        else:
            self.conn.execute(
                "INSERT INTO lang_patterns(action_type,confidence_bucket,source,"
                "opener,body_template,closer,count,last_update) "
                "VALUES(?,?,?,?,?,?,1,?)",
                (action_type, confidence_bucket, source, opener, body_template,
                 closer, ts))
        self.conn.commit()

    def query_expression_patterns(self, action_type: str,
                                   confidence_bucket: str = "",
                                   source: str = "",
                                   min_count: int = 2,
                                   top_k: int = 6) -> list[dict]:
        """
        v3.4: 查询某个场景下最常用的表达模式。

        返回: [{opener, body_template, closer, count}, ...]
        按 count 降序排列。
        """
        rows = []
        # 层级回退: 精确匹配 → 放宽 source → 放宽 confidence_bucket
        query_layers = []
        if confidence_bucket and source:
            query_layers.append(
                ("WHERE action_type=? AND confidence_bucket=? AND source=? "
                 "AND count>=? ORDER BY count DESC LIMIT ?",
                 (action_type, confidence_bucket, source, min_count, top_k)))
        if confidence_bucket:
            query_layers.append(
                ("WHERE action_type=? AND confidence_bucket=? AND count>=? "
                 "ORDER BY count DESC LIMIT ?",
                 (action_type, confidence_bucket, min_count, top_k)))
        query_layers.append(
            ("WHERE action_type=? AND count>=? ORDER BY count DESC LIMIT ?",
             (action_type, min_count, top_k)))

        for sql, params in query_layers:
            for row in self.conn.execute(
                f"SELECT opener, body_template, closer, count FROM lang_patterns {sql}",
                params):
                rows.append({
                    "opener": row[0], "body_template": row[1],
                    "closer": row[2], "count": row[3],
                })
            if rows:
                break  # 有结果就不再放宽
        return rows[:top_k]

    def get_corpus_stats(self) -> dict:
        """v3.4: 语料库统计——监控语料库是否达到质变临界点"""
        wc_total = self.conn.execute(
            "SELECT COUNT(*) FROM word_cooccur").fetchone()[0]
        lp_total = self.conn.execute(
            "SELECT COUNT(*) FROM lang_patterns").fetchone()[0]
        lt_total = self.conn.execute(
            "SELECT COUNT(*) FROM language_traces").fetchone()[0]

        # 每个 (action, confidence) 组合有多少种不同表达?
        diversity = {}
        for row in self.conn.execute(
            "SELECT action_type, confidence_bucket, COUNT(DISTINCT opener) as openers, "
            "COUNT(*) as total FROM lang_patterns GROUP BY action_type, confidence_bucket"):
            diversity[f"{row[0]}-{row[1]}"] = {
                "unique_openers": row[2], "total_patterns": row[3],
                "rich": row[2] >= 3,  # ≥3 种不同开头的算"丰富"
            }

        # 质变临界点: 平均每种场景 5+ 种变体
        avg_variants = sum(d["unique_openers"] for d in diversity.values()) / max(len(diversity), 1)
        reached_critical_mass = avg_variants >= 3 and wc_total >= 100

        return {
            "word_cooccur_total": wc_total,
            "lang_patterns_total": lp_total,
            "language_traces_total": lt_total,
            "pattern_diversity": diversity,
            "avg_variants_per_scene": round(avg_variants, 1),
            "critical_mass_reached": reached_critical_mass,
        }

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0]
