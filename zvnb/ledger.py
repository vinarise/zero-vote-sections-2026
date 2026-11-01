"""The append-only ledger, results.csv. One row per arm per run.

Rows are never edited. A later run writes new rows, and each new row names in
`supersedes` the latest earlier row of the same arm. FINDINGS.md reads only rows
that no later row supersedes.

Version 2 of the columns (1 November 2026) adds `expectation_held` at the end: for a
decision row, whether the expectation registered in EXPERIMENT.md held (true, false or
"not applicable"). A version 1 file is read with that cell blank on every earlier row.
The first append rewrites the header and adds one empty cell to the end of each
earlier line, and asserts that every earlier line is otherwise unchanged, byte for byte.
"""
import csv
import math
import os
from datetime import datetime, timezone

# Identity and factors, then metrics, then provenance. The order is the file's column order.
FACTORS = ["measure", "year", "side", "model", "event", "min_valid_votes", "category", "scope"]
METRICS = [
    "n", "n_label", "k", "share", "share_ci_low", "share_ci_high",
    "value", "value_ci_low", "value_ci_high", "value_unit", "ci_method",
    "expected", "expected_sd", "upper_99_9_exact", "p_exact_ge_observed", "u1_fires_exact",
    "ratio", "ratio_ci_low", "ratio_ci_high", "log_score", "brier", "votes_other",
]
COLUMNS = (["row_id", "run_id", "run_at", "arm"] + FACTORS
           + ["run_class", "prereg_status", "status"] + METRICS
           + ["source_stage", "source_table", "source_table_sha256", "inputs_sha256",
              "harness_sha256", "environment_sha256", "config_sha256", "seed", "note", "supersedes"])
COLUMNS_V1 = list(COLUMNS)
COLUMNS = COLUMNS_V1 + ["expectation_held"]
RUN_CLASSES = {"baseline", "main", "check", "exploratory", "known-answer"}
PREREG = {"pre-registered", "added after results", "exploratory, added after results", "not applicable"}
STATUSES = {"ok", "failed"}


def arm_key(**factors):
    """A stable name for an arm from its factors, in FACTORS order."""
    unknown = set(factors) - set(FACTORS)
    if unknown:
        raise KeyError(f"unknown factor(s): {sorted(unknown)}")
    return "|".join(f"{f}={factors[f]}" for f in FACTORS if factors.get(f) not in (None, ""))


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return "" if math.isnan(v) else "%.10g" % v
    return str(v)


class Ledger:
    def __init__(self, path, identity):
        """identity: run_id, inputs_sha256, harness_sha256, environment_sha256, config_sha256, seed."""
        self.path = path
        self.identity = identity
        self.rows = []
        self.version = 2
        if os.path.exists(path):
            with open(path, newline="") as fh:
                r = csv.DictReader(fh)
                if r.fieldnames == COLUMNS_V1:
                    self.version = 1
                elif r.fieldnames != COLUMNS:
                    raise ValueError(f"{path} has other columns than this ledger version")
                self.rows = [{**row, "expectation_held": row.get("expectation_held") or ""} for row in r]
        self.arms_this_run = set()

    def _migrate(self):
        """Rewrite a version 1 file with the version 2 header. Earlier lines gain one empty cell, nothing else."""
        with open(self.path, newline="") as fh:
            old = fh.read().split("\n")
        if old and old[-1] == "":
            old = old[:-1]
        new = [",".join(COLUMNS)] + [line + "," for line in old[1:]]
        assert old[0] == ",".join(COLUMNS_V1), "unexpected version 1 header"
        assert len(old) - 1 == len(self.rows), "a field holds a line break, so lines are not rows"
        assert all(n[:-1] == o for n, o in zip(new[1:], old[1:])), "an earlier line would change"
        tmp = f"{self.path}.migrating"
        with open(tmp, "w", newline="") as fh:
            fh.write("\n".join(new) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self.version = 2

    def _next_id(self):
        return f"R{len(self.rows) + 1:05d}"

    def append(self, row):
        unknown = set(row) - set(COLUMNS)
        if unknown:
            raise KeyError(f"unknown ledger column(s): {sorted(unknown)}")
        for need in ("measure", "run_class", "prereg_status", "status"):
            if not row.get(need):
                raise KeyError(f"ledger row needs {need}")
        if row["run_class"] not in RUN_CLASSES:
            raise ValueError(f"run_class {row['run_class']!r} not in {sorted(RUN_CLASSES)}")
        if row["prereg_status"] not in PREREG:
            raise ValueError(f"prereg_status {row['prereg_status']!r} not in {sorted(PREREG)}")
        if row["status"] not in STATUSES:
            raise ValueError(f"status {row['status']!r} not in {sorted(STATUSES)}")
        arm = arm_key(**{f: row.get(f) for f in FACTORS})
        if arm in self.arms_this_run:
            raise ValueError(f"arm written twice in one run: {arm}")
        earlier = [r for r in self.rows if r["arm"] == arm]
        full = {c: "" for c in COLUMNS}
        full.update({k: _fmt(v) for k, v in row.items()})
        full.update({k: _fmt(v) for k, v in self.identity.items()})
        full.update({"row_id": self._next_id(), "arm": arm,
                     "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                     "supersedes": earlier[-1]["row_id"] if earlier else ""})
        new_file = not os.path.exists(self.path)
        if not new_file and self.version == 1:
            self._migrate()
        with open(self.path, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
            if new_file:
                w.writeheader()
            w.writerow(full)
            fh.flush()
            os.fsync(fh.fileno())
        self.rows.append(full)
        self.arms_this_run.add(arm)
        return full["row_id"]

    def current(self):
        """Rows that no later row supersedes."""
        gone = {r["supersedes"] for r in self.rows if r["supersedes"]}
        return [r for r in self.rows if r["row_id"] not in gone]
