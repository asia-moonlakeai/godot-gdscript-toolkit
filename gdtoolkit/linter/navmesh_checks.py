"""Navigation mesh linter checks for CSG timing issues."""

import re
from types import MappingProxyType
from typing import List

from lark import Token, Tree

from ..common.ast import AbstractSyntaxTree
from .problem import Problem

CSG_TYPES = frozenset({
    "CSGBox3D",
    "CSGCylinder3D",
    "CSGSphere3D",
    "CSGTorus3D",
    "CSGPolygon3D",
    "CSGMesh3D",
    "CSGShape3D",
    "CSGCombiner3D",
})

_CSG_PATTERN = re.compile(r"^CSG\w+3D$")


def lint(parse_tree: Tree, config: MappingProxyType) -> List[Problem]:
    disabled = config.get("disable", []) or []
    problems: List[Problem] = []
    if "navmesh-bake-before-csg-ready" not in disabled:
        problems.extend(_navmesh_csg_check(parse_tree))
    return problems


def _tree_has_csg_reference(node) -> bool:
    """Check if a Lark (sub)tree contains any CSG type name token."""
    if isinstance(node, Token):
        return bool(_CSG_PATTERN.match(str(node)))
    for child in node.children:
        if _tree_has_csg_reference(child):
            return True
    return False


def _find_bake_tokens(node, results=None):
    """Find all 'bake_navigation_mesh' NAME tokens in the tree."""
    if results is None:
        results = []
    if isinstance(node, Token):
        if str(node) == "bake_navigation_mesh":
            results.append(node)
        return results
    for child in node.children:
        _find_bake_tokens(child, results)
    return results


def _find_call_deferred_targets(node, results=None):
    """Find string arguments to call_deferred(), returning (method_name, token) pairs.

    Handles both standalone calls (``call_deferred("method")``) and
    getattr calls (``obj.call_deferred("method")``).
    """
    if results is None:
        results = []
    if isinstance(node, Token):
        return results
    # standalone_call: first child is NAME "call_deferred", remaining are args
    # getattr_call: contains a getattr subtree ending with "call_deferred", then args
    if hasattr(node, "data"):
        rule = str(node.data)
        if rule == "standalone_call":
            children = node.children
            if (
                children
                and isinstance(children[0], Token)
                and str(children[0]) == "call_deferred"
            ):
                _extract_first_string_arg(children[1:], results)
                return results
        elif rule == "getattr_call":
            # Look for a getattr child whose last NAME is call_deferred
            has_call_deferred = False
            for child in node.children:
                if (
                    not isinstance(child, Token)
                    and hasattr(child, "data")
                    and str(child.data) == "getattr"
                ):
                    names = [
                        c
                        for c in child.children
                        if isinstance(c, Token) and c.type == "NAME"
                    ]
                    if names and str(names[-1]) == "call_deferred":
                        has_call_deferred = True
            if has_call_deferred:
                _extract_first_string_arg(node.children, results)
                return results
    for child in node.children:
        if not isinstance(child, Token):
            _find_call_deferred_targets(child, results)
    return results


def _extract_first_string_arg(children, results):
    """Extract the first string literal from a list of tree children."""
    for child in children:
        if isinstance(child, Token):
            continue
        if hasattr(child, "data") and str(child.data) == "string":
            for sub in child.children:
                if isinstance(sub, Token) and sub.type == "REGULAR_STRING":
                    # Strip surrounding quotes
                    method_name = str(sub)[1:-1]
                    results.append((method_name, sub))
                    return


def _has_physics_await_before(func_node, bake_line: int) -> bool:
    """Check if function contains 'await ...physics_frame' before bake_line."""
    stack = [func_node]
    while stack:
        node = stack.pop()
        if isinstance(node, Token):
            continue
        if hasattr(node, "data") and str(node.data) == "await_expr":
            # Check if this await_expr references physics_frame
            await_line = None
            has_physics_frame = False
            for child in node.children:
                if isinstance(child, Token):
                    if child.type == "NAME" and str(child) == "await":
                        await_line = child.line
                else:
                    # Walk subtree for physics_frame token
                    sub_stack = [child]
                    while sub_stack:
                        sub = sub_stack.pop()
                        if isinstance(sub, Token):
                            if str(sub) == "physics_frame":
                                has_physics_frame = True
                                if await_line is None:
                                    await_line = sub.line
                        else:
                            sub_stack.extend(sub.children)
            if has_physics_frame and await_line is not None and await_line < bake_line:
                return True
        else:
            stack.extend(node.children)
    return False


def _navmesh_csg_check(parse_tree: Tree) -> List[Problem]:
    """Detect bake_navigation_mesh() in classes that create CSG dynamically."""
    ast = AbstractSyntaxTree(parse_tree)
    problems: List[Problem] = []

    for cls in ast.all_classes:
        # Step 1: Does this class create CSG nodes in any method?
        has_csg = False
        for func in cls.all_functions:
            if _tree_has_csg_reference(func.lark_node):
                has_csg = True
                break
        # Also check class-level statements (onready vars)
        if not has_csg:
            for stmt in cls.statements:
                if _tree_has_csg_reference(stmt.lark_node):
                    has_csg = True
                    break
        if not has_csg:
            continue

        # Step 2: Find which methods contain bake calls
        safe_functions = {"_physics_process", "_process"}
        bake_methods = {}  # method_name -> list of bake tokens

        for func in cls.all_functions:
            tokens = _find_bake_tokens(func.lark_node)
            if tokens:
                bake_methods[func.name] = tokens

        # Build a lookup from function name to its lark_node
        func_nodes = {func.name: func.lark_node for func in cls.all_functions}

        # Step 3: Report problems for bake calls in unsafe functions
        for func_name, tokens in bake_methods.items():
            if func_name in safe_functions:
                continue
            func_node = func_nodes.get(func_name)
            for token in tokens:
                if func_node and _has_physics_await_before(func_node, token.line):
                    continue
                problems.append(Problem(
                    name="navmesh-bake-before-csg-ready",
                    description=(
                        "bake_navigation_mesh() called in a class that creates "
                        "CSG geometry dynamically. CSG collision shapes need "
                        "multiple physics frames to generate — baking immediately "
                        "produces an empty navmesh. Await physics frames or use "
                        "a Timer before baking."
                    ),
                    line=token.line,
                    column=token.column if hasattr(token, "column") else 0,
                ))

    return problems
