from eda.source_suites.release_fd_miller_suite import FdMiller


class PublicFdMiller(FdMiller):
    """Use the sampling grids in the frozen public examples for acceptance.

    The original source's full-matrix fixtures and base adapter are preserved.
    Those older full-matrix runs used a different grid and are not evidence
    for these three public examples.
    """

    def deck(self, case, design, model):
        text, raw = super().deck(case, design, model)
        if case["id"] in {"op_ac__tt__1.8__27", "op_ac__ss__1.62__125"}:
            assert "ac dec 50 10 10G" in text
            text = text.replace("ac dec 50 10 10G", "ac dec 100 10 10G")
        elif case["id"] == "noise__ff__1.98__-40":
            assert "noise v(voutp,voutn) VNOISE dec 50 10 15Meg" in text
            text = text.replace(
                "noise v(voutp,voutn) VNOISE dec 50 10 15Meg",
                "noise v(voutp,voutn) VNOISE dec 40 10 15Meg",
            )
        return text, raw


def create_suite(root, reference=False):
    return PublicFdMiller(source_path=root / "upstream/verify.py", reference=False)
