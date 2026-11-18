from eda.source_suites.release_reference_suites import PllChargePump

def create_suite(root, reference=False):
    return PllChargePump(source_path=root / "upstream/verify.py", reference=False)
