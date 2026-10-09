"""Fann 35 / R1B1 / Spring 1.0 CEMCADE Bingham compatibility and Lab inputs.

Float32 stores and NR vertex/accumulation order follow the owner specification.
No prior fit is used as a seed. Blind-1 retains the documented 0.002 cP gap.
"""
import math
import struct

def f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]
RB = 0.01724500022828579
LB = 0.03799999877810478
RR = 0.018415000289678574
GEOM = 1.0640000104904175
K = 0.0022121199872344732
DEG2RAD = 0.01745329238474369
RAD2DEG = 57.2957763671875
RPM2RADS = 0.10471975803375244
RADS2RPM = 9.549296379089355
INV2PI = 0.15915493667125702
INV4PI = 0.07957746833562851
TWOPI = 6.2831854820251465
FIT_2PI = 6.283180236816406
STEP = 1.0499999523162842

def _calculate_cemcade_bingham(readings):
    # CFW float32 angular-unit storage round trip; preserve incoming row order.
    pairs_input = [(_numeric(r), _numeric(d)) for r, d in readings]
    valid = [(r, d) for r, d in pairs_input if r is not None and d is not None and (r > 0) and (d > 0)]
    if len(valid) < 2:
        raise ValueError('At least two positive readings required')
    pairs = [(f32(f32(f32(r) * RPM2RADS) * RADS2RPM), f32(f32(f32(d) * DEG2RAD) * RAD2DEG)) for r, d in valid]
    q = RR / RB
    ss = f32(K / GEOM / (RB * RB * LB * FIT_2PI) * DEG2RAD)
    rs = f32(2 * q * q / (q * q - 1) * RPM2RADS)
    x = [f32(rs * r) for r, d in pairs]
    y = [f32(ss * d) for r, d in pairs]
    # Numerical Recipes unweighted fit: OLS is the seed, never the final result.
    sx = sy = 0.0
    for a, b in zip(x, y):
        sx = f32(sx + a)
        sy = f32(sy + b)
    xm = f32(sx / len(x))
    st2 = b = 0.0
    for a, c in zip(x, y):
        te = a - xm
        t = f32(te)
        st2 = f32(st2 + te * t)
        b = f32(b + t * c)
    mu = f32(b / st2)
    ty = f32((sy - sx * mu) / len(x))
    seed = (ty, mu)
    neval = 0
    if ty < 0:
        mu = f32(sum((a * b for a, b in zip(x, y))) / sum((a * a for a in x)))
        ty = 0.0
    else:
        torque = [f32(K / GEOM / LB * d * DEG2RAD) for r, d in pairs]
        omega = [f32(r * RPM2RADS) for r, d in pairs]

        # Nonlinear Couette objective (bob / partial / fully yielded regions).
        def objective(p):
            t, m = p
            if t < 0:
                return 1000.0
            if m == 0:
                raise ValueError('Bingham viscosity is zero')
            tb = f32(RB * RB * abs(t) * TWOPI)
            tr = f32(RR * RR * abs(t) * TWOPI)
            sse = 0.0
            for X, o in zip(torque, omega):
                if X < tb:
                    pred = 0.0
                else:
                    rat = f32(max(1.0, math.sqrt(f32(X * INV2PI / abs(t))) / RB)) if t != 0 and X < tr else f32(RR / RB)
                    tmp = f32((rat * rat - 1) / (rat * rat) * X * INV4PI)
                    ec = f32(tmp / (RB * RB))
                    pred = (ec - math.log(rat) * abs(t)) / m
                e = f32(pred - o)
                sse = f32(sse + e * e)
            return sse
        # Preserve NR simplex vertex order and float32 coordinate stores.
        p = [[ty, mu], [ty, f32(mu * STEP)], [f32(ty * STEP) if ty != 0 else 2.0, mu]]
        vals = [objective(v) for v in p]
        ps = [f32(f32(p[0][j] + p[1][j]) + p[2][j]) for j in range(2)]

        def attempt(ihi, fac):
            f1 = f32((1 - fac) / 2)
            f2 = f32(f1 - fac)
            pt = [f32(ps[j] * f1 - p[ihi][j] * f2) for j in range(2)]
            v = objective(pt)
            if v < vals[ihi]:
                vals[ihi] = v
                for j in range(2):
                    ps[j] = f32(ps[j] + pt[j] - p[ihi][j])
                    p[ihi][j] = pt[j]
            return v
        neval = 0
        while neval < 5000:
            ilo = 0
            if vals[0] > vals[1]:
                ihi, inhi = (0, 1)
            else:
                ihi, inhi = (1, 0)
            for i in range(3):
                if vals[i] <= vals[ilo]:
                    ilo = i
                if vals[i] > vals[ihi]:
                    inhi, ihi = (ihi, i)
                elif vals[i] > vals[inhi] and i != ihi:
                    inhi = i
            denom = abs(vals[ihi]) + abs(vals[ilo])
            rtol = 2 * abs(vals[ihi] - vals[ilo]) / denom if denom else 0.0
            if rtol < 0.01:
                break
            neval += 2
            v = attempt(ihi, -1.0)
            if v <= vals[ilo]:
                attempt(ihi, 2.0)
            elif v >= vals[inhi]:
                save = vals[ihi]
                v = attempt(ihi, 0.5)
                if v >= save:
                    for i in range(3):
                        if i != ilo:
                            p[i] = [f32(0.5 * (p[i][j] + p[ilo][j])) for j in range(2)]
                            vals[i] = objective(p[i])
                    neval += 2
                    ps = [f32(f32(p[0][j] + p[1][j]) + p[2][j]) for j in range(2)]
            else:
                neval -= 1
        if neval >= 5000:
            raise ValueError('Bingham fit did not converge within 5000 evaluations')
        ty, mu = p[ilo]
    iod = max(0.0, 1 - math.sqrt(sum(((ty + mu * a - b) ** 2 for a, b in zip(x, y))) / len(x)) / (sum(y) / len(y)))
    pv, oilfield_ty = (mu * 1000, ty * 2.088543)
    if not all((math.isfinite(v) for v in (pv, oilfield_ty, iod))) or pv <= 0:
        raise ValueError('Bingham fit produced an invalid result')
    return {'pv_cp': pv, 'ty_lbf_100ft2': oilfield_ty, 'iod': iod, 'fallback_to_newtonian': seed[0] < 0, 'is_valid_bingham': oilfield_ty > 0, 'validation_message': '' if oilfield_ty > 0 else 'Data Inconsistent: Ty must be greater than 0', 'valid_point_count': len(valid), 'ols_ty_pa': seed[0], 'ols_mu_pa_s': seed[1], 'amoeba_eval_count': neval}

