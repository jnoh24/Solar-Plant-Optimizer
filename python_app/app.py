"""Streamlit interface; all calculations live in model.py."""

from copy import deepcopy
import altair as alt
import pandas as pd
import streamlit as st

from model import PLANT, SCENARIOS, MULTI_FAULT_OPTIONS, generate_scenario, evaluate, simulate_plan

st.set_page_config(page_title="Solar Asset Optimization", layout="wide")


def reset_demo():
    for key in ("scenario", "weather", "budget", "crew", "spares", "payment", "degradation", "snow_clearance", "sections", "result", "inputs"):
        st.session_state.pop(key, None)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


def on_scenario_change():
    st.session_state["weather"] = "Scenario default"
    if st.session_state["scenario"] == "multi-fault-demo":
        for key, option in (("budget", "budget"), ("crew", "crewHours"), ("spares", "inverterSpares"),
                            ("payment", "paymentRate"), ("snow_clearance", "snowClearanceHours")):
            value = MULTI_FAULT_OPTIONS[option]
            st.session_state[key] = float(value) if key in ("payment", "snow_clearance") else value
        st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


st.title("Explainable Solar Asset Optimization")
st.warning("Synthetic demonstration — not validated plant performance.")
st.caption("Fictional Plant A | 60 MW AC limit | Six unequal array sections | 14-day horizon")
st.caption("Maintenance action selection, not a dispatch schedule. Total crew-hours are constrained; parallel crew availability is not modeled.")
st.caption("Portfolio context: approximately 325 MW AC across five Ontario plants. This fictional plant does not imply equal portfolio capacities.")

for key, value in dict(degradation=6.0, snow_clearance=24.0, budget=45000,
                       crew=22, spares=1, payment=115.0).items():
    st.session_state.setdefault(key, value)

with st.sidebar:
    st.header("Scenario inputs")
    scenario_id = st.selectbox("Scenario", [s["id"] for s in SCENARIOS],
                               format_func=lambda value: next(s["name"] for s in SCENARIOS if s["id"] == value),
                               key="scenario", on_change=on_scenario_change)
    weather = st.selectbox("Forecast weather profile", ["Scenario default", "mixed-sunny", "sunny", "cloudy"], key="weather")
    degradation = st.number_input("Existing degradation output loss (%)", min_value=0.0, max_value=100.0,
                                  value="min", step=1.0, key="degradation")
    st.caption("Constant loss in the degradation scenario. This is existing degradation, not annual aging.")
    snow_clearance = st.number_input("Assumed natural snow clearance (hours after decision)",
                                     min_value=0.0, value="min", step=1.0, key="snow_clearance")
    st.caption("User assumption, not a weather prediction. Zero means immediate clearance; values above 336 extend beyond the forecast.")
    budget = st.number_input("Maintenance budget ($)", min_value=0, value="min", step=1000, key="budget")
    crew = st.number_input("Total available crew-hours", min_value=0, value="min", step=1, key="crew")
    spares = st.number_input("Available inverter spare kits", min_value=0, value="min", step=1, key="spares")
    payment = st.number_input("Assumed payment ($/MWh)", min_value=0.0, value="min", step=1.0, key="payment")
    st.caption("Payment is an explicit assumption, not a verified PPA tariff. All dollar amounts use the same assumed currency.")
    st.button("Reset demo", on_click=reset_demo, width="stretch")

with st.expander("Section data", expanded=True):
    sections = st.data_editor(pd.DataFrame(PLANT["sections"]), hide_index=True, num_rows="fixed",
                             disabled=["id"], key=f'section_editor_{st.session_state.get("editor_version", 0)}',
                             column_config={"id": "Section", "name": "Section name",
                                            "acMw": st.column_config.NumberColumn("AC capacity (MW)", min_value=.1, step=.1)},
                             width="stretch")

plant = deepcopy(PLANT)
plant["sections"] = sections.to_dict("records")
constraints = dict(budget=budget, crewHours=crew, inverterSpares=spares)
inputs = dict(scenario=scenario_id, weather=weather, plant=plant, constraints=constraints, payment=payment,
              degradation=degradation, snow_clearance=snow_clearance)
if "result" in st.session_state and ("observations" not in st.session_state["result"]["dataset"]
                                     or "decisions" not in st.session_state["result"]["gapPlan"]):
    st.session_state.pop("result")
    st.session_state.pop("inputs", None)
