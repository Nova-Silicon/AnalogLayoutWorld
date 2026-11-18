from eda.source_suites.release_ldo_ota_suite import LdoOta

def create_suite(root, reference=False):
    return LdoOta(source_path=root / "upstream/verify.py", reference=False)
