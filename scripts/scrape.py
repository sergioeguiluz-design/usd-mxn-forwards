"""Extrae forwards USD/MXN de Investing y guarda data/forwards.json.

Si algo falla, deja el JSON anterior intacto (solo actualiza last_error).
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

FWD_URL = "https://mx.investing.com/currencies/usd-mxn-forward-rates"
SPOT_URL = "https://mx.investing.com/currencies/usd-mxn"
OUT = Path(__file__).resolve().parent.parent / "data" / "forwards.json"

# Plazo en la web -> etiqueta que mostramos
TENORS = {"1M": "1M", "3M": "3M", "6M": "6M", "9M": "9M", "1Y": "1A"}

HEADERS = {"Accept-Language": "es-MX,es;q=0.9,en;q=0.8"}


def fetch(url):
    r = requests.get(url, impersonate="chrome", headers=HEADERS, timeout=30)
    print(f"GET {url} -> {r.status_code} ({len(r.text)} bytes)")
    r.raise_for_status()
    return r.text


def to_float(text):
    text = text.strip().replace(",", "")
    return float(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None


def parse_forwards(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        name = " ".join(cells[:2]).upper()
        if "MXN" not in name or "FWD" not in name:
            continue
        print("ROW:", cells)
        m = re.search(r"\b(1M|3M|6M|9M|1Y)\b", name)
        if not m or m.group(1) in found:
            continue
        nums = [v for v in (to_float(c) for c in cells) if v is not None]
        if len(nums) >= 2:
            found[m.group(1)] = (nums[0], nums[1])
    return found


def parse_spot(html):
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find(attrs={"data-test": "instrument-price-last"})
    if el:
        return to_float(el.get_text())
    return None


def main():
    previous = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        found = parse_forwards(fetch(FWD_URL))
        missing = [t for t in TENORS if t not in found]
        if missing:
            raise ValueError(f"No se encontraron los plazos {missing}")
        spot = parse_spot(fetch(SPOT_URL))
        if spot is None:
            raise ValueError("No se encontró el spot")
        rows = []
        for key, label in TENORS.items():
            bid, ask = found[key]
            rows.append({
                "tenor": label,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 4),
            })
        data = {"updated_at": now, "spot": spot, "forwards": rows,
                "source": FWD_URL, "last_error": None}
    except Exception as e:  # conservamos los últimos datos buenos
        print("ERROR:", e, file=sys.stderr)
        data = previous or {"updated_at": None, "spot": None, "forwards": []}
        data["last_error"] = {"at": now, "message": str(e)}
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        sys.exit(1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