run = st.button("Run optimization", type="primary")
if run or "result" not in st.session_state:
    try:
        dataset = generate_scenario(scenario_id, plant, None if weather == "Scenario default" else weather,
                                    degradation, snow_clearance)
        st.session_state["result"] = evaluate(dataset, constraints, payment)
        st.session_state["inputs"] = deepcopy(inputs)
    except (ValueError, TypeError, KeyError) as error:
        st.error(f"Check your inputs: {error}")
        st.stop()
if st.session_state["inputs"] != inputs:
    st.info("Inputs have changed. Run optimization to update the results below.")

result = st.session_state["result"]
dataset = result["dataset"]
limits = result["constraints"]
optimized = result["optimizedPlan"]
gap = result["gapPlan"]
baseline = result["noIntervention"]
st.subheader(dataset["scenario"]["name"])
st.caption("Decision time: day 1, 13:00. Historical observations cover 00:00-13:00; the last interval is 12:00-13:00. "
           "Benefits are valued over the following 336 hours only.")
st.caption(f'Results use {dataset["scenario"]["weather"]} weather; budget ${limits["budget"]:,.0f}, '
           f'{limits["crewHours"]} crew-hours, {limits["inverterSpares"]} spare kits, '
           f'${result["paymentRate"]:,.2f}/MWh.')
if dataset["scenario"]["id"] == "multi-fault-demo":
    st.caption("Multi-fault demonstration: snow on B, inverter alarms on A and D. "
               "The preset uses $64,000, 32 total crew-hours, two spare kits, $115/MWh, and assumed snow clearance at 96 hours. "
               "Greedy selection can spend resources on profitable snow removal before considering both repairs.")
cols = st.columns(4)
cols[0].metric("Baseline energy", f'{baseline["baselineMwh"]:,.1f} MWh')
cols[1].metric("Additional energy", f'{optimized["recoveredMwh"]:,.1f} MWh')
cols[2].metric("Maintenance spending", f'${optimized["spend"]:,.0f}')
cols[3].metric("Incremental net benefit", f'${optimized["netBenefit"]:,.0f}')
st.caption(f'Optimized resources: {optimized["crewHours"]} crew-hours, {optimized["inverterKits"]} inverter kits.')

st.subheader("Observed evidence before the decision")
history = dataset["observations"]["hours"]
observed = pd.DataFrame({"Hour of day 1": [r["absoluteHour"] for r in history],
                         "Expected healthy": [r["expectedMw"] for r in history],
                         "Observed actual": [r["actualMw"] for r in history]})
st.line_chart(observed.set_index("Hour of day 1"), y_label="Power (MW)")
st.caption(f'Historical weather profile: {dataset["assumptions"]["observedWeather"]}. '
           'Only observed output, weather, alarms, snow observations, and recorded inspection evidence inform diagnosis.')

st.subheader("Forecast generation after the decision")
st.caption(f'Forecast assumptions: {dataset["assumptions"]["forecastWeather"]} weather; '
           f'{dataset["assumptions"]["degradationLossPct"]:g}% constant existing degradation loss; '
           f'natural snow clearance {dataset["assumptions"]["snowClearanceHours"]:g} hours after decision. '
           'These are synthetic assumptions, not future observations or validated predictions.')
generation = pd.DataFrame({"Hour": [r["hour"] for r in dataset["hours"]],
                           "Expected healthy": [r["expectedMw"] for r in dataset["hours"]],
                           "Forecast baseline": [r["actualMw"] for r in dataset["hours"]]})
lines = generation.melt("Hour", var_name="Generation", value_name="Power (MW)")
st.altair_chart(alt.Chart(lines).mark_line().encode(
    x=alt.X("Hour:Q", title="Hours after decision (14-day forecast)"),
    y=alt.Y("Power (MW):Q", scale=alt.Scale(domain=[0, dataset["plant"]["acLimitMw"]])),
    color="Generation:N", tooltip=["Hour:Q", "Generation:N", alt.Tooltip("Power (MW):Q", format=".2f")]
).properties(height=300), width="stretch")

