"""Put the repository root on the path so `skillpack` imports from anywhere."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
