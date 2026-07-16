"""传感器故障测试 — 验证 HiveMind 的多传感器容错能力"""
import sys, json, os, csv, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hivemind_repo', 'src') if 'hivemind_repo' not in sys.path[0] else '')

# Fix path
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, 'src'))

from hivemind.config import HiveMindConfig
from hivemind.mother import MotherModule
from hivemind.datasource import CSVSource

class FaultTestMother(MotherModule):
    def __init__(self, config, clean_ds, fault_ds, fault_start=300):
        super().__init__(config)
        self.clean_source = clean_ds
        self.fault_source = fault_ds
        self.fault_start = fault_start
        self.datasource = clean_ds

    def _generate_observation(self):
        val = self.clean_source.fetch()
        if val is None:
            val = 420
        return val + random.gauss(0, self.config.observation_noise)

    def _stagger_collection(self):
        latest_obs = self._generate_observation()
        alpha_obs = latest_obs
        beta_obs = self.data_buffer[-2] if len(self.data_buffer) > 1 else latest_obs * 0.7
        gamma_obs = random.choice(self.data_buffer[-3:]) if len(self.data_buffer) > 2 else (self.data_buffer[-1] if self.data_buffer else latest_obs)

        is_fault = self.round_num >= self.fault_start
        if is_fault:
            fault_val = self.fault_source.fetch()
            if fault_val is None:
                fault_val = 300
            delta_obs = fault_val * 0.7 + random.gauss(0, 5)
        else:
            delta_obs = 0.6 * latest_obs + 0.4 * self.data_buffer[-1] if self.data_buffer else latest_obs

        self.data_buffer.append(latest_obs)
        return {
            'alpha_aggressive': alpha_obs,
            'beta_conservative': beta_obs,
            'gamma_diplomat': gamma_obs,
            'delta_counter': delta_obs,
            'epsilon_survivor': latest_obs,
        }

# ── Run test ──
cfg = HiveMindConfig()
cfg.max_rounds = 400
cfg.adoption_reward = 20
cfg.observation_noise = 1.5

data_dir = os.path.join(base, 'experiments', 'data')
clean = CSVSource(os.path.join(data_dir, 'co2_mauna_loa.csv'), loop=False)
fault = CSVSource(os.path.join(data_dir, 'co2_mauna_loa.csv'), loop=False)

m = FaultTestMother(cfg, clean, fault, fault_start=300)
logs = m.run_simulation()
summary = m.final_summary()

# Save
out = os.path.join(base, 'experiments', 'exp11_sensor_fault')
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, 'summary.json'), 'w') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

# Load truth
reader = csv.DictReader(open(os.path.join(data_dir, 'co2_mauna_loa.csv')))
truth = [float(r['value']) for r in reader]

# Metrics
def avg_error(samples):
    errs = []
    for i, l in samples:
        if i < len(truth):
            errs.append(abs(l.get('consensus_value', 0) - truth[i]))
    return sum(errs)/len(errs) if errs else 999

before = [(i, logs[i]) for i in range(0, 300)]
after = [(i, logs[i]) for i in range(300, min(400, len(logs)))]
hm_before = avg_error(before)
hm_after = avg_error(after)

# Moving avg baseline
W = 10
ma_before = sum(abs(sum(truth[i-W:i])/W - truth[i]) for i in range(W, 300)) / (300-W)
ma_after_vals = [abs(sum(truth[i-W:i])/W - truth[i]) for i in range(300, min(400, len(truth)))]
ma_after = sum(ma_after_vals)/len(ma_after_vals) if ma_after_vals else 999

print('='*60)
print('传感器故障测试 — Mauna Loa CO2 (406-432 ppm)')
print('='*60)
print(f'场景: 前300轮正常, 后100轮 delta传感器输出偏低30%')
print()
print(f'{"指标":30s} {"正常(300轮)":>12s} {"故障(100轮)":>12s} {"恶化":>8s}')
print(f'{"-"*30} {"-"*12} {"-"*12} {"-"*8}')
print(f'{"HM 共识误差(ppm)":30s} {hm_before:>11.2f}  {hm_after:>11.2f}  {hm_after-hm_before:>+7.2f}')
print(f'{"移动平均误差(ppm)":30s} {ma_before:>11.2f}  {ma_after:>11.2f}  {ma_after-ma_before:>+7.2f}')
print()
print(f'结论: HM 在故障后 {"仍然优于" if hm_after < ma_after else "劣于"} 移动平均')
print(f'      误差恶化: HM {hm_after-hm_before:+.2f} vs 移动平均 {ma_after-ma_before:+.2f}')
print(f'最终共识: {summary["final_consensus"]:.1f} ppm (真值: {truth[-1]:.1f})')
print(f'存活模块: {summary["alive_modules"]}/5')

result = {
    'test': 'sensor_fault_co2',
    'hm_error_normal': hm_before, 'hm_error_fault': hm_after,
    'ma_error_normal': ma_before, 'ma_error_fault': ma_after,
    'hm_degradation': hm_after-hm_before,
    'ma_degradation': ma_after-ma_before,
    'hm_wins': hm_after < ma_after,
    'final_truth': truth[-1], 'final_consensus': summary['final_consensus'],
}
with open(os.path.join(out, 'comparison.json'), 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(f'\nSaved to {out}/')
