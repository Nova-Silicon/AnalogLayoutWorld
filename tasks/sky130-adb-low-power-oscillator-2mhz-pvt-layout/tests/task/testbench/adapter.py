from eda.source_suites.release_power_suites import LowPowerOscillator

def create_suite(root, reference=False):
    return LowPowerOscillator(source_path=root / "upstream/verify.py", reference=False)
