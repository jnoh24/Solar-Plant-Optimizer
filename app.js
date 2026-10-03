(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const fmtMoney = (value) => value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const fmtMwh = (value) => `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })} MWh`;
  const fmtMw = (value) => `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })} MW`;

  function init() {
    SolarSimulator.SCENARIOS.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.id;
      option.textContent = scenario.name;
      $("scenario").appendChild(option);
    });

    ["scenario", "budget", "crewHours", "inverterSpares", "paymentRate"].forEach((id) => {
      $(id).addEventListener("input", render);
      $(id).addEventListener("change", render);
    });

    render();
  }

  function readOptions() {
    return {
      scenarioId: $("scenario").value,
      budget: Number($("budget").value),
      crewHours: Number($("crewHours").value),
      inverterSpares: Number($("inverterSpares").value),
      paymentRate: Number($("paymentRate").value)
    };
  }

  function render() {
    const result = SolarSimulator.evaluateScenario(readOptions());
    const { dataset, diagnostics, candidates, noIntervention, gapPlan, optimizedPlan } = result;

    $("plantBadge").textContent = `${dataset.plant.name}: ${dataset.plant.acLimitMw} MW AC limit`;
    $("noInterventionMwh").textContent = fmtMwh(noIntervention.baselineMwh);
    $("gapBenefit").textContent = fmtMoney(gapPlan.netBenefit);
    $("gapMwh").textContent = `${fmtMwh(gapPlan.recoveredMwh)} recovered`;
    $("optBenefit").textContent = fmtMoney(optimizedPlan.netBenefit);
    $("optMwh").textContent = `${fmtMwh(optimizedPlan.recoveredMwh)} recovered`;
    $("optSpend").textContent = fmtMoney(optimizedPlan.spend);
    $("optResources").textContent = `${optimizedPlan.crewHours} crew-hours, ${optimizedPlan.inverterKits} spare kits`;

    renderGenerationChart(dataset);
    renderStrategyChart(noIntervention, gapPlan, optimizedPlan);
    renderDiagnostics(diagnostics);
    renderRecommendations(candidates, gapPlan, optimizedPlan);
    renderAssumptions(result);
  }

  function renderGenerationChart(dataset) {
    const width = 980;
    const height = 340;
    const pad = { top: 16, right: 18, bottom: 34, left: 48 };
    const maxY = Math.max(dataset.plant.acLimitMw, ...dataset.hours.map((row) => row.expectedMw));
    const x = (hour) => pad.left + (hour / (SolarSimulator.HOURS - 1)) * (width - pad.left - pad.right);
    const y = (mw) => height - pad.bottom - (mw / maxY) * (height - pad.top - pad.bottom);
    const line = (accessor) => dataset.hours.map((row) => `${x(row.hour).toFixed(1)},${y(accessor(row)).toFixed(1)}`).join(" ");
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = maxY * ratio;
      return `<line class="grid-line" x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}"></line>
        <text x="8" y="${y(value) + 4}" font-size="12" fill="#66737c">${Math.round(value)}</text>`;
    }).join("");
    const dayTicks = Array.from({ length: 15 }, (_, index) => index * 24).filter((hour) => hour < SolarSimulator.HOURS).map((hour) => {
      return `<line class="grid-line" x1="${x(hour)}" y1="${pad.top}" x2="${x(hour)}" y2="${height - pad.bottom}"></line>
        <text x="${x(hour) - 8}" y="${height - 10}" font-size="11" fill="#66737c">${hour / 24 + 1}</text>`;
    }).join("");

    $("generationChart").innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
        ${grid}
        ${dayTicks}
        <polyline class="expected-line" points="${line((row) => row.expectedMw)}"></polyline>
        <polyline class="actual-line" points="${line((row) => row.actualMw)}"></polyline>
        <line class="axis" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"></line>
        <line class="axis" x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}"></line>
        <text x="${width - 92}" y="${height - 10}" font-size="12" fill="#66737c">Day of horizon</text>
        <text x="8" y="14" font-size="12" fill="#66737c">MW</text>
      </svg>
      <div class="legend"><span class="expected">Expected healthy</span><span class="actual">Actual baseline</span></div>
    `;
  }

  function renderStrategyChart(noIntervention, gapPlan, optimizedPlan) {
    const rows = [
      { label: "No intervention", value: 0, className: "empty" },
      { label: "Gap-first", value: gapPlan.netBenefit, className: "secondary" },
      { label: "Optimized", value: optimizedPlan.netBenefit, className: "" }
    ];
    const max = Math.max(1, ...rows.map((row) => Math.max(0, row.value)));
    $("strategyChart").innerHTML = rows.map((row) => {
      const width = `${Math.max(3, (Math.max(0, row.value) / max) * 100)}%`;
      return `<div class="bar-row">
        <strong>${row.label}</strong>
        <div class="bar-track"><div class="bar-fill ${row.className}" style="width:${width}"></div></div>
        <span>${fmtMoney(row.value)}</span>
      </div>`;
    }).join("") + `<p class="muted">No intervention is the reference case. Benefits are incremental revenue from recovered MWh minus action costs.</p>`;
  }

  function renderDiagnostics(diagnostics) {
    $("diagnostics").innerHTML = diagnostics.map((diag) => {
      const evidence = diag.evidence.map((item) => `<span class="chip">${item}</span>`).join("");
      return `<article class="diagnostic">
        <div class="row"><strong>${diag.sectionId} · ${diag.sectionName}</strong><span>${diag.acMw} MW AC</span></div>
        <div class="row"><span class="cause">${diag.cause}</span><span>${diag.confidence} confidence</span></div>
        <div class="row"><span>14-day output gap</span><strong>${fmtMwh(diag.gapMwh)}</strong></div>
        <div class="row"><span>Current generation gap</span><strong>${fmtMw(diag.currentGapMw)}</strong></div>
        <div class="chip-list">${evidence}</div>
      </article>`;
    }).join("");
  }

  function renderRecommendations(candidates, gapPlan, optimizedPlan) {
    const optimizedIds = new Set(optimizedPlan.actions.map((action) => action.id));
    const gapIds = new Set(gapPlan.actions.map((action) => action.id));
    if (!candidates.length) {
      $("recommendations").innerHTML = `<p class="muted">No recoverable maintenance actions are indicated. If curtailment is present, maintenance is not credited with recoverable benefit for curtailed energy alone.</p>`;
      return;
    }

    $("recommendations").innerHTML = candidates.map((action) => {
      const selected = optimizedIds.has(action.id);
      const gapSelected = gapIds.has(action.id);
      const status = selected ? "Recommended" : "Deferred";
      const statusClass = selected ? "recommended" : "deferred";
      const comparison = gapSelected && !selected ? "Gap-first would choose this because the current MW gap is large." : selected && !gapSelected ? "Optimizer chooses this for higher future value within constraints." : selected ? "Selected by both strategies." : "Not selected under current constraints or economics.";
      return `<article class="action-card">
        <div class="row"><strong>${action.sectionId} · ${action.action}</strong><span class="${statusClass}">${status}</span></div>
        <div>${action.cause}: ${action.explanation}</div>
        <div class="chip-list">
          <span class="chip">${fmtMoney(action.cost)}</span>
          <span class="chip">${action.crewHours} crew-hours</span>
          <span class="chip">${action.delayHours}h delay</span>
          <span class="chip">${action.spareParts.inverterKit || 0} inverter kits</span>
          <span class="chip">${Math.round(action.effectiveness * 100)}% effectiveness</span>
        </div>
        <p class="muted">${comparison}</p>
      </article>`;
    }).join("");
  }

  function renderAssumptions(result) {
    const { dataset, optimizedPlan, gapPlan, paymentRate } = result;
    const sectionCaps = dataset.plant.sections.map((section) => `${section.id}: ${section.acMw} MW`).join(", ");
    $("assumptions").innerHTML = `
      <p>Portfolio context is approximately 325 MW AC across five Ontario solar plants; this demonstration models only ${dataset.plant.name}, a fictional ${dataset.plant.acLimitMw} MW AC plant with unequal section capacities (${sectionCaps}).</p>
      <p>Expected generation uses: section AC capacity × synthetic sunlight index × module temperature derate, where derate = 1 - 0.004 × (module temperature C - 25), bounded between 85% and 108%. Section outputs are clipped by section AC limits and scaled if the plant exceeds its AC limit.</p>
      <p>Energy is hourly power summed as MWh because each timestep is one hour. Costs use the user-entered payment assumption of ${fmtMoney(paymentRate)} per MWh, not a verified PPA tariff.</p>
      <p>Optimization enumerates all feasible action combinations under budget, crew-hour, and inverter-spare constraints. Recovered energy is simulated against the no-intervention baseline, with action delays, natural snow shedding, future sunlight, plant limits, and curtailment caps applied hour by hour.</p>
      <p>Recovered MWh excluded by curtailment: optimized ${fmtMwh(optimizedPlan.excludedCurtailmentMwh)}, gap-first ${fmtMwh(gapPlan.excludedCurtailmentMwh)}. Grid curtailment alone is not treated as a recoverable maintenance benefit.</p>
    `;
  }

  init();
})();