def calculate_cemcade_bingham(readings):
    """Fresh fit; precision follows the owner specification, sections 6–15."""
    try:
        return _calculate_cemcade_bingham(readings)
    except (OverflowError, ZeroDivisionError, struct.error):
        raise ValueError('Bingham fit cannot resolve these finite readings') from None
RPM_ORDER = (300, 200, 100, 60, 30, 6, 3)
RHEOLOGY_DATASETS = (('surface_down', 'Surface — Ramp-Down'), ('bhct_up', 'BHCT — Ramp-Up'), ('bhct_down', 'BHCT — Ramp-Down'))

def _numeric(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('Rheology readings must be finite numeric text or numbers')
    if isinstance(value, str) and (not value.strip()):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValueError('Rheology readings must be finite numeric text or numbers') from None
    if not math.isfinite(number):
        raise ValueError('Rheology readings must be finite')
    return number

def _gel(value):
    if value == '-':
        return value
    return _numeric(value)

def new_rheology_dataset():
    return {'selected': False, 'readings': {str(rpm): '' for rpm in RPM_ORDER}, 'gel_10_sec': '', 'gel_10_min': ''}

def validate_rheology_inputs(data):
    """Accept incomplete drafts, reject malformed JSON before state replacement."""
    if not isinstance(data, dict) or set(data) - {key for key, _ in RHEOLOGY_DATASETS}:
        raise ValueError('Rheology contains an invalid dataset')
    for row in data.values():
        if not isinstance(row, dict) or set(row) - {'selected', 'readings', 'gel_10_sec', 'gel_10_min'}:
            raise ValueError('Rheology dataset has an invalid shape')
        if not isinstance(row.get('selected', False), bool):
            raise ValueError('Rheology selection must be boolean')
        readings = row.get('readings', {})
        if not isinstance(readings, dict) or set(readings) - {str(rpm) for rpm in RPM_ORDER}:
            raise ValueError('Rheology contains an unexpected RPM')
        for value in readings.values():
            _numeric(value)
        for field in ('gel_10_sec', 'gel_10_min'):
            _gel(row.get(field, ''))

def build_rheology(qc):
    """Recompute all selected datasets; hidden inputs stay canonical drafts."""
    data = qc.get('rheology', {})
    if not isinstance(data, dict) or set(data) - {key for key, _ in RHEOLOGY_DATASETS}:
        raise ValueError('Rheology contains an invalid dataset')
    for row in data.values():
        if not isinstance(row, dict) or not isinstance(row.get('selected', False), bool):
            raise ValueError('Rheology selection must be boolean')
    validate_rheology_inputs({key: row for key, row in data.items() if row.get('selected', False)})
    result = {}
    selected = 0
    for key, label in RHEOLOGY_DATASETS:
        source = data.get(key, {})
        row = {'selected': source.get('selected', False), 'readings': {}, 'gel_10_sec': '-', 'gel_10_min': '-', 'is_valid_bingham': False, 'validation_message': '', 'pv_cp': None, 'ty_lbf_100ft2': None, 'iod': None}
        if row['selected']:
            selected += 1
            row['readings'] = {str(rpm): _numeric(source.get('readings', {}).get(str(rpm))) for rpm in RPM_ORDER}
            try:
                fit = calculate_cemcade_bingham(((rpm, row['readings'][str(rpm)]) for rpm in RPM_ORDER))
                row.update(fit)
                for field in ('gel_10_sec', 'gel_10_min'):
                    row[field] = _gel(source.get(field, ''))
                    if row[field] is None:
                        row['is_valid_bingham'] = False
                        row['validation_message'] = "Enter both Gel fields (finite number or '-')"
            except (ValueError, ZeroDivisionError, OverflowError) as exc:
                row['validation_message'] = str(exc)
                row['is_valid_bingham'] = False
        result[key] = row
    issues = [f"{label}: {result[key]['validation_message']}" for key, label in RHEOLOGY_DATASETS if result[key]['selected'] and (not result[key]['is_valid_bingham'])]
    if not selected:
        issues.append('Select at least one Rheology dataset')
    return (result, issues)

def validate_rheology_results(qc):
    result, issues = build_rheology(qc)
    if issues:
        raise ValueError('; '.join(issues))
    return result
