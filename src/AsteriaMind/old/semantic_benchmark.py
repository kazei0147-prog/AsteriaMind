"""
Semantic Core Benchmark — 关系假说 + 实体识别 + 否定/视角 (v3.2)

聚焦: 语言无关的认知结构是否稳定。
不测英文、不测复杂从句——只测核心管道。
"""

BENCHMARK = {
    "C1_entity_relation": [
        {
            "input": "地球绕太阳",
            "expect_subject": "地球", "expect_predicate": "ORBITS", "expect_object": "太阳",
            "desc": "实体+轨道关系"
        },
        {
            "input": "猫属于动物",
            "expect_subject": "猫", "expect_predicate": "IS_A", "expect_object": "动物",
            "desc": "属于→IS_A 关系假说"
        },
        {
            "input": "人工智能的发展",
            "expect_subject": "人工智能", "desc": "长专有名词实体不被切碎"
        },
    ],

    "C2_ambiguity": [
        {
            "input": "鸟会飞吗",
            "expect_subject": "鸟", "expect_predicate": "CAN",
            "expect_question": True, "desc": "会=能力, 问句"
        },
        {
            "input": "水能灭火吗",
            "expect_subject": "水", "expect_predicate": "CAUSES",
            "expect_question": True, "desc": "能=因果, 不是能力"
        },
    ],

    "C3_negation": [
        {
            "input": "猫不是狗",
            "expect_negated": True, "desc": "否定陈述"
        },
        {
            "input": "鲸鱼不是鱼",
            "expect_subject": "鲸鱼", "expect_predicate": "IS_A",
            "expect_negated": True, "desc": "否定+IS_A"
        },
    ],

    "C4_perspective": [
        {
            "input": "我觉得你错了",
            "expect_subject": "我", "expect_perspective": "我", "desc": "主体视角标记"
        },
        {
            "input": "你认为自己聪明吗",
            "expect_perspective_present": True, "expect_question": True, "desc": "反问+视角"
        },
    ],
}


def run_semantic_core_benchmark(ci) -> dict:
    """跑 Semantic Core Benchmark"""
    results = {}
    for dim, cases in BENCHMARK.items():
        passed = 0
        details = []
        for case in cases:
            text = case["input"]
            result = ci.process(text)
            semantic = result.get("semantic")
            struct = semantic.structure if semantic else {}
            candidates = result.get("semantic_candidates", [])

            checks = []
            for field in ["expect_subject", "expect_predicate", "expect_object"]:
                if field in case:
                    key = field.replace("expect_", "")
                    match = struct.get(key) == case[field]
                    checks.append((key, match, f"expect {case[field]} got {struct.get(key)}"))

            if "expect_question" in case:
                match = struct.get("question") == case["expect_question"]
                checks.append(("question", match, f"expect {case['expect_question']} got {struct.get('question')}"))

            if "expect_negated" in case:
                match = struct.get("negated") == case["expect_negated"]
                checks.append(("negated", match, f"expect {case['expect_negated']} got {struct.get('negated')}"))

            if "expect_perspective" in case:
                match = struct.get("perspective") == case["expect_perspective"]
                checks.append(("perspective", match, f"expect {case['expect_perspective']} got {struct.get('perspective')}"))

            if "expect_perspective_present" in case:
                match = bool(struct.get("perspective"))
                checks.append(("perspective_present", match, ""))

            all_pass = all(c[1] for c in checks)
            if all_pass:
                passed += 1

            details.append({
                "input": text, "passed": all_pass,
                "candidates": candidates,
                "checks": [{"field": c[0], "ok": c[1], "detail": c[2]} for c in checks],
                "desc": case.get("desc", ""),
            })

        results[dim] = {"passed": passed, "total": len(cases), "details": details}
    return results


def print_semantic_core(results: dict):
    total = sum(r["passed"] for r in results.values())
    total_cases = sum(r["total"] for r in results.values())
    print(f"\n{'='*60}")
    print(f"  Semantic Core Benchmark: {total}/{total_cases} ({total*100//total_cases}%)")
    print(f"{'='*60}")
    for dim, r in results.items():
        bar = "█" * r["passed"] + "░" * (r["total"] - r["passed"])
        label = dim.replace("C", "").replace("_", " ").title()
        print(f"\n  {label}")
        print(f"  [{bar}] {r['passed']}/{r['total']}")
        for d in r["details"]:
            icon = "✅" if d["passed"] else "❌"
            print(f"    {icon} {d['input']} — {d['desc']}")
            if d["candidates"]:
                print(f"       候选: {d['candidates'][:3]}")
            if not d["passed"]:
                for c in d["checks"]:
                    if not c["ok"]:
                        print(f"       ✗ {c['detail']}")
