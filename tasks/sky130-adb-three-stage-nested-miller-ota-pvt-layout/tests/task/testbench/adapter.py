from eda.source_suites.release_nested_ota_suite import NestedMiller

def create_suite(root, reference=False):
    return NestedMiller(source_path=root / "upstream/verify.py", reference=False)
