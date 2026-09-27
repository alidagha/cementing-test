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

    Commit each browser edit before a phase change can unmount its widget.
    A changed key (for an explicit lab sync or project load) starts fresh.
    """
    persist_to = kwargs.pop("persist_to", None)
    source_key = f"_editor_source_{key}"
    if key not in st.session_state or source_key not in st.session_state:
        st.session_state[source_key] = data.copy(deep=True)
    return st.data_editor(
        st.session_state[source_key], key=key,
        on_change=_commit_editor_change,
        args=(key, source_key, persist_to), **kwargs
    )


def _commit_editor_change(key: str, source_key: str, persist_to: tuple[str, str | None] | None) -> None:
    """Save the editor's pending changes before Streamlit selects the next page.

    An on_change callback runs before the main script. Without it a click on a
    different phase can skip rendering this editor and lose its latest edit.
    The source frame stays fixed while the widget is mounted: changing it here
    would reset Streamlit's edited-row indices on the next rerun.
    """
    if persist_to is None:
        return
    edits = st.session_state.get(key)
    source = st.session_state.get(source_key)
    if not isinstance(edits, dict) or not isinstance(source, pd.DataFrame):
        return

    saved = source.copy(deep=True).reset_index(drop=True)
    for position, changes in edits.get("edited_rows", {}).items():
        index = int(position)
        if 0 <= index < len(saved):
            for column, value in changes.items():
                if column in saved.columns:
                    saved.at[index, column] = value
    deleted = {int(index) for index in edits.get("deleted_rows", [])}
    if deleted:
        saved = saved.drop(index=[index for index in deleted if index in saved.index])
    added = edits.get("added_rows", [])
    if added:
        saved = pd.concat([saved, pd.DataFrame(added).reindex(columns=saved.columns)], ignore_index=True)
    saved = saved.reset_index(drop=True)

    state_key, item_key = persist_to
    if item_key is None:
        st.session_state[state_key] = saved
    else:
        st.session_state.setdefault(state_key, {})[item_key] = saved
