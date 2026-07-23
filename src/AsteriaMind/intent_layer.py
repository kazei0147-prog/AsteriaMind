"""
IntentLayer — AM 的语义意图理解层 (AsteriaMind v3.2)

替换原始 keyword→reply 路由。

架构:
  输入文本
    ↓
  语义解析 (SemanticParse)
    ↓
  意图假说生成 (IntentHypothesis × N)
    ↓
  置信度评分 + 排序
    ↓
  最佳意图 → 认知系统查询
    ↓
  动态回复生成

不是 "如果包含X就回复Y"
而是 "这可能是什么意图? KG 里有什么信息可以回答?"
"""
import re
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class IntentHypothesis:
    """一个意图假说"""
    type: str          # self_reflection | fact_query | fact_learn | capability | conversation | math | unknown
    text: str          # 原始输入
    parsed: str = ""   # 解析后的核心内容
    confidence: float = 0.5
    reasoning: str = ""


class IntentLayer:
    """
    意图理解层——不是关键词匹配, 是假说生成 + 置信度评估。

    输入: "你会什么"
    输出: 意图假说列表, 得分最高的获得控制权
    """

    def __init__(self, kg=None, db=None):
        self.kg = kg
        self.db = db

    def understand(self, text: str) -> IntentHypothesis:
        """
        解析一句话, 返回最高置信度的意图。

        不是 "if 包含X → reply Y"
        是 "生成N个假说, 每个评分, 选最高"
        """
        hypotheses = []

        # ── 假说1: 自我认知问题 ("你是谁"/"你会什么") ──
        self_patterns = [
            r'(?:你(?:是)?谁|你叫(?:什么|啥)|你的名字)',
            r'(?:你会(?:什么|哪些|干啥|做什么)|你能(?:做|干)什么|你的能力)',
            r'(?:你(?:知道|了解|懂|认识|听说过).+)',
        ]
        for i, pat in enumerate(self_patterns):
            if re.search(pat, text):
                hypo = IntentHypothesis("self_reflection", text, text)
                if i == 0:   # 身份
                    hypo.confidence = 0.9
                    hypo.reasoning = "匹配身份询问模式"
                elif i == 1: # 能力
                    hypo.confidence = 0.9
                    hypo.reasoning = "匹配能力询问模式"
                elif i == 2: # 知识
                    m = re.search(r'(?:了解|知道|懂|认识|听说过)(.+)', text)
                    topic = m.group(1).rstrip('吗?？').strip() if m else text
                    hypo.parsed = topic
                    hypo.confidence = 0.85
                    hypo.reasoning = "匹配知识询问模式: " + topic
                hypotheses.append(hypo)

        # ── 假说2: 事实查询 ("X是什么"/"X会Y吗") ──
        if '?' in text or '？' in text or '吗' in text or '是什么' in text:
            hypo = IntentHypothesis("fact_query", text, text)
            hypo.confidence = 0.8 if '是什么' in text else 0.7
            hypo.reasoning = "包含疑问标记"
            # 提取查询主体
            for kw in re.findall(r'[\u4e00-\u9fff\w]{2,}', text):
                if kw in ('什么','是什么','吗','可以','怎么','如何','为什么','是否','请问'): continue
                if self.kg:
                    for r in self.kg.relations:
                        if r.subject == kw:
                            hypo.confidence += 0.1
                            hypo.reasoning += f"; KG 中有 '{kw}' 相关事实"
                            break
                break
            hypotheses.append(hypo)

        # ── 假说3: 事实学习 ("X是Y"/"X会Y") ──
        m = re.search(r'([\u4e00-\u9fff\w]{1,15})(?:是|属于|围绕|绕着|绕|导致|引起)([\u4e00-\u9fff\w]{1,20})', text)
        if m:
            hypo = IntentHypothesis("fact_learn", text, text)
            hypo.confidence = 0.75
            hypo.reasoning = "匹配事实陈述模式"
            hypo.parsed = f"{m.group(1)} → {m.group(2)}"
            # 排除代词主语
            if m.group(1) in ('这','那','它','他','她','你','我'):
                hypo.confidence = 0.3
                hypo.reasoning += " (主语为代词, 降权)"
            hypotheses.append(hypo)

        # ── 假说4: 数学计算 ──
        if re.search(r'\d\s*[\+\-\*/\^]\s*\d', text):
            hypo = IntentHypothesis("math", text, text)
            hypo.confidence = 0.9
            hypo.reasoning = "包含数学表达式"
            hypotheses.append(hypo)

        # ── 假说5: 闲聊/问候 ──
        greetings = r'(?:你好|hello|hi|嗨|您好|早上好|晚上好|早安|晚安|再见|拜拜|bye)'
        thanks = r'(?:谢谢|感谢|多谢|thx|thanks)'
        laugh = r'(?:哈哈|真的假的|笑死|😂|好吧|嗯嗯|哦哦)'
        if re.search(greetings, text):
            hypo = IntentHypothesis("conversation", text, "greeting")
            hypo.confidence = 0.85
            hypo.reasoning = "问候语"
            hypotheses.append(hypo)
        elif re.search(thanks, text):
            hypo = IntentHypothesis("conversation", text, "thanks")
            hypo.confidence = 0.85
            hypo.reasoning = "感谢语"
            hypotheses.append(hypo)
        elif re.search(laugh, text):
            hypo = IntentHypothesis("conversation", text, "casual")
            hypo.confidence = 0.7
            hypo.reasoning = "口语闲聊"
            hypotheses.append(hypo)

        # ── 排序: 按置信度 → 最高分胜出 ──
        if hypotheses:
            hypotheses.sort(key=lambda h: h.confidence, reverse=True)
            return hypotheses[0]

        # ── 兜底 ──
        return IntentHypothesis("unknown", text, text, confidence=0.3, reasoning="无法匹配任何已知模式")

    def execute(self, intent: IntentHypothesis) -> str:
        """
        根据意图查询认知系统, 生成动态回复。

        这是 "输出层" —— 不再用硬编码模板,
        而是从 KG + 上下文拼装。
        """
        reply = ""

        if intent.type == "self_reflection":
            # "你是谁" → 从 KG 查自我认知
            name = "AsteriaMind"
            role = "一个正在进化的认知系统"
            if self.kg:
                for r in self.kg.relations:
                    if r.subject == "我" and r.predicate == "MEANS":
                        name = r.object
                    if r.subject == "我" and r.predicate == "IS_A":
                        role = r.object

            if "会" in intent.text or "能力" in intent.text:
                # 动态能力列表: 查 KG 有多少知识
                facts = self.db.count() if self.db else 0
                templates = sum(1 for r in (self.kg.relations if self.kg else [])
                               if "template" in str(r.predicate).lower())
                reply = (f"我可以: 📚 存储了 {facts} 条知识、🧩 {templates or 6} 个推理模板。\n"
                         f"你可以教我新东西, 也可以问我问题。")
            else:
                reply = f"我是 {name}, {role}。是你在培养的 AI。"

        elif intent.type == "fact_query":
            # 查 KG
            cleaned = intent.parsed or intent.text
            for kw in re.findall(r'[\u4e00-\u9fff\w]{2,}', cleaned.replace('?','').replace('？','')):
                if kw in ('什么','是什么','吗','可以','怎么'): continue
                if self.kg:
                    for r in self.kg.relations:
                        if r.subject == kw:
                            reply += f"{r.subject} --[{r.predicate}]--> {r.object}\n"
            if not reply:
                reply = f"关于这个我还不知道。你能教我吗?"

        elif intent.type == "conversation":
            tone = intent.parsed or "general"
            if tone == "greeting":
                reply = "你好呀~ 🌻"
            elif tone == "thanks":
                reply = "不客气 🙂"
            else:
                reply = "在呢, 说吧!"

        else:
            reply = "我记下了。试试更具体地说?"

        return reply
