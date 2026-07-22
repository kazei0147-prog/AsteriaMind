"""
KnowledgeDB — AM 的 SQLite 持久化后端 (AsteriaMind v3.2)

替换 JSON 文件, 让她能持续学习, 不丢数据。

特性:
  - 自动建表: relations, templates, meta_log, skill_usage
  - 增量写入: 不整库重写, 单条 insert
  - 索引查询: O(1) 精确查询 + LIKE 模糊查询
  - 并发安全: WAL 模式
  - 版本管理: schema_version 自动迁移
"""
import sqlite3, json, time, os
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1


class KnowledgeDB:
    """AM 的持久化数据库"""

    def __init__(self, db_path: str = "asteriamind.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self):
        """自动建表 + 版本迁移"""
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if not cur.fetchone():
            # 首次创建
            cur.executescript("""
                CREATE TABLE schema_version (version INTEGER);
                INSERT INTO schema_version VALUES (1);

                CREATE TABLE relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    alpha REAL DEFAULT 5.0,
                    beta REAL DEFAULT 1.0,
                    confidence REAL DEFAULT 0.5,
                    source TEXT DEFAULT 'observed',
                    counter_evidence TEXT DEFAULT '[]',
                    created_at REAL,
                    updated_at REAL
                );
                CREATE INDEX idx_relations_subj ON relations(subject);
                CREATE INDEX idx_relations_pred ON relations(predicate);
                CREATE INDEX idx_relations_obj ON relations(object);
                CREATE INDEX idx_relations_key ON relations(subject, predicate, object);

                CREATE TABLE templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mechanism TEXT,
                    status TEXT DEFAULT 'active',
                    times_used INTEGER DEFAULT 0,
                    energy_spent REAL DEFAULT 0.0,
                    notes TEXT DEFAULT '',
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE meta_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_num INTEGER,
                    patterns TEXT,
                    alert TEXT,
                    timestamp REAL
                );

                CREATE TABLE knowledge_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    urgency REAL DEFAULT 0.5,
                    context TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at REAL,
                    fulfilled_at REAL
                );

                CREATE TABLE skill_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    query TEXT,
                    success INTEGER DEFAULT 0,
                    elapsed_ms REAL,
                    timestamp REAL
                );
            """)
            print(f"[KnowledgeDB] 新数据库: {self.db_path}")
        self.conn.commit()

    # ── Relations ──

    def add_relation(self, subject: str, predicate: str, object: str,
                     confidence: float = 0.5, source: str = "observed") -> int:
        now = time.time()
        alpha = max(1, confidence * 10)
        beta = max(1, (1 - confidence) * 10)
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO relations (subject,predicate,object,alpha,beta,confidence,source,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (subject, predicate, object, alpha, beta, confidence, source, now, now)
        )
        self.conn.commit()
        return cur.lastrowid

    def query(self, subject: str = None, predicate: str = None,
              object: str = None, min_confidence: float = 0.0) -> list[dict]:
        wheres = ["confidence >= ?"]
        params = [min_confidence]
        if subject:
            wheres.append("subject = ?")
            params.append(subject)
        if predicate:
            wheres.append("predicate = ?")
            params.append(predicate)
        if object:
            wheres.append("object = ?")
            params.append(object)
        sql = f"SELECT * FROM relations WHERE {' AND '.join(wheres)} ORDER BY confidence DESC"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def search_text(self, text: str, limit: int = 10) -> list[dict]:
        """全文模糊搜索"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM relations WHERE subject LIKE ? OR object LIKE ? OR predicate LIKE ? ORDER BY confidence DESC LIMIT ?",
            (f"%{text}%", f"%{text}%", f"%{text}%", limit)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def update_confidence(self, subject: str, predicate: str, object: str,
                          confidence: float):
        alpha = max(1, confidence * 10)
        beta = max(1, (1 - confidence) * 10)
        self.conn.execute(
            "UPDATE relations SET alpha=?, beta=?, confidence=?, updated_at=? WHERE subject=? AND predicate=? AND object=?",
            (alpha, beta, confidence, time.time(), subject, predicate, object)
        )
        self.conn.commit()

    def count(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM relations")
        return cur.fetchone()[0]

    def stats(self) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(confidence) FROM relations")
        cnt, avg_conf = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM relations WHERE confidence > 0.7")
        strong = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM relations WHERE confidence < 0.4")
        weak = cur.fetchone()[0]
        return {
            "total": cnt or 0,
            "avg_confidence": round(avg_conf or 0, 3),
            "strong_beliefs": strong or 0,
            "weak_beliefs": weak or 0,
        }

    # ── Templates ──

    def save_template(self, tid: str, name: str, status: str = "active"):
        self.conn.execute(
            "INSERT OR REPLACE INTO templates (id,name,status,created_at,updated_at) VALUES (?,?,?,?,?)",
            (tid, name, status, time.time(), time.time())
        )
        self.conn.commit()

    # ── Meta Log ──

    def log_meta(self, round_num: int, patterns: dict, alert: str):
        self.conn.execute(
            "INSERT INTO meta_log (round_num, patterns, alert, timestamp) VALUES (?,?,?,?)",
            (round_num, json.dumps(patterns, ensure_ascii=False), alert, time.time())
        )
        self.conn.commit()

    # ── Knowledge Requests ──

    def add_request(self, query: str, urgency: float, context: str):
        self.conn.execute(
            "INSERT INTO knowledge_requests (query, urgency, context, created_at) VALUES (?,?,?,?)",
            (query, urgency, context, time.time())
        )
        self.conn.commit()

    def get_pending_requests(self, limit: int = 10) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM knowledge_requests WHERE status='pending' ORDER BY urgency DESC LIMIT ?",
            (limit,)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── Utilities ──

    def close(self):
        self.conn.close()

    def export_json(self, path: str):
        """导出为 JSON (兼容旧格式)"""
        cur = self.conn.cursor()
        cur.execute("SELECT subject, predicate, object, alpha, beta, confidence, source FROM relations")
        data = []
        for row in cur.fetchall():
            data.append({
                "subject": row[0], "predicate": row[1], "object": row[2],
                "alpha": row[3], "beta": row[4], "confidence": row[5],
                "source": row[6],
            })
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
