"""Checks that the executed notebook holds nothing of the machine that ran it.

  python check_notebook.py

The executed notebook is published as it is, sealed in BUNDLE.sha256. This script
changes nothing. It fails if the notebook's text holds an absolute path, the data
folder or package folder of this run, the home folder, or the host or user name of
this machine. The names are read from the running system, never written here.
"""
import getpass
import json
import os
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE / "zero_vote_sections.executed.ipynb"
# An absolute path starts the token: "data/private/x" is relative and is not one.
ABSOLUTE = re.compile(r"(?<![\w.~/-])(?:/mnt|/home|/Users|/root|/srv|/tmp|/var|/opt|/private|/media|/run)/[^\s\"'\\]+")


def main():
    text = NOTEBOOK.read_text()
    json.loads(text)  # a valid notebook
    data = Path(os.environ.get("ZV_DATA_DIR", HERE / "data")).resolve()
    local = {str(data), str(HERE), str(Path.home()), os.path.realpath(HERE / ".venv")}
    names = set()
    for get in (socket.gethostname, getpass.getuser):
        try:
            v = get().split(".")[0]
        except Exception:  # noqa: BLE001
            continue
        if len(v) >= 3:
            names.add(v)
    found = sorted({m.group(0) for m in ABSOLUTE.finditer(text)})
    found += [f"a local folder ({len(p)} characters)" for p in local if p and p in text]
    found += [f"a name of this machine ({len(n)} characters)" for n in names
              if re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", text, re.I)]
    if found:
        print(f"{NOTEBOOK.name} holds {len(found)} things of this machine:", file=sys.stderr)
        for f in found:
            print(f"  {f if not f.startswith('/') else f[:12] + '...'}", file=sys.stderr)
        return 1
    print(f"{NOTEBOOK.name}: no absolute path, local folder or machine name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
