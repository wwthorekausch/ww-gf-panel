import sys
from pathlib import Path

MODUL = Path(__file__).parent.parent
sys.path.insert(0, str(MODUL))
sys.path.insert(0, str(MODUL.parent))
