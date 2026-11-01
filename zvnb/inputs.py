"""Pre-flight: every input file present, with its size and SHA-256, and the harness identity."""
import csv
import hashlib
from pathlib import Path

# The files whose bytes define the computation. Their hashes, sorted by path, give the harness identity.
HARNESS_GLOBS = ["0*.py", "1*.py", "common.py", "zvnb/*.py", "run_all.sh", "requirements.lock",
                 "requirements-notebook.lock", ".python-version", "sources.lock.tsv", "inputs.extra.tsv",
                 "checksums/results.sha256", "zero_vote_sections.ipynb", "build_notebook.py",
                 "make_findings.py", "piece_numbers.tsv", "make_bundle.py", "check_notebook.py"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def input_table(package, data):
    """Every input with its expected size and hash and where it should be on disk.

    sources.lock.tsv: the public TSE and IBGE files (raw/) and the outside registers
    (registers/), as the v2 package pinned them. inputs.extra.tsv: the two private
    analyst-label files and the two IBGE files the map data are built from.
    """
    package, data = Path(package), Path(data)
    folder = {"tse": data / "raw", "ibge_api": data / "raw", "register": data / "registers",
              "label": data / "private" / "labels", "map": data / "map"}
    rows = []
    for src in ("sources.lock.tsv", "inputs.extra.tsv"):
        for r in read_tsv(package / src):
            rows.append({"list": src, "kind": r["kind"], "file": r["file"], "url": r.get("url", ""),
                         "bytes": int(r["bytes"]), "sha256": r["sha256"],
                         "path": folder[r["kind"]] / r["file"]})
    return rows


OPTIONAL = {"label", "map"}  # absent is allowed: the private labels are not published, the map inputs are optional
# The flags of 01_download.py. A public file the source has republished is accepted only when its flag is set.
FLAG = {"tse": "ZV_ALLOW_CHANGED_SOURCES", "ibge_api": "ZV_ACCEPT_NEW_REGISTERS", "register": "ZV_ACCEPT_NEW_REGISTERS"}


def preflight(package, data, environ=None):
    """Assert every input is present with the locked size and SHA-256. Returns the table and its digest.

    A private label file or a map input may be absent: the notebook then skips what needs it and says so.
    When present, it must match its lock like every other input. A public file that differs from its
    lock stops the run, unless the flag 01_download.py uses for its kind is set to 1. The file is then
    marked `changed`, and the digest is computed over the hashes actually read, so every ledger row of
    the run carries an inputs identity that differs from the reference.
    """
    environ = {} if environ is None else environ
    rows = input_table(package, data)
    bad = []
    for r in rows:
        p = r["path"]
        r["present"] = p.exists()
        r["changed"] = False
        if not p.exists():
            if r["kind"] not in OPTIONAL:
                bad.append(f"missing {r['kind']}/{r['file']}")
            continue
        allowed = environ.get(FLAG.get(r["kind"], ""), "") == "1"
        got = sha256(p)
        r["observed_sha256"] = got
        st = p.stat()
        r["stat"] = (st.st_size, st.st_mtime_ns, st.st_ino)
        if got != r["sha256"] or st.st_size != r["bytes"]:
            if allowed:
                r["changed"] = True
                r["observed_bytes"] = st.st_size
            else:
                bad.append(f"{r['kind']}/{r['file']}: {st.st_size} bytes, SHA-256 {got} on disk, "
                           f"{r['bytes']} bytes, {r['sha256']} locked"
                           + (f". Set {FLAG[r['kind']]}=1 to run on the new version" if r["kind"] in FLAG else ""))
    if bad:
        raise AssertionError("pre-flight failed:\n" + "\n".join(bad))
    manifest = "".join(f"{(r['observed_sha256'] if r['changed'] else r['sha256']) if r['present'] else 'absent'}"
                       f"  {r['kind']}/{r['file']}\n" for r in sorted(rows, key=lambda r: (r["kind"], r["file"])))
    return rows, hashlib.sha256(manifest.encode()).hexdigest()


def harness(package):
    """(list of (path, sha256), identity) over the code and lock files."""
    package = Path(package)
    files = sorted({p for g in HARNESS_GLOBS for p in package.glob(g) if p.is_file()})
    pairs = [(p.relative_to(package).as_posix(), sha256(p)) for p in files]
    ident = hashlib.sha256("".join(f"{h}  {p}\n" for p, h in pairs).encode()).hexdigest()
    return pairs, ident


def unchanged_since(rows):
    """True when every present input still has the size, modification time and inode it had when hashed."""
    for r in rows:
        if r["present"]:
            st = r["path"].stat()
            if (st.st_size, st.st_mtime_ns, st.st_ino) != r["stat"]:
                return False
    return True
