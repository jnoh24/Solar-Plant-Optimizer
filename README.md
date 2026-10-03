# Explainable Solar Asset Optimization Prototype

Synthetic demonstration — not validated plant performance.

This is a dependency-free static prototype for a university case competition. It models one fictional Ontario solar plant with six unequal array sections and compares no intervention, a largest-gap-first heuristic, and an exhaustive financial optimization plan.

## Run

Open `index.html` in a browser.

Optional verification:

```bash
node verify.js
```

## Calculation Summary

The app generates reproducible hourly synthetic data over a 14-day horizon. Expected healthy, snow-free generation is:

```text
section expected MW = section AC MW x sunlight index x module temperature derate
temperature derate = 1 - 0.004 x (module temperature C - 25)
```

Section expected power is clipped by each section's AC capacity. Total plant output is scaled down when it would exceed the plant AC limit. Since each timestep is one hour, hourly MW summed across the horizon is reported as MWh.

Actual generation applies transparent synthetic conditions: inverter alarms, snow observations with natural shedding, soiling, gradual degradation, and grid curtailment flags. Diagnosis requires supporting inputs where available. The app does not infer a specific fault from an output gap alone; ambiguous gaps are flagged for inspection.

The optimizer enumerates feasible action combinations under budget, crew-hour, and inverter spare-part constraints. It simulates recovered energy against the no-intervention baseline hour by hour, accounting for action completion delay, natural snow shedding, future sunlight, AC limits, and curtailment. Curtailed energy alone is not credited as recoverable maintenance benefit.

Payment per MWh is a user-entered assumption, not a verified PPA tariff.
