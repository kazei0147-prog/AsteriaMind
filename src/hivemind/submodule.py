"""
子模块 - HiveMind 认知节点种群

v0.5: 五模块架构 + 表达层
  alpha (aggressive)    — 偏好新信号，倾向高估
  beta  (conservative)  — 锚定共识，倾向低估
  gamma (diplomat)      — 外交官，随机混合策略，桥梁角色
  delta (counter_consensus) — 纠错者，逆主流而行，纠正偏移
  epsilon (survivor)    — 幸存者，懒加载休眠策略，低功耗待机

每个模块自带能量钱包、认知偏见、推演能力、表达能力。
"""

from dataclasses import dataclass
from typing import Optional, List
import random
import logging

from .energy import EnergyWallet
from .config import HiveMindConfig

logger = logging.getLogger("hivemind.submodule")


@dataclass
class Proposal:
    """子模块推演产出"""
    module_id: str
    value: float              # 提议值（对目标的估计）
    confidence: float         # 模块自身置信度 [0, 1]
    reasoning: str            # 简短推理说明
    energy_cost: float        # 本次推演消耗的能量
    round_number: int         # 产出轮次


class SubModule:
    """子模块基类"""

    def __init__(
        self,
        module_id: str,
        bias_type: str,
        wallet: EnergyWallet,
        config: HiveMindConfig,
    ):
        self.module_id = module_id
        self.bias_type = bias_type
        self.wallet = wallet
        self.config = config
        self.alive = True
        self.legacy_capsule: Optional[str] = None   # 临终胶囊
        self.history: List[float] = []               # 历史提议值
        self.adoption_count: int = 0                 # 被采纳次数
        self.total_rounds: int = 0                   # 参与推演总轮数
        self.last_proposal: Optional[Proposal] = None

    def observe(self, raw_data: float) -> float:
        """
        从原始数据中提取信息，施加模块偏见。
        不同模块对同一数据有不同的解读。
        """
        raise NotImplementedError("子类必须实现 observe()")

    def propose(self, observation: float, current_consensus: float, round_num: int) -> Optional[Proposal]:
        """
        基于观测和当前共识，生成提议。
        消耗能量。如果能量不足，返回 None。
        """
        if not self.alive:
            return None

        cost = self.config.inference_cost
        if not self.wallet.can_afford(cost):
            logger.warning(f"[{self.module_id}] 能量不足，无法推演")
            return None

        # 消耗能量（floor 只标记 struggling，不阻止消费）
        self.wallet.spend(cost, reason=f"推演 round={round_num}", floor=self.config.energy_floor)

        # 施加偏见，生成提议值
        biased_estimate = self.observe(observation)
        self.total_rounds += 1

        # 置信度：挣扎状态降半
        confidence = self._compute_confidence()

        proposal = Proposal(
            module_id=self.module_id,
            value=biased_estimate,
            confidence=confidence,
            reasoning=f"{self.bias_type} 偏见推断, 基于 obs={observation:.2f}",
            energy_cost=cost,
            round_number=round_num,
        )
        self.last_proposal = proposal
        self.history.append(biased_estimate)
        return proposal

    def _compute_confidence(self) -> float:
        """
        计算模块自身置信度，与能量余额正相关。
        v0.2: 挣扎状态置信度降半。
        """
        base = 0.5
        energy_factor = min(self.wallet.balance / self.config.initial_module_energy, 1.0)
        confidence = min(base + 0.3 * energy_factor, 1.0)

        # 挣扎状态 → 置信度降半（不再是僵尸但效能减弱）
        if self.wallet.struggling:
            confidence *= 0.5
            logger.debug(f"[{self.module_id}] 挣扎状态置信度降半: {confidence:.4f}")

        return confidence

    def on_adopted(self, reward: float):
        """被采纳时回调：获得能量奖励"""
        self.wallet.earn(reward, reason="被采纳奖励")
        self.adoption_count += 1

    def on_rejected(self):
        """未被采纳时回调"""
        pass

    def generate_legacy_capsule(self) -> str:
        """
        临终协议：生成不超过1KB的遗产摘要。
        包含模块历史特征、核心观点、与主流共识的分歧。
        """
        if not self.history:
            return f"[{self.module_id}] 空模块, 无历史数据"

        avg_value = sum(self.history) / len(self.history)
        capsule = (
            f"[{self.module_id}/{self.bias_type}] "
            f"avg={avg_value:.2f}, rounds={self.total_rounds}, "
            f"adopted={self.adoption_count}, "
            f"earned={self.wallet.total_earned:.1f}, "
            f"spent={self.wallet.total_spent:.1f}"
        )
        # 确保不超过 capsule_max_size
        if len(capsule.encode('utf-8')) > self.config.capsule_max_size:
            capsule = capsule[:self.config.capsule_max_size]
        self.legacy_capsule = capsule
        logger.info(f"[{self.module_id}] 临终胶囊: {capsule}")
        return capsule

    def kill(self):
        """标记模块死亡"""
        self.alive = False
        self.generate_legacy_capsule()
        logger.info(f"[{self.module_id}] 已死亡, 胶囊已生成")

    # ── v0.5 表达层 ──

    def _expression_templates(self) -> List[str]:
        """返回此偏见类型的表达模板。子类覆盖以提供个性化模板。"""
        return [
            "当前观测 {obs:.2f}，共识 {cs:.2f}，偏差 {dev:.2f}。我认为应当{action}。",
            "数据指向 {obs:.2f}，而共识在 {cs:.2f}。{bias_note}",
            "与共识差距 {dev:.2f}。{stance}",
        ]

    def _expression_context(self, observation: float, current_consensus: float) -> dict:
        """构建表达所需的上下文变量。子类覆盖以提供个性化变量。"""
        deviation = observation - current_consensus
        return {
            "obs": observation,
            "cs": current_consensus,
            "dev": deviation,
            "abs_dev": abs(deviation),
            "action": "观察",
            "bias_note": "",
            "stance": "",
        }

    def express(self, observation: float, current_consensus: float) -> str:
        """
        v0.5: 模块基于当前状态生成一句话自然表达。

        每次调用会：
        1. 用子类的偏见生成上下文变量（含具体数值）
        2. 从模板池中轮换选择（避免重复）
        3. 格式化输出
        """
        ctx = self._expression_context(observation, current_consensus)
        templates = self._expression_templates()
        # 轮换模板，避免重复
        idx = getattr(self, "_expr_counter", 0) % len(templates)
        self._expr_counter = idx + 1
        try:
            return templates[idx].format(**ctx)
        except KeyError:
            return templates[0].format(**ctx)


