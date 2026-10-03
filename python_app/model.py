"""Pure Python hourly solar model. Power is MW; one-hour energy is MWh."""

from copy import deepcopy
import math

HOURS = 336
OBSERVATION_HOURS = 13  # Intervals 00:00-13:00; decisions start at 13:00.
DEFAULT_DEGRADATION_LOSS_PCT = 6.0
DEFAULT_SNOW_CLEARANCE_HOURS = 24.0
NET_BENEFIT_TOLERANCE = 1e-6  # Dollars, not MWh.
MULTI_FAULT_OPTIONS = dict(budget=64000, crewHours=32, inverterSpares=2,
                          paymentRate=115, snowClearanceHours=96)
PLANT = {"name": "Fictional Plant A", "acLimitMw": 60, "sections": [
    {"id": "A", "name": "North Field", "acMw": 8},
    {"id": "B", "name": "Ridge West", "acMw": 14},
    {"id": "C", "name": "Ridge East", "acMw": 9},
    {"id": "D", "name": "South Tracker", "acMw": 12},
    {"id": "E", "name": "Pond Row", "acMw": 7},
    {"id": "F", "name": "Substation East", "acMw": 10},
]}
SCENARIOS = [
    {"id": "required-demo", "name": "Required demo: snow gap vs persistent inverter fault", "weather": "mixed-sunny"},
    {"id": "healthy-cloudy", "name": "Healthy equipment under cloudy conditions", "weather": "cloudy"},
    {"id": "inverter-fault", "name": "Inverter fault", "weather": "sunny"},
    {"id": "snow-coverage", "name": "Snow coverage", "weather": "mixed-sunny"},
    {"id": "soiling", "name": "Soiling", "weather": "sunny"},
    {"id": "module-degradation", "name": "Existing module degradation", "weather": "sunny"},
    {"id": "grid-curtailment", "name": "Grid curtailment", "weather": "sunny"},
    {"id": "multi-fault-demo", "name": "Multi-fault demo: greedy vs better combination", "weather": "mixed-sunny"},
]
# Synthetic ground truth is used only to generate observations and forecast output.
_CONDITIONS = {"required-demo": {"B": "snow", "D": "inverter"},
               "inverter-fault": {"D": "inverter"}, "snow-coverage": {"B": "snow"},
               "soiling": {"E": "soiling"}, "module-degradation": {"C": "degradation"},
               "multi-fault-demo": {"B": "snow", "A": "inverter", "D": "inverter"}}
