"""CT-only, recomputable report projections; no cement or pumping calculations."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from fractions import Fraction

from materials_db import CT_JOB

CONFIG_KEY = 'ct_stage_config'


def _decimal(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Phase V CT stages: a finite scalar volume is required.') from None


def decimal_text(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def allocate_stages(main_total, count=None):
    """Prefer whole barrels for whole totals, tenths otherwise; retain residuals."""
    total = _decimal(main_total)
    if total <= 0:
        raise ValueError('Phase V CT stages: Main volume must be positive.')
    if total > 36:
        raise ValueError('Phase V CT stages: Main volume exceeds the supported 36 bbl capacity.')
    if total <= 12:
        if count is not None:
            raise ValueError('Phase V CT stages: use one implicit stage at Main volume ≤12 bbl.')
        return (total,)
    if count is None:
        raise ValueError('Phase V CT stages: select 2 or 3 stages for Main volume >12 bbl.')
    if type(count) is not int or count not in (2, 3):
        raise ValueError('Phase V CT stages: stage count must be the integer 2 or 3.')
    if total > 12 * count:
        raise ValueError(f'Phase V CT stages: {count} stages cannot hold Main volume; maximum 12 bbl per stage.')
    with localcontext() as ctx:
        ctx.prec = max(50, len(total.as_tuple().digits) + abs(total.as_tuple().exponent) + 10)
        unit = Decimal(1) if total == total.to_integral_value() else Decimal('.1')
        base = (total / count).quantize(unit, rounding=ROUND_HALF_UP)
        stages = (base,) * (count - 1) + (total - base * (count - 1),)
        if not all(0 < v <= 12 for v in stages):
            # Near capacity, putting the entire residual last can exceed 12.
            # Distribute whole field units first, then the exact finer residual.
            base = (total / count).quantize(unit, rounding=ROUND_FLOOR)
            values = [base] * count
            remaining = total - base * count
            for i in range(count - 1):
                if remaining >= unit:
                    values[i] += unit
                    remaining -= unit
            values[-1] += remaining
            stages = tuple(values)
        # Never round away a physical limit or change the source total.
        if not all(0 < v <= 12 for v in stages) or sum(stages) != total:
            raise ValueError('Phase V CT stages: no positive allocation within 12 bbl per stage.')
        return stages


def main_volume(state):
    cfg = state.get('fluids_config', {})
    source = cfg.get('params', {}).get('Main', state.get('fluid_data', {}).get('Main', {}))
    return _decimal(source.get('volume'))


def validate_stage_config(state):
    """Admission is strict; missing choice is a valid unfinished project draft."""
    if CONFIG_KEY not in state:
        return None
    record = state[CONFIG_KEY]
    if (not isinstance(record, dict) or set(record) != {'job_type', 'main_volume', 'count'}
            or record.get('job_type') != CT_JOB or not isinstance(record.get('main_volume'), str)):
        raise ValueError('Phase V CT stages: invalid job-scoped stage selection record.')
    if state.get('job_type') != CT_JOB or 'Main' not in state.get('fluids_config', {}).get('active', []):
        raise ValueError('Phase V CT stages: stage selection applies only to active CT Main.')
    if _decimal(record['main_volume']) != main_volume(state):
        raise ValueError('Phase V CT stages: stale Main volume; select the stage count again.')
    if record['count'] is None:
        raise ValueError('Phase V CT stages: select the integer stage count 2 or 3.')
    allocate_stages(main_volume(state), record['count'])
    return record['count']


def ct_stage_projection(state):
    """Canonical consumer for Phase V and future CT report/procedure integration."""
    if state.get('job_type') != CT_JOB or 'Main' not in state.get('fluids_config', {}).get('active', []):
        return None
    count = validate_stage_config(state)
    total = main_volume(state)
    cement = allocate_stages(total, count)
    p = state.get('cement_params', {}).get('Main', {})
    water, dead = _decimal(p.get('mix_water')), _decimal(p.get('dead_vol'))
    if water < 0 or dead < 0:
        raise ValueError('Phase V CT stages: mixing water and Dead Volume must be nonnegative.')
    # Match the unchanged Cement Program's existing float addition / Note total.
    source_water = _decimal(float(water) + float(dead))
    with localcontext() as ctx:
        ctx.prec = max(50, len(source_water.as_tuple().digits) + abs(source_water.as_tuple().exponent) + 10)
        displayed = source_water.quantize(Decimal('.1'), rounding=ROUND_HALF_UP)
        # Exact rational largest-remainder allocation at the existing Note precision.
        units = int(displayed * 10)
        shares = [Fraction(source_water) * 10 * Fraction(v) / Fraction(total) for v in cement]
        whole = [x.numerator // x.denominator for x in shares]
        order = sorted(range(len(whole)), key=lambda i: (-(shares[i] - whole[i]), i))
        for i in order[:units - sum(whole)]:
            whole[i] += 1
        stage_water = tuple(Decimal(x) / 10 for x in whole)
    return {'count': len(cement), 'source_main_bbl': total, 'cement_bbl': cement,
            'source_water_bbl': source_water, 'display_water_bbl': displayed,
            'water_bbl': stage_water, 'tank_name': p.get('tank_name')}


def stage_note(projection):
    cement = ' + '.join(map(decimal_text, projection['cement_bbl']))
    water = ' + '.join(map(decimal_text, projection['water_bbl']))
    return f'Main cement stages (bbl): {cement}. Mixing water stages (bbl): {water}.'
