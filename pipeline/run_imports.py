from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SRC = ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from urban_data_explorer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
