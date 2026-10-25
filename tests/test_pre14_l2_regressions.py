"""Cumulative editor deltas must not erase a later measured density."""
from copy import deepcopy

import pandas as pd
import pytest
import test_audit_regressions as audit
import test_uat_round2_phase5_density as density
from phase_5_cement import build_components, calculate_base_results
from project_state import lab_source_signature


@pytest.fixture(scope="module")
def reviewed_plug():
    case = audit.AuditRegressions()
    return deepcopy(case.configured_app("CMT PLUG").session_state.to_dict())


def test_later_measured_density_survives_equal_default_name_change(reviewed_plug):
    case = density.Round2DensityUAT()
    state = deepcopy(reviewed_plug)
    state["cement_additives_dfs"]["Main"] = pd.DataFrame([
        density.row("O-GAS BLOCK", density=1.05),
        density.row("Micro Silica", "Dry Blend", density=2.3),
    ])
    app = case.app(audit.round_trip(state))
    case.phase(app, "phase5")
    original_generation = case.editor(app).proto.id
    other = app.session_state["cement_additives_dfs"]["Main"].iloc[1].copy()
    # First real edit: intentional Name-change reset, same catalog density.
    case.edit_rows(app, {"0": {"Name": "PK-GAS7"}})
    table = app.session_state["cement_additives_dfs"]["Main"]
    assert table.at[0, "Name"] == "PK-GAS7"
    assert table.at[0, "Density"] == 1.05
    before_measured = lab_source_signature(app.session_state, "Main")
    # Second, separate event: the new user action changes Density only. Keep
    # the earlier Name delta, as a mounted editor sends cumulative edits.
    case.edit_rows(app, {"0": {"Name": "PK-GAS7", "Density": 1.2}})
    assert app.session_state["cement_additives_dfs"]["Main"].at[0, "Density"] == 1.2
    assert lab_source_signature(app.session_state, "Main") != before_measured
    # A genuine identity change must retire the old source generation even
    # when normalization did not alter any catalog default cells.
    assert case.editor(app).proto.id != original_generation
    for phase in (None, "phase2_3", "phase5"):
        if phase is None:
            app.run()
            case.healthy(app)
        else:
            case.phase(app, phase)
        table = app.session_state["cement_additives_dfs"]["Main"]
        assert table.at[0, "Density"] == 1.2
        pd.testing.assert_series_equal(table.iloc[1], other)
    saved = audit.round_trip(app.session_state.to_dict())
    assert saved["cement_additives_dfs"]["Main"].at[0, "Density"] == 1.2
    restored = case.app(saved)
    case.phase(restored, "phase5")
    table = restored.session_state["cement_additives_dfs"]["Main"]
    assert table.at[0, "Density"] == 1.2
    visible = case.editor(restored).value
    assert visible.at[0, "Density"] == 1.2
    powders, liquids, salt = build_components(table)
    assert liquids[0]["density_ppg"] == 1.2 * (62.4 / 7.48051945)
    params = restored.session_state["cement_params"]["Main"]
    measured = calculate_base_results(params, 50., 118., powders, liquids, salt)
    default = table.copy(deep=True)
    default.at[0, "Density"] = 1.05
    assert measured != calculate_base_results(params, 50., 118., *build_components(default))
    # Genuine next Name change still resets its density and physical state,
    # while the independent row's measured value remains untouched.
    case.edit_rows(restored, {"0": {"Name": "Hidense"}})
    table = restored.session_state["cement_additives_dfs"]["Main"]
    assert table.at[0, "Density"] == 5.2
    assert table.at[0, "Physical State"] == "Powder"
    pd.testing.assert_series_equal(table.iloc[1], other)
