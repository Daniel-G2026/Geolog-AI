"""Firm-style configuration for the synthetic borehole log generator.

Chunk 3 uses 2 generic firm styles to prove the per-firm mapping layer works.
Real firms (Envision, etc.) will be added before Chunk 5 ingestion. The shape
of each config matches what Chunk 5's ingestion adapter will consume — column
mappings, abbreviation tables, units, refusal conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class FirmStyle:
    firm_name: str
    column_labels: Dict[str, str]      # internal_name -> display label on PDF
    abbreviations: Dict[str, str]      # short form used in PDF -> canonical soil term
    units: Dict[str, str]              # depth, recovery
    evidence_for_refusal: str          # explicit_column | notation_only | visual_only
    # The Chunk 1 column order for the PDF; firm styles can reorder.
    column_order: List[str] = field(default_factory=list)


FIRM_STYLES: Dict[str, FirmStyle] = {
    # ── Generic Firm A — verbose headers, full words, imperial units ──
    "firma": FirmStyle(
        firm_name="GenericFirm-A",
        column_labels={
            "depth":    "Depth (ft)",
            "sample":   "Sample No.",
            "desc":     "Soil Description",
            "blows":    "Blows per 6\"",
            "n":        "N-Value",
            "rec":      "Recovery (in)",
            "comments": "Notes",
        },
        abbreviations={
            # PDF stays verbose for this firm; no abbreviations used.
        },
        units={"depth": "feet", "recovery": "inches"},
        evidence_for_refusal="notation_only",
        column_order=["depth", "sample", "desc", "blows", "n", "rec", "comments"],
    ),
    # ── Generic Firm B — terse headers, abbreviated soil terms, comments column on the right edge ──
    "firmb": FirmStyle(
        firm_name="GenericFirm-B",
        column_labels={
            "depth":    "D (ft)",
            "sample":   "S/N",
            "desc":     "Description",
            "blows":    "SPT",
            "n":        "N",
            "rec":      "R",
            "comments": "Remarks",
        },
        abbreviations={
            "Sa": "sand",
            "Cl": "clay",
            "Si": "silt",
            "Gr": "gravel",
            "SaCl": "sandy clay",
            "SiCl": "silty clay",
            "ClSi": "clayey silt",
            "SaSi": "sandy silt",
            "SiSa": "silty sand",
        },
        units={"depth": "feet", "recovery": "inches"},
        evidence_for_refusal="notation_only",
        column_order=["depth", "sample", "desc", "blows", "n", "rec", "comments"],
    ),
}


def get_firm(name: str) -> FirmStyle:
    key = name.lower().replace("-", "").replace("_", "")
    if key not in FIRM_STYLES:
        raise KeyError(f"Unknown firm style {name!r}. Known: {list(FIRM_STYLES)}")
    return FIRM_STYLES[key]
