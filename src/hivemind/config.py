"""
HiveMind MVP 配置参数

所有可调参数集中定义，方便实验调参。
"""

from dataclasses import dataclass, field


@dataclass
class HiveMindConfig:
    """HiveMind 全局配置"""

    # ── 能量经济学 ──
    total_energy_budget: float = 1000.0        # 系统总能量预算
    initial_module_energy: float = 100.0       # 每个子模块初始能量
    inference_cost: float = 5.0                # 每次推演消耗能量
    adoption_reward: float = 15.0              # 被采纳获得的能量奖励
    communication_cost: float = 1.0            # 通信消耗
    innovation_loan_max: float = 50.0          # 创新借贷上限
    innovation_loan_rounds: int = 5            # 借贷必须在N轮内证明回报
    energy_floor: float = 10.0                # 能量地板（模块余额不低于此值，防完全破产）

    # ── 共识与置信度 ──
    confidence_decay_rate: float = 0.02        # 每轮置信度衰减率
    fallback_threshold: float = 0.3            # 保底触发阈值（置信度低于此值触发影子候选）
    shadow_parallel_rounds: int = 5            # 影子候选并行推演轮数
    interpolation_rate: float = 0.2            # 影子→主流线性插值速率

    # ── 保底机制 ──
    reactivation_interval: int = 10            # 低优先级内容每N轮重新激活
    random_reactivation_prob: float = 0.1      # 随机采样重新激活概率

    # ── 梦境机制 ──
    dream_trigger_threshold: float = 0.5       # 系统僵化检测阈值（共识变化率低于此值触发）
    dream_cost_ratio: float = 0.3              # 梦境推演成本比例（相对于正常推演）
    dream_rounds: int = 3                      # 每次梦境持续轮数
    counterfactual_mix_prob: float = 0.5       # 反事实杂交概率

    # ── 知识蒸馏 (v0.4 新增) ──
    distill_enabled: bool = True               # 是否启用知识蒸馏引擎
    distill_min_samples: int = 50              # 最少样本数才触发蒸馏
    distill_learning_rate: float = 0.05        # 蒸馏模型学习率
    distill_epochs: int = 200                  # 每次蒸馏训练轮数
    distill_label_threshold: float = 0.15      # 标签生成阈值（提案误差 / 目标值的比例）
    distill_export_interval: int = 500         # 每隔 N 轮导出一次 checkpoint
    distill_model_version: str = "0.4"         # 模型版本号

    # ── 临终协议 ──
    death_energy_threshold: float = 0.0        # 能量低于此值触发临终
    capsule_max_size: int = 1024               # 临终胶囊最大字节数（1KB）
    fossil_age_threshold: int = 50             # 知识条目超过N轮未更新视为"认知化石"

    # ── 仿真参数 ──
    max_rounds: int = 200                      # 最大推演轮数
    target_value: float = 50.0                 # 仿真目标值（系统试图逼近的真值）
    observation_noise: float = 10.0            # 观测噪声标准差

    # ── 子模块特性 ──
    aggressive_bias: float = 1.3               # 激进型偏向系数（>1 表示倾向高估）
    conservative_bias: float = 0.7             # 保守型偏向系数（<1 表示倾向低估）— v0.2 新增
    conservative_anchor_strength: float = 0.6  # 保守型锚定共识力度（0-1，越高越信任共识）— v0.2 新增
    counter_bias_strength: float = 0.8         # 反共识型反向力度（δ）

    # ── 复合型模块 (γ) — v0.3 新增 ──
    composite_strategy_weights: tuple = (0.3, 0.3, 0.4)  # (aggressive, conservative, neutral) 策略权重

    # ── 懒加载模块 (ε) — v0.5 新增 ──
    epsilon_sleep_cost_ratio: float = 0.1      # 休眠能耗比例（正常推演的 10%）
    epsilon_wake_threshold: float = 0.3        # 唤醒阈值（好奇心信号超过此值唤醒）

    # ── 好奇心与主动交互 — v0.5 新增 ──
    curiosity_threshold: float = 0.25          # 好奇心触发阈值（|obs-consensus| / |consensus|）
    interaction_confidence_threshold: float = 0.4  # 低置信触发询问的阈值
    interaction_energy_surplus_ratio: float = 1.5  # 能量盈余触发探索的倍数
    expression_enabled: bool = True            # 是否启用模块表达层

    # ── 日志 ──
    log_level: str = "INFO"                    # 日志级别
    log_file: str = ""                         # 日志文件路径（空则stdout）
