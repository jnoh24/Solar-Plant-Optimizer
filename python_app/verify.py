"""Current Python correctness tests; no historical fixtures or JavaScript needed."""

from copy import deepcopy
from itertools import combinations
import unittest

from model import (PLANT, SCENARIOS, ACTION_DEFS, DEFAULT_CONSTRAINTS, generate_scenario,
                   evaluate, simulate_plan, diagnose, natural_snow_factor, profit_screened_gap_first,
                   NET_BENEFIT_TOLERANCE, MULTI_FAULT_OPTIONS)


def flat_dataset(hours=48, conditions=None, clearance=24, cap=None):
    """Independent fixture: healthy MW equals AC capacity, without weather variation."""
    conditions = conditions or {}
    plant = deepcopy(PLANT)
    observed = []
    for section in plant["sections"]:
        kind = conditions.get(section["id"], "healthy")
        factor = {"inverter": .05, "snow": .08, "soiling": .86, "degradation": .75}.get(kind, 1)
        observed.append({**section, "expectedMw": section["acMw"], "actualMw": section["acMw"] * factor,
                         "inverterAlarm": kind == "inverter", "snowObserved": kind == "snow",
                         "inspectionEvidence": kind if kind in ("soiling", "degradation") else None,
                         "curtailmentFlag": False})
    rows = []
    for hour in range(hours):
        sections = []
        for section in plant["sections"]:
            kind = conditions.get(section["id"], "healthy")
            snow_factor = 1 if clearance == 0 else min(1, .08 + .92 * hour / clearance)
            factor = {"inverter": .05, "snow": snow_factor, "soiling": .86, "degradation": .75}.get(kind, 1)
            sections.append({**section, "expectedMw": section["acMw"],
                             "actualBeforeCurtailmentMw": section["acMw"] * factor})
        rows.append(dict(hour=hour, absoluteHour=13 + hour, curtailmentCapMw=cap, sections=sections))
    return dict(plant=plant, hours=rows,
                observations=dict(plant=deepcopy(plant), decisionHour=13,
                                  hours=[dict(absoluteHour=12, sunlightIndex=1, moduleTempC=25, sections=observed)]))


