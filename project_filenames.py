"""Shared presentation name for project JSON and Word downloads."""

import re
from decimal import Decimal


def cementing_program_basename(doc_control):
    """Filename-only view of Phase I metadata; never edit the report or sources."""
    parts = ["Cementing Program"]
    for field in ("job_type", "well_location", "well_name", "rig_name", "proposal_number", "revision_no"):
        value = doc_control.get(field)
        text = "" if value is None else str(value).strip()
        if field == "job_type":
            size = re.fullmatch(r'(CSG|LNR|TIE BACK LNR)\s+(\d{1,3}(?:\.\d{1,6})?)'
                                r'(?:\s+(\d{1,2})/(2|4|8|16|32|64))?\s*["″”]?', text)
            if size and (size[3] is None or int(size[3]) < int(size[4])):
                inches = Decimal(size[2])
                if size[3] is not None:
                    inches += Decimal(size[3]) / Decimal(size[4])
                text = f"{size[1]} {format(inches.normalize(), 'f')}"
        marker = {"proposal_number": "PR", "revision_no": "R"}.get(field)
        if marker:
            text = re.sub(rf"^(?:{marker}\s*#\s*)+", "", text, flags=re.IGNORECASE)
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', " ", text)
        text = " ".join(text.split()).rstrip(". ")
        if text:
            parts.append(f"{marker} #{text}" if marker else text)
    return " - ".join(parts)
