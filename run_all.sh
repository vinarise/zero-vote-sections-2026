#!/usr/bin/env bash
# Rebuilds the whole record with one command:
#   ./run_all.sh
# Optional: ZV_DATA_DIR=/path/with/12GB ./run_all.sh   (default: ./data)
#
# 1. Builds .venv from requirements.lock and requirements-notebook.lock, every file checked
#    against its PyPI SHA-256.
# 2. Downloads the public sources with 01_download.py only if one is missing. When all are
#    present, nothing is fetched. A present file that differs from its lock is left for the
#    notebook's pre-flight, which stops on it unless the flag for its kind is set
#    (ZV_ALLOW_CHANGED_SOURCES=1 for the TSE, ZV_ACCEPT_NEW_REGISTERS=1 for the registers).
# 3. Executes zero_vote_sections.ipynb top to bottom with nbconvert and writes
#    zero_vote_sections.executed.ipynb. The notebook appends its rows to results.csv.
# 4. Generates FINDINGS.md from the ledger, checks that the executed notebook holds nothing
#    of this machine, and checks every sealed file against BUNDLE.sha256.
set -euo pipefail
cd "$(dirname "$0")"
export ZV_DATA_DIR="${ZV_DATA_DIR:-$PWD/data}"

for cmd in python3 pdftotext; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done
want=$(cat .python-version)
have=$(python3 -c 'import platform; print(platform.python_version())')
[ "$have" = "$want" ] || echo "note: python3 is $have, the reference run used $want. The notebook will stop at its first cell." >&2

lock_sum=$(cat requirements.lock requirements-notebook.lock | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')
if [ ! -x .venv/bin/python ] || [ "$(cat .venv/locks.sha256 2>/dev/null)" != "$lock_sum" ]; then
  rm -rf .venv
  python3 -m venv .venv
  .venv/bin/pip install --quiet --require-hashes -r requirements.lock
  .venv/bin/pip install --quiet --require-hashes -r requirements-notebook.lock
  echo "$lock_sum" > .venv/locks.sha256
fi
PY=".venv/bin/python"
# The notebook's kernel is the venv's own interpreter, never a user-wide kernel.
export JUPYTER_PATH="$PWD/.venv/share/jupyter" JUPYTER_DATA_DIR="$PWD/.venv/share/jupyter"

# A quick look for missing public files only. The notebook checks every size and SHA-256 before it uses a file.
if ! $PY -I -c 'import sys; sys.path.insert(0, "."); from zvnb import inputs
missing = [r for r in inputs.input_table(".", sys.argv[1]) if r["kind"] in ("tse", "ibge_api", "register")
           and not r["path"].exists()]
sys.exit(1 if missing else 0)' "$ZV_DATA_DIR"; then
  echo "a public input is missing: running 01_download.py"
  $PY -I -B 01_download.py
fi

start=$(date +%s)
$PY -m jupyter nbconvert --to notebook --execute zero_vote_sections.ipynb \
  --output zero_vote_sections.executed.ipynb \
  --ExecutePreprocessor.timeout=7200 --ExecutePreprocessor.kernel_name=python3
echo "notebook executed in $(( $(date +%s) - start )) s"

findings=0
$PY -I -B make_findings.py || { findings=$?; echo "a number differs from the published piece: see FINDINGS.md, section 1" >&2; }
$PY -I -B check_notebook.py
$PY -I -B make_bundle.py --check
exit "$findings"
