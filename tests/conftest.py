import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORACLE_ROOT = PROJECT_ROOT / "oracle"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORACLE_ROOT))