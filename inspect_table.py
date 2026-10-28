
import os
import json
import urllib.request

chart_id = "xF0zL"
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

print("Chart:", chart.get("title"))
print("Type:", chart.get("type"))

metadata = chart.get("metadata", {})

print("METADATA SECTIONS:")
print(list(metadata.keys()))

print("COLUMN SETTINGS:")
print(json.dumps(
    metadata.get("visualize", {}).get("columns", {}),
    indent=2
))

print("CUSTOM SETTINGS:")
print(json.dumps(
    metadata.get("custom", {}),
    indent=2
))
