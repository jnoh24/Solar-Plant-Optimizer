"""Streamlit interface; all calculations live in model.py."""

from copy import deepcopy
import altair as alt
import pandas as pd
import streamlit as st

from model import PLANT, SCENARIOS, DEFAULT_CONSTRAINTS, generate_scenario, evaluate, simulate_plan

st.set_page_config(page_title="Solar Asset Optimization", layout="wide")


def reset_demo():
    for key in ("scenario", "weather", "budget", "crew", "spares", "payment", "sections", "result", "inputs"):
        st.session_state.pop(key, None)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1


def reset_weather():
    st.session_state["weather"] = "Scenario default"


st.title("Explainable Solar Asset Optimization")
st.warning("Synthetic demonstration — not validated plant performance.")
st.caption("Fictional Plant A | 60 MW AC limit | Six unequal array sections | 14-day horizon")
st.caption("Portfolio context: approximately 325 MW AC across five Ontario plants. This fictional plant does not imply equal portfolio capacities.")

with st.sidebar:
    st.header("Scenario inputs")
    scenario_id = st.selectbox("Scenario", [s["id"] for s in SCENARIOS],
                               format_func=lambda value: next(s["name"] for s in SCENARIOS if s["id"] == value),
                               key="scenario", on_change=reset_weather)
    weather = st.selectbox("Weather profile", ["Scenario default", "mixed-sunny", "sunny", "cloudy"], key="weather")
    budget = st.number_input("Maintenance budget ($)", min_value=0, value=45000, step=1000, key="budget")
    crew = st.number_input("Available crew-hours", min_value=0, value=22, step=1, key="crew")
    spares = st.number_input("Available inverter spare kits", min_value=0, value=1, step=1, key="spares")
    payment = st.number_input("Assumed payment ($/MWh)", min_value=0.0, value=115.0, step=1.0, key="payment")
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
inputs = dict(scenario=scenario_id, weather=weather, plant=plant, constraints=constraints, payment=payment)
run = st.button("Run optimization", type="primary")
if run or "result" not in st.session_state:
    try:
        dataset = generate_scenario(scenario_id, plant, None if weather == "Scenario default" else weather)
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
st.caption(f'Results use {dataset["scenario"]["weather"]} weather; budget ${limits["budget"]:,.0f}, '
           f'{limits["crewHours"]} crew-hours, {limits["inverterSpares"]} spare kits, '
           f'${result["paymentRate"]:,.2f}/MWh.')
cols = st.columns(4)
cols[0].metric("Baseline energy", f'{baseline["baselineMwh"]:,.1f} MWh')
cols[1].metric("Additional energy", f'{optimized["recoveredMwh"]:,.1f} MWh')
cols[2].metric("Maintenance spending", f'${optimized["spend"]:,.0f}')
cols[3].metric("Incremental net benefit", f'${optimized["netBenefit"]:,.0f}')
st.caption(f'Optimized resources: {optimized["crewHours"]} crew-hours, {optimized["inverterKits"]} inverter kits.')

st.subheader("Expected vs actual generation")
generation = pd.DataFrame({"Hour": [r["hour"] for r in dataset["hours"]],
                           "Expected healthy": [r["expectedMw"] for r in dataset["hours"]],
                           "Actual baseline": [r["actualMw"] for r in dataset["hours"]]})
lines = generation.melt("Hour", var_name="Generation", value_name="Power (MW)")
st.altair_chart(alt.Chart(lines).mark_line().encode(
    x=alt.X("Hour:Q", title="Hour of 14-day horizon"),
    y=alt.Y("Power (MW):Q", scale=alt.Scale(domain=[0, dataset["plant"]["acLimitMw"]])),
    color="Generation:N", tooltip=["Hour:Q", "Generation:N", alt.Tooltip("Power (MW):Q", format=".2f")]
).properties(height=300), width="stretch")

st.subheader("Strategy comparison")
comparison = pd.DataFrame([{"Strategy": label, "Total energy (MWh)": plan["planMwh"],
                            "Additional energy (MWh)": plan["recoveredMwh"], "Spending ($)": plan["spend"],
                            "Net benefit ($)": plan["netBenefit"], "Crew-hours": plan["crewHours"],
                            "Spare kits": plan["inverterKits"]}
                           for label, plan in [("No intervention", baseline), ("Largest gap first", gap),
                                               ("Financially optimized", optimized)]])
st.altair_chart(alt.Chart(comparison).mark_bar().encode(
    x=alt.X("Strategy:N", sort=comparison["Strategy"].tolist(), axis=alt.Axis(labelAngle=0)),
    y="Net benefit ($):Q", color=alt.Color("Strategy:N", legend=None),
    tooltip=["Strategy:N", alt.Tooltip("Net benefit ($):Q", format=",.2f")]
).properties(height=240), width="stretch")
st.dataframe(comparison, hide_index=True, width="stretch",
             column_config={key: st.column_config.NumberColumn(format="%.1f") for key in
                            ["Total energy (MWh)", "Additional energy (MWh)", "Net benefit ($)"]})

left, right = st.columns(2)
with left:
    st.subheader("Suspected loss causes")
    for diagnostic in result["diagnostics"]:
        st.markdown(f'**{diagnostic["sectionId"]} | {diagnostic["sectionName"]} ({diagnostic["acMw"]:g} MW AC)**')
        st.write(f'{diagnostic["cause"]} | {diagnostic["confidence"]} confidence')
        st.caption(f'Current gap (day 1, noon): {diagnostic["currentGapMw"]:.2f} MW | '
                   f'14-day gap: {diagnostic["gapMwh"]:.1f} MWh')
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
            st.write(" ".join(reasons) or "Other actions create greater total value within the shared resource limits.")
        if action["id"] in gap_ids and not chosen:
            st.write("Largest-gap-first selects this action based on its current MW gap.")
        elif chosen and action["id"] not in gap_ids:
            st.write("Financial optimization selects this for its future value; largest-gap-first does not.")
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
             "Actions run in parallel; crew-hours are a total resource limit, not a shift schedule.")
    st.write("Before completion, baseline losses persist. Inverter repair additionally shuts the section down "
             "during hours 8-11 of its 12-hour delay; that lost output is subtracted from recovery. "
             "Other actions retain the original zero-outage assumption. Snow output naturally rises from 8% "
             "to 35% at hour 18, 78% at hour 30, and 100% at hour 42 (tomorrow evening). "
             "Removal raises the snow factor to at least 92%, never above naturally shed output once clear.")
    st.write("The whole plant is simulated with each plan before applying grid caps; individual action benefits "
             "are never added together. Curtailment alone has no maintenance recovery. Grid caps may prevent "
             "otherwise recoverable energy from being exported. Fault diagnoses require alarms, snow observations, "
             "or synthetic inspection tags; unsupported output gaps are marked ambiguous.")
    st.caption(f'Optimized potential recovery excluded by grid caps: {optimized["excludedCurtailmentMwh"]:.1f} MWh; '
               f'largest-gap-first: {gap["excludedCurtailmentMwh"]:.1f} MWh.')
