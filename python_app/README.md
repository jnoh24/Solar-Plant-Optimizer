# Python Solar Maintenance Action Selection

Synthetic demonstration — not validated plant performance.

The dashboard and current calculations are entirely Python. They do not read
`reference.json` or depend on JavaScript. Calculations live in `model.py`; the
Streamlit interface lives in `app.py`.

## Run on your Mac

Use Python 3.11 or newer. In Terminal:

```bash
cd "/Users/jiyoonoh/Documents/Case Comp Prototype/python_app"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open http://localhost:8501. Press Control+C in Terminal to stop the server. For
later runs, activate the existing environment and launch Streamlit again:

```bash
cd "/Users/jiyoonoh/Documents/Case Comp Prototype/python_app"
source .venv/bin/activate
python -m streamlit run app.py
```

The default demo runs at startup. Edit sections, forecast weather, existing
degradation loss, assumed snow-clearance time, budget, total crew-hours, spares,
or payment, then click **Run optimization**. Until then, results retain their
last-run inputs. **Reset demo** restores the defaults.

## Observations and Forecast

Decision time is **day 1 at 13:00**. The observation period is the preceding
13 one-hour intervals, 00:00-13:00. Its final measurement represents 12:00-13:00.
`dataset["observations"]` contains only measured output, modeled healthy output
from observed sunlight/temperature, alarms, snow observations, export flags,
and explicit synthetic inspection records. Diagnosis accepts this view alone
and ignores records at or after decision time. It never reads scenario fault
labels or future observations. A loss without supporting evidence is ambiguous.

The forecast is a **separate 336-hour period starting at the decision time**.
`dataset["hours"]` contains future synthetic power under the no-intervention
assumptions. Actions and financial calculations operate on this forecast only.
Historical generation is never counted as recovered energy. Changing forecast
weather or future snow-clearance time does not change historical observations.
Historical snow is observed at an 8% output factor. The synthetic curtailment
scenario records a day-1 midday export restriction as historical evidence and
assumes further restrictions on days 3-6. These are demonstration inputs.

Hidden conditions are used only inside the synthetic data generator to produce
observations and forecast baseline output. They are not passed to diagnosis or
used as evidence. The dashboard separates observed evidence from forecast
assumptions; it does not claim to predict future plant conditions.

## Physical and Loss Assumptions

The fictional 60 MW AC plant has six unequal sections. It is not an equal
fifth of the illustrative 325 MW portfolio. Healthy, snow-free section power is:

```text
expected MW = section AC MW * sunlight index * temperature derate
derate = clamp(1 - 0.004 * (module temperature C - 25), 0.85, 1.08)
```

Each section is clipped to its AC cap, then all expected section outputs are
proportionally scaled if needed to meet the plant cap. Reproducible clouds
modify a 07:00-17:00 sunlight sine curve. Module temperature is synthetic
ambient temperature plus 23 times sunlight index. Power is MW; energy is the
sum of hourly MW times one hour, in MWh. Each interval uses its start-hour
output factor. The fixed seed makes identical inputs reproduce identical data.

**Existing degradation** is an editable constant percentage loss, default 6%,
on the affected section in the degradation scenario. It does not increase
hourly. It is distinct from annual aging, which is not modeled.

**Natural snow clearance** is an editable assumption measured in hours after
the decision, default 24 hours. It is not predicted from weather. The simple
curve describes output factor, not literal fractional snow-covered area:

```text
snow output factor(t) = 0.08 + 0.92 * clamp(t / clearance_hours, 0, 1)
```

Zero hours means immediate full clearance. A value beyond 336 hours means snow
persists past the forecast. The same natural curve applies to no intervention
and every action plan. Snow removal raises output to at least 92% after its
six-hour completion delay. It only earns additional energy before natural
clearance; afterward the baseline and removal plan are equal.

Inverter fault output is 5% of healthy power. Repair recovers 97% of that loss
after a 12-hour assumed delay, with zero section output during hours 8-11 of
the delay. Lost residual output during that outage is deducted from recovery.
Soiling output is 86% of healthy power; cleaning recovers 85% of the loss after
24 hours. Other actions assume no outage.

Both degradation and ambiguous-loss inspections are available as information
gathering actions with **zero immediate energy recovery**. Their information
value is not quantified. A paid inspection therefore will not be recommended
by this energy-only financial objective. No replacement actions or lifecycle
modeling are included.

## Optimization and Comparison

The objective is to maximize:

```text
(plan forecast MWh - no-intervention forecast MWh) * payment per MWh
    - maintenance spending
