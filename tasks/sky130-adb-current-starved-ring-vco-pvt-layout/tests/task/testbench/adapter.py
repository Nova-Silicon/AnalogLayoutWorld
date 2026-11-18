from eda.source_suites.additional_suites import RingVco

def create_suite(root, reference=False):
    return RingVco(source_path=root / "upstream/verify.py", reference=False)
