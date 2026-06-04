"""pytest 引导：把 src/ 加入 import path，使测试可 `from common.config import ...`。"""
import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
