# -*- coding: utf-8 -*-
"""
health_monitor.py — HealthMonitor 统一健康预警 (AsteriaMind v3.9, ID-009)

白盒观测黑盒的"仪表盘" — 汇总散落的白盒机制为统一预警等级:

信号源 (全部是白盒观测黑盒的读数, 不干预黑盒):
  ① concept health   — belief_check 方向A 一致率 (白盒验黑盒, 黑盒质量)
  ② 涌现缺口         — emergence_check 方向B 缺口数 (黑盒新涌现 vs 白盒沉淀)
  ③ 锚点漂移         — anchor_check drift (向量空间偏移)
  ④ 污染率           — 命名边中英文/残片占比 (黑盒长歪信号)
  ⑤ 能量             — energy_level (系统代谢状态)

预警等级 (对接 ID-008 介入力度谱系 — 白盒介入由黑盒健康触发, 不是想介入就介入):
  L0 normal    → 只观察 (不介入)
  L1 attention → 提示 (诚实前言/提醒喂料)
  L2 warning   → 拦截 (质量门收紧/净化器加强)
  L3 critical  → 修复 (一次性清洗/重训向量)

设计原则 (进化宪法):
  - 白盒只读数+按级响应, 不替黑盒思考 (介入力度谱系 L4 禁止)
  - 双向: 方向A 查黑盒质量, 方向B 查白盒缺口 — 无绝对真理层
"""

import time


