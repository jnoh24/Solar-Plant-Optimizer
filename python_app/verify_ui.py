"""Exercise Streamlit widgets and reruns without a browser."""

from pathlib import Path
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetState
from model import SCENARIOS


class InterfaceVerification(unittest.TestCase):
    def test_dashboard_without_legacy_data(self):
        original_open = Path.open

        def without_reference(path, *args, **kwargs):
            if path.name in ("reference.json", "export_reference.js", "simulator.js"):
                raise AssertionError("Dashboard attempted to read a legacy dependency")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", without_reference):
            app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)

    def test_new_assumptions_and_observed_forecast_separation(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=20).run()
        observations = app.session_state["result"]["dataset"]["observations"]
        app.number_input(key="snow_clearance").set_value(0.0).run()
        next(button for button in app.button if button.label == "Run optimization").click().run()
        result = app.session_state["result"]
        self.assertEqual(result["dataset"]["observations"], observations)
        self.assertEqual(result["gapPlan"]["recoveredMwh"], 0)
        app.number_input(key="snow_clearance").set_value(672.0).run()
        next(button for button in app.button if button.label == "Run optimization").click().run()
        self.assertEqual(app.session_state["result"]["dataset"]["assumptions"]["snowClearanceHours"], 672)
        app.selectbox(key="scenario").set_value("module-degradation").run()
        app.number_input(key="degradation").set_value(25.0).run()
        next(button for button in app.button if button.label == "Run optimization").click().run()
        result = app.session_state["result"]
        self.assertEqual(result["dataset"]["assumptions"]["degradationLossPct"], 25)
        self.assertEqual(result["candidates"][0]["effectiveness"], 0)
        self.assertEqual(result["optimizedPlan"]["actions"], [])
        self.assertEqual(result["gapPlan"]["recoveredMwh"], 0)
        next(button for button in app.button if button.label == "Reset demo").click().run()
        self.assertEqual(app.number_input(key="degradation").value, 6)
        self.assertEqual(app.number_input(key="snow_clearance").value, 24)
        self.assertEqual(len(app.exception), 0)
        # A session opened before the update is safely recalculated on refresh.
        previous_shape = deepcopy(app.session_state["result"])
        previous_shape["dataset"].pop("observations")
        app.session_state["result"] = previous_shape
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("observations", app.session_state["result"]["dataset"])

    def test_run_edit_reset_and_scenarios(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["result"]["optimizedPlan"]["actions"][0]["id"], "D-inverter")
        original = app.session_state["result"]["optimizedPlan"]["netBenefit"]
        app.number_input(key="spares").set_value(0).run()
        self.assertEqual(app.session_state["result"]["optimizedPlan"]["netBenefit"], original)
        self.assertEqual(len(app.info), 1)
        next(button for button in app.button if button.label == "Run optimization").click().run()
        self.assertEqual(app.session_state["result"]["optimizedPlan"]["actions"], [])
        self.assertEqual(len(app.exception), 0)
        next(button for button in app.button if button.label == "Reset demo").click().run()
        self.assertEqual(app.number_input(key="spares").value, 1)
        self.assertEqual(app.session_state["result"]["optimizedPlan"]["netBenefit"], original)
        app.selectbox(key="weather").set_value("cloudy").run()
        next(button for button in app.button if button.label == "Run optimization").click().run()
        self.assertEqual(app.session_state["result"]["dataset"]["scenario"]["weather"], "cloudy")
        # AppTest has no editor API; submit its native serialized widget state.
        editor = app.dataframe[0].proto.id
        next(button for button in app.button if button.label == "Run optimization").click()
        states = app._tree.get_widget_states()
        states.widgets.append(WidgetState(id=editor, string_value=json.dumps({
            "edited_rows": {"0": {"acMw": 24, "name": "Edited North"}},
            "added_rows": [], "deleted_rows": []})))
        app._run(states)
        self.assertEqual(app.session_state["result"]["dataset"]["plant"]["sections"][0]["acMw"], 24)
        self.assertEqual(app.session_state["result"]["dataset"]["plant"]["sections"][0]["name"], "Edited North")
        next(button for button in app.button if button.label == "Reset demo").click().run()
        self.assertEqual(app.session_state["result"]["dataset"]["plant"]["sections"][0]["acMw"], 8)
        for scenario in app.selectbox(key="scenario").options:
            # Options are formatted labels; use the underlying scenario IDs.
            scenario_id = next(s["id"] for s in SCENARIOS if s["name"] == scenario)
            app.selectbox(key="scenario").set_value(scenario_id).run()
            next(button for button in app.button if button.label == "Run optimization").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["result"]["dataset"]["scenario"]["id"], scenario_id)
        app.number_input(key="budget").set_value(1000).run()
        app.number_input(key="crew").set_value(1).run()
        next(button for button in app.button if button.label == "Run optimization").click().run()
        self.assertEqual(app.session_state["result"]["optimizedPlan"]["actions"], [])
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