class AggressiveModule(SubModule):
    """
    激进型 (alpha)
    偏好新数据和新信号，倾向于高估。
    特征：快速反应、大胆推断、容易被采纳但也容易偏移。
    """

    def __init__(self, config: HiveMindConfig):
        wallet = EnergyWallet(
            balance=config.initial_module_energy,
            loan_max=config.innovation_loan_max,
        )
        super().__init__(
            module_id="alpha_aggressive",
            bias_type="aggressive",
            wallet=wallet,
            config=config,
        )

    def observe(self, raw_data: float) -> float:
        """激进型：将观测数据乘以偏向系数，倾向高估"""
        biased = raw_data * self.config.aggressive_bias
        # 激进型更愿意冒险，噪声扰动更大
        noise = random.gauss(0, self.config.observation_noise * 0.3)
        return biased + noise

    # ── v0.5 表达层 ──
    def _expression_context(self, observation, current_consensus):
        deviation = observation - current_consensus
        direction = "上调预估" if observation > current_consensus else "注意回落信号"
        return {
            "obs": observation, "cs": current_consensus,
            "dev": deviation, "abs_dev": abs(deviation),
            "action": f"追逐新信号: {direction}",
            "bias_note": f"我的高估偏向检测到机会（×{self.config.aggressive_bias}）",
            "stance": "建议大胆行动" if abs(deviation) > 3 else "值得关注",
        }

    def _expression_templates(self):
        return [
            "📡 观测 {obs:.1f} vs 共识 {cs:.1f}，偏差 {dev:+.1f}。{bias_note}",
            "⚠️ 信号偏离 {abs_dev:.1f}。{action}。{stance}。",
            "🔺 新数据指向 {obs:.1f}，共识滞后 {abs_dev:.1f}。建议跟上节奏。",
        ]


