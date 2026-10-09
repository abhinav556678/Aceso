"""Deterministic clinical metrics. Pure functions, unit-tested against known oracles."""


def egfr_ckdepi_2021(scr_mg_dl: float, age: int, sex: str) -> float:
    """CKD-EPI 2021 (race-free) eGFR in mL/min/1.73 m²."""
    k = 0.7 if sex == "F" else 0.9
    a = -0.241 if sex == "F" else -0.302
    v = 142 * min(scr_mg_dl / k, 1) ** a * max(scr_mg_dl / k, 1) ** -1.200 * 0.9938 ** age
    return round(v * 1.012 if sex == "F" else v, 1)
