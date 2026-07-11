"""
HiveMind v0.4 - 四模块架构 + 知识蒸馏引擎

基于能量代谢与时间节律的自组织认知系统架构。
v0.1: alpha + gamma (双模块，确认 beta 结构性必需)
v0.2: alpha + beta + gamma (三模块完整架构)
      修复: energy_floor 僵尸 bug + 置信度衰减无效 bug
v0.3: alpha + beta + gamma + delta (四模块架构)
      开拓者 | 守门人 | 外交官 | 纠错者
v0.4: 知识蒸馏引擎
      梦境升级为监督学习训练管道，导出可复用 checkpoint
      特征提取 + 标签生成 + 逻辑回归 mini 模型（零外部依赖）
"""

__version__ = "0.4.0"
