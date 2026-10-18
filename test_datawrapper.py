
import os
import json
import urllib.request
import urllib.error

token = os.environ["DATAWRAPPER_API_TOKEN"]
chart_id = os.environ["DATAWRAPPER_CHART_ID"].strip()

print("Testing Datawrapper API")
print("Requested chart ID:", chart_id)

url = f"https://api.datawrapper.de/v3/charts/{chart_id}"

request = urllib.request.Request(
    url,
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
)

try:
    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.status
        chart = json.load(response)

    print("HTTP status:", status)

    if isinstance(chart, dict) and "id" in chart:
        print("SUCCESS: Connected to Datawrapper!")
        print("Chart ID:", chart["id"])
        print("Chart title:", chart.get("title", "Unknown"))
    else:
        print("Unexpected API response:")
        print(json.dumps(chart, indent=2)[:2000])
        raise SystemExit(1)

except urllib.error.HTTPError as error:
    print("HTTP error:", error.code)
    print("Response:", error.read().decode()[:1000])
    raise SystemExit(1)
