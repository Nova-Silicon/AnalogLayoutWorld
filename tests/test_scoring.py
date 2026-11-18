"""Contract and boundary regressions for the fixed paper-v1 score."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analoglayoutworld import scoring


TASK = "sky130-adb-ahuja-compensated-two-stage-load-range-pvt-layout"
MAGIC_TASK = "sky130-adb-buf-ppsf-bs-gain1-sfdr90-layout"


def observations(task: str = TASK) -> dict:
    parameters = scoring.task_parameters(task)
    return {
        "submission_present": True,
        "task_name": task,
        "profile": "full",
        "evaluation_error": False,
        "stages": {
            "drc": {"status": "passed"},
            "lvs": {"status": "passed", "tool_result": {"backend": "klayout"}},
            "area": {"status": "measured", "tool_result": {
                "geometry": {"width_um": 10.0, "height_um": 10.0},
                "raw_area_utilization": parameters["u_target"]}},
            "quality": {"status": "completed", "tool_result": {
                "subscores": {name: {"status": "measured", "value": 1.0}
                              for name in scoring.QUALITY_NAMES},
                "coupling_penalty": {"status": "measured", "value": 0.0},
                "meaningless": {"status": "measured", "value": False}}},
            "pex": {"status": "completed"},
            "postsim": {"status": "completed"},
        },
        "cases": {"pass_fraction": 1.0, "coverage": 1.0, "all_passed": True},
    }


class ScoringContractTests(unittest.TestCase):
    def test_frozen_protocol_parameters_require_an_explicit_version_review(self):
        path = Path(scoring.__file__).with_name("data") / "paper-v1.json"
        expected = "8cb1bc1b25443497c84605ab1a3b66ce5773b99b7ced4adfc6375c7ac9992690"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                         "The fixed paper-v1 parameter artifact changed; review the release version")
        self.assertEqual(scoring.SCORING_CONFIG_SHA256, expected)

    def test_all_40_tasks_use_fixed_global_parameters(self):
        self.assertEqual(len(scoring.TASK_IDS), 40)
        self.assertEqual(len(set(scoring.TASK_IDS)), 40)
        for task in scoring.TASK_IDS:
            with self.subTest(task=task):
                p = scoring.task_parameters(task)
                self.assertEqual(p["gamma"], 2)
                self.assertEqual(p["weights"], {"gds": .1, "lvs": .1, "drc": .1,
                                               "area": .2, "quality": .1, "postsim": .4})
                self.assertEqual(set(p["quality_saturation"]), set(scoring.QUALITY_NAMES))
                self.assertAlmostEqual(sum(p["weights"].values()), 1)

    def test_parameters_are_copies_and_unknown_tasks_are_rejected(self):
        p = scoring.task_parameters(TASK)
        p["weights"]["gds"] = 0
        self.assertEqual(scoring.task_parameters(TASK)["weights"]["gds"], .1)
        for task in (None, "", "not-a-task", "sky130-adb-class-d-halfbridge-eff95-tt-layout"):
            with self.subTest(task=task), self.assertRaises(ValueError):
                scoring.task_parameters(task)

    def test_full_pass_has_six_components_and_protocol_identity(self):
        result = scoring.score_submission(**observations())
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["score_components"], scoring.task_parameters(TASK)["weights"])
        self.assertTrue(result["score_complete"])
        self.assertTrue(result["design_passed"])
        self.assertEqual(result["scoring_version"], scoring.SCORING_VERSION)
        self.assertEqual(result["scoring_config_sha256"], scoring.SCORING_CONFIG_SHA256)

    def test_no_gds_and_lvs_failure_keep_only_earned_basics(self):
        facts = observations()
        facts["submission_present"] = False
        self.assertEqual(scoring.score_submission(**facts)["score"], 0)
        facts["submission_present"] = True
        facts["stages"]["lvs"]["status"] = "failed"
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], .1)
        self.assertTrue(result["score_complete"])
        self.assertFalse(result["bonuses_eligible"])

    def test_drc_failure_does_not_block_other_earned_credit(self):
        facts = observations()
        facts["stages"]["drc"]["status"] = "failed"
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], .9)
        self.assertFalse(result["design_passed"])
        self.assertTrue(result["bonuses_eligible"])

    def test_shape_gate_boundary_and_area_square(self):
        for task in scoring.TASK_IDS:
            with self.subTest(task=task):
                facts = observations(task)
                area = facts["stages"]["area"]["tool_result"]
                area["geometry"] = {"width_um": 10 * scoring.task_parameters(task)["q_max"], "height_um": 10}
                area["raw_area_utilization"] /= 2
                result = scoring.score_submission(**facts)
                self.assertTrue(result["shape_ok"])
                self.assertAlmostEqual(result["score_components"]["area"], .2 * .5 ** 2)
                area["geometry"]["width_um"] += .001
                result = scoring.score_submission(**facts)
                self.assertFalse(result["shape_ok"])
                self.assertEqual(result["score"], .3)
                self.assertTrue(result["score_complete"])
                self.assertFalse(result["bonuses_eligible"])

    def test_low_fill_and_measured_meaningless_keep_basics(self):
        for reason in ("fill", "morphology"):
            facts = observations()
            if reason == "fill":
                facts["stages"]["area"]["tool_result"]["raw_area_utilization"] = .099
            else:
                facts["stages"]["quality"]["tool_result"]["meaningless"]["value"] = True
            with self.subTest(reason=reason):
                result = scoring.score_submission(**facts)
                self.assertEqual(result["score"], .3)
                self.assertTrue(result["score_complete"])

    def test_missing_morphology_does_not_silently_unlock_bonuses(self):
        facts = observations()
        facts["stages"]["quality"]["tool_result"].pop("meaningless")
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], .3)
        self.assertEqual(result["score_pending_reasons"], ["layout_gate"])
        self.assertTrue(result["score_is_lower_bound"])

    def test_three_saturations_preserve_raw_values_and_input(self):
        facts = observations()
        report = facts["stages"]["quality"]["tool_result"]
        levels = scoring.task_parameters(TASK)["quality_saturation"]
        fractions = {"matching": .25, "critical": .5, "power": .75}
        for name in scoring.QUALITY_NAMES:
            report["subscores"][name]["value"] = levels[name] * fractions[name]
        original = deepcopy(facts)
        result = scoring.score_submission(**facts)
        self.assertEqual(facts, original)
        expected = sum(scoring.task_parameters(TASK)["quality_weights"][name] * fractions[name]
                       for name in scoring.QUALITY_NAMES)
        self.assertAlmostEqual(result["score_components"]["quality"], .1 * expected)
        for name in scoring.QUALITY_NAMES:
            item = result["quality_summary"]["subscores"][name]
            self.assertEqual(item["raw"], report["subscores"][name]["value"])
            self.assertAlmostEqual(item["saturated"], fractions[name])

    def test_missing_quality_is_not_reweighted_as_not_applicable(self):
        facts = observations()
        rows = facts["stages"]["quality"]["tool_result"]["subscores"]
        rows["matching"] = {"status": "error", "reason": "test measurement failure"}
        result = scoring.score_submission(**facts)
        self.assertAlmostEqual(result["score"], .96)
        self.assertTrue(result["score_is_lower_bound"])
        self.assertEqual(result["score_pending_reasons"], ["quality"])
        rows["matching"] = {"status": "not_applicable", "reason": "no matching requirement"}
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], 1)
        self.assertTrue(result["score_complete"])

    def test_coupling_applies_after_quality_saturation(self):
        facts = observations()
        report = facts["stages"]["quality"]["tool_result"]
        report["coupling_penalty"]["value"] = .2
        self.assertAlmostEqual(scoring.score_submission(**facts)["score_components"]["quality"], .08)
        report.pop("coupling_penalty")
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score_components"]["quality"], 0)
        self.assertTrue(result["score_is_lower_bound"])

    def test_partial_postsim_keeps_confirmed_passes_with_fixed_denominator(self):
        facts = observations()
        facts["stages"]["postsim"]["status"] = "timeout"
        facts["cases"] = {"pass_fraction": .25, "coverage": .5, "all_passed": False}
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], .7)
        self.assertEqual(result["score_components"]["postsim"], .1)
        self.assertTrue(result["score_is_lower_bound"])
        facts["stages"]["pex"]["status"] = "failed"
        self.assertEqual(scoring.score_submission(**facts)["score_components"]["postsim"], 0)
        facts["cases"]["pass_fraction"] = .75
        with self.assertRaises(ValueError):
            scoring.score_submission(**facts)

    def test_magic_policy_requires_task_backend_and_trusted_invocation(self):
        facts = observations(MAGIC_TASK)
        facts["stages"]["lvs"]["tool_result"]["backend"] = "magic_netgen"
        facts["stages"]["quality"] = {
            "status": "completed", "invocation": {"function": "eda.quality.collect"},
            "tool_result": {"status": "policy_credit", "policy_credit": {
                "id": "magic-netgen-quality-v1", "task_name": MAGIC_TASK,
                "backend": "magic_netgen"},
                "meaningless": {"status": "not_applicable_backend"}}}
        result = scoring.score_submission(**facts)
        self.assertEqual(result["score"], 1)
        self.assertTrue(result["scoring_inputs"]["quality_policy_credit"])
        facts["stages"]["quality"]["invocation"]["function"] = "untrusted.claim"
        result = scoring.score_submission(**facts)
        self.assertFalse(result["scoring_inputs"]["quality_policy_credit"])
        self.assertEqual(result["score"], .3)
        self.assertTrue(result["score_is_lower_bound"])

    def test_invalid_integrity_or_diagnostic_profile_has_no_benchmark_score(self):
        for field, value in (("evaluation_error", True), ("profile", "tt")):
            facts = observations()
            facts[field] = value
            with self.subTest(field=field):
                result = scoring.score_submission(**facts)
                self.assertIsNone(result["score"])
                self.assertFalse(result["score_valid"])
                self.assertFalse(result["design_passed"])

    def test_live_evaluator_rejects_unregistered_parameters_and_fields(self):
        facts = observations()
        p = scoring.task_parameters(TASK)
        p["u_target"] += .01
        with self.assertRaises(ValueError):
            scoring.score_submission(**facts, scoring_parameters=p)
        p = scoring.task_parameters(TASK)
        p["note"] = "unregistered field"
        with self.assertRaises(ValueError):
            scoring.normalize_scoring_parameters(p, TASK)
        facts["unregistered"] = "unexpected"
        with self.assertRaises(TypeError):
            scoring.score_submission(**facts)

    def test_nonfinite_and_boolean_quality_values_are_rejected(self):
        for value in (float("nan"), float("inf"), True, -0.1, 1.1):
            facts = observations()
            facts["stages"]["quality"]["tool_result"]["subscores"]["matching"]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                scoring.score_submission(**facts)

    def test_shape_and_score_use_the_same_task_parameters(self):
        facts = observations()
        area = facts["stages"]["area"]["tool_result"]
        shape = scoring.assess_shape(area, task_name=TASK)
        score = scoring.score_submission(**facts)
        self.assertEqual(shape["shape_ratio"], score["shape_ratio"])
        self.assertEqual(shape["shape_ok"], score["shape_ok"])
        self.assertEqual(shape["scoring_parameters"], score["scoring_parameters"])


if __name__ == "__main__":
    unittest.main()
