from eda.source_suites.release_power_suites import UnregulatedChargePump

def create_suite(root, reference=False):
    return UnregulatedChargePump(source_path=root / "upstream/verify.py", reference=False)
