"""
pdf2txt.py — PDF → TXT 语料转换器 (v3.7)

用户找的语料是 PDF → 转 txt 才能进喂料管道
用法:
  python pdf2txt.py <pdf文件或目录>
输出: 同目录 .txt (清理页眉页码/空白行)
"""

import os
import re
import sys


def pdf_to_text(path: str) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    parts = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            parts.append(text)
    doc.close()
    return "\n".join(parts)


def clean(text: str) -> str:
    """清理: 纯页码 / 空白行 / 过短行 (保留段落结构)"""
    lines = []
    for l in text.split("\n"):
        l = l.strip()
        if not l:
            continue
        if re.match(r"^\d{1,4}$", l):  # 纯页码
            continue
        if len(l) < 2:
            continue
        lines.append(l)
    return "\n".join(lines)


def convert(path: str):
    try:
        txt = pdf_to_text(path)
        txt = clean(txt)
        out_path = path.rsplit(".", 1)[0] + ".txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"✓ {os.path.basename(path)}: {len(txt)} 字 → {os.path.basename(out_path)}")
        return out_path
    except Exception as e:
        print(f"✗ {os.path.basename(path)}: {str(e)[:60]}")
        return None


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "D:/AM/corpus"
    if os.path.isdir(target):
        done = 0
        for f in sorted(os.listdir(target)):
            if f.lower().endswith(".pdf"):
                if convert(os.path.join(target, f)):
                    done += 1
        print(f"转换完成: {done} 个 PDF")
    else:
        convert(target)
