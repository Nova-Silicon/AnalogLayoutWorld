from eda.source_suites.release_sampling_ota_suites import SamplingGain8

def create_suite(root, reference=False):
    return SamplingGain8(source_path=root / "upstream/verify.py", reference=False)