class ConservativeModule(SubModule):
    """
    保守型 (beta) — v0.2 新增

    锚定共识而非追逐新信号，倾向低估。
    与 alpha 的 1.3x 对称：beta 用 0.7x 做低估锚定。
    特征：稳重、低噪声、维护共识稳定性，是系统的"锚"。

    设计依据：4 组实验确认，缺少保守锚定导致 alpha 必死、gamma 自震荡。
    """

    def __init__(self, config: HiveMindConfig):
        wallet = EnergyWallet(
            balance=config.initial_module_energy,
            loan_max=config.innovation_loan_max,
        )
        super().__init__(
            module_id="beta_conservative",
            bias_type="conservative",
            wallet=wallet,
            config=config,
        )

    def observe(self, raw_data: float) -> float:
        """
        保守型：将观测数据乘以保守偏向系数（<1），倾向低估。
        同时锚定到当前共识——保守型更信任"已经验证过的"而非"新的信号"。
        """
        # 低估偏见
        biased = raw_data * self.config.conservative_bias
        # 保守型噪声更低（更谨慎、更稳定）
        noise = random.gauss(0, self.config.observation_noise * 0.1)
        return biased + noise

    def propose(self, observation: float, current_consensus: float, round_num: int) -> Optional[Proposal]:
        """
        保守型提议：锚定共识 + 保守低估。

        beta 的提议不是纯观测，而是：
        1. 自己对观测的保守解读（低估）
        2. 与当前共识做锚定混合——更信任已有共识而非新信号
        这让 beta 成为"锚"，防止 alpha 把共识拉得太远。
        """
        if not self.alive:
            return None

        cost = self.config.inference_cost
        if not self.wallet.can_afford(cost):
            return None

        self.wallet.spend(cost, reason=f"推演 round={round_num}", floor=self.config.energy_floor)
        self.total_rounds += 1

        # 保守型核心逻辑：锚定混合
        # anchor_strength 控制 beta 多信任已有共识 vs 新信号
        # anchor_strength=0.6 → 60%信任共识 + 40%自己的保守解读
        my_estimate = self.observe(observation)  # 保守低估版本
        anchor_strength = self.config.conservative_anchor_strength
        biased_estimate = anchor_strength * current_consensus + (1 - anchor_strength) * my_estimate

        confidence = self._compute_confidence()

        proposal = Proposal(
            module_id=self.module_id,
            value=biased_estimate,
            confidence=confidence,
            reasoning=f"保守锚定, anchor={anchor_strength:.2f}, "
                      f"consensus={current_consensus:.2f}, my={my_estimate:.2f}",
            energy_cost=cost,
            round_number=round_num,
        )
        self.last_proposal = proposal
        self.history.append(biased_estimate)
        return proposal

    # ── v0.5 表达层 ──
    def _expression_context(self, observation, current_consensus):
        deviation = observation - current_consensus
        return {
            "obs": observation, "cs": current_consensus,
            "dev": deviation, "abs_dev": abs(deviation),
            "action": "锚定当前共识" if abs(deviation) < 5 else "微调偏离",
            "bias_note": f"保守锚定（偏向 {self.config.conservative_bias}x，锚力度 {self.config.conservative_anchor_strength}）",
            "stance": "维持稳定" if abs(deviation) < 5 else "需警惕过度波动",
        }

    def _expression_templates(self):
        return [
            "🔒 观测 {obs:.1f} vs 共识 {cs:.1f}。{bias_note}",
            "📉 偏差 {dev:+.1f}，但不急于调整。{action}。{stance}。",
            "🛡️ 共识 {cs:.1f} 尚稳，新信号 {obs:.1f} 不足以动摇。继续锚定。",
        ]


