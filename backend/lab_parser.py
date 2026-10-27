"""Deterministic extraction preserving printed numbers, units and reference ranges."""

import math
import re

# These adult examples are educational defaults, not universal laboratory intervals.
PANELS = [
    (
        "Hemoglobin",
        r"hemoglobin|haemoglobin|hgb|hb",
        12,
        17.5,
        "g/dL",
        "Carries oxygen in blood.",
    ),
    (
        "White blood cells",
        r"white blood cells?|wbc|total leucocyte count",
        4,
        11,
        "10^3/uL",
        "Cells involved in immune response.",
    ),
    (
        "Platelets",
        r"platelets?|platelet count",
        150,
        450,
        "10^3/uL",
        "Cells involved in blood clotting.",
    ),
    (
        "Red blood cells",
        r"red blood cells?|rbc",
        4,
        6,
        "10^6/uL",
        "Oxygen-carrying blood cells.",
    ),
    ("MCV", r"mcv", 80, 100, "fL", "Average size of red blood cells."),
    (
        "Hematocrit",
        r"hematocrit|haematocrit|hct",
        36,
        53,
        "%",
        "Proportion of blood occupied by red cells.",
    ),
    (
        "Glucose",
        r"glucose|fasting blood sugar|fbs",
        70,
        99,
        "mg/dL",
        "Blood sugar; the example interval assumes fasting.",
    ),
    (
        "HbA1c",
        r"hba1c|glycated hemoglobin",
        4,
        5.6,
        "%",
        "Reflects blood sugar over the preceding months.",
    ),
    (
        "Cholesterol",
        r"(?:total )?cholesterol",
        0,
        200,
        "mg/dL",
        "A blood fat measurement.",
    ),
    (
        "LDL",
        r"ldl(?: cholesterol)?",
        0,
        100,
        "mg/dL",
        "One component of the cholesterol profile.",
    ),
    (
        "HDL",
        r"hdl(?: cholesterol)?",
        40,
        100,
        "mg/dL",
        "One component of the cholesterol profile.",
    ),
    (
        "Triglycerides",
        r"triglycerides?",
        0,
        150,
        "mg/dL",
        "Another blood fat measurement.",
    ),
    (
        "Creatinine",
        r"(?:serum )?creatinine",
        0.6,
        1.3,
        "mg/dL",
        "Used with other information to assess kidney function.",
    ),
    (
        "Urea",
        r"(?:blood )?urea",
        15,
        40,
        "mg/dL",
        "A waste product interpreted with kidney and hydration context.",
    ),
    (
        "Sodium",
        r"sodium",
        135,
        145,
        "mmol/L",
        "An electrolyte involved in fluid balance.",
    ),
    (
        "Potassium",
        r"potassium",
        3.5,
        5.1,
        "mmol/L",
        "An electrolyte involved in muscle and nerve function.",
    ),
    (
        "ALT",
        r"alt|sgpt",
        0,
        40,
        "U/L",
        "An enzyme interpreted with liver and other clinical information.",
    ),
    (
        "AST",
        r"ast|sgot",
        0,
        40,
        "U/L",
        "An enzyme that may arise from several tissues.",
    ),
    ("TSH", r"tsh", 0.4, 4, "mIU/L", "A hormone used to assess thyroid function."),
    ("Free T4", r"free t4|ft4", 0.8, 1.8, "ng/dL", "A thyroid hormone measurement."),
    (
        "Vitamin D",
        r"vitamin d(?: total)?|25[- ]oh vitamin d",
        20,
        50,
        "ng/mL",
        "A nutrient measurement related to bone health.",
    ),
    (
        "Vitamin B12",
        r"vitamin b12|b12",
        200,
        900,
        "pg/mL",
        "A nutrient measurement interpreted with symptoms and other tests.",
    ),
]
NUMBER = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?"
RANGE = re.compile(
    r"(?:ref(?:erence)?(?:\s*(?:range|interval))?|range)?\s*[:=]?\s*("
    + NUMBER
    + r")\s*[-–—]\s*("
    + NUMBER
    + r")",
    re.I,
)
UNIT = re.compile(
    r"^(?:10\^[36]/[uµμ]L|x10\^[36]/[uµμ]L|mg/dL|g/dL|ng/dL|ng/mL|pg/mL|mIU/L|uIU/mL|mmol/L|U/L|fL|%)\b|^%",
    re.I,
)


def normalize(unit):
    return (
        unit.lower()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("x10", "10")
        .replace(" ", "")
    )


def parse(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        for name, alias, low, high, expected, explanation in PANELS:
            match = re.match(
                r"^(?:" + alias + r")\b\s*[:=]?\s*(" + NUMBER + r")\s*(.*)$", line, re.I
            )
            if not match:
                continue
            original = match[1]
            value = float(original.replace(",", ""))
            if not math.isfinite(value):
                continue
            remainder = match[2].strip()
            unit_match = UNIT.match(remainder)
            # Unknown units are preserved; never silently converted to the default unit.
            unit = (
                unit_match[0]
                if unit_match
                else (remainder.split()[0] if remainder else "not supplied")
            )
            rest = remainder[len(unit_match[0]) :].strip() if unit_match else remainder
            interval = RANGE.search(rest)
            source = "illustrative adult example"
            valid = normalize(unit) == normalize(expected) and value >= 0
            reference_low, reference_high = low, high
            if interval:
                supplied_low = float(interval[1].replace(",", ""))
                supplied_high = float(interval[2].replace(",", ""))
                if (
                    math.isfinite(supplied_low)
                    and math.isfinite(supplied_high)
                    and supplied_low <= supplied_high
                    and unit_match
                    and value >= 0
                ):
                    reference_low, reference_high = supplied_low, supplied_high
                    source = "printed report"
                    valid = True
                else:
                    valid = False
                    reference_low, reference_high = (
                        (supplied_low, supplied_high)
                        if math.isfinite(supplied_low) and math.isfinite(supplied_high)
                        else (None, None)
                    )
                    source = "printed range needs review"
            flag = (
                (
                    "low"
                    if value < reference_low
                    else "high"
                    if value > reference_high
                    else "within supplied range"
                    if source == "printed report"
                    else "within demo range"
                )
                if valid
                else "reference needs review"
                if source == "printed range needs review"
                else "unit needs review"
            )
            reference_text = (
                f"{reference_low:g}–{reference_high:g}"
                if reference_low is not None and reference_high is not None
                else interval[0]
            )
            rows.append(
                {
                    "name": name,
                    "value": value,
                    "display_value": original,
                    "unit": unit,
                    "reference": f"{reference_text} {unit if source.startswith('printed') else expected} ({source})",
                    "reference_low": reference_low,
                    "reference_high": reference_high,
                    "reference_source": source,
                    "flag": flag,
                    "explanation": explanation,
                    "source_line": line,
                }
            )
            break
    return rows
