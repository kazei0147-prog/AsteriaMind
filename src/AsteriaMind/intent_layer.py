"""
IntentLayer — 意图驱动边权重重排 (AsteriaMind v3.6)

收到问题 → 推断意图 → 按意图重排 query_edges 的关系优先级
同一个星图，同一个概念，不同意图看到的是不同的"重要边"
"""

# 意图向量: {关系类型: 权重乘数}
INTENT_PROFILES = {
    "CORRECT": {   # "纠正误解" — NOT_CAN 推到最前
        "NOT_CAN": 3.0, "NOT_IS_A": 3.0,
        "IS_A": 1.5, "CAN": 0.5, "HAS": 0.5,
    },
    "EXPLAIN": {   # "解释原因" — IS_A → CAN/HAS 链条
        "IS_A": 2.5, "CAN": 2.0, "HAS": 2.0,
        "NOT_CAN": 0.8, "EATS": 1.0, "LIVES_IN": 1.0,
    },
    "COMPARE": {   # "对比差异" — 所有非 IS_A 都激活
        "NOT_CAN": 2.0, "CAN": 2.0, "HAS": 2.0,
        "EATS": 2.0, "LIVES_IN": 2.0, "IS_A": 0.5,
    },
    "CONFIRM": {   # "确认事实" — 只取 IS_A + HAS
        "IS_A": 3.0, "HAS": 1.5,
        "NOT_CAN": 0.3, "CAN": 0.3,
    },
    "ASK": {       # 默认: "提问" — 均衡
    },
}

# 意图触发词: 问句中的关键词 → 意图
INTENT_TRIGGERS = {
    "CORRECT":  ["不会","不能","不是","真的吗","是不是","错了吧","怎么可能"],
    "EXPLAIN":  ["为什么","怎么","原因","是什么","有什么"],
    "COMPARE":  ["区别","比较","哪个","还是","有什么不同"],
    "CONFIRM":  ["是吗","对吧","是不是","确实","对吗"],
}


def infer_intent(text: str) -> str:
    """从问句推断意图"""
    scores = {}
    for intent, triggers in INTENT_TRIGGERS.items():
        scores[intent] = sum(1 for t in triggers if t in text)
    best = max(scores, key=scores.get) if max(scores.values()) > 0 else "ASK"
    return best


def apply_intent_weight(edges: list[dict], intent: str) -> list[dict]:
    """按意图重排边的 salience"""
    profile = INTENT_PROFILES.get(intent, {})
    for e in edges:
        multiplier = profile.get(e["relation"], 1.0)
        e["salience"] = round(e["salience"] * multiplier, 3)
    edges.sort(key=lambda x: -x["salience"])
    return edges
