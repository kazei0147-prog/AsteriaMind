"""
母模块 - HiveMind 调度中心

母模块整合：调度器、能量会计、保底控制器。
主循环：收集提议 → 评估 → 分发能量 → 保底检查 → 梦境触发 → 临终处理。

v0.4 新增：每轮记录提案到 DistillationEngine，模拟结束后导出 checkpoint。
"""

import random
import json
import logging
from pathlib import Path
from typing import List, Optional

from .config import HiveMindConfig
from .energy import EnergyWallet
from .submodule import SubModule, AggressiveModule, ConservativeModule, CompositeModule, CounterConsensusModule, SurvivorModule, Proposal
from .consensus import ConsensusTracker, ConsensusState
from .fallback import FallbackController
from .dream import DreamMechanism
from .death import DeathProtocol

logger = logging.getLogger("hivemind.mother")


class MotherModule:
    """
    母模块 - HiveMind 调度中心

    职责：
    1. 调度器：错峰采集，同步推演，收集模块提议
    2. 能量会计处：分发奖励，审计借贷，管控总预算
    3. 保底器：监控置信度衰减，触发影子候选机制
    4. 梦境触发器：检测僵化，启动低功耗反思
    5. 临终管理：执行死亡协议，归档/丢弃临终胶囊

    主循环每轮执行：
    ┌→ 采集数据（错峰，不同模块不同时间窗口）
    │→ 收集提议（各模块基于观测+偏见生成）
    │→ 评估与采纳（加权汇总，选出最优）
    │→ 分发能量奖励（被采纳模块获得 reward）
    │→ 置信度衰减与保底检查
    │→ 梦境触发（如果僵化）
    │→ 临终检查与执行
    └→ 下一轮
    """

    def __init__(self, config: HiveMindConfig):
        self.config = config
        self.round_num = 0

        # ── 能量会计 ──
        self.system_wallet = EnergyWallet(
            balance=config.total_energy_budget,
            loan_max=0,  # 系统本身不借贷
        )

        # ── 子模块 ──
        self.modules: List[SubModule] = [
            AggressiveModule(config),       # alpha (aggressive)
            ConservativeModule(config),     # beta (conservative)
            CounterConsensusModule(config), # delta (counter_consensus) — 纠错者
            CompositeModule(config),        # gamma (diplomat) — 外交官
            SurvivorModule(config),         # epsilon (survivor) — 幸存者 v0.5
        ]

        # ── 共识追踪器 ──
        self.consensus = ConsensusTracker(
            config=config,
            initial_value=config.target_value * 0.5,  # 初始共识远离目标，需要收敛
        )

        # ── 保底控制器 ──
        self.fallback = FallbackController(config, self.consensus)

        # ── 梦境机制 ──
        self.dream = DreamMechanism(config, self.consensus)

        # ── 临终协议 ──
        self.death = DeathProtocol(config, self.consensus)

        # ── 数据采集 ──
        self.data_buffer: List[float] = []

        # ── 运行日志 ──
        self.log: List[dict] = []
        self._last_expression_round: int = -100  # v0.5: 表达冷却计数器

        # ── 统计 ──
        self.stats = {
            "total_rounds": 0,
            "total_proposals": 0,
            "total_adoptions_by_module": {},
            "total_energy_spent": 0,
            "total_energy_earned": 0,
            "fallback_count": 0,
            "dream_count": 0,
            "death_count": 0,
        }

    def _generate_observation(self) -> float:
        """
        生成一轮观测数据（带噪声的目标值）。
        模拟外部数据采集：真实值 + 噪声。
        """
        noise = random.gauss(0, self.config.observation_noise)
        return self.config.target_value + noise

    def _stagger_collection(self) -> dict:
        """
        错峰采集：不同模块在不同时间窗口采集数据。
        alpha：使用最新观测（激进追逐新信号）
        beta：使用稍延迟观测 + 共识锚定参考（保守审慎）
        gamma：使用稍早观测 + 共识锚定参考（外交官需要多角度信息）— 外交官角色
        delta：使用加权混合观测（纠错者融合多信号）
        """
        latest_obs = self._generate_observation()

        # alpha：最新观测
        alpha_obs = latest_obs

        # beta：稍延迟观测（保守型不追最新信号）
        if len(self.data_buffer) > 1:
            beta_obs = self.data_buffer[-2]  # 用上一轮数据（延迟一轮）
        else:
            beta_obs = latest_obs * self.config.conservative_bias  # 第一轮直接低估

        # gamma (外交官)：稍早观测（需要多角度信息做混合策略）
        if len(self.data_buffer) > 2:
            gamma_obs = random.choice(self.data_buffer[-3:])
        elif len(self.data_buffer) > 0:
            gamma_obs = self.data_buffer[-1]
        else:
            gamma_obs = latest_obs

        # delta (纠错者)：加权混合最新+延迟观测（反共识需要距离感）
        if len(self.data_buffer) > 1:
            delta_obs = 0.6 * latest_obs + 0.4 * self.data_buffer[-1]  # 60%最新 + 40%上一轮
        else:
            delta_obs = latest_obs

        self.data_buffer.append(latest_obs)

        return {
            "alpha_aggressive": alpha_obs,
            "beta_conservative": beta_obs,
            "gamma_diplomat": gamma_obs,
            "delta_counter": delta_obs,
            "epsilon_survivor": latest_obs,  # v0.5: 幸存者用最新观测
        }

    def run_round(self) -> dict:
        """
        执行一轮完整推演循环。
        返回本轮状态快照。

        v0.4 新增：每轮将提案记录到蒸馏引擎。
        v0.5 新增：好奇心检测 + Epsilon 唤醒 + 主动交互表达式。
        """
        self.round_num += 1
        round_log = {"round": self.round_num}

        # ── 1. 错峰采集 ──
        observations = self._stagger_collection()

        # ── v0.5: 好奇心检测 + Epsilon 唤醒 ──
        curiosity_signal = self._check_curiosity()
        round_log["curiosity_signal"] = curiosity_signal
        if curiosity_signal > 0:
            # 尝试唤醒 epsilon
            epsilon = self._get_module("epsilon_survivor")
            if epsilon is not None and hasattr(epsilon, "try_wake"):
                epsilon.try_wake(curiosity_signal)
            # 为 epsilon 生成观测（即使它可能还在睡）
            if len(self.data_buffer) > 0:
                observations["epsilon_survivor"] = self.data_buffer[-1]

        # ── v0.5: 主动交互表达式 ──
        if self.config.expression_enabled:
            expressions = self._schedule_expressions(observations, curiosity_signal)
            if expressions:
                round_log["expressions"] = expressions

        # ── 2. 收集提议 ──
        proposals: List[Proposal] = []
        current_consensus = self.consensus.current.value

        for m in self.modules:
            if not m.alive:
                continue
            obs = observations.get(m.module_id, observations.get("alpha_aggressive"))
            proposal = m.propose(obs, current_consensus, self.round_num)
            if proposal is not None:
                proposals.append(proposal)

                # v0.4：将提案记录到蒸馏引擎，积累训练数据
                if self.config.distill_enabled:
                    self.dream.record_proposal(m, proposal.value)

        self.stats["total_proposals"] += len(proposals)
        round_log["proposals"] = [(p.module_id, p.value, p.confidence) for p in proposals]

        # ── 3. 重新激活机制 ──
        reactivated = self.consensus.try_reactivation(self.round_num)
        if reactivated is not None:
            # 重新激活的历史共识值作为额外参考
            round_log["reactivated"] = reactivated

        # ── 4. 评估与采纳 ──
        new_consensus = self.consensus.update(proposals, self.round_num)

        # 分发能量奖励（v0.2: 比例奖励，而非平均共享）
        # 每个模块按其置信度权重占比分配奖励
        # 高置信度模块贡献更大 → 赚更多 → 真正的竞争经济
        if proposals and new_consensus.contributors:
            contributor_proposals = [p for p in proposals if p.module_id in new_consensus.contributors]
            total_weight = sum(p.confidence for p in contributor_proposals)

            for p in contributor_proposals:
                proportion = p.confidence / total_weight if total_weight > 0 else 1.0 / len(contributor_proposals)
                individual_reward = self.config.adoption_reward * proportion
                for m in self.modules:
                    if m.module_id == p.module_id and m.alive:
                        m.on_adopted(individual_reward)
                        self.stats["total_energy_earned"] += individual_reward
                        self.stats["total_adoptions_by_module"][p.module_id] = \
                            self.stats["total_adoptions_by_module"].get(p.module_id, 0) + 1

        round_log["consensus_value"] = new_consensus.value
        round_log["consensus_confidence"] = new_consensus.confidence

        # ── 5. 系统总能量审计 ──
        total_module_energy = sum(m.wallet.balance for m in self.modules if m.alive)
        total_spent_this_round = sum(
            m.wallet.total_spent for m in self.modules if m.alive
        )
        round_log["total_module_energy"] = total_module_energy

        # ── 6. 保底检查 ──
        fallback_triggered = self.fallback.check_and_trigger(self.round_num)
        if fallback_triggered:
            self.stats["fallback_count"] += 1
            round_log["fallback_triggered"] = True

        # ── 7. 梦境触发 ──
        if self.dream.should_trigger() and self.round_num % 5 == 0:  # 每5轮检查一次
            dream_result = self.dream.execute(self.modules, self.round_num)
            self.stats["dream_count"] += 1
            round_log["dream_triggered"] = True
            round_log["dream_result"] = dream_result

        # ── 8. 临终检查 ──
        dead_modules = self.death.check_modules(self.modules, self.round_num)
        if dead_modules:
            self.stats["death_count"] += len(dead_modules)
            round_log["deaths"] = [m.module_id for m in dead_modules]

        # ── 9. 记录本轮状态 ──
        round_log["module_states"] = {
            m.module_id: {
                "alive": m.alive,
                "energy_balance": m.wallet.balance,
                "loan_balance": m.wallet.loan_balance,
                "struggling": m.wallet.struggling,
                "adoption_count": m.adoption_count,
                "total_rounds": m.total_rounds,
                "last_proposal_value": m.last_proposal.value if m.last_proposal else None,
            }
            for m in self.modules
        }

        self.log.append(round_log)
        self.stats["total_rounds"] = self.round_num

        return round_log

    def run_simulation(self, max_rounds: Optional[int] = None) -> List[dict]:
        """
        运行完整仿真。

        v0.4 新增：每隔 distill_export_interval 轮自动导出蒸馏 checkpoint。
        """
        rounds = max_rounds or self.config.max_rounds
        logger.info(f"开始仿真: {rounds}轮, 目标值={self.config.target_value}")

        all_logs = []
        for i in range(rounds):
            round_log = self.run_round()
            all_logs.append(round_log)

            # 检查所有模块是否都已死亡
            alive_count = sum(1 for m in self.modules if m.alive)
            if alive_count == 0:
                logger.warning(f"所有模块已死亡, 仿真终止于 round={self.round_num}")
                break

            # 每50轮输出进度
            if i % 50 == 0 and i > 0:
                error = abs(self.consensus.current.value - self.config.target_value)
                logger.info(
                    f"round={self.round_num}, "
                    f"consensus={self.consensus.current.value:.2f}, "
                    f"error={error:.2f}, "
                    f"confidence={self.consensus.current.confidence:.4f}, "
                    f"alive={alive_count}"
                )

            # v0.4：定期导出蒸馏 checkpoint
            export_interval = self.config.distill_export_interval
            if (
                export_interval > 0
                and self.config.distill_enabled
                and self.dream.distiller is not None
                and i > 0
                and i % export_interval == 0
                and self.dream.distiller.has_enough_data()
            ):
                # 执行蒸馏（如果还没蒸馏过）
                self.dream.distiller.distill()
                # 利用 export_checkpoint 生成数据但不写文件（仿真中途不写磁盘）
                ckpt = self.dream.distiller.export_checkpoint()
                logger.info(
                    f"[轮次 {self.round_num}] 自动蒸馏 checkpoint: "
                    f"samples={ckpt.get('n_training_samples')}, "
                    f"loss={ckpt.get('final_loss', 'N/A')}"
                )

        logger.info(f"仿真完成: {self.round_num}轮")
        return all_logs

    # ── v0.5 好奇心与主动交互 ──

    def _get_module(self, module_id: str) -> Optional[SubModule]:
        """查找指定 ID 的模块"""
        for m in self.modules:
            if m.module_id == module_id:
                return m
        return None

    def _check_curiosity(self) -> float:
        """
        v0.5: 好奇心检测。

        计算 |最新观测 - 当前共识| / |共识| 作为"惊讶度"。
        超过 curiosity_threshold 时返回信号值 [0, 1]。
        """
        if not self.data_buffer or self.consensus.current.value == 0:
            return 0.0

        latest_obs = self.data_buffer[-1]
        consensus_val = self.consensus.current.value
        deviation = abs(latest_obs - consensus_val)
        normalized = deviation / max(abs(consensus_val), 0.01)
        threshold = self.config.curiosity_threshold

        if normalized > threshold:
            signal = min(normalized / (threshold * 2), 1.0)
            if self.round_num % 50 == 0:
                logger.debug(f"[好奇心] 信号={signal:.3f} obs={latest_obs:.2f} consensus={consensus_val:.2f}")
            return signal
        return 0.0

    def _schedule_expressions(self, observations: dict, curiosity_signal: float) -> Optional[list]:
        """
        v0.5: 主动交互调度层。

        按三条规则决定是否让模块说话：
        A. 低置信 → 让最自信的模块发问
        B. 能量盈余 → 让盈余最多的模块声明探索
        C. 好奇心触发 → 让偏离最大的模块发言

        如果多条规则同时触发，组合多个表达（不分先后）。
        返回 [{"module": id, "expression": str, "trigger": str}, ...] 或 None。
        """
        expressions = []
        consensus_val = self.consensus.current.value
        confidence = self.consensus.current.confidence
        total_energy = sum(m.wallet.balance for m in self.modules if m.alive)
        budget = self.config.total_energy_budget

        alive_modules = [m for m in self.modules if m.alive]
        if not alive_modules:
            return None

        # 表达冷却：至少间隔 5 轮（避免能量盈余时每轮都说）
        if self.round_num - self._last_expression_round < 5:
            return None

        # 取最新观测（用 alpha 的观测作为代表）
        latest_obs = observations.get("alpha_aggressive", self.data_buffer[-1] if self.data_buffer else 50.0)

        # 规则 A: 低置信 → 询问
        if confidence < self.config.interaction_confidence_threshold:
            best = max(alive_modules, key=lambda m: (
                m.last_proposal.confidence if m.last_proposal else 0
            ))
            expr = best.express(latest_obs, consensus_val)
            expressions.append({
                "module": best.module_id,
                "expression": expr,
                "trigger": "low_confidence",
            })

        # 规则 B: 能量盈余 → 探索
        if total_energy > budget * self.config.interaction_energy_surplus_ratio:
            richest = max(alive_modules, key=lambda m: m.wallet.balance)
            expr = richest.express(latest_obs, consensus_val)
            expressions.append({
                "module": richest.module_id,
                "expression": expr + " 🚀 [探索模式]",
                "trigger": "energy_surplus",
            })

        # 规则 C: 好奇心 → 惊讶声明
        if curiosity_signal > 0 and self.round_num > 3:
            if alive_modules:
                most_deviant = max(alive_modules, key=lambda m: (
                    abs(m.history[-1] - consensus_val) if m.history else 0
                ))
                expr = most_deviant.express(latest_obs, consensus_val)
                expressions.append({
                    "module": most_deviant.module_id,
                    "expression": expr + " 🔍 [好奇心触发]",
                    "trigger": "curiosity",
                })

        if expressions:
            self._last_expression_round = self.round_num
        return expressions if expressions else None
        """返回仿真最终摘要"""
    def final_summary(self) -> dict:
        """返回仿真最终摘要"""
        consensus = self.consensus.current
        final_error = abs(consensus.value - self.config.target_value)

        summary = {
            "simulation_rounds": self.round_num,
            "target_value": self.config.target_value,
            "final_consensus": consensus.value,
            "final_error": final_error,
            "final_confidence": consensus.confidence,
            "alive_modules": sum(1 for m in self.modules if m.alive),
            "total_proposals": self.stats["total_proposals"],
            "total_energy_earned": self.stats["total_energy_earned"],
            "total_energy_spent": sum(m.wallet.total_spent for m in self.modules),
            "fallback_count": self.stats["fallback_count"],
            "dream_count": self.stats["dream_count"],
            "death_count": self.stats["death_count"],
            "module_summaries": {
                m.module_id: {
                    "alive": m.alive,
                    "legacy_capsule": m.legacy_capsule,
                    "wallet": m.wallet.snapshot(),
                    "adoption_count": m.adoption_count,
                    "total_rounds": m.total_rounds,
                    "avg_proposal": sum(m.history) / len(m.history) if m.history else None,
                }
                for m in self.modules
            },
            "fallback_summary": self.fallback.summary(),
            "dream_summary": self.dream.summary(),
            "death_summary": self.death.summary(),
            "consensus_summary": self.consensus.summary(),
        }

        # v0.4：追加蒸馏引擎摘要
        if self.config.distill_enabled and self.dream.distiller is not None:
            summary["distillation_summary"] = self.dream.distiller.summary()

        return summary

    # ── v0.4 知识蒸馏导出/导入 ──

    def export_distillation_checkpoint(self, filepath: str):
        """
        导出蒸馏模型 checkpoint 到文件。

        可在仿真结束后调用，将学到的知识持久化。
        """
        if not self.config.distill_enabled or self.dream.distiller is None:
            logger.warning("蒸馏引擎未启用，无法导出 checkpoint")
            return

        # 先执行一次最终蒸馏（如果还有数据没蒸馏过）
        if self.dream.distiller.has_enough_data():
            self.dream.distiller.distill()

        self.dream.distiller.save_checkpoint(filepath)
        logger.info(f"蒸馏 checkpoint 已导出: {filepath}")

    def load_distillation_checkpoint(self, filepath: str) -> bool:
        """
        从文件加载蒸馏模型 checkpoint。

        在仿真开始前调用，跳过冷启动。
        返回 True 表示加载成功。
        """
        if not self.config.distill_enabled or self.dream.distiller is None:
            logger.warning("蒸馏引擎未启用，无法加载 checkpoint")
            return False

        return self.dream.distiller.load_checkpoint_file(filepath)
