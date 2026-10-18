
import os
import json
import urllib.request

chart_id = "ZD3pl"
token = os.environ["DATAWRAPPER_API_TOKEN"]

request = urllib.request.Request(
    f"https://api.datawrapper.de/v3/charts/{chart_id}",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
)

with urllib.request.urlopen(request, timeout=30) as response:
    chart = json.load(response)

visualize = chart.get("metadata", {}).get("visualize", {})

print("Chart:", chart.get("title"))
print("Type:", chart.get("type"))
print("Visualization color settings:")
print(json.dumps({
    "custom-colors": visualize.get("custom-colors"),
    "color-category": visualize.get("color-category"),
    "color-by": visualize.get("color-by"),
    "color-palette": visualize.get("color-palette")
}, indent=2))
