"""Pure Python hourly solar model. Power is MW; one-hour energy is MWh."""

from copy import deepcopy
import math

HOURS = 336
PLANT = {"name": "Fictional Plant A", "acLimitMw": 60, "sections": [
    {"id": "A", "name": "North Field", "acMw": 8},
    {"id": "B", "name": "Ridge West", "acMw": 14},
    {"id": "C", "name": "Ridge East", "acMw": 9},
    {"id": "D", "name": "South Tracker", "acMw": 12},
    {"id": "E", "name": "Pond Row", "acMw": 7},
    {"id": "F", "name": "Substation East", "acMw": 10},
]}
SCENARIOS = [
    {"id": "required-demo", "name": "Required demo: snow gap vs persistent inverter fault", "weather": "mixed-sunny", "issues": {"B": "snow", "D": "inverter"}, "curtailment": False},
    {"id": "healthy-cloudy", "name": "Healthy equipment under cloudy conditions", "weather": "cloudy", "issues": {}, "curtailment": False},
    {"id": "inverter-fault", "name": "Inverter fault", "weather": "sunny", "issues": {"D": "inverter"}, "curtailment": False},
    {"id": "snow-coverage", "name": "Snow coverage", "weather": "mixed-sunny", "issues": {"B": "snow"}, "curtailment": False},
    {"id": "soiling", "name": "Soiling", "weather": "sunny", "issues": {"E": "soiling"}, "curtailment": False},
    {"id": "module-degradation", "name": "Gradual module degradation", "weather": "sunny", "issues": {"C": "degradation"}, "curtailment": False},
    {"id": "grid-curtailment", "name": "Grid curtailment", "weather": "sunny", "issues": {}, "curtailment": True},
]
ACTION_DEFS = {
    "inverter": dict(action="Repair inverter", cost=32000, crewHours=16, delayHours=12, spareParts={"inverterKit": 1}, effectiveness=.97, downtimeHours=4, explanation="Restores most output after a 12-hour completion delay; the final four hours are a zero-output repair outage. Requires one inverter kit."),
    "snow": dict(action="Remove snow", cost=9000, crewHours=12, delayHours=6, spareParts={"inverterKit": 0}, effectiveness=.92, downtimeHours=0, explanation="Clears modules after six hours. Natural shedding continues in both the baseline and plan."),
    "soiling": dict(action="Clean array section", cost=7000, crewHours=10, delayHours=24, spareParts={"inverterKit": 0}, effectiveness=.85, downtimeHours=0, explanation="Recovers 85% of soiling loss after cleaning completes at hour 24."),
    "degradation": dict(action="Inspect degradation", cost=4500, crewHours=8, delayHours=18, spareParts={"inverterKit": 0}, effectiveness=.15, downtimeHours=0, explanation="Preserves the original assumed 15% loss recovery from inspection and minor adjustment; this is synthetic, not an established inspection benefit."),
    "ambiguous": dict(action="Inspect section", cost=3500, crewHours=6, delayHours=24, spareParts={"inverterKit": 0}, effectiveness=0, downtimeHours=0, explanation="Collects evidence; no energy recovery is assumed over this horizon."),
}
DEFAULT_CONSTRAINTS = dict(budget=45000, crewHours=22, inverterSpares=1)


def clamp(value, low, high):
    return max(low, min(high, value))


