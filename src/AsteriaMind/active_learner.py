"""
ActiveLearner — AM 的主动学习 + 语言习得能力 (AsteriaMind v3.2)

不是被动接收。是主动发现缺口、主动提问。

核心循环:
  1. 遇到未知 → 先查 KG → 再试 Skill → 搜网络 → 最后提问用户
  2. 语言习得: 词汇/语法/翻译 → 存入 KG → 向量化 → 跨语言类比
  3. 问题队列: 攒够一批再问, 不逐条打断
"""
import re, time
from typing import Optional, List


class ActiveLearner:
    """
    主动学习者——不知道就查, 查不到就问。

    不是 LLM 那种"猜一个"。是"我不知道, 让我想办法知道"。
    """

    def __init__(self, kg=None, vl=None, web_search=None, cmd_tool=None):
        self.kg = kg
        self.vl = vl
        self.web_search = web_search
        self.cmd = cmd_tool
        self.pending_questions: list[dict] = []  # 待提问用户的问题

    def learn_word(self, word: str, lang: str = "zh") -> dict:
        """
        学习一个词: 查 KG → 查向量 → 搜网络 → 问用户。

        返回 {word, known, definition, source, confidence}
        """
        result = {"word": word, "lang": lang, "known": False}

        # 1. 查 KG
        if self.kg:
            for r in self.kg.relations:
                if r.subject == word:
                    if r.predicate in ("IS_A", "MEANS", "TRANSLATES_TO", "HAS_MEANING"):
                        result["known"] = True
                        result["definition"] = r.object
                        result["confidence"] = r.confidence
                        result["source"] = "kg_cache"
                        return result

        # 2. 查向量 (语义相似: 不认识但可能认识类似的?)
        if self.vl:
            similar = self.vl.search(word, top_k=3, min_similarity=0.3)
            if similar:
                result["hints"] = [(k, s) for k, s, _ in similar]
                result["note"] = "向量空间有相似概念，但无精确匹配"

        # 3. 搜网络
        if self.web_search:
            try:
                search_result = self.web_search.search(f"{word} 定义", max_results=2)
                for r in search_result:
                    if r.snippet and "未连接" not in r.snippet:
                        result["known"] = True
                        result["definition"] = r.snippet[:200]
                        result["confidence"] = 0.5
                        result["source"] = "web_search"
                        # 存入 KG
                        if self.kg:
                            self.kg.add(word, "MEANS", r.snippet[:100],
                                       confidence=0.5, source="web_search")
                        return result
            except Exception:
                pass

        # 4. 都不行 → 问用户
        self.pending_questions.append({
            "word": word, "context": f"不认识 '{word}'，KG/向量/网络均未找到",
            "timestamp": time.time(),
        })

        result["pending"] = True
        result["note"] = "已加入提问队列，等待用户解答"
        return result

    def learn_from_text(self, text: str) -> dict:
        """
        从一段文本中学习。分词 → 对每个不认识的字提问。

        不是一次性全吞——不认识的才问。
        """
        # 简单分词: 中文按字+词, 英文按空格
        words = []
        # 英文词
        words.extend(re.findall(r'[a-zA-Z]{3,}', text.lower()))
        # 中文双字
        cn = re.sub(r'[a-zA-Z0-9\s]+', '', text)
        for i in range(len(cn) - 1):
            words.append(cn[i:i+2])

        results = []
        for w in set(words[:20]):  # 最多 20 个不同词
            r = self.learn_word(w)
            if not r.get("known"):
                results.append(r)

        return {
            "total_words": len(words),
            "unique": len(set(words)),
            "known": len(results) == 0,
            "unknown": len(results),
            "pending_questions": [r["word"] for r in results if r.get("pending")],
        }

    def ask_user(self, question: str, context: str = "") -> dict:
        """
        主动提问用户。

        不打断——加入队列, 等待合适时机一并呈现。
        """
        self.pending_questions.append({
            "question": question,
            "context": context,
            "timestamp": time.time(),
        })
        return {"queued": True, "position": len(self.pending_questions)}

    def get_questions(self, max_q: int = 5) -> List[dict]:
        """取出待提问的问题 (不清除, 回答后由外部清除)"""
        return self.pending_questions[-max_q:]

    def answer_question(self, word: str, answer: str, confidence: float = 0.8):
        """用户回答了问题 → 存入 KG"""
        if self.kg:
            self.kg.add(word, "MEANS", answer, confidence=confidence,
                       source="user_taught")
        # 清除对应的 pending
        self.pending_questions = [
            q for q in self.pending_questions
            if q.get("word") != word and word not in q.get("question", "")
        ]
        return {"learned": word, "answer": answer}
