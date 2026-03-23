COHESIVE_TERMS = ["silty clay", "clayey silt","silt","clay"]
COHESIONLESS_TERMS = ["sand and silt", "silty sand", "sandy silt", "sand and gravel", "sand", "gravel"]
INCHES_TO_MM = {1: 25, 2: 51, 3: 76, 4: 102, 5: 127, 6: 152}

def get_consistency_density(soil_name: str,n_value: int):
    if isinstance(soil_name,list):
        cohesion = False
        cohesive = False
        soils_lower = []
        consistencies = []
        consistency_return = ""
        for name in soil_name:
            soils_lower.append(name.lower())
        if any(soil in COHESIVE_TERMS for soil in soils_lower) and any(soil in COHESIONLESS_TERMS for soil in soils_lower):
            for soil in soils_lower:
                if soil in COHESIONLESS_TERMS and cohesion == False:
                    consistencies.append(consistency_density_condition(soil,n_value))
                    cohesion = True
                elif soil in COHESIVE_TERMS and cohesive == False:
                    consistencies.append(consistency_density_condition(soil,n_value))
                    cohesive = True
            for consistency in consistencies:
                consistency_return += f"{consistency}/"
            consistency_return = consistency_return.strip("/")
            return consistency_return
        else:
            return consistency_density_condition(soils_lower[0],n_value)


    else:
        soil_lower = soil_name.lower()
        return consistency_density_condition(soil_lower, n_value)

def consistency_density_condition(soil_lower,n_value):
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
            return "compact"
        elif n_value == 30:
            return "compact to dense"
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

def parse_blow_counts(blow_counts: list, pen_depths: list) -> dict:
    if len(blow_counts) == 4:
        n_value = blow_counts[1] + blow_counts[2]
        n_value_log = str(n_value)
        refusal = False
    elif len(blow_counts) == 1:
        n_value = blow_counts[0]
        pen_depth = round(pen_depths[0] * 25.4)
        n_value_log = f"{blow_counts[0]}/{pen_depth}mm"
        refusal = True
    elif len(blow_counts) == 2:
        n_value = blow_counts[1]
        pen_depth = round(pen_depths[1] * 25.4)
        n_value_log = f"{blow_counts[1]}/{pen_depth}mm"
        refusal = True
    else:
        n_value = blow_counts[1] + blow_counts[2]
        pen_depth = round((pen_depths[1] + pen_depths[2]) * 25.4)
        n_value_log = f"{n_value}/{pen_depth}mm"
        refusal = True


    return {
            "n_value": n_value,
            "n_value_log": n_value_log,
            "refusal": refusal
            }   
        
