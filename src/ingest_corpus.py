"""
ingest_corpus.py — 喂料点火 (v3.7)

新书落地后一键处理, 让 AM 消化:
  1. 分句 → language_traces (语言接触史 → 骨架池长肉)
  2. spread_write (联想层增长)
  3. 向量重训 (word2vec: 全部语料 + 种子知识)
  4. 骨架重挖 (language_model 从 language_traces)
  5. CorpusMiner (命名知识提取)
  6. 前后对比报告

用法: python ingest_corpus.py
"""

import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CORPUS = "D:/AM/corpus"
_DB = "D:/AM/HiveMind_repo/src/asteriamind.db"
_INGESTED_TABLE = "ingested_files"


def _get_conn():
    conn = sqlite3.connect(_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS ingested_files("
                 "filename TEXT PRIMARY KEY, ts REAL, chars INT)")
    return conn


def _sentence_split(text: str) -> list:
    """分句: 中文句号/感叹/问号/换行"""
    parts = re.split(r"[。！？；\n]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


def step1_language_traces(conn, filename, text) -> int:
    """新书句子 → language_traces (去重)"""
    n = 0
    for sent in _sentence_split(text):
        exists = conn.execute(
            "SELECT 1 FROM language_traces WHERE sentence=? LIMIT 1",
            (sent[:200],)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO language_traces(sentence, subj, pred, obj, "
            "timestamp, sentence_type) VALUES (?,?,?,?,?,?)",
            (sent[:500], filename[:30], "", "", time.time(), "corpus"))
        n += 1
    conn.commit()
    return n


def step2_spread_write(star_map, text) -> int:
    """联想层: 全文 spread_write (能量累加, 边数不暴涨)"""
    before = star_map.conn.execute(
        "SELECT COUNT(*) FROM directed_edges WHERE relation='co_text'"
    ).fetchone()[0]
    for sent in _sentence_split(text):
        star_map.spread_write(sent)
    after = star_map.conn.execute(
        "SELECT COUNT(*) FROM directed_edges WHERE relation='co_text'"
    ).fetchone()[0]
    return after - before


def step3_retrain_vectors() -> dict:
    """向量重训: 全部语料 + 种子知识"""
    from AsteriaMind.vector_space import train, store
    model = train(corpus_dir=_CORPUS, dim=128, min_count=1, epochs=15)
    store(model)
    return {"vocab": len(model.wv.index_to_key)}


def step4_remine_skeletons() -> dict:
    """骨架重挖: language_model 从 language_traces"""
    from AsteriaMind.language_model import LanguageModel
    lm = LanguageModel()
    lm.mine(min_count=1)
    return {rel: len(v) for rel, v in lm._pool.items() if v}


def step5_corpus_miner() -> dict:
    """命名知识提取"""
    from AsteriaMind.cognitive_star_map import CognitiveStarMap
    from AsteriaMind.corpus_miner import CorpusMiner
    s = CognitiveStarMap(os.path.join(os.path.dirname(_DB), "asteriamind.db"))
    m = CorpusMiner(s, corpus_dir=_CORPUS)
    r = m.mine()
    return {"confirmed": r["confirmed"], "skipped": r["skipped"]}


def main():
    t0 = time.time()
    conn = _get_conn()
    from AsteriaMind.cognitive_star_map import CognitiveStarMap
    star_map = CognitiveStarMap(os.path.join(os.path.dirname(_DB),
                                             "asteriamind.db"))

    # 统计基线
    lt_before = conn.execute(
        "SELECT COUNT(*) FROM language_traces").fetchone()[0]
    named_before = conn.execute(
        "SELECT COUNT(*) FROM directed_edges WHERE relation IN "
        "('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN')").fetchone()[0]

    print("═══ 喂料点火 ═══")
    for f in sorted(os.listdir(_CORPUS)):
        if not f.endswith(".txt"):
            continue
        path = os.path.join(_CORPUS, f)
        done = conn.execute(
            "SELECT 1 FROM ingested_files WHERE filename=?", (f,)).fetchone()
        if done:
            print(f"⏭  {f}: 已处理过, 跳过")
            continue
        text = open(path, encoding="utf-8", errors="ignore").read()
        n_lt = step1_language_traces(conn, f, text)
        n_co = step2_spread_write(star_map, text)
        conn.execute("INSERT INTO ingested_files VALUES (?,?,?)",
                     (f, time.time(), len(text)))
        conn.commit()
        print(f"✓ {f}: {len(text):,}字 → 语言史+{n_lt} 联想+{n_co:,}")

    print("\n── 向量重训 (全部语料) ──")
    vr = step3_retrain_vectors()
    print(f"  词表: {vr['vocab']}")

    print("\n── 骨架重挖 (语言) ──")
    sk = step4_remine_skeletons()
    print(f"  {sk}")

    print("\n── 命名知识提取 (CorpusMiner) ──")
    cm = step5_corpus_miner()
    print(f"  确认: {cm['confirmed']} 跳过: {cm['skipped']}")

    # 报告
    lt_after = conn.execute(
        "SELECT COUNT(*) FROM language_traces").fetchone()[0]
    named_after = conn.execute(
        "SELECT COUNT(*) FROM directed_edges WHERE relation IN "
        "('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN')").fetchone()[0]
    co_after = conn.execute(
        "SELECT COUNT(*) FROM directed_edges WHERE relation='co_text'"
    ).fetchone()[0]
    conn.close()

    print("\n═══ 消化报告 ═══")
    print(f"语言史: {lt_before:,} → {lt_after:,} (+{lt_after-lt_before:,})")
    print(f"命名边: {named_before:,} → {named_after:,} (+{named_after-named_before})")
    print(f"联想边: {co_after:,} 条 (能量累加)")
    print(f"总耗时: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
