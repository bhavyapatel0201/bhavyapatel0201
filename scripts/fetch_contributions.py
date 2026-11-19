#!/usr/bin/env python3
"""Refresh data/contributions.json from the GitHub GraphQL API.

Needs a token in GH_TOKEN (the workflow passes PROFILE_TOKEN or GITHUB_TOKEN).
Private contributions are only counted if the token belongs to the profile owner
(PROFILE_TOKEN) and "Include private contributions" is on in profile settings.
"""
import json, os, sys, urllib.request, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "scripts/config.json").read_text(encoding="utf-8"))
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("fetch_contributions: set GH_TOKEN")

def gql(query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if out.get("errors"):
        sys.exit(f"GraphQL error: {out['errors']}")
    return out["data"]

Q = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
  }
}"""
SQ = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) { totalCommitContributions }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(first:1, contributionTypes:[COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations:OWNER, isFork:false, privacy:PUBLIC, first:100) {
      nodes { stargazerCount languages(first:10, orderBy:{field:SIZE, direction:DESC}) { edges { size node { name color } } } }
    }
  }
}"""
RQ = """
query($login:String!, $name:String!) {
  repository(owner:$login, name:$name) {
    description stargazerCount forkCount pushedAt
    primaryLanguage { name color }
  }
}"""

today = dt.datetime.now(dt.timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
start = (today - dt.timedelta(days=364)).replace(hour=0, minute=0, second=0)
d = gql(Q, {"login": CFG["user"], "from": start.isoformat(), "to": today.isoformat()})
cal = d["user"]["contributionsCollection"]["contributionCalendar"]
days = [{"date": x["date"], "count": x["contributionCount"]}
        for w in cal["weeks"] for x in w["contributionDays"]]

repos = {}
for r in CFG["repos"]:
    try:
        n = gql(RQ, {"login": CFG["user"], "name": r["name"]})["repository"]
    except SystemExit:
        continue
    if n:
        repos[r["name"]] = {
            "description": n["description"], "stars": n["stargazerCount"], "forks": n["forkCount"],
            "pushed": n["pushedAt"], "language": (n["primaryLanguage"] or {}).get("name"),
            "language_color": (n["primaryLanguage"] or {}).get("color"),
        }

u = gql(SQ, {"login": CFG["user"], "from": start.isoformat(), "to": today.isoformat()})["user"]
stars, langs = 0, {}
for n in u["repositories"]["nodes"]:
    stars += n["stargazerCount"]
    for e in n["languages"]["edges"]:
        l = langs.setdefault(e["node"]["name"], {"name": e["node"]["name"], "color": e["node"]["color"], "bytes": 0})
        l["bytes"] += e["size"]
top = sorted(langs.values(), key=lambda x: -x["bytes"])
stats = {"stars": stars, "commits": u["contributionsCollection"]["totalCommitContributions"],
         "prs": u["pullRequests"]["totalCount"], "issues": u["issues"]["totalCount"],
         "contributed_to": u["repositoriesContributedTo"]["totalCount"]}

out = {"sample": False, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "user": CFG["user"], "total": cal["totalContributions"], "days": days, "repos": repos,
       "stats": stats, "languages": top[:12]}
(ROOT / "data").mkdir(exist_ok=True)
(ROOT / "data/contributions.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
print(f"wrote {len(days)} days, {cal['totalContributions']} contributions, {len(repos)} repos")
