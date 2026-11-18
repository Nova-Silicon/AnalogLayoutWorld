from eda.source_suites.release_sampling_ota_suites import SamplingGain1

def create_suite(root, reference=False):
    return SamplingGain1(source_path=root / "upstream/verify.py", reference=False)
