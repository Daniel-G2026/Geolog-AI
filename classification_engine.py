COHESIVE_TERMS = ["silty clay", "clayey silt","silt","clay"]
COHESIONLESS_TERMS = ["sand and silt", "silty sand", "sandy silt", "gravel","sand"]


def get_consistency_density(soil_name: str,n_value: int):
    soil_lower = soil_name.lower()
    if soil_lower.endswith("till"):
        soil_lower = soil_lower.replace("till","").strip()
    if any(term in soil_lower for term in COHESIONLESS_TERMS ):
        if 0 <= n_value < 4:
            return "very loose"
        elif n_value == 4:
            return "very loose to loose"
        elif 4 < n_value < 10:
            return "loose"
        elif n_value == 10:
            return "loose to medium dense"
        elif 10 < n_value < 30:
            return "Compact"
        elif n_value == 30:
            return "Compact to dense"
        elif 30 < n_value < 50:
            return "dense"
        elif n_value == 50:
            return "dense to very dense"
        elif n_value > 50:
            return "very dense"
    elif any(term in soil_lower for term in COHESIVE_TERMS):
        if 0 <= n_value < 2:
            return "very soft"
        elif n_value == 2:
            return "very soft to soft"
        elif 2 < n_value < 4:
            return "soft"
        elif n_value == 4:
            return "soft to firm"
        elif 4 < n_value < 8:
            return "firm"
        elif n_value == 8:
            return "firm to stiff"
        elif 8 < n_value < 15:
            return "stiff"
        elif n_value == 15:
            return "stiff to very stiff"
        elif 15 < n_value < 30:
            return "very stiff"
        elif n_value ==30:
            return "very stiff to hard"
        elif n_value > 30:
            return "hard"
    else:
        return None 