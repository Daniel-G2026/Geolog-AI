from dotenv import load_dotenv
import anthropic
import os

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

field_description = "clayey silt, brown, moist, stiff"

message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": f"""You are a principal geotechnical engineer specializing in soil and rock 
classification per USCS standards (ASTM D2488).

A field technician has provided the following soil description:
"{field_description}"

Return a structured report-ready soil description with the following fields:
- USCS Classification Symbol (e.g. CL, SM, GW)
- USCS Soil Name
- Color
- Moisture Content (dry/moist/wet/saturated)
- Consistency/Density
- Additional observations

Return the result as a JSON object with these exact field names:
uscs_symbol, uscs_name, color, moisture, consistency, observations"""
        }
    ]
)

print(message.content[0].text)