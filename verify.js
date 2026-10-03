const assert = require("assert");
const sim = require("./simulator.js");

function evaluate(overrides = {}) {
  return sim.evaluateScenario({
    scenarioId: "required-demo",
    budget: 45000,
    crewHours: 22,
    inverterSpares: 1,
    paymentRate: 115,
    ...overrides
  });
}

const result = evaluate();
const snow = result.diagnostics.find((diag) => diag.sectionId === "B");
const inverter = result.diagnostics.find((diag) => diag.sectionId === "D");

assert.equal(result.dataset.hours.length, 336, "14-day hourly horizon should contain 336 rows");
assert(result.dataset.hours.every((row) => row.expectedMw <= sim.PLANT.acLimitMw + 1e-9), "Plant AC limit must be respected");
assert(result.dataset.hours.every((row) => row.sections.every((section) => section.expectedMw <= section.acMw + 1e-9)), "Section AC limits must be respected");
assert(snow.currentGapMw > inverter.currentGapMw, "Snow-covered section must have the largest current generation gap in the demo");
assert.equal(snow.cause, "Snow coverage", "Snow diagnosis should use snow observation evidence");
assert.equal(inverter.cause, "Inverter fault", "Inverter diagnosis should use alarm evidence");
assert(result.optimizedPlan.actions.some((action) => action.sectionId === "D"), "Optimized plan should repair persistent inverter");
assert(!result.optimizedPlan.actions.some((action) => action.sectionId === "B"), "Optimized plan should not clear snow that sheds naturally tomorrow under default constraints");
assert(result.gapPlan.actions.some((action) => action.sectionId === "B"), "Gap-first heuristic should choose the largest current gap snow action");
assert(result.optimizedPlan.netBenefit > result.gapPlan.netBenefit, "Optimized inverter repair should create greater value than clearing snow");
assert(result.optimizedPlan.spend <= result.constraints.budget, "Optimized plan must respect budget");
assert(result.optimizedPlan.crewHours <= result.constraints.crewHours, "Optimized plan must respect crew-hour limit");
assert(result.optimizedPlan.inverterKits <= result.constraints.inverterSpares, "Optimized plan must respect spare-parts limit");

const noSpare = evaluate({ inverterSpares: 0 });
assert(!noSpare.optimizedPlan.actions.some((action) => action.action === "Repair inverter"), "Spare-parts restriction should block inverter repair");

const snowOnly = sim.generateScenario("snow-coverage");
const snowDiag = sim.diagnose(snowOnly).find((diag) => diag.sectionId === "B");
assert(snowOnly.hours[12].sections.find((section) => section.id === "B").actualMw < snowOnly.hours[36].sections.find((section) => section.id === "B").actualMw || snowOnly.hours[36].sunlightIndex === 0, "Natural snow shedding should improve output after day one");
assert(snowDiag.evidence.some((item) => item.includes("snow observation")), "Snow diagnosis should include supporting input evidence");

const curtailment = sim.evaluateScenario({
  scenarioId: "grid-curtailment",
  budget: 100000,
  crewHours: 100,
  inverterSpares: 3,
  paymentRate: 115
});
assert.equal(curtailment.candidates.length, 0, "Grid curtailment alone should produce no recoverable maintenance action");
assert.equal(curtailment.optimizedPlan.recoveredMwh, 0, "Grid curtailment alone should have no maintenance recovery");

const energyCheck = result.dataset.hours.reduce((sum, row) => sum + row.actualMw, 0);
assert(Math.abs(energyCheck - result.noIntervention.baselineMwh) < 1e-6, "Hourly MW summed over one-hour steps should equal MWh baseline");

console.log("Verification passed");
console.log(`Required demo: snow current gap ${snow.currentGapMw.toFixed(2)} MW, inverter current gap ${inverter.currentGapMw.toFixed(2)} MW`);
console.log(`Gap-first: ${result.gapPlan.recoveredMwh.toFixed(1)} MWh, ${result.gapPlan.netBenefit.toFixed(0)} net benefit`);
console.log(`Optimized: ${result.optimizedPlan.recoveredMwh.toFixed(1)} MWh, ${result.optimizedPlan.netBenefit.toFixed(0)} net benefit`);
