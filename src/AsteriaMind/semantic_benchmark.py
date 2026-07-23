"""
Semantic Stress Benchmark — AM 语言理解基准 (v3.2)

不是"能不能答对"——是"每一层有没有产出正确的中间结果"。

测试维度:
  D1: 实体边界识别
  D2: 关系词识别
  D3: 疑问/否定标记
  D4: 歧义分辨 (会=能力 vs 会=因果)
  D5: 多从句
  D6: 英文基础
"""

BENCHMARK = {
    "D1_entity_boundary": [
        {
            "input": "地球绕太阳",
            "expect_entities": ["地球", "太阳"],
            "expect_relation": "ORBITS",
            "desc": "多字实体不被切碎"
        },
        {
            "input": "海豚是哺乳动物",
            "expect_entities": ["海豚", "哺乳动物"],
            "expect_relation": "IS_A",
            "desc": "三字实体+四字实体"
        },
        {
            "input": "中国人民大学在北京",
            "expect_entities": ["中国人民大学", "北京"],
            "desc": "长专有名词"
        },
        {
            "input": "咖啡因会导致失眠",
            "expect_entities": ["咖啡因", "失眠"],
            "expect_relation": "CAUSES",
            "desc": "三字主语+二字宾语"
        },
    ],

    "D2_relation_variants": [
        {
            "input": "猫属于动物吗",
            "expect_relation": "IS_A",
            "desc": "属于 → IS_A 同义映射"
        },
        {
            "input": "猫是什么动物",
            "expect_relation": "IS_A",
            "desc": "是什么X → IS_A 追问"
        },
        {
            "input": "猫和动物有什么关系",
            "expect_subject": "猫",
            "expect_object": "动物",
            "desc": "X和Y有关系 → 关系询问"
        },
        {
            "input": "火星属于行星吗",
            "expect_relation": "IS_A",
            "desc": "属于+吗 → IS_A 询问"
        },
    ],

    "D3_ambiguity": [
        {
            "input": "鸟会飞吗",
            "expect_pragmatic": "info_request",
            "expect_subject": "鸟",
            "expect_predicate": "CAN",
            "desc": "会=能力, 询问"
        },
        {
            "input": "你会飞吗",
            "expect_pragmatic": "capability_check",
            "desc": "你会X → 探测系统能力"
        },
        {
            "input": "飞机会飞吗",
            "expect_subject": "飞机",
            "expect_predicate": "CAN",
            "desc": "飞机+会 → 能力询问"
        },
        {
            "input": "水能灭火",
            "expect_predicate": "CAUSES",
            "desc": "能在这里是因果, 不是能力"
        },
    ],

    "D4_negation": [
        {
            "input": "猫不是狗吗",
            "expect_negated": True,
            "expect_question": True,
            "desc": "不是+吗 → 反问"
        },
        {
            "input": "蝙蝠不是鸟",
            "expect_negated": True,
            "desc": "否定陈述"
        },
    ],

    "D5_english_basic": [
        {
            "input": "cat is an animal",
            "expect_subject": "cat",
            "expect_relation": "IS_A",
            "expect_object": "animal",
            "desc": "英文 IS_A 基本句型"
        },
        {
            "input": "bird can fly",
            "expect_subject": "bird",
            "expect_predicate": "CAN",
            "desc": "英文能力句式"
        },
        {
            "input": "what is a dog",
            "expect_question": True,
            "expect_subject": "dog",
            "desc": "英文疑问句"
        },
    ],

    "D6_complex": [
        {
            "input": "猫是哺乳动物，海豚也是",
            "expect_multi_clause": True,
            "desc": "逗号分隔双从句"
        },
        {
            "input": "恐龙以前生活在哪里",
            "expect_subject": "恐龙",
            "expect_time": "以前",
            "desc": "含时间原语的问句"
        },
    ],

    "D7_pragmatic_depth": [
        {
            "input": "你觉得我怎么样",
            "expect_pragmatic": ("capability_check", "social_ritual", "info_request"),
            "desc": "多种语用解释共存"
        },
        {
            "input": "这个设计是不是有问题",
            "expect_negated": True,
            "expect_question": True,
            "desc": "反问+评价请求"
        },
    ],
}


def run_benchmark(ci) -> dict:
    """
    对 CognitiveInterface 跑全部基准测试。

    返回: { dimension: { passed: N, total: M, details: [...] } }
    """
    results = {}

    for dim, cases in BENCHMARK.items():
        passed = 0
        details = []

        for case in cases:
            text = case["input"]
            result = ci.process(text)
            semantic = result.get("semantic")
            pragmatic = result.get("pragmatic")
            struct = semantic.structure if semantic else {}

            checks = []
            # 检查实体
            if "expect_entities" in case:
                found = [struct.get("subject", ""), struct.get("object", "")]
                match = all(e in found for e in case["expect_entities"])
                checks.append(("entities", match, f"expect {case['expect_entities']} got {found}"))

            if "expect_relation" in case:
                match = struct.get("predicate") == case["expect_relation"]
                checks.append(("relation", match, f"expect {case['expect_relation']} got {struct.get('predicate')}"))

            if "expect_question" in case:
                match = struct.get("question") == case["expect_question"]
                checks.append(("question", match, f"expect {case['expect_question']} got {struct.get('question')}"))

            if "expect_negated" in case:
                match = struct.get("negated") == case["expect_negated"]
                checks.append(("negated", match, f"expect {case['expect_negated']} got {struct.get('negated')}"))

            if "expect_pragmatic" in case:
                expected = case["expect_pragmatic"]
                if isinstance(expected, str): expected = (expected,)
                match = pragmatic.type in expected if pragmatic else False
                checks.append(("pragmatic", match, f"expect {expected} got {pragmatic.type if pragmatic else 'None'}"))

            if "expect_subject" in case:
                match = struct.get("subject") == case["expect_subject"]
                checks.append(("subject", match, f"expect {case['expect_subject']} got {struct.get('subject')}"))

            if "expect_object" in case:
                match = struct.get("object") == case["expect_object"]
                checks.append(("object", match, f"expect {case['expect_object']} got {struct.get('object')}"))

            all_pass = all(c[1] for c in checks)
            if all_pass: passed += 1
            details.append({
                "input": text,
                "passed": all_pass,
                "checks": [{"field": c[0], "ok": c[1], "detail": c[2]} for c in checks],
                "desc": case.get("desc", ""),
            })

        results[dim] = {"passed": passed, "total": len(cases), "details": details}

    return results


def print_benchmark(results: dict):
    """打印基准测试结果"""
    total_pass = sum(r["passed"] for r in results.values())
    total_cases = sum(r["total"] for r in results.values())

    print(f"\n{'='*60}")
    print(f"  AM Semantic Stress Benchmark: {total_pass}/{total_cases} ({total_pass*100//total_cases}%)")
    print(f"{'='*60}")

    for dim, r in results.items():
        bar = "█" * r["passed"] + "░" * (r["total"] - r["passed"])
        score = f"{r['passed']}/{r['total']}"
        label = dim.replace("D", "").replace("_", " ").title()
        print(f"\n  {label}")
        print(f"  [{bar}] {score}")
        for d in r["details"]:
            icon = "✅" if d["passed"] else "❌"
            print(f"    {icon} {d['input']} — {d['desc']}")
            if not d["passed"]:
                for c in d["checks"]:
                    if not c["ok"]:
                        print(f"       ✗ {c['detail']}")
