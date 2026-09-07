#!/usr/bin/env python3
"""Build vehicles/index.json: the catalogue of every OBDb vehicle worth using.

Most OBDb repos are placeholders -- roughly 57% contain no commands at all --
so a raw repo listing is mostly noise. This walks the whole organisation once,
keeps only the vehicles that actually have data, and records enough about each
one (signal counts, categories, model years) for `select_vehicle.py --all` to
offer a useful searchable list offline.

The index is committed. Signalsets themselves are not: each kit needs exactly
one, fetched on demand, and vendoring all of them would be ~14MB of mostly
unused data that goes stale.

    scripts/build_index.py              # refresh the index
    scripts/build_index.py --workers 8  # be gentler on the network
"""

import argparse
import datetime
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "vehicles" / "index.json"

ORG_REPOS = "https://api.github.com/orgs/OBDb/repos?per_page=100&page={page}"
SIGNALSET = "https://raw.githubusercontent.com/OBDb/{name}/main/signalsets/v3/default.json"
GENERATIONS = "https://raw.githubusercontent.com/OBDb/{name}/main/generations.yaml"

UA = {"User-Agent": "obd-ev/build-index"}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_repos():
    names = []
    for page in range(1, 12):
        try:
            batch = json.loads(get(ORG_REPOS.format(page=page)))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print("  GitHub API rate limit hit while listing repos.",
                      file=sys.stderr)
                break
            raise
        if not batch:
            break
        for repo in batch:
            name = repo.get("name", "")
            if name and not name.startswith("."):
                names.append(name)
        if len(batch) < 100:
            break
    return sorted(set(names))


def years_for(name):
    """Model years from generations.yaml, if the repo has one."""
    try:
        raw = get(GENERATIONS.format(name=name)).decode()
    except Exception:
        return []
    try:
        import yaml
        doc = yaml.safe_load(raw) or {}
    except Exception:
        return []
    horizon = datetime.date.today().year + 1
    years = set()
    for gen in doc.get("generations") or []:
        start = gen.get("start_year")
        if not isinstance(start, int):
            continue
        end = gen.get("end_year")
        if not isinstance(end, int):
            end = horizon
        years.update(range(start, min(end, horizon) + 1))
    return sorted(years)


def inspect(name):
    """Return an index entry, or None for a repo with nothing in it."""
    try:
        raw = get(SIGNALSET.format(name=name))
    except Exception:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    commands = doc.get("commands") or []
    if not commands:
        return None

    groups, services = {}, set()
    signals = 0
    for command in commands:
        services.update(command.get("cmd", {}).keys())
        for signal in command.get("signals") or []:
            signals += 1
            group = (signal.get("path") or "").split(".")[0] or "-"
            groups[group] = groups.get(group, 0) + 1
    if not signals:
        return None

    return {
        "name": name,
        "commands": len(commands),
        "signals": signals,
        "services": sorted(services),
        "groups": dict(sorted(groups.items(), key=lambda kv: -kv[1])),
        "years": years_for(name),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out", default=str(INDEX_PATH))
    args = parser.parse_args()

    print("Listing OBDb repositories...")
    names = list_repos()
    if not names:
        print("No repositories listed; aborting.", file=sys.stderr)
        return 1
    print(f"  {len(names)} repositories")

    print(f"Inspecting signalsets with {args.workers} workers "
          f"(most are empty and get dropped)...")
    entries, done = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for entry in pool.map(inspect, names):
            done += 1
            if entry:
                entries.append(entry)
            if done % 50 == 0 or done == len(names):
                print(f"  {done}/{len(names)} checked, {len(entries)} with data",
                      end="\r", flush=True)
    print()

    entries.sort(key=lambda e: e["name"])
    index = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "https://github.com/OBDb",
        "repos_scanned": len(names),
        "vehicles": entries,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=1) + "\n")

    size_kb = out.stat().st_size / 1024
    print(f"\nWrote {out.name}: {len(entries)} vehicles with data "
          f"out of {len(names)} repos ({size_kb:.0f} KB)")
    richest = sorted(entries, key=lambda e: -e["signals"])[:5]
    print("\nMost detailed profiles:")
    for e in richest:
        print(f"  {e['name']:<32} {e['signals']:>5} signals  "
              f"{e['commands']:>4} commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
