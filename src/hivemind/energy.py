"""
能量钱包 - HiveMind 能量经济学核心

每个子模块持有独立能量余额。
支出：推演、通信、策略更新。
收入：被母模块采纳获得奖励。

v0.2 修复：energy_floor 不再制造僵尸模块。
- floor 变为"挣扎线"而非"僵尸线"
- 模块可以花到 balance < floor（甚至 0）
- 余额 < floor 时标记 struggling，置信度降半
- 余额 <= death_threshold (0) 时触发临终协议
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger("hivemind.energy")


@dataclass
class EnergyWallet:
    """子模块能量钱包"""

    balance: float = 100.0
    total_earned: float = 0.0
    total_spent: float = 0.0
    loan_balance: float = 0.0          # 创新借贷余额
    loan_rounds_remaining: int = 0     # 借贷剩余轮数
    loan_max: float = 50.0             # 借贷上限
    struggling: bool = False           # 余额低于挣扎线（非僵尸，仍可行动但置信度降半）

    def can_afford(self, cost: float, floor: float = 0.0) -> bool:
        """
        检查余额是否足够支付。

        v0.2 修复：floor 不阻止消费，只标记 struggling 状态。
        模块只要余额 > 0 就可以消费（花到 0 才触发临终）。
        """
        # 余额大于花费 → 可以支付
        if self.balance >= cost:
            return True
        # 余额不够但有借贷空间 → 可以借贷支付
        if self.balance + (self.loan_max - self.loan_balance) >= cost:
            return True
        # 完全不够 → 无法支付
        return False

    def spend(self, cost: float, reason: str = "", floor: float = 0.0) -> bool:
        """
        消耗能量。如果余额不足但有借贷额度，自动触发借贷。

        v0.2 修复：floor 参数只用于标记 struggling，不阻止消费。
        余额 < floor → struggling=True（置信度降半）
        余额 <= 0 → is_dead=True（触发临终协议）
        """
        # 余额够 → 直接扣
        if self.balance >= cost:
            self.balance -= cost
            self.total_spent += cost
            # 检查挣扎线
            self._check_struggling(floor)
            logger.debug(f"能量支出 {cost:.1f} ({reason}), 余额 {self.balance:.1f}")
            return True

        # 余额不够 → 借贷补足
        shortfall = cost - self.balance
        if self.loan_balance + shortfall <= self.loan_max:
            # 先用余额
            self.total_spent += self.balance
            remaining_cost = shortfall
            self.balance = 0.0
            # 借贷补足
            self.loan_balance += remaining_cost
            self.total_spent += remaining_cost
            self.loan_rounds_remaining = 5
            self._check_struggling(floor)
            logger.info(f"触发创新借贷 {remaining_cost:.1f}, 借贷余额 {self.loan_balance:.1f}")
            return True

        # 完全无法支付
        logger.warning(f"能量不足! 需要 {cost:.1f}, 余额 {self.balance:.1f}, 借贷 {self.loan_balance:.1f}")
        return False

    def _check_struggling(self, floor: float) -> None:
        """检查是否处于挣扎状态（余额低于挣扎线但未死）"""
        self.struggling = self.balance < floor and self.balance > 0
        if self.struggling:
            logger.debug(f"模块进入挣扎状态, 余额 {self.balance:.1f} < floor {floor:.1f}")

    def earn(self, reward: float, reason: str = "") -> None:
        """获得能量奖励"""
        self.balance += reward
        self.total_earned += reward

        # 挣脱挣扎线 → 恢复
        if self.struggling and self.balance >= 10.0:  # 恢复阈值
            self.struggling = False
            logger.info(f"模块脱离挣扎状态, 余额恢复至 {self.balance:.1f}")

        logger.debug(f"能量收入 {reward:.1f} ({reason}), 余额 {self.balance:.1f}")

        # 如果有借贷，优先偿还
        if self.loan_balance > 0 and self.loan_rounds_remaining > 0:
            repayment = min(reward * 0.5, self.loan_balance)  # 50%奖励用于还贷
            self.loan_balance -= repayment
            self.loan_rounds_remaining -= 1
            if self.loan_balance <= 0:
                self.loan_balance = 0
                self.loan_rounds_remaining = 0
                logger.info(f"借贷已全部偿还")

    def tick_loan(self) -> bool:
        """
        每轮调用，递减借贷轮数。
        如果借贷到期未偿还，返回 True 表示需要强制剪枝。
        """
        if self.loan_rounds_remaining > 0:
            self.loan_rounds_remaining -= 1
            if self.loan_rounds_remaining <= 0 and self.loan_balance > 0:
                logger.warning(f"借贷到期未偿还 {self.loan_balance:.1f}, 标记强制剪枝")
                return True  # 需要剪枝
        return False

    def is_dead(self, threshold: float = 0.0) -> bool:
        """检查模块是否已死亡（余额 <= 阈值且无借贷空间）"""
        return self.balance <= threshold and self.loan_balance >= self.loan_max

    def snapshot(self) -> dict:
        """返回钱包状态快照"""
        return {
            "balance": self.balance,
            "total_earned": self.total_earned,
            "total_spent": self.total_spent,
            "loan_balance": self.loan_balance,
            "loan_rounds_remaining": self.loan_rounds_remaining,
            "struggling": self.struggling,
        }
