"""Run one v2 stage script, unchanged, in its own isolated interpreter."""
import os
import subprocess
import sys
import time
from pathlib import Path

TIMINGS = {}


def mask(text, package, data):
    """The stage's output with the data folder written as $ZV_DATA_DIR and the package folder as ".".

    Some stage scripts print a path in full, for example a label file they did not find. The
    notebook's record must hold no path of the machine that ran it, so it prints the folders by
    these names. The log in the data folder keeps the stage's own words.
    """
    names = set()
    for p, name in ((data, "$ZV_DATA_DIR"), (package, ".")):
        names.add((str(Path(p)), name))
        names.add((str(Path(p).resolve()), name))
    for p, name in sorted(names, key=lambda t: -len(t[0])):
        text = text.replace(p, name)
    return text


def run_stage(script, package, data, quiet_after=None, check=True):
    """Run `python -I -B <script>` in the package folder with ZV_DATA_DIR set.

    Prints the stage's output into the notebook, with its folders masked (see mask), up to
    `quiet_after` lines and then only the last 15 when it is given, and fails the cell on a
    non-zero exit. Returns the stage's own output.
    """
    env = dict(os.environ, ZV_DATA_DIR=str(data))
    t0 = time.time()
    p = subprocess.run([sys.executable, "-I", "-B", script], cwd=str(package), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = mask(p.stdout, package, data).splitlines()
    if quiet_after is not None and len(lines) > quiet_after + 15:
        shown = lines[:quiet_after] + [f"... {len(lines) - quiet_after - 15} lines not shown ..."] + lines[-15:]
    else:
        shown = lines
    print("\n".join(shown))
    TIMINGS[script] = round(time.time() - t0, 1)
    print(f"[{script}] exit {p.returncode}, {TIMINGS[script]} s")
    log = Path(data) / "logs"
    log.mkdir(exist_ok=True)
    (log / f"{Path(script).stem}.log").write_text(p.stdout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{script} failed with exit {p.returncode}")
    return p.stdout
