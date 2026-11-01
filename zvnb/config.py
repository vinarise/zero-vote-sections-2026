"""The run's configuration and its strict schema. Unknown keys are errors."""
import hashlib
import json

SCHEMA = {
    "years": list,
    "sides": list,
    "ballot": dict,
    "seed": int,
    "min_valid_votes": list,
    "events": list,
    "models": list,
    "models_preregistered": list,
    "wilson_z": float,
    "u1_quantile": float,
    "u2_factor": float,
    "u3_r1_share": float,
    "u3_ratio": float,
    "u3_min_sections": int,
    "python_version": str,
    "stages": list,
    "stages_not_run": dict,
    "reference_checksums": str,
    "ledger": str,
    "finding_dir": str,
}


def validate(cfg):
    """Raise on an unknown key, a missing key or a wrong type."""
    unknown = sorted(set(cfg) - set(SCHEMA))
    missing = sorted(set(SCHEMA) - set(cfg))
    if unknown:
        raise KeyError(f"unknown config keys: {unknown}")
    if missing:
        raise KeyError(f"missing config keys: {missing}")
    for k, t in SCHEMA.items():
        if not isinstance(cfg[k], t) or (t is int and isinstance(cfg[k], bool)):
            raise TypeError(f"config key {k} must be {t.__name__}, got {type(cfg[k]).__name__}")
    return True


def digest(cfg):
    """SHA-256 of the canonical JSON of the config."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
