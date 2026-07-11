"""
知识蒸馏引擎 - HiveMind 自我训练核心

v0.4 新增：将模块提案历史蒸馏为可复用轻量决策模型。

三层架构：
  1. 特征提取 — 从模块历史中提取密集特征向量
  2. 标签生成 — 基于"提案是否接近真值"生成监督信号
  3. 模型训练 — 纯 Python 逻辑回归，零外部依赖，模型仅 ~KB 级别

蒸馏产物（DistilledModel）可导出为 JSON checkpoint，下次冷启动直接加载。
"""

import math
import random
import json
import logging
from typing import List, Optional, Tuple

from .submodule import SubModule
from .config import HiveMindConfig

logger = logging.getLogger("hivemind.distill")


# ============================================================
#  特征工程
# ============================================================

def extract_features(module: SubModule, current_consensus: float) -> List[float]:
    """
    从单个模块的当前状态提取特征向量（8 维）。

    特征设计原则：只使用 runtime 可获取的信息，不依赖 oracle（target）。
    """
    if not module.history:
        return [0.0] * 8

    recent_n = min(20, len(module.history))
    recent = module.history[-recent_n:]

    # 1. bias_type 编码（one-hot 的四档映射）
    bias_map = {"aggressive": 1.0, "conservative": -1.0, "counter_consensus": -0.5, "diplomat": 0.5}
    f_bias = bias_map.get(module.bias_type, 0.0)

    # 2. 能量健康度
    f_energy = min(module.wallet.balance / module.config.initial_module_energy, 2.0)

    # 3. 近期被采纳率
    f_adopt_rate = module.adoption_count / max(module.total_rounds, 1)

    # 4. 提案与当前共识的偏差
    last_val = module.history[-1] if module.history else 0.0
    f_consensus_delta = (last_val - current_consensus) / max(abs(current_consensus), 0.01)

    # 5. 近期提案波动性（标准差）
    avg = sum(recent) / len(recent)
    variance = sum((x - avg) ** 2 for x in recent) / len(recent)
    f_volatility = math.sqrt(variance) / max(abs(avg), 0.01)

    # 6. 挣扎标志
    f_struggling = 1.0 if module.wallet.struggling else 0.0

    # 7. 近期平均提案值（归一化）
    f_avg_recent = avg / 100.0  # 假设值域大致在 0-100

    # 8. 偏见强度（提案 vs 原始观测的反推）
    # 用历史均值 / 共识均值估算偏见幅度
    if module.config.target_value > 0:
        f_bias_magnitude = abs(avg - module.config.target_value) / module.config.target_value
    else:
        f_bias_magnitude = 0.0

    features = [
        f_bias,
        f_energy,
        f_adopt_rate,
        f_consensus_delta,
        f_volatility,
        f_struggling,
        f_avg_recent,
        f_bias_magnitude,
    ]

    # 防御：NaN → 0
    features = [0.0 if math.isnan(x) else x for x in features]
    # 防御：爆炸值裁剪
    features = [max(-5.0, min(5.0, x)) for x in features]

    return features


def compute_label(proposal_value: float, target_value: float, threshold_ratio: float = 0.15) -> float:
    """
    基于提案与真值的距离生成标签。

    标签 = sigmoid 平滑而不是硬 0/1，让梯度更好。
    距离越小 → 标签越接近 1（好提案）。
    """
    error = abs(proposal_value - target_value)
    threshold = max(abs(target_value) * threshold_ratio, 1.0)
    # sigmoid 平滑：error=0 → label≈1, error=threshold → label≈0.5, error>threshold → label→0
    label = 2.0 / (1.0 + math.exp(error / (threshold / 3.0))) - 1.0
    return max(0.0, min(1.0, label))


# ============================================================
#  轻量模型（逻辑回归，纯 Python）
# ============================================================

