"""Historical conversion checks ONLY: archived pre-update Python assumptions."""

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from legacy_model import (PLANT, DEFAULT_CONSTRAINTS, generate_scenario, evaluate,
                   healthy_power, simulate_plan, feasible, natural_snow_factor, diagnose)

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = json.loads((ROOT / "reference.json").read_text())


class Verification(unittest.TestCase):
    def close(self, actual, expected):
        self.assertTrue(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7), (actual, expected))

    def test_shared_hourly_inputs_and_35_reference_evaluations(self):
        for case in REFERENCE["cases"]:
            dataset = case["dataset"]
            for row in dataset["hours"]:
                raw = [healthy_power(s["acMw"], row["sunlightIndex"], row["moduleTempC"]) for s in row["sections"]]
                scale = min(1, dataset["plant"]["acLimitMw"] / sum(raw)) if sum(raw) else 1
                for power, section in zip(raw, row["sections"]):
                    self.close(power * scale, section["expectedMw"])
            for expected in case["results"]:
                # Use the original zero-outage assumptions for parity only.
                result = evaluate(dataset, expected["constraints"], expected["paymentRate"], expected["candidates"])
                for actual_diag, expected_diag in zip(result["diagnostics"], expected["diagnostics"]):
                    self.assertEqual(actual_diag["cause"], expected_diag["cause"])
                    self.assertEqual(actual_diag["actionType"], expected_diag["actionType"])
                    for key in ("expectedMwh", "actualMwh", "gapMwh", "currentGapMw"):
                        self.close(actual_diag[key], expected_diag[key])
                for name in ("noIntervention", "gapPlan", "optimizedPlan"):
                    actual, original = result[name], expected[name]
                    self.assertEqual([a["id"] for a in actual["actions"]], [a["id"] for a in original["actions"]])
                    for key in ("baselineMwh", "planMwh", "recoveredMwh", "spend", "crewHours", "inverterKits", "revenue", "netBenefit", "excludedCurtailmentMwh"):
                        self.close(actual[key], original[key])

    def test_reproducible_generator(self):
        for case in REFERENCE["cases"]:
            dataset = case["dataset"]
            generated = generate_scenario(dataset["scenario"]["id"])
            self.assertEqual(generated, generate_scenario(dataset["scenario"]["id"]))
            for actual, expected in zip(generated["hours"], dataset["hours"]):
                for key in ("sunlightIndex", "moduleTempC", "expectedMw", "actualMw"):
                    self.close(actual[key], expected[key])
                for a, b in zip(actual["sections"], expected["sections"]):
                    for key in ("expectedMw", "actualMw", "actualBeforeCurtailmentMw"):
                        self.close(a[key], b[key])

    def test_constraints_and_curtailment(self):
        for case in REFERENCE["cases"]:
            for expected in case["results"]:
                result = evaluate(case["dataset"], expected["constraints"])
                for key in ("gapPlan", "optimizedPlan"):
                    plan = result[key]
                    self.assertTrue(feasible(plan["actions"], expected["constraints"]))
                    self.close(plan["recoveredMwh"], plan["planMwh"] - plan["baselineMwh"])
                if not expected["constraints"]["inverterSpares"]:
                    self.assertFalse(any(a["spareParts"]["inverterKit"] for a in result["optimizedPlan"]["actions"]))
                if case["dataset"]["scenario"]["id"] == "grid-curtailment":
                    self.assertEqual(result["candidates"], [])
                    self.assertEqual(result["optimizedPlan"]["recoveredMwh"], 0)

    def test_demo_downtime_and_energy_units(self):
        dataset = REFERENCE["cases"][0]["dataset"]
        result = evaluate(dataset)
        snow, inverter = result["diagnostics"][1], result["diagnostics"][3]
        self.assertGreater(snow["currentGapMw"], inverter["currentGapMw"])
        self.assertEqual([a["id"] for a in result["gapPlan"]["actions"]], ["B-snow"])
        self.assertEqual([a["id"] for a in result["optimizedPlan"]["actions"]], ["D-inverter"])
        self.assertGreater(result["optimizedPlan"]["netBenefit"], result["gapPlan"]["netBenefit"])
        original = REFERENCE["cases"][0]["results"][0]["optimizedPlan"]
        outage_loss = sum(next(s for s in row["sections"] if s["id"] == "D")["actualMw"] for row in dataset["hours"][8:12])
        corrected = result["optimizedPlan"]
        self.close(original["recoveredMwh"] - corrected["recoveredMwh"], outage_loss)
        self.close(original["netBenefit"] - corrected["netBenefit"], outage_loss * 115)
        self.assertTrue(all(r["incrementalMwh"] < 0 for r in corrected["hourly"][8:12]))
        self.close(sum(r["actualMw"] for r in dataset["hours"]), corrected["baselineMwh"])
        self.close(sum(r["incrementalMwh"] for r in corrected["hourly"]), corrected["recoveredMwh"])

    def test_natural_shedding(self):
        self.assertEqual([natural_snow_factor(h) for h in (17, 18, 29, 30, 41, 42)], [.08, .35, .35, .78, .78, 1])
        result = evaluate(generate_scenario("snow-coverage"))
        plan = simulate_plan(result["dataset"], result["candidates"], 115)
        self.assertGreater(plan["recoveredMwh"], 0)
        self.assertTrue(all(abs(r["incrementalMwh"]) < 1e-9 for r in plan["hourly"][42:]))

    def test_caps_and_no_double_counting(self):
        dataset = generate_scenario()
        # Deterministic interacting actions behind one export cap.
        for row in dataset["hours"]:
            row["curtailmentCapMw"] = 5
        result = evaluate(dataset, dict(budget=100000, crewHours=100, inverterSpares=2))
        actions = result["candidates"]
        joint = simulate_plan(dataset, actions, 115)
        singles = sum(simulate_plan(dataset, [a], 115)["recoveredMwh"] for a in actions)
        self.assertLess(joint["recoveredMwh"], singles)
        self.assertTrue(all(r["planMw"] <= 5 for r in joint["hourly"]))
        self.close(joint["recoveredMwh"], joint["planMwh"] - joint["baselineMwh"])
        with self.assertRaises(ValueError):
            simulate_plan(dataset, [actions[0], actions[0]], 115)
        for row in dataset["hours"]:
            row["curtailmentCapMw"] = 0
        zero = simulate_plan(dataset, actions, 115)
        self.assertEqual(zero["planMwh"], 0)
        self.assertEqual(zero["recoveredMwh"], 0)

    def test_edited_capacities_weather_and_ambiguous_evidence(self):
        plant = deepcopy(PLANT)
        for section in plant["sections"]:
            section["acMw"] *= 3
        for weather in ("sunny", "cloudy", "mixed-sunny"):
            dataset = generate_scenario(plant=plant, weather=weather)
            for row in dataset["hours"]:
                self.assertLessEqual(row["expectedMw"], 60 + 1e-9)
                self.assertTrue(all(s["expectedMw"] <= s["acMw"] for s in row["sections"]))
        dataset = generate_scenario("inverter-fault")
        dataset["scenario"]["issues"] = {}
        for row in dataset["hours"]:
            for section in row["sections"]:
                section["inverterAlarm"] = False
        self.assertEqual(diagnose(dataset)[3]["actionType"], "ambiguous")
        ambiguous = evaluate(dataset)
        inspection = simulate_plan(dataset, ambiguous["candidates"], 115)
        self.assertEqual(inspection["recoveredMwh"], 0)
        self.assertEqual(ambiguous["optimizedPlan"]["actions"], [])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Verification)
    run = unittest.TextTestRunner(verbosity=2).run(suite)
    if not run.wasSuccessful():
        raise SystemExit(1)
    dataset = REFERENCE["cases"][0]["dataset"]
    corrected = evaluate(dataset)
    original = REFERENCE["cases"][0]["results"][0]
    lines = ["PASS: 7 verification tests; 35 shared-input JavaScript/Python evaluations.",
             "Original assumptions: generation, actions, costs, resources, energy and benefits match within 1e-7 absolute / 1e-10 relative tolerance.",
             "Required demo (same JavaScript-exported hourly input data):"]
    for name in ("noIntervention", "gapPlan", "optimizedPlan"):
        old, new = original[name], corrected[name]
        lines.append(f'{name}: original {old["recoveredMwh"]:.6f} extra MWh, ${old["netBenefit"]:.2f} net; '
                     f'Python {new["recoveredMwh"]:.6f} extra MWh, ${new["netBenefit"]:.2f} net; '
                     f'actions {[a["id"] for a in new["actions"]]}; spend ${new["spend"]:.0f}.')
    lines.append("Difference: explicit inverter repair downtime; net energy includes lost residual output during hours 8-11.")
    lines.append("Additional regression fixes: a zero-MW grid cap stays zero; zero-effectiveness inspection cannot restore an ambiguous gap.")
    report = "\n".join(lines) + "\n"
    print("Historical conversion checks; not validation of the current model.")
    print(report)

