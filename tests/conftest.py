import os
import sys
from pathlib import Path

try:
    import pyproj

    os.environ["PROJ_LIB"] = pyproj.datadir.get_data_dir()
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "geosteiner: optional tests requiring GeoSteiner efst/bb binaries",
    )