st.subheader("Strategy comparison")
comparison = pd.DataFrame([{"Strategy": label, "Total energy (MWh)": plan["planMwh"],
                            "Additional energy (MWh)": plan["recoveredMwh"], "Spending ($)": plan["spend"],
                            "Net benefit ($)": plan["netBenefit"], "Crew-hours": plan["crewHours"],
                            "Spare kits": plan["inverterKits"]}
                           for label, plan in [("No intervention", baseline), ("Profit-screened largest-gap-first", gap),
                                               ("Financially optimized", optimized)]])
st.altair_chart(alt.Chart(comparison).mark_bar().encode(
    y=alt.Y("Strategy:N", sort=comparison["Strategy"].tolist(), axis=alt.Axis(labelLimit=310)),
    x="Net benefit ($):Q", color=alt.Color("Strategy:N", legend=None),
    tooltip=["Strategy:N", alt.Tooltip("Net benefit ($):Q", format=",.2f")]
).properties(height=240), width="stretch")
st.dataframe(comparison, hide_index=True, width="stretch",
             column_config={key: st.column_config.NumberColumn(format="%.1f") for key in
                            ["Total energy (MWh)", "Additional energy (MWh)", "Net benefit ($)"]})

st.subheader("Profit-screened baseline decisions")
st.caption(f'Candidates are checked by descending latest observed gap, then section ID and action ID. '
           f'Acceptance requires marginal combined-plan net benefit greater than ${gap["netBenefitTolerance"]:g}. '
           'Resource failures are skipped before valuation; shared export caps are included in each simulated plan.')
action_names = {a["id"]: a["action"] for a in result["candidates"]}
if gap["decisions"]:
    decisions = pd.DataFrame([{
        "Order": index + 1, "Action": f'{decision["sectionId"]} | {action_names[decision["actionId"]]}',
        "Observed gap (MW)": decision["currentGapMw"],
        "Decision": "Accepted" if decision["accepted"] else "Skipped",
        "Marginal net benefit ($)": decision["marginalNetBenefit"],
        "Explanation": " ".join(decision["reasons"])
    } for index, decision in enumerate(gap["decisions"])])
    st.dataframe(decisions, hide_index=True, width="stretch", column_config={
        "Observed gap (MW)": st.column_config.NumberColumn(format="%.2f"),
        "Marginal net benefit ($)": st.column_config.NumberColumn(format="%.6f")})
else:
    st.write("No candidate actions; the baseline retains no intervention.")

left, right = st.columns(2)
with left:
    st.subheader("Suspected loss causes")
    for diagnostic in result["diagnostics"]:
        st.markdown(f'**{diagnostic["sectionId"]} | {diagnostic["sectionName"]} ({diagnostic["acMw"]:g} MW AC)**')
        st.write(f'{diagnostic["cause"]} | {diagnostic["confidence"]} confidence')
        st.caption(f'Last observed gap (12:00-13:00): {diagnostic["currentGapMw"]:.2f} MW | '
                   f'Historical observed gap: {diagnostic["gapMwh"]:.1f} MWh')
        for evidence in diagnostic["evidence"]:
            st.write(evidence)
        st.divider()
with right:
    st.subheader("Recommended and deferred actions")
    selected_ids = {a["id"] for a in optimized["actions"]}
    gap_ids = {a["id"] for a in gap["actions"]}
    if not result["candidates"]:
        st.write("No intervention recommended. No recoverable maintenance actions are indicated.")
    for action in result["candidates"]:
        chosen = action["id"] in selected_ids
        st.markdown(f'**{action["sectionId"]} | {action["action"]}: {"Recommended" if chosen else "Deferred"}**')
        st.write(action["explanation"])
        st.caption(f'${action["cost"]:,.0f} | {action["crewHours"]} crew-hours | '
                   f'{action["delayHours"]}h completion delay | {action["downtimeHours"]}h outage | '
                   f'{action["spareParts"]["inverterKit"]} spare kits | {action["effectiveness"]:.0%} effectiveness')
        standalone = simulate_plan(dataset, [action], result["paymentRate"])
        st.write(f'If performed alone: {standalone["recoveredMwh"]:.1f} additional MWh; '
                 f'${standalone["netBenefit"]:,.0f} incremental net benefit.')
        if chosen:
            st.write("Included in the feasible combination with the highest incremental net benefit.")
        else:
            reasons = []
            if action["cost"] > limits["budget"]:
                reasons.append("Budget is insufficient for this action.")
            if action["crewHours"] > limits["crewHours"]:
                reasons.append("Available crew-hours are insufficient.")
            if action["spareParts"]["inverterKit"] > limits["inverterSpares"]:
                reasons.append("Required inverter spare kit is unavailable.")
            if standalone["netBenefit"] <= 0:
                reasons.append("Assumed recovered revenue does not exceed action cost.")
            if action["actionType"] in ("degradation", "ambiguous"):
                reasons.append("Inspection is available for information gathering; its information value is not quantified.")
            st.write(" ".join(reasons) or "Other actions create greater total value within the shared resource limits.")
        if action["id"] in gap_ids and not chosen:
            st.write("Profit-screened largest-gap-first accepts this action; its marginal gain is positive, but a different combination creates greater value.")
        elif chosen and action["id"] not in gap_ids:
            st.write("Financial optimization selects this for its future value; profit-screened largest-gap-first skips it.")
        st.divider()