class CounterConsensusModule(SubModule):
    """
    纠错者 (delta) — 反共识
    主动关注异常值与少数派观点，倾向于逆主流而行。
    特征：纠正偏移、发现异常、但容易被忽视。
    """

    def __init__(self, config: HiveMindConfig):
        wallet = EnergyWallet(
            balance=config.initial_module_energy,
            loan_max=config.innovation_loan_max,
        )
        super().__init__(
            module_id="delta_counter",
            bias_type="counter_consensus",
            wallet=wallet,
            config=config,
        )

    def observe(self, raw_data: float) -> float:
        """反共识型：偏离当前共识方向，主动寻找异常"""
        return raw_data  # 基础值不变，偏见在 propose 中施加

    def propose(self, observation: float, current_consensus: float, round_num: int) -> Optional[Proposal]:
        """
        反共识型提议：偏离当前共识方向。
        如果共识偏高了，就往低拉；偏低了就往高拉。
        """
        if not self.alive:
            return None

        cost = self.config.inference_cost
        if not self.wallet.can_afford(cost):
            return None

        self.wallet.spend(cost, reason=f"推演 round={round_num}", floor=self.config.energy_floor)
        self.total_rounds += 1

        # 反共识偏见：将共识向观测方向反向拉回
        drift = current_consensus - observation  # 共识偏离观测的方向
        counter_direction = -drift * self.config.counter_bias_strength  # 反向拉回
        biased_estimate = current_consensus + counter_direction

        # 加入少量随机性
        noise = random.gauss(0, self.config.observation_noise * 0.2)
        biased_estimate += noise

        confidence = self._compute_confidence()

        proposal = Proposal(
            module_id=self.module_id,
            value=biased_estimate,
            confidence=confidence,
            reasoning=f"反共识偏离, consensus={current_consensus:.2f}, counter_shift={counter_direction:.2f}",
            energy_cost=cost,
            round_number=round_num,
        )
        self.last_proposal = proposal
        self.history.append(biased_estimate)
        return proposal

    # ── v0.5 表达层 ──
    def _expression_context(self, observation, current_consensus):
        deviation = observation - current_consensus
        counter_dir = "共识可能偏高, 拉回" if deviation < 0 else "共识可能偏低, 上推"
        return {
            "obs": observation, "cs": current_consensus,
            "dev": deviation, "abs_dev": abs(deviation),
            "action": counter_dir,
            "bias_note": f"反向力度 ×{self.config.counter_bias_strength}，偏移 {deviation:+.1f}",
            "stance": "质疑主流" if abs(deviation) > 5 else "微调方向",
        }

    def _expression_templates(self):
        return [
            "🔍 共识 {cs:.1f} vs 观测 {obs:.1f}，偏移 {dev:+.1f}。{bias_note}",
            "↩️ {action}。{stance}。",
            "❗ 主流通往 {cs:.1f}，但我观测到 {obs:.1f}。差距 {abs_dev:.1f} 值得质疑。",
        ]


