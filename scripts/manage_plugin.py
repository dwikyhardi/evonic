#!/usr/bin/env python3
"""
CLI tool to install or uninstall a plugin.

Usage:
  python manage_plugin.py install <path_to_plugin_dir_or_zip>
  python manage_plugin.py uninstall <plugin_id>
  python manage_plugin.py list
"""

import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.plugin_manager import plugin_manager


def cmd_install(path: str, force: bool = False):
    path = os.path.abspath(path)
    if path.endswith('.zip'):
        if not os.path.isfile(path):
            print(f"Error: file not found: {path}")
            sys.exit(1)
        result = plugin_manager.install_plugin(path, force=force)
    elif os.path.isdir(path):
        result = plugin_manager.install_plugin_from_dir(path, force=force)
    else:
        print(f"Error: {path} is not a zip file or directory")
        sys.exit(1)

    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Installed plugin: {result.get('name', result.get('id', '?'))}")


def cmd_uninstall(plugin_id: str):
    result = plugin_manager.uninstall_plugin(plugin_id)
    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    print(f"Uninstalled plugin: {plugin_id}")


def cmd_list():
    plugins = plugin_manager.list_plugins()
    if not plugins:
        print("No plugins installed.")
        return
    for p in plugins:
        status = "enabled" if p.get('enabled', True) else "disabled"
        events = ', '.join(p.get('events', []))
        print(f"  {p['id']:20s}  v{p.get('version', '?'):8s}  [{status}]  events: {events or 'none'}  {p.get('name', '')}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    command = sys.argv[1]

    if command == 'install':
        if len(sys.argv) < 3:
            print("Usage: python manage_plugin.py install <path> [--force]")
            sys.exit(1)
        force = '--force' in sys.argv
        args = [a for a in sys.argv[2:] if a != '--force']
        if not args:
            print("Usage: python manage_plugin.py install <path> [--force]")
            sys.exit(1)
        cmd_install(args[0], force=force)
    elif command == 'uninstall':
        if len(sys.argv) < 3:
            print("Usage: python manage_plugin.py uninstall <plugin_id>")
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