class HealthMonitor:
    """统一健康预警 — 汇总白盒观测黑盒的信号"""

    # 各信号权重 (归一化后加权 → 0~1 健康分)
    WEIGHTS = {
        "concept_health": 0.30,
        "emergence_gap": 0.20,
        "anchor_drift": 0.20,
        "pollution": 0.15,
        "energy": 0.15,
    }

    # 预警阈值 (信号 → 等级)
    # 污染率阈值: 命名边英文/残片占比
    POLLUTION_THRESHOLD = (0.02, 0.05, 0.10)   # attention / warning / critical

    def __init__(self, star_map, concept_layer=None, critic=None,
                 registry=None):
        self.star_map = star_map
        self.concept = concept_layer
        self.critic = critic
        self.registry = registry
        self._last_report = None
        self._last_ts = 0.0

    # ── 信号采集 ──
    def _collect_signals(self) -> dict:
        """采集 5 类黑盒健康信号 (全部只读, 不干预)"""
        signals = {}

        # ① concept health (方向A 白盒验黑盒)
        #    小样本控制耗时: emergence 逐个向量近邻较慢 (17842 词全量余弦)
        if self.concept and hasattr(self.concept, "dual_check"):
            try:
                dual = self.concept.dual_check(sample=6)
                signals["concept_health"] = dual[
                    "direction_a_whitebox_to_blackbox"]["consistency"]
                signals["emergence_gap"] = dual[
                    "direction_b_blackbox_to_whitebox"]["emergent_count"]
            except Exception:
                signals["concept_health"] = 0.5
                signals["emergence_gap"] = 0
        else:
            signals["concept_health"] = 0.5
            signals["emergence_gap"] = 0

        # ③ 锚点漂移 (向量空间偏移)
        if self.concept and hasattr(self.concept, "anchor_check"):
            try:
                ac = self.concept.anchor_check()
                signals["anchor_drift"] = ac["drift"]   # >0.1 视为漂移
            except Exception:
                signals["anchor_drift"] = 0.0
        else:
            signals["anchor_drift"] = 0.0

        # ④ 污染率 (命名边中英文/残片占比 — 采样估算)
        signals["pollution"] = self._estimate_pollution()

        # ⑤ 能量
        el = "medium"
        try:
            el = self.star_map.energy_level()
        except Exception:
            pass
        energy_score = {"high": 1.0, "medium": 0.6,
                        "low": 0.3, "critical": 0.0}.get(el, 0.5)
        signals["energy"] = energy_score
        signals["energy_level"] = el

        return signals

    def _estimate_pollution(self) -> float:
        """污染率估算: 命名边中 source/target 含英文或已知残片模式的占比
        采样 500 条命名边 (不扫 1165 万全表)
        """
        try:
            rows = self.star_map.conn.execute(
                "SELECT source, target FROM directed_edges "
                "WHERE relation != 'co_text' "
                "ORDER BY RANDOM() LIMIT 500").fetchall()
            if not rows:
                return 0.0
            bad = 0
            for s, t in rows:
                if not s or not t:
                    bad += 1
                    continue
                # 英文/无中文
                if not any('\u4e00' <= ch <= '\u9fff' for ch in s) or \
                   not any('\u4e00' <= ch <= '\u9fff' for ch in t):
                    bad += 1
                    continue
                # 残片模式
                if any(b in s or b in t for b in
                       ("因此", "而且", "虽然", "但是", "不仅", "然而",
                        "世界上", "地方都")):
                    bad += 1
            return round(bad / len(rows), 3)
        except Exception:
            return 0.0

    # ── 预警判定 (对接 ID-008 介入力度谱系) ──
    def _decide_level(self, signals: dict) -> dict:
        """根据信号 → 预警等级 L0~L3 + 驱动建议"""
        notes = []
        level = "normal"
        score = 0.0

        # ① concept health (黑盒贴合度): <0.5 注意, <0.35 警告
        ch = signals.get("concept_health", 0.5)
        score += ch * self.WEIGHTS["concept_health"]
        if ch < 0.35:
            level = max(level, "warning")
            notes.append("concept health 低 — 向量贴合白盒差, 建议喂料")
        elif ch < 0.5:
            level = max(level, "attention")
            notes.append("concept health 偏低 — 黑盒质量需关注")

        # ② 涌现缺口 (方向B): >=3 注意, >=6 警告 (白盒该被复核)
        eg = signals.get("emergence_gap", 0)
        score += max(0.0, 1.0 - eg / 10) * self.WEIGHTS["emergence_gap"]
        if eg >= 6:
            level = max(level, "warning")
            notes.append(f"黑盒涌现 {eg} 个缺口未被白盒沉淀 — 白盒该被复核(方向B)")
        elif eg >= 3:
            level = max(level, "attention")
            notes.append(f"黑盒涌现 {eg} 个缺口 — 白盒有知识缺口候选")

        # ③ 锚点漂移: >0.1 警告 (向量空间偏移)
        drift = signals.get("anchor_drift", 0.0)
        score += max(0.0, 1.0 - drift * 5) * self.WEIGHTS["anchor_drift"]
        if drift > 0.1:
            level = max(level, "warning")
            notes.append(f"锚点漂移 {drift:.3f} — 向量空间偏移, 需重训评估")

        # ④ 污染率: 分档
        poll = signals.get("pollution", 0.0)
        score += max(0.0, 1.0 - poll * 8) * self.WEIGHTS["pollution"]
        if poll >= self.POLLUTION_THRESHOLD[2]:
            level = max(level, "critical")
            notes.append(f"污染率 {poll:.1%} — 命名边含英文/残片, 需清洗(L3)")
        elif poll >= self.POLLUTION_THRESHOLD[1]:
            level = max(level, "warning")
            notes.append(f"污染率 {poll:.1%} — 质量门应收紧(L2)")
        elif poll >= self.POLLUTION_THRESHOLD[0]:
            level = max(level, "attention")
            notes.append(f"污染率 {poll:.1%} — 关注, 暂不介入(L1)")

        # ⑤ 能量: low 注意, critical 警告
        el = signals.get("energy_level", "medium")
        score += signals.get("energy", 0.5) * self.WEIGHTS["energy"]
        if el == "critical":
            level = max(level, "warning")
            notes.append("能量枯竭 critical — 求助模式, 需用户喂料/确认")
        elif el == "low":
            level = max(level, "attention")
            notes.append("能量偏低 low — 保守策略中")

        # 介入力度映射 (ID-008: L0观察/L1提示/L2拦截/L3修复)
        intervention = {
            "normal": "L0 观察 — 不介入, 白盒只读数",
            "attention": "L1 提示 — 诚实标注/提醒喂料, 不阻断黑盒",
            "warning": "L2 拦截 — 质量门收紧/净化加强, 不改黑盒内部",
            "critical": "L3 修复 — 一次性清洗/重训评估, 用完即止",
        }[level]

        return {
            "level": level,
            "intervention": intervention,
            "health_score": round(score, 3),
            "notes": notes,
            "signals": {k: v for k, v in signals.items()
                        if k != "energy_level"},
            "energy_level": el,
        }

    # ── 对外报告 (带缓存, 防高频调用扫库) ──
    def report(self, force: bool = False) -> dict:
        """全景健康报告 — 缓存 60s"""
        now = time.time()
        if not force and self._last_report and now - self._last_ts < 60:
            return self._last_report
        signals = self._collect_signals()
        report = self._decide_level(signals)
        report["timestamp"] = round(now)
        self._last_report = report
        self._last_ts = now
        return report

    def summary(self) -> dict:
        """精简摘要 (前端展示用)"""
        r = self.report()
        return {
            "level": r["level"],
            "health_score": r["health_score"],
            "intervention": r["intervention"],
            "notes": r["notes"],
            "signals": r["signals"],
            "energy_level": r["energy_level"],
        }