ACTION_DEFS = {
    "inverter": dict(action="Repair inverter", cost=32000, crewHours=16, delayHours=12, spareParts={"inverterKit": 1}, effectiveness=.97, downtimeHours=4, explanation="Restores most output after a 12-hour completion delay; the final four hours are a zero-output repair outage. Requires one inverter kit."),
    "snow": dict(action="Remove snow", cost=9000, crewHours=12, delayHours=6, spareParts={"inverterKit": 0}, effectiveness=.92, downtimeHours=0, explanation="Clears modules after six hours. Natural shedding continues in both the baseline and plan."),
    "soiling": dict(action="Clean array section", cost=7000, crewHours=10, delayHours=24, spareParts={"inverterKit": 0}, effectiveness=.85, downtimeHours=0, explanation="Recovers 85% of soiling loss after cleaning completes at hour 24."),
    "degradation": dict(action="Inspect degradation", cost=4500, crewHours=8, delayHours=18, spareParts={"inverterKit": 0}, effectiveness=0, downtimeHours=0, explanation="Gathers information, with zero immediate energy recovery. Information value is not quantified by this prototype."),
    "ambiguous": dict(action="Inspect section", cost=3500, crewHours=6, delayHours=24, spareParts={"inverterKit": 0}, effectiveness=0, downtimeHours=0, explanation="Gathers information, with zero immediate energy recovery. Information value is not quantified by this prototype."),
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


def natural_snow_factor(hour, clearance_hours=DEFAULT_SNOW_CLEARANCE_HOURS):
    """Linear output-factor rise from 8% at decision to 100% at clearance."""
    if not math.isfinite(clearance_hours) or clearance_hours < 0:
        raise ValueError("Snow clearance must be finite and nonnegative.")
    if clearance_hours == 0:
        return 1.0
    return .08 + .92 * clamp(hour / clearance_hours, 0, 1)


def issue_factor(issue, hour, degradation_loss_pct, clearance_hours):
    return {"inverter": .05, "snow": natural_snow_factor(hour, clearance_hours), "soiling": .86,
            "degradation": 1 - degradation_loss_pct / 100}.get(issue, 1)


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


def generate_scenario(scenario_id="required-demo", plant=None, weather=None,
                      degradation_loss_pct=DEFAULT_DEGRADATION_LOSS_PCT,
                      snow_clearance_hours=DEFAULT_SNOW_CLEARANCE_HOURS):
    plant = deepcopy(plant or PLANT)
    validate_inputs(plant)
    scenario = deepcopy(next(s for s in SCENARIOS if s["id"] == scenario_id))
    observed_weather = scenario["weather"]
    scenario["weather"] = weather or observed_weather
    if scenario["weather"] not in ("cloudy", "mixed-sunny", "sunny"):
        raise ValueError("Unknown weather profile.")
    if not math.isfinite(degradation_loss_pct) or not 0 <= degradation_loss_pct <= 100:
        raise ValueError("Existing degradation loss must be between 0 and 100 percent.")
    natural_snow_factor(0, snow_clearance_hours)
    conditions = _CONDITIONS.get(scenario_id, {})
    history, hours = [], []
    random = seeded_random(hash_string(scenario_id))
    for absolute_hour in range(OBSERVATION_HOURS + HOURS):
        historical = absolute_hour < OBSERVATION_HOURS
        hour = absolute_hour - OBSERVATION_HOURS
        day, hod = divmod(absolute_hour, 24)
        profile = observed_weather if historical else scenario["weather"]
        daylight = math.sin((hod - 7) / 10 * math.pi) if 7 <= hod <= 17 else 0
        sunlight = daylight * cloud_multiplier(profile, absolute_hour, next(random))
        ambient = 4 if profile == "cloudy" else (1 + 6 * math.sin(hod / 24 * math.pi) if profile == "mixed-sunny" else 10 + 7 * math.sin(hod / 24 * math.pi))
        temperature = ambient + sunlight * 23
        sections = [{**s, "expectedMw": healthy_power(s["acMw"], sunlight, temperature)} for s in plant["sections"]]
        expected_total = sum(s["expectedMw"] for s in sections)
        scale = min(1, plant["acLimitMw"] / expected_total) if expected_total else 1
        for section in sections:
            section["expectedMw"] *= scale
            condition = conditions.get(section["id"], "healthy")
            # Historical snow evidence is fixed; future clearance is an assumption.
            factor = .08 if historical and condition == "snow" else issue_factor(condition, hour, degradation_loss_pct, snow_clearance_hours)
            section["actualBeforeCurtailmentMw"] = section["expectedMw"] * factor
        grid_event = (historical or 2 <= day <= 5) and 10 <= hod <= 15
        cap = 34 if scenario_id == "grid-curtailment" and grid_event else None
        total = sum(s["actualBeforeCurtailmentMw"] for s in sections)
        curtail_scale = min(1, cap / total) if cap is not None and total else 1
        for section in sections:
            section["actualMw"] = section["actualBeforeCurtailmentMw"] * curtail_scale
            if historical:
                condition = conditions.get(section["id"], "healthy")
                section.update(inverterAlarm=condition == "inverter", snowObserved=condition == "snow",
                               inspectionEvidence=condition if condition in ("soiling", "degradation") else None,
                               curtailmentFlag=curtail_scale < 1)
                # Observation records contain measured evidence, never latent labels.
                section.pop("actualBeforeCurtailmentMw")
        record = dict(hour=hour, absoluteHour=absolute_hour, day=day + 1, hourOfDay=hod, sunlightIndex=sunlight,
                          moduleTempC=temperature, curtailmentFlag=curtail_scale < 1,
                          curtailmentCapMw=cap, expectedMw=sum(s["expectedMw"] for s in sections),
                          actualMw=sum(s["actualMw"] for s in sections), sections=sections)
        (history if historical else hours).append(record)
    return dict(scenario=scenario, plant=plant, hours=hours,
                observations=dict(plant=deepcopy(plant), decisionHour=OBSERVATION_HOURS, hours=history),
                assumptions=dict(degradationLossPct=degradation_loss_pct, snowClearanceHours=snow_clearance_hours,
                                 forecastWeather=scenario["weather"], observedWeather=observed_weather))


def diagnose(observations):
    """Read only the observation view, filtering out records after decision time."""
    observed_hours = [r for r in observations["hours"] if r["absoluteHour"] < observations["decisionHour"]]
    if not observed_hours:
        raise ValueError("Diagnosis requires observations before the decision time.")
    observed_hours.sort(key=lambda r: r["absoluteHour"])
    diagnostics = []
    for section in observations["plant"]["sections"]:
        rows = [next(s for s in row["sections"] if s["id"] == section["id"]) for row in observed_hours]
        expected = sum(r["expectedMw"] for r in rows)
        actual = sum(r["actualMw"] for r in rows)
        alarms = sum(r["inverterAlarm"] for r in rows)
        snow = sum(r["snowObserved"] for r in rows)
        curtailment = sum(r["curtailmentFlag"] for r in rows)
        gaps = sum(r["expectedMw"] > .5 and r["expectedMw"] - r["actualMw"] > r["acMw"] * .08 for r in rows)
        tags = {r.get("inspectionEvidence") for r in rows}
        unexplained_gaps = any(r["expectedMw"] > .5 and r["expectedMw"] - r["actualMw"] > r["acMw"] * .08
                               and not r["curtailmentFlag"] for r in rows)
        confidence = "High"
        if alarms:
            cause, action, evidence = "Inverter fault", "inverter", [f"{alarms} inverter alarm hours"]
        elif snow:
            cause, action, evidence = "Snow coverage", "snow", [f"{snow} snow observation hours"]
        elif "soiling" in tags:
            cause, action, evidence = "Soiling", "soiling", ["Output is persistently below expected with soiling inspection tag"]
        elif "degradation" in tags:
            cause, action, evidence = "Existing module degradation", "degradation", ["Historical inspection evidence of existing degradation"]
        elif curtailment and gaps and not unexplained_gaps:
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
                                currentGapMw=max(0, rows[-1]["expectedMw"] - rows[-1]["actualMw"]), evidence=evidence))
    return diagnostics


