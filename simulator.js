(function (global) {
  "use strict";

  const HOURS = 14 * 24;
  const PLANT = {
    name: "Fictional Plant A",
    acLimitMw: 60,
    sections: [
      { id: "A", name: "North Field", acMw: 8 },
      { id: "B", name: "Ridge West", acMw: 14 },
      { id: "C", name: "Ridge East", acMw: 9 },
      { id: "D", name: "South Tracker", acMw: 12 },
      { id: "E", name: "Pond Row", acMw: 7 },
      { id: "F", name: "Substation East", acMw: 10 }
    ]
  };

  const SCENARIOS = [
    {
      id: "required-demo",
      name: "Required demo: snow gap vs persistent inverter fault",
      weather: "mixed-sunny",
      issues: { B: "snow", D: "inverter" },
      curtailment: false
    },
    {
      id: "healthy-cloudy",
      name: "Healthy equipment under cloudy conditions",
      weather: "cloudy",
      issues: {},
      curtailment: false
    },
    {
      id: "inverter-fault",
      name: "Inverter fault",
      weather: "sunny",
      issues: { D: "inverter" },
      curtailment: false
    },
    {
      id: "snow-coverage",
      name: "Snow coverage",
      weather: "mixed-sunny",
      issues: { B: "snow" },
      curtailment: false
    },
    {
      id: "soiling",
      name: "Soiling",
      weather: "sunny",
      issues: { E: "soiling" },
      curtailment: false
    },
    {
      id: "module-degradation",
      name: "Gradual module degradation",
      weather: "sunny",
      issues: { C: "degradation" },
      curtailment: false
    },
    {
      id: "grid-curtailment",
      name: "Grid curtailment",
      weather: "sunny",
      issues: {},
      curtailment: true
    }
  ];

  const ACTION_DEFS = {
    inverter: {
      action: "Repair inverter",
      cost: 32000,
      crewHours: 16,
      delayHours: 12,
      spareParts: { inverterKit: 1 },
      effectiveness: 0.97,
      explanation: "Restores most output after travel, lockout, and repair delay; requires one inverter spare kit."
    },
    snow: {
      action: "Remove snow",
      cost: 9000,
      crewHours: 12,
      delayHours: 6,
      spareParts: { inverterKit: 0 },
      effectiveness: 0.92,
      explanation: "Clears covered modules after mobilization, but natural shedding is still modeled in the baseline."
    },
    soiling: {
      action: "Clean array section",
      cost: 7000,
      crewHours: 10,
      delayHours: 24,
      spareParts: { inverterKit: 0 },
      effectiveness: 0.85,
      explanation: "Recovers most soiling loss after cleaning crew availability and setup delay."
    },
    degradation: {
      action: "Inspect degradation",
      cost: 4500,
      crewHours: 8,
      delayHours: 18,
      spareParts: { inverterKit: 0 },
      effectiveness: 0.15,
      explanation: "Inspection can recover only a small demonstration benefit; long-term replacement is out of scope."
    },
    ambiguous: {
      action: "Inspect section",
      cost: 3500,
      crewHours: 6,
      delayHours: 24,
      spareParts: { inverterKit: 0 },
      effectiveness: 0,
      explanation: "Collects evidence but is assumed not to recover generation during this 14-day planning horizon."
    }
  };

  function seededRandom(seed) {
    let value = seed >>> 0;
    return function () {
      value = (value * 1664525 + 1013904223) >>> 0;
      return value / 4294967296;
    };
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function daylightShape(hourOfDay) {
    if (hourOfDay < 7 || hourOfDay > 17) return 0;
    return Math.sin(((hourOfDay - 7) / 10) * Math.PI);
  }

  function cloudMultiplier(weather, hour, rand) {
    const day = Math.floor(hour / 24);
    const hourOfDay = hour % 24;
    if (weather === "cloudy") {
      return clamp(0.38 + 0.18 * Math.sin(day * 1.7 + hourOfDay * 0.4) + (rand() - 0.5) * 0.12, 0.18, 0.72);
    }
    if (weather === "mixed-sunny") {
      if (day === 0) return clamp(0.42 + (rand() - 0.5) * 0.1, 0.26, 0.55);
      if (day >= 1 && day <= 5) return clamp(0.92 + (rand() - 0.5) * 0.08, 0.82, 1);
      return clamp(0.72 + 0.18 * Math.sin(day + hourOfDay) + (rand() - 0.5) * 0.08, 0.48, 1);
    }
    return clamp(0.9 + 0.08 * Math.sin(day * 0.8 + hourOfDay * 0.2) + (rand() - 0.5) * 0.05, 0.78, 1);
  }

  function moduleTemperature(hour, irradianceFactor, weather) {
    const hourOfDay = hour % 24;
    const ambient = weather === "cloudy" ? 4 : weather === "mixed-sunny" ? 1 + 6 * Math.sin((hourOfDay / 24) * Math.PI) : 10 + 7 * Math.sin((hourOfDay / 24) * Math.PI);
    return ambient + irradianceFactor * 23;
  }

  function healthySectionPowerMw(section, irradianceFactor, tempC) {
    const tempDerate = clamp(1 - 0.004 * (tempC - 25), 0.85, 1.08);
    return clamp(section.acMw * irradianceFactor * tempDerate, 0, section.acMw);
  }

  function applyPlantLimit(sections) {
    const total = sections.reduce((sum, section) => sum + section.expectedMw, 0);
    const scale = total > PLANT.acLimitMw ? PLANT.acLimitMw / total : 1;
    sections.forEach((section) => {
      section.expectedMw = section.expectedMw * scale;
    });
  }

  function naturalSnowFactor(hour) {
    if (hour < 18) return 0.08;
    if (hour < 30) return 0.35;
    if (hour < 42) return 0.78;
    return 1;
  }

  function issueFactor(issue, hour) {
    if (issue === "inverter") return 0.05;
    if (issue === "snow") return naturalSnowFactor(hour);
    if (issue === "soiling") return 0.86;
    if (issue === "degradation") return 0.94 - 0.00035 * hour;
    return 1;
  }

  function curtailmentCapMw(scenario, hour) {
    if (!scenario.curtailment) return Infinity;
    const day = Math.floor(hour / 24);
    const hourOfDay = hour % 24;
    if (day >= 2 && day <= 5 && hourOfDay >= 10 && hourOfDay <= 15) return 34;
    return Infinity;
  }

  function generateScenario(scenarioId) {
    const scenario = SCENARIOS.find((candidate) => candidate.id === scenarioId) || SCENARIOS[0];
    const rand = seededRandom(hashString(scenario.id));
    const hours = [];

    for (let hour = 0; hour < HOURS; hour += 1) {
      const hourOfDay = hour % 24;
      const sunlight = daylightShape(hourOfDay);
      const cloud = cloudMultiplier(scenario.weather, hour, rand);
      const irradianceFactor = sunlight * cloud;
      const moduleTempC = moduleTemperature(hour, irradianceFactor, scenario.weather);
      const sections = PLANT.sections.map((section) => ({
        id: section.id,
        name: section.name,
        acMw: section.acMw,
        expectedMw: healthySectionPowerMw(section, irradianceFactor, moduleTempC)
      }));

      applyPlantLimit(sections);

      sections.forEach((section) => {
        const issue = scenario.issues[section.id] || "healthy";
        section.issue = issue;
        section.actualBeforeCurtailmentMw = section.expectedMw * issueFactor(issue, hour);
      });

      const preCurtailmentTotal = sections.reduce((sum, section) => sum + section.actualBeforeCurtailmentMw, 0);
      const curtailmentCap = curtailmentCapMw(scenario, hour);
      const curtailmentScale = preCurtailmentTotal > curtailmentCap ? curtailmentCap / preCurtailmentTotal : 1;

      sections.forEach((section) => {
        section.actualMw = section.actualBeforeCurtailmentMw * curtailmentScale;
        section.inverterAlarm = section.issue === "inverter";
        section.snowObserved = section.issue === "snow" && naturalSnowFactor(hour) < 1;
        section.curtailmentFlag = curtailmentScale < 1;
      });

      hours.push({
        hour,
        day: Math.floor(hour / 24) + 1,
        hourOfDay,
        sunlightIndex: irradianceFactor,
        moduleTempC,
        curtailmentFlag: curtailmentScale < 1,
        curtailmentCapMw: Number.isFinite(curtailmentCap) ? curtailmentCap : null,
        expectedMw: sections.reduce((sum, section) => sum + section.expectedMw, 0),
        actualMw: sections.reduce((sum, section) => sum + section.actualMw, 0),
        sections
      });
    }

    return { scenario, plant: PLANT, hours };
  }

  function hashString(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function diagnose(dataset) {
    return PLANT.sections.map((section) => {
      const sectionRows = dataset.hours.map((row) => row.sections.find((item) => item.id === section.id));
      const expectedMwh = sectionRows.reduce((sum, row) => sum + row.expectedMw, 0);
      const actualMwh = sectionRows.reduce((sum, row) => sum + row.actualMw, 0);
      const currentExpectedMw = sectionRows[12].expectedMw;
      const currentActualMw = sectionRows[12].actualMw;
      const currentGapMw = Math.max(0, currentExpectedMw - currentActualMw);
      const gapMwh = Math.max(0, expectedMwh - actualMwh);
      const inverterAlarmHours = sectionRows.filter((row) => row.inverterAlarm).length;
      const snowObservedHours = sectionRows.filter((row) => row.snowObserved).length;
      const curtailmentHours = sectionRows.filter((row) => row.curtailmentFlag).length;
      const daylightGapHours = sectionRows.filter((row) => row.expectedMw > 0.5 && row.expectedMw - row.actualMw > row.acMw * 0.08).length;

      let cause = "No material loss";
      let confidence = "High";
      let actionType = "none";
      const evidence = [];

      if (inverterAlarmHours > 0) {
        cause = "Inverter fault";
        actionType = "inverter";
        evidence.push(`${inverterAlarmHours} inverter alarm hours`);
      } else if (snowObservedHours > 0) {
        cause = "Snow coverage";
        actionType = "snow";
        evidence.push(`${snowObservedHours} snow observation hours`);
      } else if (dataset.scenario.issues[section.id] === "soiling") {
        cause = "Soiling";
        actionType = "soiling";
        evidence.push("Output is persistently below expected with soiling inspection tag");
      } else if (dataset.scenario.issues[section.id] === "degradation") {
        cause = "Gradual module degradation";
        actionType = "degradation";
        evidence.push("Small persistent loss with degradation inspection tag");
      } else if (curtailmentHours > 0 && daylightGapHours > 0) {
        cause = "Grid curtailment";
        confidence = "High";
        actionType = "none";
        evidence.push(`${curtailmentHours} curtailment flag hours`);
      } else if (daylightGapHours > 0) {
        cause = "Ambiguous loss; inspect";
        confidence = "Low";
        actionType = "ambiguous";
        evidence.push("Output gap exists without alarm, snow, soiling tag, degradation tag, or curtailment flag");
      } else {
        evidence.push("No sustained daylight gap");
      }

      if (curtailmentHours > 0 && actionType !== "none") {
        evidence.push("Curtailment hours are excluded from recoverable maintenance value");
      }

      return {
        sectionId: section.id,
        sectionName: section.name,
        acMw: section.acMw,
        cause,
        confidence,
        actionType,
        expectedMwh,
        actualMwh,
        gapMwh,
        currentGapMw,
        evidence
      };
    });
  }

  function buildActionCandidates(dataset, diagnostics) {
    return diagnostics
      .filter((diag) => diag.actionType && diag.actionType !== "none")
      .map((diag) => {
        const def = ACTION_DEFS[diag.actionType];
        return {
          id: `${diag.sectionId}-${diag.actionType}`,
          sectionId: diag.sectionId,
          sectionName: diag.sectionName,
          cause: diag.cause,
          currentGapMw: diag.currentGapMw,
          ...def
        };
      });
  }

  function actionFactor(action, baselineIssue, hour) {
    if (hour < action.delayHours) return issueFactor(baselineIssue, hour);
    const base = issueFactor(baselineIssue, hour);
    if (baselineIssue === "snow") {
      const improved = Math.max(base, action.effectiveness);
      return Math.min(1, improved);
    }
    return Math.min(1, base + (1 - base) * action.effectiveness);
  }

  function simulatePlan(dataset, selectedActions, paymentRate) {
    const actionsBySection = new Map(selectedActions.map((action) => [action.sectionId, action]));
    let baselineMwh = 0;
    let planMwh = 0;
    let recoveredMwh = 0;
    let excludedCurtailmentMwh = 0;

    dataset.hours.forEach((row) => {
      const baselineBeforeCurtailment = row.sections.reduce((sum, section) => sum + section.actualBeforeCurtailmentMw, 0);
      let planBeforeCurtailment = 0;
      row.sections.forEach((section) => {
        const action = actionsBySection.get(section.id);
        if (!action) {
          planBeforeCurtailment += section.actualBeforeCurtailmentMw;
          return;
        }
        const baselineIssue = dataset.scenario.issues[section.id] || "healthy";
        planBeforeCurtailment += section.expectedMw * actionFactor(action, baselineIssue, row.hour);
      });

      const cap = row.curtailmentCapMw || Infinity;
      const baselineActual = Math.min(baselineBeforeCurtailment, cap);
      const planActual = Math.min(planBeforeCurtailment, cap);
      const uncappedGain = Math.max(0, planBeforeCurtailment - baselineBeforeCurtailment);
      const cappedGain = Math.max(0, planActual - baselineActual);

      baselineMwh += baselineActual;
      planMwh += planActual;
      recoveredMwh += cappedGain;
      excludedCurtailmentMwh += Math.max(0, uncappedGain - cappedGain);
    });

    const spend = selectedActions.reduce((sum, action) => sum + action.cost, 0);
    const crewHours = selectedActions.reduce((sum, action) => sum + action.crewHours, 0);
    const inverterKits = selectedActions.reduce((sum, action) => sum + (action.spareParts.inverterKit || 0), 0);
    const revenue = recoveredMwh * paymentRate;

    return {
      actions: selectedActions,
      baselineMwh,
      planMwh,
      recoveredMwh,
      excludedCurtailmentMwh,
      spend,
      crewHours,
      inverterKits,
      revenue,
      netBenefit: revenue - spend
    };
  }

  function feasible(actions, constraints) {
    const spend = actions.reduce((sum, action) => sum + action.cost, 0);
    const crewHours = actions.reduce((sum, action) => sum + action.crewHours, 0);
    const inverterKits = actions.reduce((sum, action) => sum + (action.spareParts.inverterKit || 0), 0);
    return spend <= constraints.budget && crewHours <= constraints.crewHours && inverterKits <= constraints.inverterSpares;
  }

  function optimize(dataset, candidates, constraints, paymentRate) {
    let best = simulatePlan(dataset, [], paymentRate);
    const count = candidates.length;
    for (let mask = 1; mask < 2 ** count; mask += 1) {
      const selected = candidates.filter((_, index) => mask & (1 << index));
      if (!feasible(selected, constraints)) continue;
      const result = simulatePlan(dataset, selected, paymentRate);
      if (result.netBenefit > best.netBenefit || (result.netBenefit === best.netBenefit && result.recoveredMwh > best.recoveredMwh)) {
        best = result;
      }
    }
    return best;
  }

  function gapFirst(dataset, candidates, constraints, paymentRate) {
    const selected = [];
    const sorted = [...candidates].sort((a, b) => b.currentGapMw - a.currentGapMw);
    sorted.forEach((candidate) => {
      const next = [...selected, candidate];
      if (feasible(next, constraints)) selected.push(candidate);
    });
    return simulatePlan(dataset, selected, paymentRate);
  }

  function evaluateScenario(options) {
    const dataset = generateScenario(options.scenarioId);
    const diagnostics = diagnose(dataset);
    const candidates = buildActionCandidates(dataset, diagnostics);
    const constraints = {
      budget: Number(options.budget),
      crewHours: Number(options.crewHours),
      inverterSpares: Number(options.inverterSpares)
    };
    const paymentRate = Number(options.paymentRate);
    const noIntervention = simulatePlan(dataset, [], paymentRate);
    const gapPlan = gapFirst(dataset, candidates, constraints, paymentRate);
    const optimizedPlan = optimize(dataset, candidates, constraints, paymentRate);
    return { dataset, diagnostics, candidates, constraints, paymentRate, noIntervention, gapPlan, optimizedPlan };
  }

  global.SolarSimulator = {
    HOURS,
    PLANT,
    SCENARIOS,
    ACTION_DEFS,
    generateScenario,
    diagnose,
    buildActionCandidates,
    simulatePlan,
    evaluateScenario
  };

  if (typeof module !== "undefined") {
    module.exports = global.SolarSimulator;
  }
})(typeof window !== "undefined" ? window : globalThis);
