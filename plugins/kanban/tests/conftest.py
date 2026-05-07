import os
import sys

# Add project root to sys.path so that 'plugins', 'skills', 'backend', etc. are importable.
# conftest.py lives at plugins/kanban/tests/, so the project root is 4 levels up from __file__.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
