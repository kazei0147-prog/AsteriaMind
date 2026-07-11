"""
HiveMind MVP 仿真入口

运行 +1/-1 模块最小可行原型，观察能量消耗曲线、共识收敛、保底触发等。
"""

import json
import logging
import sys
from pathlib import Path

# Ensure hivemind package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hivemind.config import HiveMindConfig
from hivemind.mother import MotherModule


def setup_logging(config: HiveMindConfig):
    """配置日志"""
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(config.log_file) if config.log_file else logging.StreamHandler(sys.stdout),
        ],
    )


def run_mvp(config: HiveMindConfig, output_dir: str = "./output") -> dict:
    """
    运行 MVP 仿真并保存结果。

    Args:
        config: HiveMind 配置
        output_dir: 输出目录

    Returns:
        仿真最终摘要
    """
    setup_logging(config)

    logger = logging.getLogger("hivemind.runner")
    logger.info("=" * 60)
    logger.info("HiveMind MVP 仿真启动")
    logger.info("=" * 60)
    logger.info(f"目标值: {config.target_value}")
    logger.info(f"总能量预算: {config.total_energy_budget}")
    logger.info(f"模块初始能量: {config.initial_module_energy}")
    logger.info(f"推演消耗: {config.inference_cost}")
    logger.info(f"采纳奖励: {config.adoption_reward}")
    logger.info(f"最大轮数: {config.max_rounds}")
    logger.info("=" * 60)

    # 创建母模块
    mother = MotherModule(config)

    # 运行仿真
    all_logs = mother.run_simulation()

    # 生成最终摘要
    summary = mother.final_summary()

    # 保存结果
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 保存逐轮日志
    with open(output_path / "round_logs.json", "w", encoding="utf-8") as f:
        json.dump(all_logs, f, indent=2, ensure_ascii=False)

    # 保存最终摘要
    with open(output_path / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # v0.4：导出蒸馏检查点
    if config.distill_enabled:
        distill_path = output_path / "distilled_model.json"
        mother.export_distillation_checkpoint(str(distill_path))
        logger.info(f"蒸馏检查点已导出: {distill_path}")

    logger.info("=" * 60)
    logger.info("仿真完成 - 关键指标:")
    logger.info(f"  最终共识值: {summary['final_consensus']:.4f}")
    logger.info(f"  目标值: {summary['target_value']:.4f}")
    logger.info(f"  最终误差: {summary['final_error']:.4f}")
    logger.info(f"  最终置信度: {summary['final_confidence']:.4f}")
    logger.info(f"  保底触发次数: {summary['fallback_count']}")
    logger.info(f"  梦境触发次数: {summary['dream_count']}")
    logger.info(f"  模块死亡数: {summary['death_count']}")
    logger.info(f"  存活模块数: {summary['alive_modules']}")
    logger.info("=" * 60)

    # 打印模块临终胶囊（如果有）
    for mid, mdata in summary["module_summaries"].items():
        logger.info(f"  [{mid}] alive={mdata['alive']}, capsule={mdata.get('legacy_capsule', 'N/A')}")

    return summary


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="HiveMind MVP 仿真")
    parser.add_argument("--rounds", type=int, default=200, help="推演轮数")
    parser.add_argument("--target", type=float, default=50.0, help="目标值")
    parser.add_argument("--energy-budget", type=float, default=1000.0, help="系统总能量预算")
    parser.add_argument("--module-energy", type=float, default=100.0, help="模块初始能量")
    parser.add_argument("--inference-cost", type=float, default=5.0, help="推演消耗")
    parser.add_argument("--adoption-reward", type=float, default=15.0, help="采纳奖励")
    parser.add_argument("--noise", type=float, default=10.0, help="观测噪声")
    parser.add_argument("--energy-floor", type=float, default=10.0, help="能量地板")
    parser.add_argument("--decay-rate", type=float, default=0.02, help="置信度衰减率")
    parser.add_argument("--output", type=str, default="./output", help="输出目录")
    parser.add_argument("--log-level", type=str, default="INFO", help="日志级别")

    args = parser.parse_args()

    config = HiveMindConfig(
        max_rounds=args.rounds,
        target_value=args.target,
        total_energy_budget=args.energy_budget,
        initial_module_energy=args.module_energy,
        inference_cost=args.inference_cost,
        adoption_reward=args.adoption_reward,
        observation_noise=args.noise,
        energy_floor=args.energy_floor,
        confidence_decay_rate=args.decay_rate,
        log_level=args.log_level,
    )

    summary = run_mvp(config, args.output)

    # 输出简洁结果到 stdout
    print(f"\n{'=' * 40}")
    print(f"HiveMind MVP 仿真结果")
    print(f"{'=' * 40}")
    print(f"最终共识: {summary['final_consensus']:.4f}")
    print(f"目标值:   {summary['target_value']:.4f}")
    print(f"误差:     {summary['final_error']:.4f}")
    print(f"保底触发: {summary['fallback_count']}")
    print(f"梦境触发: {summary['dream_count']}")
    print(f"模块死亡: {summary['death_count']}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
