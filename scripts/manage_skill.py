#!/usr/bin/env python3
"""
CLI tool to install or uninstall a skill.

Usage:
  python manage_skill.py install <path_to_skill_dir_or_zip>
  python manage_skill.py uninstall <skill_id>
  python manage_skill.py list
"""

import sys
import os
import json

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.skills_manager import skills_manager


def cmd_install(path: str, force: bool = False):
    path = os.path.abspath(path)
    if path.endswith('.zip'):
        if not os.path.isfile(path):
            print(f"Error: file not found: {path}")
            sys.exit(1)
        result = skills_manager.install_skill(path, force=force)
    elif os.path.isdir(path):
        result = skills_manager.install_skill_from_dir(path, force=force)
    else:
        print(f"Error: {path} is not a zip file or directory")
        sys.exit(1)

    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Installed skill: {result.get('name', result.get('id', '?'))}")
    setup = result.get('_setup_result', {})
    if setup.get('error'):
        print(f"Warning — setup.install() error: {setup['error']}")
    elif setup.get('message'):
        print(f"  {setup['message']}")


def cmd_uninstall(skill_id: str):
    result = skills_manager.uninstall_skill(skill_id)
    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    print(f"Uninstalled skill: {skill_id}")
    setup = result.get('setup_result', {})
    if setup.get('message'):
        print(f"  {setup['message']}")


def cmd_list():
    skills = skills_manager.list_skills()
    if not skills:
        print("No skills installed.")
        return
    for s in skills:
        status = "enabled" if s.get('enabled', True) else "disabled"
        print(f"  {s['id']:20s}  v{s.get('version', '?'):8s}  {s.get('tool_count', 0):2d} tools  [{status}]  {s.get('name', '')}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    command = sys.argv[1]

    if command == 'install':
        if len(sys.argv) < 3:
            print("Usage: python manage_skill.py install <path> [--force]")
            sys.exit(1)
        force = '--force' in sys.argv
        args = [a for a in sys.argv[2:] if a != '--force']
        if not args:
            print("Usage: python manage_skill.py install <path> [--force]")
            sys.exit(1)
        cmd_install(args[0], force=force)
    elif command == 'uninstall':
        if len(sys.argv) < 3:
            print("Usage: python manage_skill.py uninstall <skill_id>")
            sys.exit(1)
        cmd_uninstall(sys.argv[2])
    elif command == 'list':
        cmd_list()
    else:
        print(f"Unknown command: {command}")
        print(__doc__.strip())
        sys.exit(1)


if __name__ == '__main__':
    main()
