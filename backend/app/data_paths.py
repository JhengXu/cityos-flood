"""Project-local data paths; no dependency on sibling Downloads folders."""
from pathlib import Path

BACKEND_DATA = Path(__file__).resolve().parents[1] / "data"
REAL_GIS = BACKEND_DATA / "real_gis"


def real_file(name: str) -> str:
    return str(REAL_GIS / name)
