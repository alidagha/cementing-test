"""Shared Formation input widgets and presentation of the prepared B-1 result.

Reads canonical source values; writes only explicit profile/mode edits and
transient widget metadata. No pressure, placement, crossing or security math.
"""
from copy import deepcopy

import pandas as pd
import streamlit as st

from cement_chart_model import PORE_FIELD, FRAC_FIELD, chart_readiness
from project_state import invalidate_document, reconcile_formation_profile
from well_profile import tvd_at_md

SAFE = ('Static Well Security: SAFE — Hydrostatic pressure remains within the '
        'Pore–Fracture window throughout the current open-hole interval.')
UNAVAILABLE = ('Advanced Formation Profile is not applicable because no current '
               'open-hole interval is exposed for this job.')


def _flush_stations(state):
    """Commit mounted browser cells before mode/row callbacks retire their keys."""
    config = state.get('formation_pressure_config', {})
    if config.get('mode') != 'advanced':
        return
    before = deepcopy(config['profile'])
    for index, field, key, epoch in state.get('_formation_widgets', []):
        if epoch == state.get('_formation_epoch', 0) and key in state and index < len(config['profile']):
            config['profile'][index][field] = state[key]
    if before != config['profile']:
        invalidate_document(state)


def _commit_mode(key):
    state = st.session_state
    _flush_stations(state)
    config = state.setdefault('formation_pressure_config', {'mode': 'basic', 'profile': []})
    if config['mode'] != state[key]:
        config['mode'] = state[key]
        invalidate_document(state)


def _commit_station(index, field, key, epoch):
    state = st.session_state
    config = state.get('formation_pressure_config', {})
    rows = config.get('profile', [])
    if (config.get('mode') != 'advanced' or epoch != state.get('_formation_epoch', 0)
            or key not in state or not 0 <= index < len(rows)
            or (field == 'md_m' and index in (0, len(rows)-1))):
        return
    if rows[index][field] != state[key]:
        rows[index][field] = state[key]
        invalidate_document(state)


def _change_rows(index, action, epoch):
    state = st.session_state
    config = state.get('formation_pressure_config', {})
    if config.get('mode') != 'advanced' or epoch != state.get('_formation_epoch', 0):
        return
    _flush_stations(state)
    rows = config['profile']
    if action == 'add' and 0 <= index < len(rows)-1:
        rows.insert(index+1, {'md_m': None, 'pore_psi': None, 'frac_psi': None})
    elif action == 'remove' and 0 < index < len(rows)-1:
        rows.pop(index)
    else:
        return
    state['_formation_epoch'] = epoch+1
    invalidate_document(state)


