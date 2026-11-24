"""Run every browser scenario one after the other (each starts and stops its own servers / browser).

Usage: python run_all.py [--only NAME [--only NAME ...]] [--keep-going] [--list]
  NAME: a scenario name with or without the "scenario_" prefix, e.g. `autosave` or `scenario_autosave`.
  --keep-going: run the remaining scenarios after a failure (default: stop at the first failure).

Works with any Python 3 (standard library only); the scenarios themselves run with Forge's Python
(PB_FORGE_PYTHON or auto-detected, see devenv.py). Each scenario's full output goes to a log file in
the scratch logs folder; the console gets one line per scenario and a summary. Exit code 0 only if every
selected scenario passed.
"""
import argparse
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True

import devenv  # noqa: E402

SCENARIOS = [
    ("scenario_autosave", "auto-save + Reload on block switches (section 26)"),
    ("scenario_small_fixes", "gallery highlight, rename-category reload, tile cleanup (section 21)"),
    ("scenario_tab_fixes", "management tab fixes, slowed saves (section 23a)"),
    ("scenario_accordion", "accordion / popup JS against the harness (section 23b)"),
    ("scenario_second_round", "second round of fixes, tab + slowed tab + harness (section 24)"),
    ("scenario_sub_rows", "sub-block rows: Include default, All <mode> buttons, row classes (section 37)"),
    ("scenario_bans_popup", "autocomplete popup in the Bans box (section 39)"),
    ("scenario_browser", "block browser: dimmed tiles, tooltips, category counts, search (section 40)"),
]


def _select(only):
    if not only:
        return SCENARIOS
    known = {name: (name, desc) for name, desc in SCENARIOS}
    picked = []
    for o in only:
        key = o if o.startswith("scenario_") else "scenario_" + o
        key = key[:-3] if key.endswith(".py") else key
        if key not in known:
            sys.exit("unknown scenario %r; known: %s" % (o, ", ".join(n for n, _ in SCENARIOS)))
        picked.append(known[key])
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", default=[], metavar="NAME")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the scenarios and exit")
    args = ap.parse_args()
    if args.list:
        for name, desc in SCENARIOS:
            print("%-24s %s" % (name, desc))
        return 0

    try:
        python = devenv.forge_python()
        chrome = devenv.chrome_exe()
    except devenv.SetupError as e:
        print("SETUP ERROR: %s" % e)
        return 1
    print("python:  %s" % python)
    print("browser: %s" % chrome)
    print("scratch: %s" % devenv.SCRATCH_ROOT)
    env = dict(os.environ, GRADIO_ANALYTICS_ENABLED="False", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               PB_FORGE_PYTHON=python, PB_CHROME=chrome)

    results = []
    t_all = time.time()
    for name, desc in _select(args.only):
        log = devenv.log_path(name + ".log")
        t0 = time.time()
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.call([python, str(devenv.HERE / (name + ".py"))], env=env, stdout=fh,
                                 stderr=subprocess.STDOUT, cwd=str(devenv.HERE))
        dt = time.time() - t0
        ok = rc == 0
        results.append((name, ok, dt))
        print("%s  %-24s %6.1f s  %s" % ("PASS" if ok else "FAIL", name, dt, desc), flush=True)
        if not ok:
            with open(log, encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip() for ln in f if ln.startswith("FAIL") or '"ok": false' in ln
                         or ln.startswith("RESULT") or "Error" in ln]
            for ln in lines[-12:]:
                print("      " + ln.encode("ascii", "replace").decode("ascii")[:300])
            print("      full log: %s" % log)
            if not args.keep_going:
                break
    total = time.time() - t_all
    passed = sum(1 for _, ok, _ in results if ok)
    skipped = len(_select(args.only)) - len(results)
    print("SUMMARY: %d/%d passed%s, total %.1f s" % (passed, len(results),
                                                    ", %d not run" % skipped if skipped else "", total))
    left = devenv.processes_with(devenv.CHROME_PROFILE)
    if left:
        print("WARNING: headless browser processes still running: %s" % left)
    return 0 if results and passed == len(results) and not skipped else 1


if __name__ == "__main__":
    sys.exit(main())
