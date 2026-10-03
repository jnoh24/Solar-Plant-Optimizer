// Read the preserved JavaScript model; export shared inputs and reference outputs.
const fs = require('fs');
const path = require('path');
const sim = require('../simulator.js');
const constraints = [
  {budget: 45000, crewHours: 22, inverterSpares: 1},
  {budget: 100000, crewHours: 100, inverterSpares: 3},
  {budget: 45000, crewHours: 22, inverterSpares: 0},
  {budget: 0, crewHours: 0, inverterSpares: 0},
  {budget: 45000, crewHours: 5, inverterSpares: 1}
];
const cases = sim.SCENARIOS.map(scenario => ({
  dataset: sim.generateScenario(scenario.id),
  results: constraints.map(limits => sim.evaluateScenario({
    scenarioId: scenario.id, ...limits, paymentRate: 115
  })) .map(result => ({
    constraints: result.constraints, paymentRate: result.paymentRate,
    diagnostics: result.diagnostics, candidates: result.candidates,
    noIntervention: result.noIntervention, gapPlan: result.gapPlan,
    optimizedPlan: result.optimizedPlan
  }))
}));
fs.writeFileSync(path.join(__dirname, 'reference.json'), JSON.stringify({
  plant: sim.PLANT, scenarios: sim.SCENARIOS, actions: sim.ACTION_DEFS, cases
}));
console.log('Exported shared hourly inputs and 35 JavaScript reference evaluations.');
