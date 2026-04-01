# classification_engine.py
# Handles all SPT (Standard Penetration Test) data processing and soil classification.
# This file does the geotechnical math so Claude never has to.
# Scope: Soil only. Rock core to be added later.

# ─────────────────────────────────────────────
# SOIL TERM LISTS
# Order matters — longer/more specific terms must come before shorter ones
# that are substrings of them (e.g. "silty clay" before "clay").
# This prevents partial matches during parsing.
# ─────────────────────────────────────────────

COHESIVE_TERMS = ["silty clay", "clayey silt", "silt", "clay"]
# Fine-grained soils — use the cohesive (clay) consistency table for classification

COHESIONLESS_TERMS = ["sand and silt", "silty sand", "sandy silt", "sand and gravel", "sand", "gravel"]
# Coarse-grained soils — use the cohesionless (sand) density table for classification

# Conversion table: penetration depths spoken in inches by tech, converted to mm for log
INCHES_TO_MM = {1: 25, 2: 51, 3: 76, 4: 102, 5: 127, 6: 152}


# ─────────────────────────────────────────────
# MAIN CLASSIFICATION FUNCTION
# ─────────────────────────────────────────────

def get_consistency_density(soil_name, n_value: int):
    """
    Takes a soil name and N-value, returns the correct consistency or density term.
    
    Handles three cases:
    1. Single soil name (string) → routes to consistency_density_condition()
    2. List of soils, all same type → uses first soil for classification
    3. List of soils, mixed cohesive + cohesionless → gets one term from each 
       table and combines with / separator (e.g. "very stiff/compact")
    
    Returns None if soil type is unrecognized — triggers manual review in pipeline.
    """
    if isinstance(soil_name, list):
        # Multiple soil names detected — handle mixed or same-type cases
        cohesion_found = False   # tracks if we already got a cohesionless term
        cohesive_found = False   # tracks if we already got a cohesive term
        soils_lower = [name.lower() for name in soil_name]
        consistencies = []
        consistency_return = ""

        # Check if the list contains both cohesive AND cohesionless soils
        has_cohesive = any(soil in COHESIVE_TERMS for soil in soils_lower)
        has_cohesionless = any(soil in COHESIONLESS_TERMS for soil in soils_lower)

        if has_cohesive and has_cohesionless:
            # Mixed case — get one consistency term from each table
            for soil in soils_lower:
                if soil in COHESIONLESS_TERMS and not cohesion_found:
                    consistencies.append(consistency_density_condition(soil, n_value))
                    cohesion_found = True
                elif soil in COHESIVE_TERMS and not cohesive_found:
                    consistencies.append(consistency_density_condition(soil, n_value))
                    cohesive_found = True

            # Combine terms with / separator e.g. "very stiff/compact"
            for consistency in consistencies:
                consistency_return += f"{consistency}/"
            consistency_return = consistency_return.strip("/")
            return consistency_return
        else:
            # All same type — just classify using the first soil in the list
            return consistency_density_condition(soils_lower[0], n_value)

    else:
        # Single soil name — normal path
        return consistency_density_condition(soil_name.lower(), n_value)


# ─────────────────────────────────────────────
# CORE LOOKUP FUNCTION
# ─────────────────────────────────────────────