class CompositeModule(SubModule):
    """
    外交官 (gamma) — 随机混合策略

    外交官角色：每轮随机选择一种策略（激进/保守/中性），
    概率由 composite_strategy_weights 控制。
    不站队任何一方，而是在 alpha（开拓者）和 beta（守门人）之间随机切换，
    为系统提供"混合视角"与桥梁沟通，防止任何单一偏见主导。
    """

    def __init__(self, config: HiveMindConfig):
        wallet = EnergyWallet(
            balance=config.initial_module_energy,
            loan_max=config.innovation_loan_max,
        )
        super().__init__(
            module_id="gamma_diplomat",
            bias_type="diplomat",
            wallet=wallet,
            config=config,
        )
        # 策略权重：激进 / 保守 / 中性
        self.strategy_weights = config.composite_strategy_weights  # (aggressive_w, conservative_w, neutral_w)
        self.strategy_names = ["aggressive", "conservative", "neutral"]
        self.current_strategy = "neutral"  # v0.5: 供表达层使用

    def observe(self, raw_data: float) -> float:
        """复合型：基础值不变，偏见在 propose 中按策略施加"""
        return raw_data

    def propose(self, observation: float, current_consensus: float, round_num: int) -> Optional[Proposal]:
        """
        复合型提议：每轮随机选择一种策略。

        - aggressive 策略：高估观测值（像 alpha）
        - conservative 策略：低估 + 锚定共识（像 beta）
        - neutral 策略：纯观测值 + 小噪声（独立视角）
        """
        if not self.alive:
            return None

        cost = self.config.inference_cost
        if not self.wallet.can_afford(cost):
            return None

        self.wallet.spend(cost, reason=f"推演 round={round_num}", floor=self.config.energy_floor)
        self.total_rounds += 1

        # 按权重随机选择本轮策略
        strategy = random.choices(
            self.strategy_names,
            weights=self.strategy_weights,
            k=1,
        )[0]
        self.current_strategy = strategy  # v0.5: 供表达层使用

        if strategy == "aggressive":
            # 激进策略：高估，像 alpha
            biased_estimate = observation * self.config.aggressive_bias
            noise = random.gauss(0, self.config.observation_noise * 0.25)
            biased_estimate += noise
            reasoning_tag = "激进混合"

        elif strategy == "conservative":
            # 保守策略：低估 + 锚定，像 beta
            my_low = observation * self.config.conservative_bias
            anchor = self.config.conservative_anchor_strength
            biased_estimate = anchor * current_consensus + (1 - anchor) * my_low
            reasoning_tag = "保守混合"

        else:
            # 中性策略：纯观测 + 小噪声，独立视角
            biased_estimate = observation
            noise = random.gauss(0, self.config.observation_noise * 0.15)
            biased_estimate += noise
            reasoning_tag = "中性独立"

        confidence = self._compute_confidence()

        proposal = Proposal(
            module_id=self.module_id,
            value=biased_estimate,
            confidence=confidence,
            reasoning=f"{reasoning_tag}, strategy={strategy}, "
                      f"obs={observation:.2f}, consensus={current_consensus:.2f}",
            energy_cost=cost,
            round_number=round_num,
        )
        self.last_proposal = proposal
        self.history.append(biased_estimate)
        return proposal

    # ── v0.5 表达层 ──
    def _expression_context(self, observation, current_consensus):
        deviation = observation - current_consensus
        strategy_labels = {
            "aggressive": "激进视角", "conservative": "保守视角", "neutral": "中性视角"
        }
        label = strategy_labels.get(self.current_strategy, "混合视角")
        return {
            "obs": observation, "cs": current_consensus,
            "dev": deviation, "abs_dev": abs(deviation),
            "action": f"采用{label}",
            "bias_note": f"本轮策略: {label}（权重 {self.strategy_weights}）",
            "stance": "综合判断中" if abs(deviation) > 5 else "保持平衡",
        }

    def _expression_templates(self):
        return [
            "🤝 {bias_note}。观测 {obs:.1f} vs 共识 {cs:.1f}。",
            "⚖️ {action}。偏差 {dev:+.1f}，{stance}。",
            "🌐 各模块意见不一。我的{action}指向 {obs:.1f}，共识当前 {cs:.1f}。",
        ]


# ============================================================
#  ε 幸存者 (懒加载) — v0.5 新增
# ============================================================