with st.expander("Assumptions and calculations", expanded=True):
    st.write("Expected snow-free, healthy power = section AC MW x sunlight index x temperature derate. "
             "Derate = 1 - 0.004 x (module temperature C - 25), bounded to 0.85-1.08. "
             "Section AC caps are applied, then section expectations are scaled proportionally to the 60 MW plant cap.")
    st.write("Sunlight follows a 07:00-17:00 sine curve with reproducible cloud variation. Module temperature "
             "is synthetic ambient temperature plus 23 x sunlight index. The model has 336 one-hour steps; "
             "energy (MWh) = sum of power (MW) x one hour.")
    st.write("Objective: maximize (plan MWh - no-intervention MWh) x assumed payment per MWh - maintenance costs. "
             "All subsets of indicated actions are enumerated, including doing nothing. Spending, total crew-hours, "
             "and inverter kits must fit the same limits for both intervention strategies. At most one action is chosen per section. "
             "This is maintenance action selection, not a dispatch schedule. Completion delays are assumptions; "
             "total crew-hours do not model parallel crew availability or detailed scheduling.")
    st.write("Before completion, baseline losses persist. Inverter repair additionally shuts the section down "
             "during hours 8-11 of its 12-hour delay; that lost output is subtracted from recovery. "
             "Hours are measured after the decision; other actions assume zero outage. Natural snow output "
             "factor = 0.08 + 0.92 x min(hours after decision / assumed clearance hours, 1). "
             "Zero clearance hours means fully clear immediately. Clearance beyond 336 hours leaves snow at the end. "
             "The same curve applies to every plan; removal raises the factor to at least 92% after completion "
             "and earns credit only before natural clearance. Clearance time is a user assumption, not predicted from weather.")
    st.write("Profit-screened largest-gap-first starts with no actions, ranks by latest observed MW gap "
             "(ties by section ID, then action ID), and checks the same resource and one-action-per-section limits. "
             "It simulates each feasible addition and accepts only a marginal combined-plan net benefit above $0.000001. "
             "Standalone profitability is not sufficient: shared export caps can reduce marginal value. "
             "Skipped actions do not prevent later candidates from being checked; earlier choices are not revisited.")
    st.write("Both strategies select discretionary actions. Mandatory safety or compliance actions would need "
             "separate requirements and must not be rejected solely on profitability; they are not modeled here.")
    st.write("Existing degradation is a constant user-entered percentage loss across the forecast, not an hourly "
             "decline or annual aging rate. Inspection has zero immediate energy recovery. Its information value "
             "is not quantified; the energy-only financial objective will not recommend a paid inspection. "
             "No replacement or lifecycle modeling is included.")
    st.write("The whole plant is simulated with each plan before applying grid caps; individual action benefits "
             "are never added together. Curtailment alone has no maintenance recovery. Grid caps may prevent "
             "otherwise recoverable energy from being exported. Fault diagnoses require alarms, snow observations, "
             "or explicit historical inspection evidence; unsupported output gaps are marked ambiguous. "
             "Diagnosis sees only records before day 1 at 13:00. Forecast weather and condition assumptions "
             "are used only to value future actions, never to establish a historical diagnosis.")
    st.caption(f'Optimized potential recovery excluded by grid caps: {optimized["excludedCurtailmentMwh"]:.1f} MWh; '
               f'profit-screened largest-gap-first: {gap["excludedCurtailmentMwh"]:.1f} MWh.')
