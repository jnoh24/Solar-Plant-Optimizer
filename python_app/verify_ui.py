"""Exercise Streamlit widgets and reruns without a browser."""

from pathlib import Path
import json
import unittest
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetState
from model import SCENARIOS


class InterfaceVerification(unittest.TestCase):
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
