import os
import sys

# Add project root to sys.path so that 'plugins', 'skills', 'backend', etc. are importable.
# The test files live at plugins/kanban/tests/, so the project root is 3 levels up from here.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
