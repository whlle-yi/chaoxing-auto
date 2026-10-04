"""把 src 目录加入 sys.path，使测试可以直接 import cxauto。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
