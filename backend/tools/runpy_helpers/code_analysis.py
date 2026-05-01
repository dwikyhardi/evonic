"""
evonic.code_analysis — AST-based Python code inspection.
"""

import ast
import os
import fnmatch


# ---------------------------------------------------------------------------
# Internal AST helpers
# ---------------------------------------------------------------------------

def _parse_file(path: str) -> ast.Module:
    with open(path, errors='replace') as f:
        source = f.read()
    return ast.parse(source, filename=path)


def _arg_names(args: ast.arguments) -> list:
    names = [a.arg for a in args.args]
    if args.vararg:
        names.append(f'*{args.vararg.arg}')
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append(f'**{args.kwarg.arg}')
    return names


def _decorator_names(decorators: list) -> list:
    names = []
    for d in decorators:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(f'{d.value.id}.{d.attr}' if isinstance(d.value, ast.Name) else d.attr)
        elif isinstance(d, ast.Call):
            if isinstance(d.func, ast.Name):
                names.append(d.func.id)
    return names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_functions(path: str) -> list:
    """List all top-level functions in a Python file.

    Args:
        path: Path to a .py file.

    Returns:
        List of dicts: [{name, line, args, decorators}]

    Example:
        for fn in list_functions('/workspace/app.py'):
            print(fn['line'], fn['name'], fn['args'])
    """
    tree = _parse_file(path)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only top-level (direct children of module)
            results.append({
                'name': node.name,
                'line': node.lineno,
                'args': _arg_names(node.args),
                'decorators': _decorator_names(node.decorator_list),
                'async': isinstance(node, ast.AsyncFunctionDef),
            })
    results.sort(key=lambda x: x['line'])
    return results


def outline(path: str) -> str:
    """Return a hierarchical code outline of a Python file.

    Shows classes with their methods and top-level functions, with line numbers.

    Args:
        path: Path to a .py file.

    Returns:
        Multi-line string outline (also printed to stdout).

    Example:
        print(outline('/workspace/evaluator/engine.py'))
    """
    tree = _parse_file(path)
    lines = [os.path.basename(path)]

    # Top-level nodes in order
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases_str = f'({", ".join(b.id for b in node.bases if isinstance(b, ast.Name))})' if node.bases else ''
            lines.append(f'  class {node.name}{bases_str}  [L{node.lineno}]')
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = 'async ' if isinstance(item, ast.AsyncFunctionDef) else ''
                    args = _arg_names(item.args)
                    lines.append(f'    {prefix}def {item.name}({", ".join(args)})  [L{item.lineno}]')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = 'async ' if isinstance(node, ast.AsyncFunctionDef) else ''
            args = _arg_names(node.args)
            lines.append(f'  {prefix}def {node.name}({", ".join(args)})  [L{node.lineno}]')

    result = '\n'.join(lines)
    print(result)
    return result


