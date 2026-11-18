from eda.source_suites.additional_suites import Divider2

def create_suite(root, reference=False):
    return Divider2(source_path=root / "upstream/verify.py", reference=False)
