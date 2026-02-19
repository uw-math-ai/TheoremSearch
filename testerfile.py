import requests
r = requests.get(
    "https://oeis.org/search",
    params={"q": "keyword:core", "fmt": "json", "start": 0, "n": 2},
    headers={"User-Agent": "MathCopilot/1.0 (Educational research)"}
)
print(r.status_code)
print(r.text[:1000])