def render_formation_inputs(state, commit_basic):
    """Native row widgets enforce endpoint/TVD locking before any edit occurs."""
    st.subheader('Formation Pressure')
    config = state.get('formation_pressure_config', {'mode': 'basic', 'profile': []})
    load = str(state.get('last_loaded_hash', 'new'))
    mode_key = f'_formation_mode_{load}'
    state[mode_key] = config['mode']
    st.selectbox('Formation Pressure Mode', ['basic', 'advanced'], key=mode_key,
                 format_func=lambda mode: 'Basic' if mode == 'basic' else 'Advanced Formation Profile',
                 on_change=_commit_mode, args=(mode_key,))
    if config['mode'] == 'basic':
        for column, field, label in zip(st.columns(2), (PORE_FIELD, FRAC_FIELD),
                                       ('Pore Gradient (pcf EMW)', 'Fracture Gradient (pcf EMW)')):
            with column:
                key = f'_w_{field}'
                state[key] = state.get(field)
                st.number_input(label, value=None, step=1.0, key=key,
                                on_change=commit_basic, args=(field,),
                                help='One finite positive equivalent mud weight; Pore must be less than Fracture.')
        return
    try:
        domain = reconcile_formation_profile(state)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        st.warning(str(exc))
        return
    if domain is None:
        return  # The shared live panel presents the applicability explanation.
    st.caption('Endpoint MD and every TVD are read-only. Enter pressures in psig; add intermediate stations explicitly.')
    for column, heading in zip(st.columns([1.1, 1.1, 1.6, 1.6, 1.4]),
                               ('MD (m)', 'TVD (m)', 'Pore Pressure (psig)', 'Fracture Pressure (psig)', 'Stations')):
        column.markdown(f'**{heading}**')
    epoch = state.get('_formation_epoch', 0)
    state['_formation_widgets'] = []
    rows = config['profile']
    for index, row in enumerate(rows):
        role = 'Top endpoint' if index == 0 else 'Bottom endpoint' if index == len(rows)-1 else f'Station {index+1}'
        columns = st.columns([1.1, 1.1, 1.6, 1.6, 1.4])
        for column, field, title in ((columns[0], 'md_m', 'MD (m)'),
                                     (columns[2], 'pore_psi', 'Pore Pressure (psig)'),
                                     (columns[3], 'frac_psi', 'Fracture Pressure (psig)')):
            with column:
                if field == 'md_m' and index in (0, len(rows)-1):
                    st.text(f"{row[field]:.1f}")
                    continue
                key = f'_formation_{epoch}_{index}_{field}_{load}'
                state[key] = row[field]
                state['_formation_widgets'].append((index, field, key, epoch))
                st.number_input(f'{title} — {role}', value=None, min_value=0.0, step=1.0, key=key,
                                on_change=_commit_station, args=(index, field, key, epoch))
        with columns[1]:
            try:
                tvd = tvd_at_md(state['well_geometry'], [row['md_m']])[0] if row['md_m'] is not None else None
            except ValueError:
                tvd = None  # Undefined display only; B-1 readiness exposes the source issue.
            st.text('—' if tvd is None else f'{tvd:.1f}')
        with columns[4]:
            if index < len(rows)-1:
                st.button(f'Add station below {role}', key=f'_formation_add_{epoch}_{index}_{load}',
                          on_click=_change_rows, args=(index, 'add', epoch))
            if 0 < index < len(rows)-1:
                st.button(f'Remove {role}', key=f'_formation_remove_{epoch}_{index}_{load}',
                          on_click=_change_rows, args=(index, 'remove', epoch))


def render_static_security(state):
    """Both phases use one current B-1 preparation and format its records only."""
    st.subheader('Static Well Security')
    if state.get('job_type') in ('CMT PLUG', 'CMT SQUEEZE', 'CMT PLUG WITH CT'):
        st.info('Static Well Security: Not applicable for Plug/Squeeze.')
        return
    domain_resolved = False
    try:
        domain = reconcile_formation_profile(state)
        domain_resolved = True
    except (ValueError, TypeError, KeyError, OverflowError):
        pass  # The same unresolved source is reported by authoritative readiness below.
    chart = chart_readiness(state, include_fluids=True)
    for issue in chart['issues']:
        st.warning(issue)
    for warning in chart['warnings']:
        if not warning.startswith('Static Well Security:'):
            st.warning(warning)
    if (state.get('formation_pressure_config', {}).get('mode') == 'advanced'
            and domain_resolved and domain is None):
        st.info(UNAVAILABLE)
        return
    security = chart['model']['static_security'] if chart['model'] is not None else None
    if chart['issues'] or security is None:
        st.info('Static Well Security is not available yet. Complete Formation Pressure and final fluid inputs.')
        return
    if security['domain'] is None:
        st.info('Static Well Security: no current open-hole interval is exposed for this job.')
        return
    if security['status'] == 'safe':
        st.success(SAFE)
    for key, label, maximum, risk in (
            ('frac_violations', 'Fracture limit exceeded', 'exceedance', 'formation breakdown / lost circulation'),
            ('pore_violations', 'Underbalance detected', 'underbalance', 'formation influx / well flow')):
        for row in security[key]:
            st.warning(f"{label} from MD {row['start_md_m']:.1f} m to {row['end_md_m']:.1f} m. "
                       f"Maximum {maximum}: {row['max_delta_psi']:.0f} psi at MD {row['max_at_md_m']:.1f} m / "
                       f"TVD {row['max_at_tvd_m']:.1f} m. Risk of {risk}.")
    if security['crossings']:
        st.caption('Crossings / boundary contacts')
        st.dataframe(pd.DataFrame([{'Boundary': row['boundary'], 'MD (m)': f"{row['md_m']:.1f}",
            'TVD (m)': f"{row['tvd_m']:.1f}", 'Pressure (psi)': f"{row['pressure_psi']:.0f}"}
            for row in security['crossings']]), hide_index=True)