def consistency_density_condition(soil_lower: str, n_value: int):
    """
    Core classification lookup. Takes a lowercase soil name and N-value integer,
    returns the appropriate consistency or density term.
    
    First strips 'till' if present — "silty clay till" becomes "silty clay"
    for routing purposes, but the original name is preserved in the log.
    
    Boundary values (exact N=4, 8, 15 etc.) return transitional terms like
    "soft to firm" — this mirrors how engineers handle borderline N-values.
    """

    # Strip 'till' suffix before routing — till is a depositional descriptor,
    # not a soil type classifier. "sandy silt till" classifies same as "sandy silt"
    if soil_lower.endswith("till"):
        soil_lower = soil_lower.replace("till", "").strip()

    if any(term in soil_lower for term in COHESIONLESS_TERMS):
        # ── COHESIONLESS (SAND / GRAVEL) TABLE ──
        # Source: ASTM D2488 relative density scale
        if 0 <= n_value < 4:       return "very loose"
        elif n_value == 4:         return "very loose to loose"
        elif 4 < n_value < 10:     return "loose"
        elif n_value == 10:        return "loose to medium dense"
        elif 10 < n_value < 30:    return "compact"
        elif n_value == 30:        return "compact to dense"
        elif 30 < n_value < 50:    return "dense"
        elif n_value == 50:        return "dense to very dense"
        elif n_value > 50:         return "very dense"

    elif any(term in soil_lower for term in COHESIVE_TERMS):
        # ── COHESIVE (CLAY / SILT) TABLE ──
        # Source: ASTM D2488 consistency scale
        if 0 <= n_value < 2:       return "very soft"
        elif n_value == 2:         return "very soft to soft"
        elif 2 < n_value < 4:      return "soft"
        elif n_value == 4:         return "soft to firm"
        elif 4 < n_value < 8:      return "firm"
        elif n_value == 8:         return "firm to stiff"
        elif 8 < n_value < 15:     return "stiff"
        elif n_value == 15:        return "stiff to very stiff"
        elif 15 < n_value < 30:    return "very stiff"
        elif n_value == 30:        return "very stiff to hard"
        elif n_value > 30:         return "hard"

    else:
        # Soil type not recognized — return None to trigger manual review flag
        return None


# ─────────────────────────────────────────────
# SPT BLOW COUNT PARSER
# ─────────────────────────────────────────────

def parse_blow_counts(blow_counts: list, pen_depths: list) -> dict:
    """
    Processes raw SPT blow count data into N-value and log notation string.
    
    SPT drive convention:
    - 4 intervals of 6 inches each = 24 inches total drive
    - Interval 1: seating drive — recorded but NOT used in N-value
    - Interval 2 + Interval 3 = N-value
    - Interval 4: recorded but NOT used in N-value
    - Each interval stops at 50 blows regardless of penetration depth
    
    Inputs:
    - blow_counts: list of 1–4 integers (one per completed interval)
    - pen_depths:  list of penetration depths in inches (6 = full interval);
      must have the same length as blow_counts (enforced in pipeline.py)
    
    Returns dict: {
        "n_value":     int  — used for consistency classification,
        "n_value_log": str  — what gets written in the log,
        "refusal":     bool — whether 50 blows was hit before full penetration
    }
    """

    if len(blow_counts) == 4:
        n_value = blow_counts[1] + blow_counts[2]
        
        # Check if any interval hit refusal (pen_depth < 6 inches)
        refusal_interval = None
        for i, depth in enumerate(pen_depths):
            if depth < 6.0:
                refusal_interval = i
                break
    
        if refusal_interval is not None:
            # Refusal mid-drive — log notation uses the refusal interval's count
            # and combined pen depth of intervals 2 and 3 (indices 1 and 2)
            combined_pen_mm = round((pen_depths[1] + pen_depths[2]) * 25.4)
            n_value_log = f"{n_value}/{combined_pen_mm}mm"
            refusal = True
        else:
            # Normal full drive
            n_value_log = str(n_value)
            refusal = False

    elif len(blow_counts) == 1:
        # ── REFUSAL ON INTERVAL 1 ──
        # Hit 50 blows before completing first interval
        n_value = blow_counts[0]
        pen_depth = round(pen_depths[0] * 25.4)    # convert inches to mm
        n_value_log = f"{blow_counts[0]}/{pen_depth}mm"   # e.g. "50/76mm"
        refusal = True

    elif len(blow_counts) == 2:
        # ── REFUSAL ON INTERVAL 2 ──
        # Completed interval 1, hit 50 on interval 2
        n_value = blow_counts[1]
        pen_depth = round(pen_depths[1] * 25.4)
        n_value_log = f"{blow_counts[1]}/{pen_depth}mm"   # e.g. "50/51mm"
        refusal = True

    else:
        # ── REFUSAL ON INTERVAL 3 (3 blow counts received) ──
        # Completed intervals 1 and 2, hit 50 on interval 3
        # N-value = interval 2 + interval 3
        # Log depth = combined penetration of intervals 2 and 3
        n_value = blow_counts[1] + blow_counts[2]
        pen_depth = round((pen_depths[1] + pen_depths[2]) * 25.4)
        n_value_log = f"{n_value}/{pen_depth}mm"          # e.g. "62/254mm"
        refusal = True

    return {
        "n_value": n_value,
        "n_value_log": n_value_log,
        "refusal": refusal
    }
