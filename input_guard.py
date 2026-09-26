"""Offer explicit repair before rendering bounded numeric widgets."""
import math
import hashlib
import streamlit as st


def _parse(raw, minimum=None, maximum=None, integer=False):
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (integer and not number.is_integer()):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if integer else number


def repair_invalid_inputs(specs, namespace):
    """Return True when the phase must pause for a user's explicit correction.

    Each specification is (container, field, label, minimum, maximum, integer).
    Canonical values remain unchanged until every proposed replacement passes.
    """
    invalid = []
    for container, field, label, minimum, maximum, integer in specs:
        raw = container.get(field)
        if _parse(raw, minimum, maximum, integer) is None:
            invalid.append((container, field, label, minimum, maximum, integer, raw))
    if not invalid:
        return False

    st.error("Some saved or calculated values fall outside the input limits. Review and apply corrections below; the existing values are preserved until then.")
    proposed = []
    for container, field, label, minimum, maximum, integer, raw in invalid:
        range_text = (f"{minimum if minimum is not None else 'any'}"
                      f" to {maximum if maximum is not None else 'any'}")
        field_id = hashlib.sha256(f"{namespace}:{label}:{field}".encode()).hexdigest()[:12]
        widget_key = f"_repair_{namespace}_{field_id}"
        entered = st.text_input(f"Correct {label} (current: {raw!s}; allowed: {range_text})",
                                value=str(raw) if raw is not None else "", key=widget_key)
        proposed.append((container, field, label, minimum, maximum, integer, entered, range_text))
    if st.button("Apply corrected values", key=f"_apply_repair_{namespace}"):
        replacements = []
        for container, field, label, minimum, maximum, integer, entered, range_text in proposed:
            parsed = _parse(entered, minimum, maximum, integer)
            if parsed is None:
                st.error(f"{label}: enter a valid number within {range_text}.")
            replacements.append((container, field, parsed))
        if all(parsed is not None for _, _, parsed in replacements):
            for container, field, parsed in replacements:
                container[field] = parsed
            st.rerun()
    return True
