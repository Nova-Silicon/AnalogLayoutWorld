from eda.source_suites.release_reference_suites import BetaMultiplier

def create_suite(root, reference=False):
    return BetaMultiplier(source_path=root / "upstream/verify.py", reference=False)
