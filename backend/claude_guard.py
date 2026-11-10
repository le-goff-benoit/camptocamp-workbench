"""PreToolUse hook for a single Workbench run; deny everything not requested."""
import json
from pathlib import Path
import sys


def allowed_tool(name, arguments, allowed, root):
    if name not in allowed:
        return False
    if name in {'Read', 'Glob', 'Grep'}:
        root = Path(root).resolve()
        path = Path(arguments.get('file_path') or arguments.get('path') or root).expanduser().resolve()
        if not (path.is_relative_to(root) or path.is_relative_to(Path.home()/'odoo-sources')):
            return False
        if any(p.startswith('.env') or p in {'.git', '.aws', '.ssh', '.codex', '.claude', 'private'}
               or 'credential' in p.casefold() or 'token' in p.casefold() for p in path.parts):
            return False
    return True


if __name__ == '__main__':
    try:
        config = json.loads(Path(sys.argv[1]).read_text())
        event = json.load(sys.stdin)
        permit = allowed_tool(event.get('tool_name'), event.get('tool_input') or {}, config['allowed'], config['root'])
    except Exception:
        permit = False
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                      'permissionDecision': 'allow' if permit else 'deny',
                      'permissionDecisionReason': 'Workbench autorise uniquement les lectures demandées.'}}))
