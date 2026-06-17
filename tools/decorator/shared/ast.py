from __future__ import annotations

import ast


def extract_export_names(tree: ast.Module, sentinel_name: str) -> set[str] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == sentinel_name for target in node.targets):
            continue
        values: list[str] = []
        literal = node.value
        items: list[ast.expr] = []
        if isinstance(literal, (ast.Tuple, ast.List, ast.Set)):
            items = list(literal.elts)
        elif isinstance(literal, ast.Dict):
            for key, value in zip(literal.keys, literal.values):
                if isinstance(key, ast.Constant) and key.value in {"exports", "export"}:
                    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                        items.extend(list(value.elts))
        for item in items:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
        return set(values)
    return None


def collect_name_references(expr: ast.AST | None) -> set[str]:
    names: set[str] = set()
    if expr is None:
        return names
    for child in ast.walk(expr):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


def collect_argument_references(args: ast.arguments) -> set[str]:
    names: set[str] = set()
    for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        if arg.annotation is not None:
            names |= collect_name_references(arg.annotation)
    if args.vararg is not None and args.vararg.annotation is not None:
        names |= collect_name_references(args.vararg.annotation)
    if args.kwarg is not None and args.kwarg.annotation is not None:
        names |= collect_name_references(args.kwarg.annotation)
    for default in args.defaults:
        names |= collect_name_references(default)
    for default in args.kw_defaults:
        names |= collect_name_references(default)
    return names


def has_decorator(node: ast.FunctionDef | ast.ClassDef, decorator_name: str) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == decorator_name:
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == decorator_name:
            return True
    return False


def collect_import_dependencies(
    tree: ast.Module,
    exported_names: set[str] | None,
    *,
    sentinel_name: str,
    decorator_name: str,
) -> set[str]:
    needed: set[str] = set(exported_names or set())

    def is_exported(node_name: str) -> bool:
        if exported_names is not None:
            return node_name in exported_names
        return not node_name.startswith("_")

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == sentinel_name for target in node.targets):
                continue
            if any(isinstance(target, ast.Name) and is_exported(target.id) for target in node.targets):
                needed |= collect_name_references(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and is_exported(node.target.id):
                needed |= collect_name_references(node.annotation)
                needed |= collect_name_references(node.value)
        elif isinstance(node, ast.FunctionDef):
            if is_exported(node.name) or has_decorator(node, decorator_name):
                for decorator in node.decorator_list:
                    needed |= collect_name_references(decorator)
                needed |= collect_name_references(node.returns)
                needed |= collect_argument_references(node.args)
        elif isinstance(node, ast.ClassDef):
            if is_exported(node.name) or has_decorator(node, decorator_name):
                for decorator in node.decorator_list:
                    needed |= collect_name_references(decorator)
                for base in node.bases:
                    needed |= collect_name_references(base)
                for keyword in node.keywords:
                    needed |= collect_name_references(keyword.value)
                for child in node.body:
                    if isinstance(child, ast.AnnAssign):
                        needed |= collect_name_references(child.annotation)
                        needed |= collect_name_references(child.value)
                    elif isinstance(child, ast.Assign):
                        needed |= collect_name_references(child.value)
                    elif isinstance(child, ast.FunctionDef):
                        needed |= collect_name_references(child.returns)
                        needed |= collect_argument_references(child.args)
                        for decorator in child.decorator_list:
                            needed |= collect_name_references(decorator)
    return needed
