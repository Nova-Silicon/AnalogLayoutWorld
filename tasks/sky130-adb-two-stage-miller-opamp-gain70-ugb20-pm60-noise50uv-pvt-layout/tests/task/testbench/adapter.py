from eda.source_suites.ota_suites import Miller70

def create_suite(root, reference=False):
    return Miller70(source_path=root / "upstream/verify.py", reference=False)