class SurvivorModule(SubModule):
    """
    幸存者 (epsilon) — v0.5 新增

    懒加载休眠策略：大部分时间低能耗待机，仅在系统需要时唤醒。
    设计理念：
    - 休眠时：极低能耗（10% 正常推演），不参与提案
    - 唤醒条件：好奇心信号 > 阈值 / 系统置信度暴跌 / 外部唤醒
    - 唤醒后：以中性视角提出观察，提供"局外人"视角

    代表 HiveMind 的"储备力量"——平常不占资源，关键时刻出场。
    """

    def __init__(self, config: HiveMindConfig):
        wallet = EnergyWallet(
            balance=config.initial_module_energy,  # 与其他模块一致（非节能模式）
            loan_max=config.innovation_loan_max,
        )
        super().__init__(
            module_id="epsilon_survivor",
            bias_type="survivor",
            wallet=wallet,
            config=config,
        )
        self.sleeping = True       # 初始休眠
        self.sleep_rounds = 0      # 已休眠轮数
        self.wake_rounds = 0       # 唤醒后活跃轮数
        self.max_wake_rounds = 10  # 每次唤醒最多活跃 N 轮后重新评估

    def observe(self, raw_data: float) -> float:
        """幸存者：中性观察，不施加偏见——它是旁观者"""
        noise = random.gauss(0, self.config.observation_noise * 0.1)  # 低噪声
        return raw_data + noise

    def propose(self, observation: float, current_consensus: float, round_num: int) -> Optional[Proposal]:
        """
        幸存者提议：仅在唤醒时参与。

        休眠状态：
        - 消耗极小能量（sleep_cost_ratio × inference_cost）
        - 不生成提案
        - 不断累计休眠轮数

        唤醒后：
        - 以中性视角生成提案
        - 活跃 N 轮后重新评估是否继续醒着
        """
        if not self.alive:
            return None

        # 休眠态：消耗极低能量
        if self.sleeping:
            sleep_cost = self.config.inference_cost * self.config.epsilon_sleep_cost_ratio
            if self.wallet.can_afford(sleep_cost):
                self.wallet.spend(sleep_cost, reason=f"休眠维护 round={round_num}", floor=self.config.energy_floor)
                self.sleep_rounds += 1
            return None

        # 唤醒态：正常参与推演
        cost = self.config.inference_cost
        if not self.wallet.can_afford(cost):
            self.sleeping = True
            logger.info(f"[epsilon] 能量不足，回到休眠")
            return None

        self.wallet.spend(cost, reason=f"推演 round={round_num}", floor=self.config.energy_floor)
        self.total_rounds += 1
        self.wake_rounds += 1

        # 中性提案：离群观测产生局外人视角
        biased_estimate = observation
        noise = random.gauss(0, self.config.observation_noise * 0.15)
        biased_estimate += noise

        confidence = self._compute_confidence()
        # 幸存者基础置信度更低（它不常参与，知识可能过时）
        confidence *= 0.7

        proposal = Proposal(
            module_id=self.module_id,
            value=biased_estimate,
            confidence=confidence,
            reasoning=f"幸存者唤醒提供, sleep_rounds={self.sleep_rounds}, wake_rounds={self.wake_rounds}",
            energy_cost=cost,
            round_number=round_num,
        )
        self.last_proposal = proposal
        self.history.append(biased_estimate)

        # 活跃 N 轮后重新评估
        if self.wake_rounds >= self.max_wake_rounds:
            self.sleeping = True
            self.wake_rounds = 0
            logger.info(f"[epsilon] 活跃 {self.max_wake_rounds} 轮，回到休眠")

        return proposal

    def try_wake(self, curiosity_signal: float) -> bool:
        """
        尝试唤醒：如果好奇心信号超过阈值且能量充足，唤醒模块。

        返回 True 表示已唤醒。
        """
        if not self.alive:
            return False

        if self.sleeping and curiosity_signal >= self.config.epsilon_wake_threshold:
            if self.wallet.balance > self.config.energy_floor * 2:
                self.sleeping = False
                self.wake_rounds = 0
                logger.info(f"[epsilon] 好奇心信号 {curiosity_signal:.3f} 触发唤醒, 休眠 {self.sleep_rounds} 轮")
                return True

        return False

    # ── v0.5 表达层 ──
    def _expression_context(self, observation, current_consensus):
        deviation = observation - current_consensus
        if self.sleeping:
            return {
                "obs": observation, "cs": current_consensus,
                "dev": deviation, "abs_dev": abs(deviation),
                "action": "休眠中",
                "bias_note": f"已休眠 {self.sleep_rounds} 轮，等待唤醒信号",
                "stance": "节能待机",
            }
        return {
            "obs": observation, "cs": current_consensus,
            "dev": deviation, "abs_dev": abs(deviation),
            "action": "局外人观察",
            "bias_note": f"休眠 {self.sleep_rounds} 轮后唤醒，提供独立视角",
            "stance": f"偏差 {abs(deviation):.1f} — 值得注意" if abs(deviation) > 5 else "正常范围内",
        }

    def _expression_templates(self):
        if self.sleeping:
            return [
                "💤 {bias_note}。共识 {cs:.1f}。{stance}。",
                "😴 休眠轮数 {sleep_rounds}。观测 {obs:.1f}，但我不说话。",
            ]
        return [
            "👁️ 局外人视角：观测 {obs:.1f} vs 共识 {cs:.1f}，偏差 {dev:+.1f}。{stance}",
            "🔔 休眠 {sleep_rounds} 轮后唤醒！{bias_note}。",
            "⏰ 终于醒来了。{action}：差距 {abs_dev:.1f}。{stance}",
        ]
