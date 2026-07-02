"""
HiveMind v0.3 - 四模块架构原型

基于能量代谢与时间节律的自组织认知系统架构。
v0.1: alpha + gamma (双模块，确认 beta 结构性必需)
v0.2: alpha + beta + gamma (三模块完整架构)
      修复: energy_floor 僵尸 bug + 置信度衰减无效 bug
v0.3: alpha + beta + gamma + delta (四模块架构)
      开拓者 | 守门人 | 外交官 | 纠错者
      gamma 外交官：随机混合策略（30%激进/30%保守/40%中性）
      delta 纠错者：反共识纠正偏移
"""

__version__ = "0.3.0"