```

Payment is an explicit assumption, not a verified PPA tariff. Exhaustive search
evaluates all subsets of indicated actions, including doing nothing. Spending,
total crew-hours, and inverter spare kits must fit the input limits. At most
one action is selected per section. Ties retain the higher recovered energy.

This is **maintenance action selection, not a dispatch schedule**. Completion
delays are assumed independently; parallel crew availability, shifts, travel
sequencing, and scheduling are not modeled. Total crew-hours are only a shared
resource allowance.

The comparison is now **Profit-screened largest-gap-first**:

1. Start with no selected actions and zero incremental net benefit.
2. Sort by descending latest observed MW gap; break ties by section ID, then
   action ID, in ascending order.
3. Check the proposed combined plan against budget, total crew-hours, spare
   kits, and the one-action-per-section rule. Skip infeasible additions.
4. Simulate the combined plan using the same hourly model as the optimizer.
5. Accept the action only if combined-plan net benefit increases by more than
   **$0.000001**. Otherwise skip it and continue to the next candidate.

The screen uses **marginal** benefit relative to the plan already selected,
not standalone profitability. Shared export caps can make a profitable action
unprofitable as an addition. Earlier greedy choices are not reconsidered, so
this strategy can still miss a better combination. The dashboard records each
accept/skip decision, its marginal value when simulated, and resource failures.
Both active strategies use identical constraints and can choose no intervention.
Neither selects a plan worse than no intervention; exhaustive search remains
unchanged and achieves at least the greedy plan's value within tolerance.

In the original snow-versus-inverter demo, the new baseline skips unprofitable
snow removal, continues to check the inverter, and matches the optimized repair.

These strategies select discretionary actions only. Mandatory safety or
compliance actions would require separate requirements and **must not be rejected
solely on profitability**. No such mandatory actions are modeled here.

Whole-plant generation is recalculated for each combination before applying
export caps. Individual action benefits are not summed, avoiding shared-cap
double-counting. Signed hourly differences account for repair losses. A zero
export cap remains zero. Curtailment alone earns no maintenance benefit.

## Multi-Fault Demonstration

Choose **Multi-fault demo: greedy vs better combination**, then click
**Run optimization**. Choosing this scenario restores the original section
capacities and loads these explicit input assumptions:

| Input | Value |
| --- | --- |
| Faults | Snow on B; inverter faults on A and D |
| Weather | Mixed-sunny, fixed seed for this scenario |
| Natural snow clearance | 96 hours after decision |
| Maintenance budget | $64,000 |
| Total crew-hours | 32 |
| Inverter spare kits | 2 |
| Assumed payment | $115/MWh |

Existing physical/loss models, repair costs, delays, and effectiveness are
unchanged. You can edit the preset inputs; the result may then differ.

| Strategy | Selected actions | Additional MWh | Spending | Incremental net benefit |
| --- | --- | ---: | ---: | ---: |
| No intervention | None | 0 | $0 | $0 |
| Profit-screened largest-gap-first | B snow removal + D repair | 853.119 | $41,000 | $57,108.63 |
| Financially optimized | A repair + D repair | 1,262.037 | $64,000 | $81,134.29 |

Snow has the largest observed gap. Its $2,028.06 standalone net benefit is
positive under the slower-clearance assumption, so greedy selection accepts
it, followed by the profitable D repair. Adding A would exceed both budget and
crew limits. Exhaustive search instead finds both repairs feasible and worth
$24,025.66 more. It is not modified to obtain this result.

Tests independently integrate healthy forecast MW using the documented snow
curve and repair recovery/outage factors, then score all feasible subsets with
simple cost/crew/spare arithmetic. They do not use the simulation function to
calculate expected demo values. A separate flat-output, 45 MW export-cap test
checks that a profitable standalone repair is skipped when the first selected
repair already fills the shared cap.

## Verification and History

Current independent correctness tests require only Python's standard library:

```bash
python3 verify.py
```

They cover constant degradation, zero inspection recovery, immediate/late snow
clearance, historical-only diagnosis, forecast-information leakage, budgets,
crew-hours, spares, repair downtime, MW/MWh units, AC/export caps, and duplicate
actions. Separate hand-calculated all-subsets oracles verify the highest
net-benefit feasible combination, including doing nothing. New tests check
marginal profit screening, ties, numerical tolerance, continued checking after
skips, shared export caps, and both strategies' resource/value invariants across
160 scenario/clearance/resource combinations. Streamlit controls can be checked after
installing requirements:

```bash
python verify_ui.py
```

Historical conversion checks are archived separately:

```bash
python3 historical_conversion/verify_conversion.py
```

That command uses a frozen pre-update **Python** model and the original
`reference.json` to reproduce the earlier 35 conversion comparisons. It does
not validate current assumptions. The reference is unchanged and is not
regenerated. `export_reference.js` is a historical conversion artifact, not a
dashboard or correctness-test dependency. The original JavaScript application
on its Git branch is untouched.

The pre-update working Python version is preserved by local Git tag
`pre-model-assumptions-20261003` at commit `970714f`. The tag has not been pushed.
The corrected working version immediately before this strategy update is
committed at `4c9e7c3`, with local tag `pre-profit-screened-20261003`.
Neither backup tag nor the new backup commit was pushed by this update.
See `verification_results.txt` for current verification results and
`historical_conversion/verification_results.txt` for the earlier conversion.
