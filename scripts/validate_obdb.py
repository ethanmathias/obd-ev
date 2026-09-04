#!/usr/bin/env python3
"""Check our OBDb decoder against every test vector OBDb publishes.

Each vehicle repo ships `tests/test_cases/<year>/commands/*.yaml`: captured
adapter responses paired with the values they are supposed to decode to. This
downloads those repos and replays the lot through `obd_ev.obdb`.

    scripts/validate_obdb.py Hyundai-IONIQ-5 Porsche-Taycan
    scripts/validate_obdb.py --all-evs

The trimmed fixture used by the unit tests lives in
tests/fixtures/obdb_vectors.json; this is the full sweep.
"""

import argparse
import glob
import io
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

TARBALL = "https://github.com/OBDb/{name}/archive/refs/heads/main.tar.gz"

EV_REPOS = [
    "Hyundai-IONIQ-5", "Hyundai-IONIQ-Electric", "Kia-Niro-EV",
    "Porsche-Taycan", "Ford-Mustang-Mach-E", "Chevrolet-Bolt-EV",
    "Audi-Q8-e-tron", "BMW-iX",
]


def fetch(name: str, dest: Path) -> Path | None:
    target = dest / f"{name}-main"
    if target.exists():
        return target
    try:
        with urllib.request.urlopen(TARBALL.format(name=name), timeout=120) as resp:
            blob = resp.read()
    except Exception as exc:
        print(f"  {name}: download failed ({exc})")
        return None
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        tar.extractall(dest)
    return target if target.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vehicles", nargs="*")
    parser.add_argument("--all-evs", action="store_true",
                        help=f"sweep {len(EV_REPOS)} EV repos")
    parser.add_argument("--cache", default=None,
                        help="directory to keep downloaded repos in")
    args = parser.parse_args()

    names = args.vehicles or (EV_REPOS if args.all_evs else [])
    if not names:
        parser.error("name at least one vehicle, or pass --all-evs")

    try:
        import yaml
    except ImportError:
        print("PyYAML is required: pip install PyYAML", file=sys.stderr)
        return 2
    from obd_ev.obdb import SignalSet, reassemble

    cache = Path(args.cache) if args.cache else Path(tempfile.mkdtemp(prefix="obdb-"))
    cache.mkdir(parents=True, exist_ok=True)
    print(f"cache: {cache}")

    grand_total = grand_pass = 0
    for name in names:
        repo = fetch(name, cache)
        if repo is None:
            continue
        ss_path = repo / "signalsets" / "v3" / "default.json"
        if not ss_path.exists():
            print(f"  {name}: no signalset")
            continue
        signalset = SignalSet.load(ss_path)

        total = passed = 0
        failures = []
        for tc in glob.glob(str(repo / "tests/test_cases/*/commands/*.yaml")):
            year = int(re.search(r"test_cases/(\d{4})/", tc).group(1))
            doc = yaml.safe_load(open(tc))
            if not doc:
                continue
            base = doc.get("command_id", "").split("|")[0]
            file_fmt = 29 if doc.get("can_id_format") == "TWENTY_NINE_BIT" else None
            cmds = [c for c in signalset.for_year(year).commands
                    if f"{c.hdr}.{c.rax}.{c.request()}" == base]
            if not cmds:
                continue
            cmd = cmds[0]
            for case in doc.get("test_cases") or []:
                resp = case.get("response") or ""
                if isinstance(resp, list):
                    resp = "\n".join(resp)
                fmt = 29 if case.get("can_id_format") == "TWENTY_NINE_BIT" else file_fmt
                payload = cmd.select_payload(reassemble(
                    resp, can_id_len=fmt or cmd.can_id_len,
                    extended_addressing=bool(cmd.eax)))
                if payload is None:
                    continue
                got = cmd.decode(payload)
                for sig, want in (case.get("expected_values") or {}).items():
                    total += 1
                    have = got.get(sig)
                    if isinstance(want, (int, float)) and isinstance(have, (int, float)):
                        # Upstream expectations are rounded to five decimals.
                        ok = abs(have - want) <= 6e-6 + abs(want) * 1e-4
                    else:
                        ok = have == want
                    if ok:
                        passed += 1
                    elif len(failures) < 10:
                        failures.append((doc["command_id"], sig, want, have))

        grand_total += total
        grand_pass += passed
        status = "ok" if passed == total else "FAIL"
        pct = 100 * passed / total if total else 100.0
        print(f"  {name:<26} {passed:>7}/{total:<7} {pct:6.2f}%  {status}")
        for f in failures:
            print(f"      {f}")

    print(f"\ntotal: {grand_pass}/{grand_total} "
          f"({100 * grand_pass / grand_total if grand_total else 100:.3f}%)")
    return 0 if grand_pass == grand_total else 1


if __name__ == "__main__":
    sys.exit(main())