def hash_string(text):
    value = 2166136261
    for char in text:
        value = ((value ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return value


def seeded_random(seed):
    value = seed & 0xFFFFFFFF
    while True:
        value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
        yield value / 4294967296


def cloud_multiplier(weather, hour, random):
    day, hod = divmod(hour, 24)
    if weather == "cloudy":
        return clamp(.38 + .18 * math.sin(day * 1.7 + hod * .4) + (random - .5) * .12, .18, .72)
    if weather == "mixed-sunny":
        if day == 0:
            return clamp(.42 + (random - .5) * .1, .26, .55)
        if 1 <= day <= 5:
            return clamp(.92 + (random - .5) * .08, .82, 1)
        return clamp(.72 + .18 * math.sin(day + hod) + (random - .5) * .08, .48, 1)
    return clamp(.9 + .08 * math.sin(day * .8 + hod * .2) + (random - .5) * .05, .78, 1)


def natural_snow_factor(hour):
    return .08 if hour < 18 else .35 if hour < 30 else .78 if hour < 42 else 1


def issue_factor(issue, hour):
    return {"inverter": .05, "snow": natural_snow_factor(hour), "soiling": .86,
            "degradation": .94 - .00035 * hour}.get(issue, 1)


def healthy_power(ac_mw, sunlight, temperature):
    return clamp(ac_mw * sunlight * clamp(1 - .004 * (temperature - 25), .85, 1.08), 0, ac_mw)


def validate_inputs(plant, constraints=None, payment_rate=115):
    if not math.isfinite(plant["acLimitMw"]) or plant["acLimitMw"] <= 0:
        raise ValueError("Plant AC limit must be positive and finite.")
    if len(plant["sections"]) != 6 or {s["id"] for s in plant["sections"]} != set("ABCDEF"):
        raise ValueError("Keep six sections with IDs A through F.")
    for section in plant["sections"]:
        if not isinstance(section["name"], str) or not section["name"].strip() or not math.isfinite(section["acMw"]) or section["acMw"] <= 0:
            raise ValueError("Each section needs a name and positive, finite AC capacity.")
    if not math.isfinite(payment_rate) or payment_rate < 0:
        raise ValueError("Payment rate must be finite and nonnegative.")
    if constraints:
        if any(not math.isfinite(v) or v < 0 for v in constraints.values()):
            raise ValueError("Resource limits must be finite and nonnegative.")
        if constraints["inverterSpares"] != int(constraints["inverterSpares"]):
            raise ValueError("Spare kits must be a whole number.")


def generate_scenario(scenario_id="required-demo", plant=None, weather=None):
    plant = deepcopy(plant or PLANT)
    validate_inputs(plant)
    scenario = deepcopy(next(s for s in SCENARIOS if s["id"] == scenario_id))
    scenario["weather"] = weather or scenario["weather"]
    if scenario["weather"] not in ("cloudy", "mixed-sunny", "sunny"):
        raise ValueError("Unknown weather profile.")
    random = seeded_random(hash_string(scenario_id))
    hours = []
    for hour in range(HOURS):
        day, hod = divmod(hour, 24)
        daylight = math.sin((hod - 7) / 10 * math.pi) if 7 <= hod <= 17 else 0
        sunlight = daylight * cloud_multiplier(scenario["weather"], hour, next(random))
        ambient = 4 if scenario["weather"] == "cloudy" else (1 + 6 * math.sin(hod / 24 * math.pi) if scenario["weather"] == "mixed-sunny" else 10 + 7 * math.sin(hod / 24 * math.pi))
        temperature = ambient + sunlight * 23
        sections = [{**s, "expectedMw": healthy_power(s["acMw"], sunlight, temperature)} for s in plant["sections"]]
        expected_total = sum(s["expectedMw"] for s in sections)
        scale = min(1, plant["acLimitMw"] / expected_total) if expected_total else 1
        for section in sections:
            section["expectedMw"] *= scale
            section["issue"] = scenario["issues"].get(section["id"], "healthy")
            section["actualBeforeCurtailmentMw"] = section["expectedMw"] * issue_factor(section["issue"], hour)
        cap = 34 if scenario["curtailment"] and 2 <= day <= 5 and 10 <= hod <= 15 else None
        total = sum(s["actualBeforeCurtailmentMw"] for s in sections)
        curtail_scale = min(1, cap / total) if cap is not None and total else 1
        for section in sections:
            section.update(actualMw=section["actualBeforeCurtailmentMw"] * curtail_scale,
                           inverterAlarm=section["issue"] == "inverter",
                           snowObserved=section["issue"] == "snow" and natural_snow_factor(hour) < 1,
                           curtailmentFlag=curtail_scale < 1)
        hours.append(dict(hour=hour, day=day + 1, hourOfDay=hod, sunlightIndex=sunlight,
                          moduleTempC=temperature, curtailmentFlag=curtail_scale < 1,
                          curtailmentCapMw=cap, expectedMw=sum(s["expectedMw"] for s in sections),
                          actualMw=sum(s["actualMw"] for s in sections), sections=sections))
    return dict(scenario=scenario, plant=plant, hours=hours)


def diagnose(dataset):
    diagnostics = []
    for section in dataset["plant"]["sections"]:
        rows = [next(s for s in row["sections"] if s["id"] == section["id"]) for row in dataset["hours"]]
        expected = sum(r["expectedMw"] for r in rows)
        actual = sum(r["actualMw"] for r in rows)
        alarms = sum(r["inverterAlarm"] for r in rows)
        snow = sum(r["snowObserved"] for r in rows)
        curtailment = sum(r["curtailmentFlag"] for r in rows)
        gaps = sum(r["expectedMw"] > .5 and r["expectedMw"] - r["actualMw"] > r["acMw"] * .08 for r in rows)
        issue = dataset["scenario"]["issues"].get(section["id"])
        confidence = "High"
        if alarms:
            cause, action, evidence = "Inverter fault", "inverter", [f"{alarms} inverter alarm hours"]
        elif snow:
            cause, action, evidence = "Snow coverage", "snow", [f"{snow} snow observation hours"]
        elif issue == "soiling":
            cause, action, evidence = "Soiling", "soiling", ["Output is persistently below expected with soiling inspection tag"]
        elif issue == "degradation":
            cause, action, evidence = "Gradual module degradation", "degradation", ["Small persistent loss with degradation inspection tag"]
        elif curtailment and gaps:
            cause, action, evidence = "Grid curtailment", "none", [f"{curtailment} curtailment flag hours"]
        elif gaps:
            cause, action, confidence = "Ambiguous loss; inspect", "ambiguous", "Low"
            evidence = ["Output gap exists without alarm, snow, soiling tag, degradation tag, or curtailment flag"]
        else:
            cause, action, evidence = "No material loss", "none", ["No sustained daylight gap"]
        if curtailment and action != "none":
            evidence.append("Only recovery that can pass the grid cap is valued")
        diagnostics.append(dict(sectionId=section["id"], sectionName=section["name"], acMw=section["acMw"],
                                cause=cause, confidence=confidence, actionType=action, expectedMwh=expected,
                                actualMwh=actual, gapMwh=max(0, expected - actual),
                                currentGapMw=max(0, rows[12]["expectedMw"] - rows[12]["actualMw"]), evidence=evidence))
    return diagnostics


def build_candidates(diagnostics):
    return [dict(id=f'{d["sectionId"]}-{d["actionType"]}', sectionId=d["sectionId"],
                 sectionName=d["sectionName"], cause=d["cause"], currentGapMw=d["currentGapMw"],
                 **deepcopy(ACTION_DEFS[d["actionType"]])) for d in diagnostics if d["actionType"] != "none"]


def action_factor(action, issue, hour):
    base = issue_factor(issue, hour)
    completion = action["delayHours"]
    if completion - action.get("downtimeHours", 0) <= hour < completion:
        return 0
    if hour < completion:
        return base
    if issue == "snow":
        return min(1, max(base, action["effectiveness"]))
    return min(1, base + (1 - base) * action["effectiveness"])


def resources(actions):
    return dict(spend=sum(a["cost"] for a in actions), crewHours=sum(a["crewHours"] for a in actions),
                inverterKits=sum(a["spareParts"].get("inverterKit", 0) for a in actions))


def feasible(actions, constraints):
    used = resources(actions)
    return (used["spend"] <= constraints["budget"] and used["crewHours"] <= constraints["crewHours"]
            and used["inverterKits"] <= constraints["inverterSpares"])


def simulate_plan(dataset, actions, payment_rate):
    if len({a["sectionId"] for a in actions}) != len(actions):
        raise ValueError("Choose at most one action per section; recovery cannot be counted twice.")
    by_section = {a["sectionId"]: a for a in actions}
    baseline_mwh = plan_mwh = excluded = 0.0
    hourly = []
    for row in dataset["hours"]:
        baseline_before = sum(s["actualBeforeCurtailmentMw"] for s in row["sections"])
        plan_before = 0.0
        for section in row["sections"]:
            action = by_section.get(section["id"])
            if action and (action["effectiveness"] > 0 or action.get("downtimeHours", 0) > 0):
                issue = dataset["scenario"]["issues"].get(section["id"], "healthy")
                plan_before += section["expectedMw"] * action_factor(action, issue, row["hour"])
            else:
                plan_before += section["actualBeforeCurtailmentMw"]
        # None means no grid cap; a zero-MW cap must remain zero.
        grid_cap = row["curtailmentCapMw"]
        cap = min(dataset["plant"]["acLimitMw"], grid_cap if grid_cap is not None else math.inf)
        baseline = min(baseline_before, cap)
        plan = min(plan_before, cap)
        baseline_mwh += baseline
        plan_mwh += plan
        excluded += max(0, max(0, plan_before - baseline_before) - max(0, plan - baseline))
        hourly.append(dict(hour=row["hour"], baselineMw=baseline, planMw=plan, incrementalMwh=plan - baseline))
    recovered = plan_mwh - baseline_mwh
    used = resources(actions)
    revenue = recovered * payment_rate
    return dict(actions=actions, baselineMwh=baseline_mwh, planMwh=plan_mwh, recoveredMwh=recovered,
                excludedCurtailmentMwh=excluded, **used, revenue=revenue,
                netBenefit=revenue - used["spend"], hourly=hourly)


def optimize(dataset, candidates, constraints, payment_rate):
    best = simulate_plan(dataset, [], payment_rate)
    for mask in range(1, 2 ** len(candidates)):
        selected = [a for i, a in enumerate(candidates) if mask & (1 << i)]
        if feasible(selected, constraints):
            result = simulate_plan(dataset, selected, payment_rate)
            if (result["netBenefit"], result["recoveredMwh"]) > (best["netBenefit"], best["recoveredMwh"]):
                best = result
    return best


def evaluate(dataset, constraints=None, payment_rate=115, candidates=None):
    constraints = dict(constraints or DEFAULT_CONSTRAINTS)
    validate_inputs(dataset["plant"], constraints, payment_rate)
    diagnostics = diagnose(dataset)
    candidates = build_candidates(diagnostics) if candidates is None else candidates
    gap_actions = []
    for candidate in sorted(candidates, key=lambda a: -a["currentGapMw"]):
        if feasible(gap_actions + [candidate], constraints):
            gap_actions.append(candidate)
    return dict(dataset=dataset, diagnostics=diagnostics, candidates=candidates, constraints=constraints,
                paymentRate=payment_rate, noIntervention=simulate_plan(dataset, [], payment_rate),
                gapPlan=simulate_plan(dataset, gap_actions, payment_rate),
                optimizedPlan=optimize(dataset, candidates, constraints, payment_rate))

