"""Keep dynamic Streamlit grids mounted while their edited values change."""

import pandas as pd
import streamlit as st


def persistent_data_editor(data: pd.DataFrame, *, key: str, **kwargs) -> pd.DataFrame:
    """Use a stable source frame for a dynamic editor until it is unmounted.

    Streamlit includes the entire input DataFrame in the widget identity for
    ``num_rows='dynamic'``. Feeding its edited result straight back on the
    next rerun recreates the widget, dropping the pending browser edit. The
    widget's own edit state is applied to this unchanged source instead; the
    caller still receives the current edits on every rerun for calculations.

    After navigation removes the widget, a fresh mount starts from the latest
    canonical data, so edits also survive leaving and returning to the phase.
    A changed key (for an explicit lab sync or project load) starts fresh too.
    """
    source_key = f"_editor_source_{key}"
    if key not in st.session_state or source_key not in st.session_state:
        st.session_state[source_key] = data.copy(deep=True)
    return st.data_editor(st.session_state[source_key], key=key, **kwargs)
