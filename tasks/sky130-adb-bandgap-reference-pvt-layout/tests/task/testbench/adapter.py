from eda.source_suites.release_bandgap_suite import Bandgap

def create_suite(root, reference=False):
    return Bandgap(source_path=root / "upstream/verify.py", reference=False)