class DistilledModel:
    """
    极轻量逻辑回归模型。

    设计约束：
    - 零外部依赖（不用 sklearn / numpy）
    - 训练速度优先于精度（几百轮内完成）
    - 导出为纯 JSON（<10KB）
    """

    def __init__(self, n_features: int = 8, name: str = "hivemind-distilled"):
        self.n_features = n_features
        self.name = name
        self.weights = [0.0] * n_features
        self.bias = 0.0
        self.trained_epochs = 0
        self.training_loss: List[float] = []
        self.feature_names = [
            "bias_type", "energy_health", "adoption_rate",
            "consensus_delta", "volatility", "struggling",
            "avg_recent", "bias_magnitude",
        ]

    def _sigmoid(self, z: float) -> float:
        """sigmoid 激活，防溢出"""
        if z > 20:
            return 1.0
        if z < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def predict(self, features: List[float]) -> float:
        """前向传播：sigmoid(w·x + b)"""
        z = self.bias
        for w, x in zip(self.weights, features):
            z += w * x
        return self._sigmoid(z)

    def predict_batch(self, X: List[List[float]]) -> List[float]:
        """批量预测"""
        return [self.predict(x) for x in X]

    def train(
        self,
        X: List[List[float]],
        y: List[float],
        lr: float = 0.05,
        epochs: int = 200,
        verbose: bool = False,
    ) -> dict:
        """
        批量梯度下降训练。

        参数：
        - X: 特征矩阵 [n_samples, n_features]
        - y: 标签向量 [n_samples]
        - lr: 学习率
        - epochs: 训练轮数
        """
        n = len(X)
        if n == 0 or len(X[0]) != self.n_features:
            return {"error": "数据维度不匹配", "n": n, "n_features": len(X[0]) if X else 0}

        losses = []
        for epoch in range(epochs):
            # 前向
            total_loss = 0.0
            dw = [0.0] * self.n_features
            db = 0.0

            for xi, yi in zip(X, y):
                y_pred = self.predict(xi)
                error = y_pred - yi
                total_loss += error ** 2

                # 梯度：∂L/∂w_j = 2 * (y_pred - y) * y_pred * (1 - y_pred) * x_j
                grad_factor = 2.0 * error * y_pred * (1.0 - y_pred)
                for j in range(self.n_features):
                    dw[j] += grad_factor * xi[j]
                db += grad_factor

            # 平均梯度
            for j in range(self.n_features):
                dw[j] /= n
            db /= n

            # 更新
            for j in range(self.n_features):
                self.weights[j] -= lr * dw[j]
            self.bias -= lr * db

            avg_loss = total_loss / n
            losses.append(avg_loss)

            if verbose and (epoch % 50 == 0 or epoch == epochs - 1):
                logger.info(f"  epoch {epoch:4d}/{epochs}  loss={avg_loss:.6f}")

        self.trained_epochs += epochs
        self.training_loss = losses

        return {
            "n_samples": n,
            "epochs": epochs,
            "final_loss": losses[-1],
        }

    def export(self) -> dict:
        """导出模型为 JSON 可序列化字典"""
        return {
            "name": self.name,
            "version": "v0.4",
            "n_features": self.n_features,
            "feature_names": self.feature_names,
            "weights": self.weights,
            "bias": self.bias,
            "trained_epochs": self.trained_epochs,
            "final_loss": self.training_loss[-1] if self.training_loss else None,
        }

    def load(self, data: dict):
        """从 export() 产出的字典恢复模型"""
        self.name = data.get("name", self.name)
        self.n_features = data["n_features"]
        self.feature_names = data.get("feature_names", self.feature_names)
        self.weights = data["weights"]
        self.bias = data["bias"]
        self.trained_epochs = data.get("trained_epochs", 0)

    def feature_importance(self) -> List[Tuple[str, float]]:
        """返回特征重要性（权重绝对值排序）"""
        pairs = [(self.feature_names[i], abs(self.weights[i])) for i in range(self.n_features)]
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs

    def summary(self) -> str:
        """人类可读摘要"""
        lines = [
            f"DistilledModel: {self.name}",
            f"  features={self.n_features}, epochs={self.trained_epochs}",
            f"  loss={self.training_loss[-1]:.6f}" if self.training_loss else "  loss=N/A",
            "  feature_importance:",
        ]
        for name, imp in self.feature_importance():
            lines.append(f"    {name:20s} → {imp:.4f}")
        return "\n".join(lines)