class Verification(unittest.TestCase):
    def test_constant_existing_degradation(self):
        for percent in (0, 6, 25, 100):
            dataset = generate_scenario("module-degradation", degradation_loss_pct=percent)
            for row in dataset["hours"]:
                section = row["sections"][2]
                self.assertAlmostEqual(section["actualBeforeCurtailmentMw"], section["expectedMw"] * (1 - percent / 100))
        independent = evaluate(flat_dataset(24, {"C": "degradation"}))
        self.assertEqual(independent["noIntervention"]["baselineMwh"], (51 + 9 * .75) * 24)
        for value in (-1, 101, float("nan")):
            with self.assertRaises(ValueError):
                generate_scenario(degradation_loss_pct=value)

    def test_inspection_zero_recovery(self):
        for kind, section_id in (("degradation", "C"), ("ambiguous", "D")):
            dataset = flat_dataset(24, {section_id: "degradation" if kind == "degradation" else "inverter"})
            if kind == "ambiguous":
                dataset["observations"]["hours"][0]["sections"][3]["inverterAlarm"] = False
            result = evaluate(dataset, dict(budget=100000, crewHours=100, inverterSpares=2), 10000)
            self.assertEqual(result["candidates"][0]["actionType"], kind)
            self.assertEqual(result["candidates"][0]["effectiveness"], 0)
            plan = simulate_plan(dataset, result["candidates"], 10000)
            self.assertEqual(plan["recoveredMwh"], 0)
            self.assertEqual(plan["netBenefit"], -ACTION_DEFS[kind]["cost"])
            self.assertEqual(result["optimizedPlan"]["actions"], [])

    def test_editable_snow_curve_and_credit(self):
        for h, expected in ((0, .08), (2, .54), (4, 1), (10, 1)):
            self.assertAlmostEqual(natural_snow_factor(h, 4), expected)
        self.assertEqual(natural_snow_factor(0, 0), 1)
        self.assertAlmostEqual(natural_snow_factor(336, 672), .54)
        dataset = flat_dataset(6, {"B": "snow"}, clearance=4)
        action = evaluate(dataset)["candidates"][0]
        action["delayHours"] = 1
        plan = simulate_plan(dataset, [action], 115)
        # Hours 1,2,3: 92% after removal vs 31%,54%,77% naturally.
        self.assertAlmostEqual(plan["recoveredMwh"], 14 * (.61 + .38 + .15))
        self.assertTrue(all(r["incrementalMwh"] == 0 for r in plan["hourly"][4:]))
        immediate = evaluate(flat_dataset(24, {"B": "snow"}, clearance=0))
        self.assertEqual(simulate_plan(immediate["dataset"], immediate["candidates"], 115)["recoveredMwh"], 0)
        for clearance in (0, 3, 24, 672):
            result = evaluate(generate_scenario("snow-coverage", snow_clearance_hours=clearance))
            plan = simulate_plan(result["dataset"], result["candidates"], 115)
            self.assertTrue(all(abs(r["incrementalMwh"]) < 1e-8 for r in plan["hourly"] if r["hour"] >= clearance))
            if clearance == 672:
                # At forecast hour 335 (daylight), half the shedding horizon remains.
                section = result["dataset"]["hours"][335]["sections"][1]
                self.assertGreater(section["expectedMw"], 0)
                self.assertAlmostEqual(section["actualBeforeCurtailmentMw"] / section["expectedMw"], .08 + .92 * 335 / 672)
                self.assertGreater(plan["recoveredMwh"], 0)
        with self.assertRaises(ValueError):
            generate_scenario(snow_clearance_hours=-1)

    def test_no_future_information_leakage(self):
        original = generate_scenario("required-demo")
        expected = diagnose(original["observations"])
        poisoned = deepcopy(original)
        poisoned["scenario"] = {"issues": {"A": "degradation"}, "name": "Hidden fault bait"}
        for row in poisoned["hours"]:
            row["sections"] = []
        self.assertEqual(diagnose(poisoned["observations"]), expected)
        for clearance in (0, 672):
            changed = generate_scenario("required-demo", weather="cloudy", snow_clearance_hours=clearance)
            self.assertEqual(changed["observations"], original["observations"])
            self.assertEqual(diagnose(changed["observations"]), expected)
        observation_view = deepcopy(original["observations"])
        future = deepcopy(observation_view["hours"][-1])
        future["absoluteHour"] = observation_view["decisionHour"]
        future["sections"][0].update(inverterAlarm=True, inspectionEvidence="degradation")
        observation_view["hours"].append(future)
        self.assertEqual(diagnose(observation_view), expected)
        for row in original["observations"]["hours"]:
            self.assertTrue(all("issue" not in s for s in row["sections"]))

    def test_diagnosis_requires_historical_evidence(self):
        dataset = flat_dataset(24, {"D": "inverter", "E": "soiling", "C": "degradation"})
        for section in dataset["observations"]["hours"][0]["sections"]:
            section["inverterAlarm"] = False
            section["inspectionEvidence"] = None
            section["issue"] = "soiling"  # Latent labels cannot establish diagnosis.
        diagnostics = diagnose(dataset["observations"])
        for index in (2, 3, 4):
            self.assertEqual(diagnostics[index]["actionType"], "ambiguous")
        dataset["observations"]["hours"][0]["sections"][4]["inspectionEvidence"] = "soiling"
        self.assertEqual(diagnose(dataset["observations"])[4]["actionType"], "soiling")

    def test_repair_downtime_and_energy_units(self):
        result = evaluate(flat_dataset(16, {"D": "inverter"}))
        plan = simulate_plan(result["dataset"], result["candidates"], 115)
        baseline_power = 48 + 12 * .05
        expected_gain = 4 * 12 * .95 * .97 - 4 * 12 * .05
        self.assertAlmostEqual(plan["baselineMwh"], baseline_power * 16)
        self.assertAlmostEqual(plan["recoveredMwh"], expected_gain)
        self.assertAlmostEqual(plan["netBenefit"], expected_gain * 115 - 32000)
        self.assertTrue(all(abs(r["incrementalMwh"] + .6) < 1e-8 for r in plan["hourly"][8:12]))
        self.assertAlmostEqual(sum(r["incrementalMwh"] for r in plan["hourly"]), plan["planMwh"] - plan["baselineMwh"])

    def test_resources_and_profit_screened_gap_first(self):
        dataset = generate_scenario()
        for limits in (dict(budget=0, crewHours=22, inverterSpares=1),
                       dict(budget=45000, crewHours=0, inverterSpares=1),
                       dict(budget=45000, crewHours=22, inverterSpares=0), DEFAULT_CONSTRAINTS):
            result = evaluate(dataset, limits)
            for name in ("optimizedPlan", "gapPlan"):
                plan = result[name]
                self.assertLessEqual(plan["spend"], limits["budget"])
                self.assertLessEqual(plan["crewHours"], limits["crewHours"])
                self.assertLessEqual(plan["inverterKits"], limits["inverterSpares"])
        self.assertEqual(evaluate(dataset, payment_rate=0)["optimizedPlan"]["actions"], [])
        self.assertEqual([a["id"] for a in evaluate(dataset)["gapPlan"]["actions"]], ["D-inverter"])
        self.assertEqual([a["id"] for a in evaluate(dataset)["optimizedPlan"]["actions"]], ["D-inverter"])

    def test_greedy_marginal_shared_export_cap(self):
        dataset = flat_dataset(48, {"B": "inverter", "D": "inverter"}, cap=45)
        limits = dict(budget=100000, crewHours=100, inverterSpares=3)
        result = evaluate(dataset, limits)
        candidates = {a["sectionId"]: a for a in result["candidates"]}
        standalone = simulate_plan(dataset, [candidates["D"]], 115)
        # Baseline 35.3 MW; cap 45 gives 9.7 MW headroom after completion.
        # D alone: 36 hours * 9.7 MWh less 4 hours * 0.6 MWh outage loss.
        self.assertAlmostEqual(standalone["netBenefit"], (36 * 9.7 - 4 * .6) * 115 - 32000)
        self.assertGreater(standalone["netBenefit"], 0)
        greedy = result["gapPlan"]
        self.assertEqual([a["id"] for a in greedy["actions"]], ["B-inverter"])
        decision = greedy["decisions"][1]
        self.assertFalse(decision["accepted"])
        # B already fills the cap; D adds only its outage loss and repair cost.
        self.assertAlmostEqual(decision["marginalNetBenefit"], -4 * .6 * 115 - 32000)
        self.assertGreater(result["optimizedPlan"]["netBenefit"], greedy["netBenefit"])

    def test_greedy_ties_tolerance_duplicates_and_continuation(self):
        dataset = flat_dataset(48, {"B": "inverter", "D": "inverter"})
        limits = dict(budget=100000, crewHours=100, inverterSpares=3)
        candidates = evaluate(dataset, limits)["candidates"]
        for action in candidates:
            action["currentGapMw"] = 1
        forward = profit_screened_gap_first(dataset, candidates, limits, 115)
        reverse = profit_screened_gap_first(dataset, list(reversed(candidates)), limits, 115)
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["decisions"][0]["sectionId"], "B")
        alternate = dict(candidates[0], id="B-inverter-alternate")
        repeated = profit_screened_gap_first(dataset, candidates + [alternate], limits, 115)
        self.assertEqual(len({a["sectionId"] for a in repeated["actions"]}), len(repeated["actions"]))
        self.assertTrue(any("already selected" in " ".join(d["reasons"]) for d in repeated["decisions"]))
        inspection_data = flat_dataset(24, {"C": "degradation"})
        inspection = evaluate(inspection_data)["candidates"][0]
        inspection["cost"] = 0
        zero = profit_screened_gap_first(inspection_data, [inspection], limits, 115)
        self.assertFalse(zero["decisions"][0]["accepted"])
        self.assertEqual(zero["decisions"][0]["marginalNetBenefit"], 0)
        # Exact analytical inverter gain at 16 hours is 41.832 MWh.
        short_data = flat_dataset(16, {"D": "inverter"})
        action = evaluate(short_data)["candidates"][0]
        action["cost"] = 41.832 * 115 - NET_BENEFIT_TOLERANCE / 2
        tiny = profit_screened_gap_first(short_data, [action], limits, 115)
        self.assertFalse(tiny["decisions"][0]["accepted"])
        action["cost"] = 41.832 * 115 - NET_BENEFIT_TOLERANCE * 2
        positive = profit_screened_gap_first(short_data, [action], limits, 115)
        self.assertTrue(positive["decisions"][0]["accepted"])
        demo = evaluate(generate_scenario())
        self.assertFalse(demo["gapPlan"]["decisions"][0]["accepted"])
        self.assertTrue(demo["gapPlan"]["decisions"][1]["accepted"])

    def test_multi_fault_demo_independent_energy_and_subset_values(self):
        options = MULTI_FAULT_OPTIONS
        dataset = generate_scenario("multi-fault-demo", snow_clearance_hours=options["snowClearanceHours"])
        limits = {key: options[key] for key in ("budget", "crewHours", "inverterSpares")}
        result = evaluate(dataset, limits, options["paymentRate"])
        energy = dict(A=0.0, B=0.0, D=0.0)
        # Independently integrate the documented recovery/outage factors against
        # supplied future healthy MW; do not call simulation or factor helpers.
        for row in dataset["hours"]:
            h = row["hour"]
            healthy = {s["id"]: s["expectedMw"] for s in row["sections"]}
            for section in ("A", "D"):
                if h >= 12:
                    energy[section] += healthy[section] * .95 * .97
                elif 8 <= h < 12:
                    energy[section] -= healthy[section] * .05
            if 6 <= h < 96:
                energy["B"] += healthy["B"] * max(0, .92 - (.08 + .92 * h / 96))
        self.assertEqual([a["id"] for a in result["gapPlan"]["actions"]], ["B-snow", "D-inverter"])
        self.assertEqual([a["id"] for a in result["optimizedPlan"]["actions"]], ["A-inverter", "D-inverter"])
        self.assertAlmostEqual(result["gapPlan"]["recoveredMwh"], energy["B"] + energy["D"])
        self.assertAlmostEqual(result["gapPlan"]["netBenefit"], (energy["B"] + energy["D"]) * 115 - 41000)
        self.assertAlmostEqual(result["optimizedPlan"]["recoveredMwh"], energy["A"] + energy["D"])
        self.assertAlmostEqual(result["optimizedPlan"]["netBenefit"], (energy["A"] + energy["D"]) * 115 - 64000)
        self.assertAlmostEqual(result["gapPlan"]["netBenefit"], 57108.62941299107)
        self.assertAlmostEqual(result["optimizedPlan"]["netBenefit"], 81134.28619752836)
        scores = []
        for size in range(4):
            for subset in combinations("ABD", size):
                spend = sum(9000 if s == "B" else 32000 for s in subset)
                crew = sum(12 if s == "B" else 16 for s in subset)
                kits = sum(s != "B" for s in subset)
                if spend <= 64000 and crew <= 32 and kits <= 2:
                    scores.append((sum(energy[s] for s in subset) * 115 - spend, subset))
        self.assertEqual(max(scores)[1], ("A", "D"))
        self.assertGreater(result["gapPlan"]["decisions"][0]["marginalNetBenefit"], NET_BENEFIT_TOLERANCE)
        self.assertIsNone(result["gapPlan"]["decisions"][2]["marginalNetBenefit"])

    def test_discretionary_strategies_satisfy_value_and_resource_invariants(self):
        for scenario in SCENARIOS:
            for clearance in (0, 24, 96, 672):
                dataset = generate_scenario(scenario["id"], snow_clearance_hours=clearance)
                for limits, rate in ((DEFAULT_CONSTRAINTS, 115),
                                     (dict(budget=64000, crewHours=32, inverterSpares=2), 115),
                                     (dict(budget=100000, crewHours=100, inverterSpares=0), 115),
                                     (dict(budget=100000, crewHours=100, inverterSpares=3), 0),
                                     (dict(budget=0, crewHours=0, inverterSpares=0), 115)):
                    result = evaluate(dataset, limits, rate)
                    greedy, optimum = result["gapPlan"], result["optimizedPlan"]
                    for plan in (greedy, optimum):
                        self.assertGreaterEqual(plan["netBenefit"], -NET_BENEFIT_TOLERANCE)
                        self.assertLessEqual(plan["spend"], limits["budget"])
                        self.assertLessEqual(plan["crewHours"], limits["crewHours"])
                        self.assertLessEqual(plan["inverterKits"], limits["inverterSpares"])
                        self.assertEqual(len({a["sectionId"] for a in plan["actions"]}), len(plan["actions"]))
                    self.assertGreaterEqual(optimum["netBenefit"] + NET_BENEFIT_TOLERANCE, greedy["netBenefit"])
                    for decision in greedy["decisions"]:
                        if decision["accepted"]:
                            self.assertGreater(decision["marginalNetBenefit"], NET_BENEFIT_TOLERANCE)
                        if decision["marginalNetBenefit"] is not None:
                            self.assertEqual(decision["accepted"], decision["marginalNetBenefit"] > NET_BENEFIT_TOLERANCE)

    def test_optimizer_against_independent_all_subsets_oracle(self):
        dataset = flat_dataset(48, {"B": "snow", "D": "inverter", "E": "soiling", "C": "degradation"}, cap=50)
        for budget, crew, spares, rate in ((45000, 22, 1, 115), (100000, 100, 3, 115),
                                          (100000, 100, 0, 115), (100000, 100, 3, 0)):
            result = evaluate(dataset, dict(budget=budget, crewHours=crew, inverterSpares=spares), rate)
            candidates = result["candidates"]
            scores = []
            for size in range(len(candidates) + 1):
                for subset in combinations(candidates, size):
                    cost = sum(a["cost"] for a in subset)
                    hours = sum(a["crewHours"] for a in subset)
                    kits = sum(a["spareParts"]["inverterKit"] for a in subset)
                    if cost > budget or hours > crew or kits > spares:
                        continue
                    ids = {a["sectionId"] for a in subset}
                    recovered = 0
                    for h in range(48):
                        snow = min(1, .08 + .92 * h / 24)
                        inverter = 0 if "D" in ids and 8 <= h < 12 else (.05 + .95 * .97 if "D" in ids and h >= 12 else .05)
                        soil = .86 + .14 * .85 if "E" in ids and h >= 24 else .86
                        removed_snow = max(snow, .92) if "B" in ids and h >= 6 else snow
                        # Healthy A+F=18 MW; C=9 MW at 75%, unchanged by inspection.
                        base = 18 + 9 * .75 + 14 * snow + 12 * .05 + 7 * .86
                        planned = 18 + 9 * .75 + 14 * removed_snow + 12 * inverter + 7 * soil
                        recovered += min(planned, 50) - min(base, 50)
                    scores.append((recovered * rate - cost, recovered))
            best = max(scores)
            self.assertAlmostEqual(result["optimizedPlan"]["netBenefit"], best[0])
            self.assertAlmostEqual(result["optimizedPlan"]["recoveredMwh"], best[1])

    def test_export_caps_and_no_double_counting(self):
        dataset = flat_dataset(48, {"B": "snow", "D": "inverter"}, cap=50)
        actions = evaluate(dataset)["candidates"]
        joint = simulate_plan(dataset, actions, 115)
        singles = sum(simulate_plan(dataset, [a], 115)["recoveredMwh"] for a in actions)
        self.assertLess(joint["recoveredMwh"], singles)
        self.assertTrue(all(r["planMw"] <= 50 for r in joint["hourly"]))
        self.assertAlmostEqual(joint["recoveredMwh"], joint["planMwh"] - joint["baselineMwh"])
        with self.assertRaises(ValueError):
            simulate_plan(dataset, [actions[0], actions[0]], 115)
        for row in dataset["hours"]:
            row["curtailmentCapMw"] = 0
        self.assertEqual(simulate_plan(dataset, actions, 115)["recoveredMwh"], 0)
        curtailed = evaluate(generate_scenario("grid-curtailment"))
        self.assertEqual(curtailed["candidates"], [])
        self.assertEqual(curtailed["optimizedPlan"]["recoveredMwh"], 0)

    def test_reproducibility_and_ac_limits(self):
        for scenario in SCENARIOS:
            self.assertEqual(generate_scenario(scenario["id"]), generate_scenario(scenario["id"]))
        plant = deepcopy(PLANT)
        for section in plant["sections"]:
            section["acMw"] *= 3
        for weather in ("sunny", "cloudy", "mixed-sunny"):
            dataset = generate_scenario(plant=plant, weather=weather)
            self.assertEqual(len(dataset["hours"]), 336)
            self.assertEqual(len(dataset["observations"]["hours"]), 13)
            for row in dataset["hours"]:
                self.assertLessEqual(row["expectedMw"], 60 + 1e-9)
                self.assertTrue(all(s["expectedMw"] <= s["acMw"] for s in row["sections"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
