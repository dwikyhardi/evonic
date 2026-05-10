#!/usr/bin/env python3
"""
Evonic one-time migration: flat repo layout → release-based structure.

Run ONCE with the server STOPPED. Can be safely re-run — it tracks progress
and resumes from the last completed step.

Usage:
    python3 supervisor/migrate.py [--app-root /path/to/evonic] [--tag v0.1.0] [--dry-run]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Reuse the supervisor's helper so flat-mode and release-mode share a single
# implementation. Both files live side-by-side in supervisor/, so adding this
# directory to sys.path lets ``import supervisor`` resolve to supervisor.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from supervisor import detect_python_bin  # noqa: E402


# ---------------------------------------------------------------------------
# Items moved to shared/ (source_name, is_directory)
# Plugins are special: only config.json files move, not the whole dir.
# ---------------------------------------------------------------------------
SHARED_MOVES = [
    ('db',      True),
    ('agents',  True),
    ('logs',    True),
    ('run',     True),
    ('kb',      True),
    ('data',    True),
    ('.env',    False),
    ('.ssh',    True),
]

# Plugin config files: plugins/*/config.json → shared/plugins/*/config.json
PLUGIN_CONFIG_GLOB = 'plugins/*/config.json'


def info(msg):
    print(f'[migrate] {msg}')


def err(msg):
    print(f'[migrate] ERROR: {msg}', file=sys.stderr)


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f'Command {cmd} failed:\n{result.stderr}')
    return result


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {'completed_steps': []}


def save_state(state_file: Path, state: dict):
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def step_done(state: dict, step_name: str) -> bool:
    return step_name in state.get('completed_steps', [])


def mark_done(state: dict, state_file: Path, step_name: str):
    state.setdefault('completed_steps', []).append(step_name)
    save_state(state_file, state)
    info(f'  ✓ {step_name}')


def migrate(app_root: str, initial_tag: str, dry_run: bool):
    root = Path(app_root).resolve()

    # --- Pre-flight checks ---
    if not (root / '.git').exists():
        err(f'No .git found in {root}. Are you sure this is the Evonic repo?')
        sys.exit(1)

    if (root / 'releases').exists():
        err('"releases/" already exists. Migration may have already run.')
        err('If you want to re-run, remove releases/ manually first.')
        sys.exit(1)

    # State tracking so re-runs resume
    shared_dir = root / 'shared'
    state_file = shared_dir / '.migration_state'
    # shared/ may already exist if a previous partial run got this far
    shared_dir.mkdir(exist_ok=True)
    state = load_state(state_file)

    info(f'Starting migration of {root}')
    if dry_run:
        info('DRY-RUN mode — no changes will be made')

    # --- Step 1: Move mutable dirs to shared/ ---
    if not step_done(state, 'move_shared'):
        info('Step 1/7: Moving mutable data to shared/')
        for name, is_dir in SHARED_MOVES:
            src = root / name
            dst = shared_dir / name
            if dst.exists():
                info(f'  {name} already in shared/, skipping')
                continue
            if src.exists():
                info(f'  Moving {name}/ → shared/{name}/')
                if not dry_run:
                    shutil.move(str(src), str(dst))
            else:
                info(f'  {name} not found, creating empty in shared/')
                if not dry_run:
                    if is_dir:
                        (shared_dir / name).mkdir(parents=True, exist_ok=True)
                    else:
                        (shared_dir / name).touch()

        # Move plugin config.json files
        plugins_src = root / 'plugins'
        plugins_shared = shared_dir / 'plugins'
        if plugins_src.exists():
            info('  Migrating plugins/*/config.json to shared/plugins/')
            if not dry_run:
                plugins_shared.mkdir(exist_ok=True)
            for config_json in plugins_src.glob('*/config.json'):
                rel = config_json.relative_to(plugins_src)
                dst_cfg = plugins_shared / rel
                if not dst_cfg.exists():
                    info(f'    Moving {config_json} → shared/plugins/{rel}')
                    if not dry_run:
                        dst_cfg.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(config_json), str(dst_cfg))

        if not dry_run:
            mark_done(state, state_file, 'move_shared')

    # --- Step 2: Create initial git tag ---
    if not step_done(state, 'create_tag'):
        info(f'Step 2/7: Creating initial git tag {initial_tag}')
        result = run(['git', '-C', str(root), 'tag', '-l', initial_tag], check=False)
        if initial_tag in result.stdout:
            info(f'  Tag {initial_tag} already exists, skipping')
        else:
            info(f'  Running: git tag {initial_tag} HEAD')
            if not dry_run:
                # Use -a (annotated) without SSH sign for migration simplicity
                # User can sign it afterwards: git tag -s -f v0.1.0
                run(['git', '-C', str(root), 'tag', '-a', initial_tag,
                     '-m', f'Initial release — migration baseline'])
                info(f'  Tag {initial_tag} created (unsigned annotated tag)')
                info(f'  TIP: Sign it with: git -C {root} tag -s -f {initial_tag} -m "Initial release"')
        if not dry_run:
            mark_done(state, state_file, 'create_tag')

    # --- Step 3: Create git worktree ---
    if not step_done(state, 'create_worktree'):
        info(f'Step 3/7: Creating git worktree for {initial_tag}')
        releases_dir = root / 'releases'
        release_path = releases_dir / initial_tag
        if not dry_run:
            releases_dir.mkdir(exist_ok=True)
            run(['git', '-C', str(root), 'worktree', 'add',
                 str(release_path), initial_tag])
            mark_done(state, state_file, 'create_worktree')
        else:
            info(f'  Would create: {release_path}')

    # --- Step 4: Create venv in release ---
    if not step_done(state, 'create_venv'):
        info('Step 4/7: Creating Python venv in release')
        release_path = root / 'releases' / initial_tag
        venv_path = release_path / '.venv'
        req_file = release_path / 'requirements.txt'
        if not dry_run:
            run([sys.executable, '-m', 'venv', str(venv_path)])
            if req_file.exists():
                if sys.platform == 'win32':
                    pip = venv_path / 'Scripts' / 'pip'
                else:
                    pip = venv_path / 'bin' / 'pip'
                run([str(pip), 'install', '-r', str(req_file)])
            mark_done(state, state_file, 'create_venv')
        else:
            info(f'  Would create venv at {venv_path}')

    # --- Step 5: Symlink shared dirs into release ---
    if not step_done(state, 'link_shared'):
        info('Step 5/7: Symlinking shared/ items into release')
        release_path = root / 'releases' / initial_tag

        all_items = SHARED_MOVES + [('plugins', True)]
        for name, is_dir in all_items:
            target = shared_dir / name
            link = release_path / name
            if not target.exists():
                info(f'  shared/{name} not found, skipping link')
                continue
            info(f'  Linking {link} → {target}')
            if not dry_run:
                if link.is_symlink():
                    link.unlink()
                elif link.is_dir():
                    shutil.rmtree(str(link))
                elif link.exists():
                    link.unlink()
                if sys.platform == 'win32' and is_dir:
                    subprocess.run(['cmd', '/c', 'mklink', '/J',
                                    str(link), str(target)], check=True)
                else:
                    # Relative symlink: portable across repo relocation
                    # (matches supervisor.link_shared_dirs).
                    rel_target = os.path.relpath(str(target), os.path.dirname(str(link)))
                    os.symlink(rel_target, str(link),
                               target_is_directory=is_dir)
        if not dry_run:
            mark_done(state, state_file, 'link_shared')

    # --- Step 6: Write VERSION + create current pointer ---
    if not step_done(state, 'create_pointer'):
        info('Step 6/7: Writing VERSION file and creating "current" pointer')
        release_path = root / 'releases' / initial_tag
        if not dry_run:
            (release_path / 'VERSION').write_text(initial_tag)

        if sys.platform == 'win32':
            slot_file = root / 'current.slot'
            info(f'  Writing {slot_file}')
            if not dry_run:
                slot_file.write_text(initial_tag)
        else:
            link = root / 'current'
            rel = os.path.relpath(release_path, root)
            info(f'  Creating symlink: current → {rel}')
            if not dry_run:
                if link.is_symlink():
                    link.unlink()
                os.symlink(rel, str(link))
        if not dry_run:
            mark_done(state, state_file, 'create_pointer')

    # --- Step 7: Write rollback.slot + supervisor/config.json ---
    if not step_done(state, 'finalize'):
        info('Step 7/7: Writing rollback.slot and supervisor config template')
        if not dry_run:
            rollback_file = root / 'rollback.slot'
            rollback_file.write_text(initial_tag)

            sup_dir = root / 'supervisor'
            sup_dir.mkdir(exist_ok=True)
            cfg_template = {
                'app_root': str(root),
                'poll_interval': 300,
                'git_remote': 'origin',
                'health_port': 8080,
                'health_temp_port': 18080,
                'health_timeout': 10,
                'monitor_duration': 60,
                'keep_releases': 3,
                'python_bin': detect_python_bin(str(root)),
                'uv_bin': None,
                'telegram_bot_token': '',
                'telegram_chat_id': '',
            }
            cfg_path = sup_dir / 'config.json'
            if not cfg_path.exists():
                with open(cfg_path, 'w') as f:
                    json.dump(cfg_template, f, indent=4)
                info(f'  Created {cfg_path} — fill in telegram_bot_token and telegram_chat_id')
            else:
                info(f'  {cfg_path} already exists, skipping')

            mark_done(state, state_file, 'finalize')

    # --- Done ---
    info('')
    info('Migration complete!')
    info('')
    info('Next steps:')
    info(f'  1. Review shared/ — confirm all mutable data is there')
    info(f'  2. (Optional) Sign the tag:')
    info(f'     git -C {root} tag -s -f {initial_tag} -m "Initial release"')
    info(f'  3. Configure SSH signing (see supervisor/README.md)')
    info(f'  4. Fill in supervisor/config.json (telegram creds, etc.)')
    info(f'  5. Start the server from the new layout:')
    info(f'     cd {root}/releases/{initial_tag} && .venv/bin/python app.py')
    info(f'     OR: evonic start -d  (if cli reads "current" pointer)')
    info(f'  6. Start the supervisor:')
    info(f'     python3 {root}/supervisor/supervisor.py --config {root}/supervisor/config.json &')


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Evonic from flat repo to release-based layout')
    parser.add_argument('--app-root', default=None,
        help='Path to Evonic repo root (default: parent of this script)')
    parser.add_argument('--tag', default='v0.1.0',
        help='Initial release tag to create (default: v0.1.0)')
    parser.add_argument('--dry-run', action='store_true',
        help='Show what would be done without making changes')
    args = parser.parse_args()

    app_root = args.app_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    migrate(app_root, args.tag, args.dry_run)


if __name__ == '__main__':
    main()
