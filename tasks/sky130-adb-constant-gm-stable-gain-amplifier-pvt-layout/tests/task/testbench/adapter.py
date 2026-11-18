from eda.source_suites.constant_gm_suite import ConstantGm

def create_suite(root, reference=False):
    return ConstantGm(source_path=root / "upstream/verify.py", reference=False)
