"""Manual test for heuristic safety fixes."""
import sys
sys.path.insert(0, '/workspace')
from backend.tools.lib.heuristic_safety import check_safety

tests = [
    # (code, tool_type, expected_level, description)
    ('rm -rf /tmp/file', 'bash', 'safe', 'rm -rf /tmp/file should be safe'),
    ('rm -rf /tmp', 'bash', 'safe', 'rm -rf /tmp should be safe'),
    ('rm -rf /etc/passwd', 'bash', 'requires_approval', 'rm -rf /etc/passwd should be blocked'),
    ('rm -rf /var/log', 'bash', 'requires_approval', 'rm -rf /var/log should be blocked'),
    ('ls -la', 'bash', 'safe', 'ls -la should be safe'),
    ('cd /tmp', 'bash', 'safe', 'cd /tmp should be safe'),
    ('echo hello', 'bash', 'safe', 'echo hello should be safe'),
    ('grep pattern file', 'bash', 'safe', 'grep should be safe'),
    ('cat /etc/passwd', 'bash', 'safe', 'cat should be safe'),
    ('docker ps', 'bash', 'dangerous', 'docker should be dangerous'),
    ('chmod 777 file', 'bash', 'warning', 'chmod 777 should be warning'),
    ('sudo command', 'bash', 'requires_approval', 'sudo should be requires_approval'),
    ('eval something', 'bash', 'requires_approval', 'eval should be requires_approval'),
    ('base64 -d data', 'bash', 'warning', 'base64 decode should be warning'),
]

passed = 0
failed = 0

for code, tool_type, expected, desc in tests:
    result = check_safety(code, tool_type)
    actual = result['level']
    status = 'PASS' if actual == expected else 'FAIL'
    if status == 'FAIL':
        failed += 1
    else:
        passed += 1
    print(f'{status}: {desc} -> score={result["score"]}, level={actual} (expected={expected})')

print(f'\n{passed}/{passed+failed} tests passed')
if failed > 0:
    sys.exit(1)
