"""Debug base64 pattern matching."""
import re

# Check what matches
code = 'base64 -d data'

# BASH_DANGEROUS_PATTERNS
BASH_PATTERNS = [
    {'pattern': r'\bbase64\s+(-d|--decode)', 'weight': 7, 'category': 'obfuscation'},
]

# DANGEROUS_PATTERNS (from the file)
DANGEROUS_PATTERNS = [
    {'pattern': r'base64\s+-d', 'weight': 7, 'category': 'obfuscation'},
    {'pattern': r'base64\s+--decode', 'weight': 7, 'category': 'obfuscation'},
    {'pattern': r'\bexec\s*\(.*base64', 'weight': 10, 'category': 'obfuscation'},
    {'pattern': r'\beval\s*\(.*base64', 'weight': 10, 'category': 'obfuscation'},
]

print("BASH_DANGEROUS_PATTERNS:")
for p in BASH_PATTERNS:
    m = re.search(p['pattern'], code, re.IGNORECASE)
    if m:
        print(f"  MATCH: {p['pattern']} -> weight={p['weight']}")

print("\nDANGEROUS_PATTERNS:")
for p in DANGEROUS_PATTERNS:
    m = re.search(p['pattern'], code, re.IGNORECASE)
    if m:
        print(f"  MATCH: {p['pattern']} -> weight={p['weight']}")

# Now check what check_safety returns for bash
import sys
sys.path.insert(0, '/workspace')
from backend.tools.lib.heuristic_safety import BASH_DANGEROUS_PATTERNS

print("\nActual BASH_DANGEROUS_PATTERNS base64 patterns:")
for p in BASH_DANGEROUS_PATTERNS:
    if 'base64' in p.get('pattern', ''):
        print(f"  {p}")
