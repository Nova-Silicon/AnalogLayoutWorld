from eda.source_suites.release_nmos_ldo_suite import NmosLdo

def create_suite(root, reference=False):
    return NmosLdo(source_path=root / "upstream/verify.py", reference=False)
