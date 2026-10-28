
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

def find_values(obj, path="metadata"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            find_values(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            find_values(value, f"{path}[{index}]")
    elif isinstance(obj, str):
        if (
            "8B69B4" in obj.upper()
            or "Dan Osborn" in obj
            or "color" in path.lower()
        ):
            print(f"{path}: {obj}")

print("CHART COLOR SETTINGS:")
find_values(metadata)
