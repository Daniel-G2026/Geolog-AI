from dotenv import load_dotenv
import anthropic
import os
import json
load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

field_description = "clayey silt, brown, moist, stiff"

message = client.messages.create(
    model="claude-Sonnet-4-6",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": "hi"
        }
    ]
)


print(message.content[0].text)