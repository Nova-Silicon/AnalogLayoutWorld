"""Retain the historical 5 uA SFDR case. Evaluation selects the 10 uA SFDR case."""
from eda.source_suites.release_tia_suite import Tia
from eda.source_suites.release_waveform import require_table_axis
from measure_sfdr import measure_sfdr

PUBLIC_SFDR = "sfdr_public5u__tt__27"


class PublicTia(Tia):
    def plan(self):
        return super().plan() + [{
            "id": PUBLIC_SFDR,
            "score_group": "tt__27",
            "analysis": "sfdr",
            "point": ("tt", 27),
            "profile": "tt",
            "input_peak_a": 5e-6,
        }]

    def deck(self, case, design, model):
        if case["id"] != PUBLIC_SFDR:
            return super().deck(case, design, model)
        text = (self.root / "public_sfdr.spi").read_text()
        return text.replace("__MODEL_LIB__", str(model)).replace("__DUT_NETLIST__", str(design)), False

    def analyze(self, case, work, run):
        if case["id"] != PUBLIC_SFDR:
            return super().analyze(case, work, run)
        require_table_axis(work / "sfdr_tt.dat", 10e-9, 170e-9,
                           first_tolerance=20e-12 * 1.01)
        values = measure_sfdr(work / "sfdr_tt.dat", input_peak_a=5e-6)
        return {"analysis": "sfdr", "point": tuple(case["point"]),
                "name": "tt/+27C/1.80V/public-5uA", "public_input_peak_a": 5e-6,
                **values}

    def reduce_selected(self, records, report, plan):
        # AC, noise and SFDR limits are all applied per case by Tia.checks().
        return report

    def original_suite_checks(self, rows, run_summary):
        original = [row for row in rows if "public_input_peak_a" not in row]
        return super().original_suite_checks(original, run_summary)


def create_suite(root, reference=False):
    suite = PublicTia(source_path=root / "upstream/verify.py", reference=False)
    suite.root = root
    return suite
