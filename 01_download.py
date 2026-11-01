"""Step 1. Download every source file and check it against sources.lock.tsv.

sources.lock.tsv lists each file's kind, URL, size and SHA-256 from the reference
download of 2026-10-29. A file already on disk with the right size and hash is kept.
Anything else is downloaded, with resume, one file at a time.

Kinds, and what happens when a file differs from the lock:
  tse       TSE result and electorate files, into raw/. The TSE sometimes regenerates
            published files. A difference stops the run unless
            ZV_ALLOW_CHANGED_SOURCES=1, because results would no longer be comparable.
  ibge_api  the IBGE municipal mesh, an API response built on request, into raw/.
  register  the outside registers used by step 11 (IBGE census localities and sectors,
            FUNAI indigenous lands and villages, INCRA quilombola territories), into
            the registers folder. INCRA regenerates its file every night and FUNAI
            builds its files on request, so a fresh download will usually differ.
            ibge_api and register differences stop the run unless
            ZV_ACCEPT_NEW_REGISTERS=1. With newer registers, the step-11 tables
            (results/m5b_*) can differ from the published ones. No other table uses them.
The observed values for this run are written to sources.tsv either way.
"""
import csv
import hashlib
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, RAW, REGISTERS  # noqa: E402

LOCK = HERE / "sources.lock.tsv"
OBSERVED = HERE / "sources.tsv"
FOLDER = {"tse": RAW, "ibge_api": RAW, "register": REGISTERS}
ALLOWED = {"tse": os.environ.get("ZV_ALLOW_CHANGED_SOURCES") == "1",
           "ibge_api": os.environ.get("ZV_ACCEPT_NEW_REGISTERS") == "1",
           "register": os.environ.get("ZV_ACCEPT_NEW_REGISTERS") == "1"}
UA = {"User-Agent": "zero-vote-sections-reproduction/2"}
# The FUNAI server sends an incomplete certificate chain and refuses non-browser
# clients. The missing intermediate certificate is fetched from its issuer.
FUNAI_PAGE = "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas"
SECTIGO_CA = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCAOVR36.crt"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def head(url):
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers.get("Content-Length"), r.headers.get("Last-Modified")


def funai_context():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=urllib.request.urlopen(SECTIGO_CA, timeout=60).read())
    return ctx


def fetch(url, dest, headers=None, context=None, tries=8):
    """Download url to dest, resuming a partial file. Fail if no try succeeds."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, tries + 1):
        start = part.stat().st_size if part.exists() else 0
        h = dict(headers or UA, **({"Range": f"bytes={start}-"} if start else {}))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=3600,
                                        context=context) as r:
                mode = "ab" if start and r.status == 206 else "wb"
                with open(part, mode) as fh:
                    while chunk := r.read(1 << 20):
                        fh.write(chunk)
            part.rename(dest)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"  try {attempt} failed for {dest.name}: {e}", flush=True)
            time.sleep(5)
    sys.exit(f"FAILED to download {url} after {tries} tries")


def main():
    with open(LOCK, newline="") as fh:
        lock = list(csv.DictReader(fh, delimiter="\t"))
    rows, changed = [], {k: [] for k in FOLDER}
    ctx = None
    for src in lock:
        kind, dest = src["kind"], FOLDER[src["kind"]] / src["file"]
        clen = lmod = None
        if kind == "tse":  # only the TSE CDN gives stable size and date headers
            clen, lmod = head(src["url"])
            time.sleep(1)  # one request per second, to be polite to the CDN
        digest = sha256(dest) if dest.exists() and dest.stat().st_size == int(src["bytes"]) else None
        fresh = digest != src["sha256"]
        if fresh:
            print(f"downloading {src['file']}", flush=True)
            if src["url"].startswith("https://geoserver.funai.gov.br/"):
                ctx = ctx or funai_context()
                fetch(src["url"], dest, headers={"User-Agent": "Mozilla/5.0", "Referer": FUNAI_PAGE},
                      context=ctx)
            else:
                fetch(src["url"], dest)
            downloaded = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            digest = sha256(dest)
        else:
            downloaded = "(already present)"
        size = dest.stat().st_size
        if fresh and clen is not None and int(clen) != size:  # a truncated download
            sys.exit(f"SIZE MISMATCH {src['file']}: {size} bytes on disk, server says {clen}")
        # The archived reference copy is intact, but the server now serves another version.
        server_changed = (not fresh) and clen is not None and int(clen) != size
        if server_changed:
            print(f"  note: the server now serves a different version of {src['file']} ({clen} bytes, "
                  f"last modified {lmod}). The reference copy on disk is used.", flush=True)
        same = digest == src["sha256"]
        if not same:
            changed[kind].append(src["file"])
        rows.append({"kind": kind, "file": src["file"], "url": src["url"], "bytes": size,
                     "http_content_length": clen, "http_last_modified": lmod, "downloaded_utc": downloaded,
                     "sha256": digest, "matches_lock": same, "server_serves_other_version": server_changed})
        print(f"ok {src['file']} {size} {'matches lock' if same else 'DIFFERS FROM LOCK'}", flush=True)
    with open(OBSERVED, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    stop = []
    if changed["tse"] and not ALLOWED["tse"]:
        stop.append("These TSE files differ from the reference download, so results may differ: "
                    + ", ".join(changed["tse"]) + ". Set ZV_ALLOW_CHANGED_SOURCES=1 to continue.")
    regs = changed["ibge_api"] + changed["register"]
    if regs and not ALLOWED["register"]:
        stop.append("These register files differ from the archived reference copy: " + ", ".join(regs)
                    + ". INCRA rebuilds its file every night and FUNAI builds its files on request, so "
                    "this is expected for a fresh download. Set ZV_ACCEPT_NEW_REGISTERS=1 to continue. "
                    "The step-11 tables (results/m5b_*) may then differ from the published ones.")
    if stop:
        sys.exit("\n".join(stop))
    print(f"{len(rows)} files, {sum(map(len, changed.values()))} differ from the lock")


if __name__ == "__main__":
    main()
