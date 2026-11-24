import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / 'src'), str(HERE), str(HERE / 'tests'), str(ROOT / 'experiments')]
