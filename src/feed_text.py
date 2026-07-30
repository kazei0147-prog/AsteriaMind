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

        ingested += 1

    star.conn.commit()
    return ingested


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