# ============================================================
#  蒸馏引擎
# ============================================================

class DistillationEngine:
    """
    知识蒸馏引擎。

    生命周期：
    1. record() → 每轮仿真积累训练样本
    2. distill() → 梦境内触发训练
    3. export_checkpoint() / load_checkpoint() → 持久化

    训练样本 = (特征向量, 标签)：
    - 特征：从模块状态提取（extract_features）
    - 标签：提案与目标值的接近程度（compute_label）
    """

    def __init__(self, config: HiveMindConfig):
        self.config = config
        self.training_data: List[Tuple[List[float], float]] = []
        self.model: Optional[DistilledModel] = DistilledModel(
            n_features=8,
            name=f"hivemind-v{config.distill_model_version}",
        )
        self.distill_count: int = 0
        self.export_count: int = 0
        self.checkpoints: List[dict] = []

    def record(
        self,
        module: SubModule,
        proposal_value: float,
        current_consensus: float,
    ):
        """
        记录一轮提案的特征和标签。

        在每轮仿真结束后调用，积累训练数据。
        """
        features = extract_features(module, current_consensus)
        label = compute_label(proposal_value, self.config.target_value, self.config.distill_label_threshold)
        self.training_data.append((features, label))

    def has_enough_data(self) -> bool:
        """是否有足够数据开始蒸馏"""
        return len(self.training_data) >= self.config.distill_min_samples

    def distill(self, force: bool = False) -> Optional[dict]:
        """
        执行知识蒸馏：用累积数据训练 mini 模型。

        返回训练结果摘要，失败返回 None。
        """
        if not force and not self.has_enough_data():
            logger.debug(f"蒸馏跳过：样本不足 ({len(self.training_data)} < {self.config.distill_min_samples})")
            return None

        X = [f for f, _ in self.training_data]
        y = [l for _, l in self.training_data]

        result = self.model.train(
            X, y,
            lr=self.config.distill_learning_rate,
            epochs=self.config.distill_epochs,
            verbose=True,
        )
        self.distill_count += 1

        logger.info(
            f"蒸馏完成: samples={len(X)}, "
            f"epochs={self.config.distill_epochs}, "
            f"final_loss={result.get('final_loss', 'N/A'):.6f}"
        )
        return result

    def export_checkpoint(self) -> dict:
        """导出当前模型为 checkpoint"""
        ckpt = self.model.export()
        ckpt["distill_count"] = self.distill_count
        ckpt["n_training_samples"] = len(self.training_data)
        self.checkpoints.append(ckpt)
        self.export_count += 1
        return ckpt

    def load_checkpoint(self, data: dict):
        """从 checkpoint 恢复模型"""
        self.model.load(data)
        self.distill_count = data.get("distill_count", 0)
        logger.info(f"加载蒸馏检查点: {self.model.name}, features={self.model.n_features}")

    def save_checkpoint(self, filepath: str):
        """保存 checkpoint 到文件"""
        ckpt = self.export_checkpoint()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(ckpt, f, indent=2, ensure_ascii=False)
        logger.info(f"蒸馏检查点已保存: {filepath}")

    def load_checkpoint_file(self, filepath: str) -> bool:
        """从文件加载 checkpoint"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.load_checkpoint(data)
            return True
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"加载检查点失败: {e}")
            return False

    def predict_module_trust(self, module: SubModule, current_consensus: float) -> float:
        """
        用蒸馏模型预测模块的"可信度"。

        输出 [0,1]，越高表示模型认为该模块此刻的提案越可能接近真值。
        可用于加权共识聚合。
        """
        features = extract_features(module, current_consensus)
        return self.model.predict(features)

    def summary(self) -> dict:
        """蒸馏引擎状态摘要"""
        return {
            "n_training_samples": len(self.training_data),
            "distill_count": self.distill_count,
            "export_count": self.export_count,
            "model_name": self.model.name,
            "model_epochs": self.model.trained_epochs,
            "model_loss": self.model.training_loss[-1] if self.model.training_loss else None,
            "feature_importance": self.model.feature_importance(),
        }
