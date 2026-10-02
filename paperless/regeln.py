"""Duplikaterkennung Paperless: nur inhaltsgleiche Dokumente (normalisierter OCR-Text, min. 50 Zeichen)."""
import hashlib
import re
from collections import defaultdict

MIN_ZEICHEN = 50


def schluessel(dok: dict) -> str | None:
    text = re.sub(r"\s+", " ", (dok.get("content") or "")).strip().lower()
    if len(text) < MIN_ZEICHEN:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gruppen(docs: list[dict]) -> list[list[dict]]:
    g = defaultdict(list)
    for d in docs:
        k = schluessel(d)
        if k:
            g[k].append(d)
    out = [sorted(x, key=lambda d: d["id"]) for x in g.values() if len(x) > 1]
    return sorted(out, key=lambda x: x[0]["id"])


def loeschplan(gruppe: list[dict]) -> tuple[dict, list[dict]]:
    """Ältestes Dokument (added, dann id) bleibt, Rest wird gelöscht."""
    sortiert = sorted(gruppe, key=lambda d: (d.get("added") or "", d["id"]))
    return sortiert[0], sorted(sortiert[1:], key=lambda d: d["id"])


def noch_gleich(behalten: dict, frisch: dict) -> bool:
    k = schluessel(behalten)
    return k is not None and k == schluessel(frisch)
