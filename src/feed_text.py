"""
AsteriaMind 文本饲养脚本

把任意文本切成段落，灌入星图和符号星图。
co_text 边 ← spread_write (词对共现)
language_traces ← store (原始句存档，未来学句型)
symbol_star ← learn_symbol (关系词频统计)

用法:
  python feed_text.py fei_man.txt
  python feed_text.py "科学美国人_2024摘要.txt"
  python feed_text.py "D:/corpus/"   # 目录批量
"""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(__file__))
from AsteriaMind.cognitive_star_map import CognitiveStarMap

# ── 关系动词正则: 只抓动词本身, 不抓完整短语 ──
VERB_PATTERNS = [
    (r'(不会|不能|无法|不具备|做不到|没法)', "NOT_CAN", "ASK"),
    (r'(不是|并非)', "NOT_IS_A", "ASK"),
    (r'(属于|是一种|作为)', "IS_A", "ASK"),
    (r'(会|可以|擅长|善于|能)', "CAN", "ASK"),
    (r'(具有|拥有|具备|有)', "HAS", "ASK"),
    (r'(生活|栖息|分布)', "LIVES_IN", "ASK"),
    (r'(捕食|猎食|吃)', "EATS", "ASK"),
]

# 排除词: 太通用的功能词不计入
EXCLUDE_VERBS = {"是", "能", "会", "有", "吃"}

# ── 句式骨架提取: 段落 → lang_patterns ──
NAMED_RELS = {"NOT_CAN", "NOT_IS_A", "IS_A", "CAN", "HAS", "EATS", "LIVES_IN", "ORBITS"}
REPLACE_MAP = {
    "NOT_CAN": "{NOT_CAN}", "NOT_IS_A": "{NOT_IS_A}", "IS_A": "{IS_A}",
    "CAN": "{CAN}", "HAS": "{HAS}", "EATS": "{EATS}",
    "LIVES_IN": "{LIVES_IN}", "ORBITS": "{ORBITS}",
}

def feed_file(filepath: str, star: CognitiveStarMap, min_chars: int = 8):
    """啃一本书/一篇文章"""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # 按句号、换行、逗号切，确保 8 字以上的碎片都能被吃到
    paragraphs = re.split(r'[。\n，；]+', text)
    ingested = 0

    for para in paragraphs:
        para = para.strip()
        if len(para) < min_chars:
            continue

        # 1. 词对共现 → co_text 有向边
        star.spread_write(para)

        # 2. 存原始句 → language_traces (用虚拟 subj/pred/obj 作为键)
        star.store(
            f"doc:{os.path.basename(filepath)}",
            "HAS_PARAGRAPH",
            para[:60],
            "confirmed", para)

        # 3. 抓关系动词 → symbol_star 频次
        for pattern, rel, intent in VERB_PATTERNS:
            for match in re.findall(pattern, para):
                if match not in EXCLUDE_VERBS:
                    star.learn_symbol(rel, intent, match)

        # 4. ★ v3.6: 句式骨架提取 → lang_patterns 自动学习 ★
        _extract_pattern(star, para)

        ingested += 1

    star.conn.commit()
    return ingested


def _extract_pattern(star: CognitiveStarMap, para: str):
    """从句中找出命名实体, 替换为占位符, 生成句式骨架"""
    if len(para) < 10: return
    # 找出句中所有在星图中有命名关系的实体
    entities_found = []
    for w in (3, 2, 4):
        for i in range(len(para) - w + 1):
            kw = para[i:i+w]
            if kw in entities_found: continue
            n = star.conn.execute(
                "SELECT COUNT(*) FROM directed_edges "
                "WHERE source=? AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS','EATS','LIVES_IN','ORBITS')",
                (kw,)).fetchone()[0]
            if n >= 2:
                entities_found.append(kw)
    if not entities_found: return

    # 用第一个实体做主语, 查它的关系目标
    subj = entities_found[0]
    targets_by_rel = {}
    for row in star.conn.execute(
        "SELECT DISTINCT relation, target FROM directed_edges "
        "WHERE source=? AND relation IN ('NOT_CAN','NOT_IS_A','IS_A','CAN','HAS','EATS','LIVES_IN','ORBITS')",
        (subj,)):
        rel, target = row
        if rel not in targets_by_rel: targets_by_rel[rel] = []
        if target not in targets_by_rel[rel]:
            targets_by_rel[rel].append((target, len(target)))  # (target, length)
    if not targets_by_rel: return

    # 在段落中替换具体词 → 占位符
    pattern = para
    replaced = set()
    for rel, targs in sorted(targets_by_rel.items(), key=lambda x: -max(t[1] for t in x[1])):
        for target, _ in targs:
            if target in pattern and target not in replaced:
                pattern = pattern.replace(target, REPLACE_MAP.get(rel, rel), 1)
                replaced.add(target)
    # 替换主语
    pattern = pattern.replace(subj, "{subj}", 1)

    # 至少替换了 2 个槽位才算有效句式
    slot_count = pattern.count('{')
    if slot_count < 3: return  # 需要 {subj} + 至少 2 个关系槽

    # 存入 lang_patterns (先查后插, 避免重复)
    ts = __import__('time').time()
    existing = star.conn.execute(
        "SELECT id, count FROM lang_patterns WHERE body_template=? LIMIT 1",
        (pattern,)).fetchone()
    if existing:
        star.conn.execute(
            "UPDATE lang_patterns SET count=count+1, last_update=? WHERE id=?",
            (ts, existing[0]))
    else:
        star.conn.execute(
            "INSERT INTO lang_patterns(action_type, confidence_bucket, source, opener, body_template, closer, count, last_update) "
            "VALUES(?,?,?,?,?,?,1,?)",
            ("info_request", "mid", "auto", "", pattern, "", ts))


def feed_directory(dirpath: str, star: CognitiveStarMap):
    """啃一个文件夹"""
    total = 0
    for root, _, files in os.walk(dirpath):
        for fname in files:
            if fname.endswith((".txt", ".md")):
                n = feed_file(os.path.join(root, fname), star)
                print(f"  📖 {fname}: {n} 段落")
                total += n
    return total


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if not target:
        print("用法: python feed_text.py <文件或目录>")
        sys.exit(1)

    star = CognitiveStarMap()
    # 确保符号星图表存在
    star.conn.execute('''
        CREATE TABLE IF NOT EXISTS symbol_star (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relation_type TEXT NOT NULL, intent TEXT NOT NULL,
            symbol TEXT NOT NULL, count INTEGER DEFAULT 1,
            UNIQUE(relation_type, intent, symbol)
        )
    ''')
    star.conn.execute('CREATE INDEX IF NOT EXISTS idx_ss_ri ON symbol_star(relation_type,intent)')
    ts = time.time()

    if os.path.isdir(target):
        total = feed_directory(target, star)
    else:
        total = feed_file(target, star)

    elapsed = time.time() - ts
    traces = star.count()
    de = star.conn.execute("SELECT COUNT(*) FROM directed_edges").fetchone()[0]
    ss = star.conn.execute("SELECT COUNT(*) FROM symbol_star").fetchone()[0]

    print(f"\n🍽️ 吃完了: {total} 段落, {elapsed:.1f}s")
    print(f"   星图: {traces} 节点, {de} 有向边")
    print(f"   符号星图: {ss} 条关系词汇")
