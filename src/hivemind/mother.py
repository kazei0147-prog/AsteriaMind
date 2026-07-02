"""
母模块 - HiveMind 调度中心

母模块整合：调度器、能量会计、保底控制器。
主循环：收集提议 → 评估 → 分发能量 → 保底检查 → 梦境触发 → 临终处理。
"""

import random
import logging
from typing import List, Optional

from .config import HiveMindConfig
from .energy import EnergyWallet
from .submodule import SubModule, AggressiveModule, ConservativeModule, CounterConsensusModule, Proposal
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
            ConservativeModule(config),     # beta (conservative) — v0.2 新增
            CounterConsensusModule(config), # gamma (counter_consensus)
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
        gamma：使用稍早观测（反共识需要"距离感"）
        """
        latest_obs = self._generate_observation()

        # alpha：最新观测
        alpha_obs = latest_obs

        # beta：稍延迟观测（保守型不追最新信号）
        if len(self.data_buffer) > 1:
            beta_obs = self.data_buffer[-2]  # 用上一轮数据（延迟一轮）
        else:
            beta_obs = latest_obs * self.config.conservative_bias  # 第一轮直接低估

        # gamma：稍早观测（延迟更大，需要"距离感"做反向推演）
        if len(self.data_buffer) > 2:
            gamma_obs = random.choice(self.data_buffer[-3:])
        elif len(self.data_buffer) > 0:
            gamma_obs = self.data_buffer[-1]
        else:
            gamma_obs = latest_obs

        self.data_buffer.append(latest_obs)

        return {
            "alpha_aggressive": alpha_obs,
            "beta_conservative": beta_obs,
            "gamma_counter": gamma_obs,
        }

    def run_round(self) -> dict:
        """
        执行一轮完整推演循环。
        返回本轮状态快照。
        """
        self.round_num += 1
        round_log = {"round": self.round_num}

        # ── 1. 错峰采集 ──
        observations = self._stagger_collection()

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

        logger.info(f"仿真完成: {self.round_num}轮")
        return all_logs

    def final_summary(self) -> dict:
        """返回仿真最终摘要"""
        consensus = self.consensus.current
        final_error = abs(consensus.value - self.config.target_value)

        return {
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
