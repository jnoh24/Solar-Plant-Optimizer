# Python Solar Optimization Demo

Synthetic demonstration — not validated plant performance.

The original JavaScript application in the parent folder is preserved. This
version uses Python for both calculations (`model.py`) and the Streamlit
interface (`app.py`). No JavaScript is needed to run or modify this app.

## Run on your Mac

Open a terminal and run these commands exactly:

```bash
cd "/Users/jiyoonoh/Documents/Case Comp Prototype/python_app"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open http://localhost:8501 if Streamlit does not open your browser. To stop,
press Control+C in the terminal. For later runs:

```bash
cd "/Users/jiyoonoh/Documents/Case Comp Prototype/python_app"
source .venv/bin/activate
python -m streamlit run app.py
```

The default demo runs when the page opens. Edit section names/capacities, weather,
budget, crew-hours, spare kits, or payment, then click **Run optimization**.
**Reset demo** restores the original inputs and runs the default demonstration.
Results remain tied to the last run until you click Run optimization.

## How it works

The 60 MW fictional plant has six unequal sections. It represents one plant,
not five equal shares of the illustrative 325 MW portfolio. Each scenario
produces 336 hourly rows using a fixed seed and cloud profile. Identical inputs
produce identical results. Weather controls override the cloud/temperature
profile; synthetic equipment conditions remain those of the chosen scenario.

Healthy, snow-free power is section AC MW times sunlight index times temperature
derate: `1 - 0.004 * (module_temperature_C - 25)`, bounded to 0.85-1.08.
Section outputs are clipped at section capacity, then proportionally scaled to
the plant AC cap. Power is MW; summing MW times one-hour intervals gives MWh.
Synthetic conditions reduce output; grid caps are applied to the whole plant.
Diagnosis uses alarms, snow observations, or synthetic inspection tags. A gap
alone leads to inspection, not a specific fault diagnosis.

For each possible action combination, the model recalculates whole-plant output
against doing nothing. It accounts for future sunlight, action completion,
natural snow shedding, repair outages, and export caps. Benefits are **net extra
MWh times assumed payment minus maintenance costs**. The optimizer enumerates
every subset, excludes combinations exceeding spending, total crew-hours, or
spare kits, and chooses the highest net benefit. Doing nothing is an option.
Equal benefits are resolved by higher recovered energy. Actions run in parallel;
crew-hours are a total allowance rather than a detailed scheduling model.
Largest-gap-first selects actions in descending day-1 noon gap order under the
same constraints, without screening their profitability.

Snow naturally clears at hour 42, tomorrow evening; clearing it has little
lasting value. The inverter fault persists through sunny days, so its repair
usually creates greater value. Payment is an assumption, not a verified tariff.
Inspection of degradation retains the original illustrative 15% recovery
assumption; that benefit is not validated. No lifecycle replacement is modeled.

## Verification and corrections

Run the checks without installing Streamlit:

```bash
python3 verify.py
```

`reference.json` contains shared hourly input data exported from the preserved
JavaScript model plus its results for all seven scenarios and five constraint
sets (35 evaluations). Verification recomputes healthy generation from those
exact sunlight/temperature inputs, and compares diagnoses, selected actions,
energy, spending, crew, spare use, revenue, and net benefit. It first uses the
original action definitions to establish parity, then tests corrected Python
actions. This does not rely on independently generated weather matching by chance.
An additional check verifies the Python generator reproduces the original rows.

To refresh the reference after deliberately changing the original JS model
(Node.js is needed only for this optional step):

```bash
node export_reference.js
python3 verify.py
```

Corrections from the original:

- The original has a completion delay but no actual repair outage. Python adds
  an explicit, synthetic four-hour inverter outage in hours 8-11 before
  completion at hour 12. This is a new modeling assumption correcting the
  missing downtime, not validated equipment data.
- Original recovery clips each hourly gain to zero, which would overstate
  benefits once repair downtime is included. Python sums signed differences,
  so recovered energy always equals plan energy minus baseline energy.
- The original treats a zero-MW grid cap as uncapped because it uses a truthy
  fallback. Python treats only `None` as uncapped. Existing scenarios use
  34 MW caps, so this correction does not alter their original results.
- For an ambiguous gap without a scenario fault tag, the original could credit
  inspection with full recovery despite zero effectiveness, because it used a
  healthy issue factor rather than the measured baseline. Python retains actual
  baseline output for zero-effectiveness, zero-outage actions. This affects only
  ambiguous input cases, not the seven original scenarios.

Tests also cover unavailable spares, tight budgets and crew, natural snow
shedding, explicit downtime losses, MW/MWh conversion, section/plant AC limits
after capacity edits, shared-cap interactions, duplicate-action rejection,
ambiguous diagnoses, and zero maintenance recovery from curtailment alone.

See `verification_results.txt` for measured comparison results from this build.

The Streamlit controls are also tested using its native AppTest framework:

```bash
python verify_ui.py
```

This checks all scenarios, weather changes, stale results before Run, unavailable
spares, section edits, and Reset demo. Dependencies are pinned to the versions
used for verification. Python 3.11 or newer is recommended.
