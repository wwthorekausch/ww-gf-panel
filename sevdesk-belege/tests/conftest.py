import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

MODUL = Path(__file__).parent.parent
sys.path.insert(0, str(MODUL))
sys.path.insert(0, str(MODUL.parent))

HEUTE = date(2026, 10, 1)


def D(x) -> Decimal:
    return Decimal(str(x))
