
import os
import urllib.request
import json

token = os.environ["DATAWRAPPER_API_TOKEN"]
chart_id = os.environ["DATAWRAPPER_CHART_ID"]

request = urllib.request.Request(
    f"https://api.datawrapper.de/v3/charts/{chart_id}",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
)

with urllib.request.urlopen(request, timeout=30) as response:
    chart = json.load(response)

print("Connected to Datawrapper!")
print("Chart ID:", chart["id"])
print("Chart title:", chart["title"])