def build_candidates(diagnostics):
    return [dict(id=f'{d["sectionId"]}-{d["actionType"]}', sectionId=d["sectionId"],
                 sectionName=d["sectionName"], cause=d["cause"], currentGapMw=d["currentGapMw"],
                 actionType=d["actionType"], **deepcopy(ACTION_DEFS[d["actionType"]])) for d in diagnostics if d["actionType"] != "none"]


def action_factor(action, base, hour):
    completion = action["delayHours"]
    if completion - action.get("downtimeHours", 0) <= hour < completion:
        return 0
    if hour < completion:
        return base
    if action["actionType"] == "snow":
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
                base = section["actualBeforeCurtailmentMw"] / section["expectedMw"] if section["expectedMw"] else 1
                plan_before += section["expectedMw"] * action_factor(action, base, row["hour"])
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


def profit_screened_gap_first(dataset, candidates, constraints, payment_rate,
                              tolerance=NET_BENEFIT_TOLERANCE):
    """Greedy action selection by observed gap, screened on combined-plan value."""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Net-benefit tolerance must be finite and nonnegative.")
    current = simulate_plan(dataset, [], payment_rate)
    decisions = []
    ordered = sorted(candidates, key=lambda a: (-a["currentGapMw"], a["sectionId"], a["id"]))
    for candidate in ordered:
        proposed_actions = current["actions"] + [candidate]
        used = resources(proposed_actions)
        reasons = []
        if used["spend"] > constraints["budget"]:
            reasons.append("Combined spending exceeds the maintenance budget.")
        if used["crewHours"] > constraints["crewHours"]:
            reasons.append("Combined crew-hours exceed the total allowance.")
        if used["inverterKits"] > constraints["inverterSpares"]:
            reasons.append("Combined inverter kit requirements exceed available spares.")
        if any(a["sectionId"] == candidate["sectionId"] for a in current["actions"]):
            reasons.append("An action is already selected for this section.")
        decision = dict(actionId=candidate["id"], sectionId=candidate["sectionId"],
                        currentGapMw=candidate["currentGapMw"], accepted=False,
                        currentNetBenefit=current["netBenefit"], proposedNetBenefit=None,
                        marginalNetBenefit=None, reasons=reasons)
        if not reasons:
            proposed = simulate_plan(dataset, proposed_actions, payment_rate)
            marginal = proposed["netBenefit"] - current["netBenefit"]
            decision.update(proposedNetBenefit=proposed["netBenefit"], marginalNetBenefit=marginal)
            if marginal > tolerance:
                decision["accepted"] = True
                reasons.append("Combined-plan marginal net benefit exceeds the numerical tolerance.")
                current = proposed
            else:
                reasons.append("Combined-plan marginal net benefit does not exceed the numerical tolerance.")
        decisions.append(decision)
    return dict(current, decisions=decisions, netBenefitTolerance=tolerance)


def evaluate(dataset, constraints=None, payment_rate=115, candidates=None):
    constraints = dict(constraints or DEFAULT_CONSTRAINTS)
    validate_inputs(dataset["plant"], constraints, payment_rate)
    diagnostics = diagnose(dataset["observations"])
    candidates = build_candidates(diagnostics) if candidates is None else candidates
    return dict(dataset=dataset, diagnostics=diagnostics, candidates=candidates, constraints=constraints,
                paymentRate=payment_rate, noIntervention=simulate_plan(dataset, [], payment_rate),
                gapPlan=profit_screened_gap_first(dataset, candidates, constraints, payment_rate),
                optimizedPlan=optimize(dataset, candidates, constraints, payment_rate))
