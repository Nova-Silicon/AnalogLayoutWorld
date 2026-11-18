from eda.source_suites.ota_suites import Ota5

def create_suite(root, reference=False):
    return Ota5(source_path=root / "upstream/verify.py", reference=False)
