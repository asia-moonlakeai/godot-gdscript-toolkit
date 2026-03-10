"""Lint checks for unresolvable type inference with := operator.

Godot 4.6 cannot infer the type of a variable declared with := when the
right-hand side evaluates to Variant.  Common patterns that trigger this:

- ``var x := a and b``  (and/or chains with nullable operands)
- ``var x := null``     (null has no type)
- ``var x := a if cond else null``  (ternary with a null branch)

The fix is to use an explicit type annotation:
    var x: bool = a and b
    var x: Node3D = get_node("p") if has_node("p") else null
"""

from types import MappingProxyType
from typing import List

from lark import Token, Tree

from .problem import Problem


RULE_NAME = "type-inference-on-variant"

# AST node names that produce Variant when used with :=
_VARIANT_EXPR_TYPES = frozenset({
    "and_test",
    "or_test",
})


def lint(parse_tree: Tree, config: MappingProxyType) -> List[Problem]:
    disabled = config.get("disable", []) or []
    if RULE_NAME in disabled:
        return []
    return _check_inferred_type_on_variant(parse_tree)


def _check_inferred_type_on_variant(parse_tree: Tree) -> List[Problem]:
    """Walk the parse tree for func_var_inf / class_var_inf nodes
    whose RHS expression evaluates to Variant."""
    problems: List[Problem] = []

    for subtree in parse_tree.iter_subtrees():
        rule = str(subtree.data)
        if rule not in ("func_var_inf", "class_var_inf"):
            continue

        # Structure: var_inf -> NAME, expr
        # The NAME is the variable name, expr wraps the RHS
        name_token = None
        expr_node = None
        for child in subtree.children:
            if isinstance(child, Token) and child.type == "NAME":
                name_token = child
            elif isinstance(child, Tree) and str(child.data) == "expr":
                expr_node = child

        if expr_node is None:
            continue

        if _expr_produces_variant(expr_node):
            line = name_token.line if name_token else _get_line(subtree)
            col = name_token.column if name_token and hasattr(name_token, "column") else 0
            problems.append(Problem(
                name=RULE_NAME,
                description=(
                    "Type cannot be inferred with := because the expression "
                    "evaluates to Variant. Use an explicit type annotation "
                    "instead (e.g. var x: bool = ...)."
                ),
                line=line,
                column=col,
            ))

    return problems


def _expr_produces_variant(expr_node: Tree) -> bool:
    """Check whether an expr node produces a Variant type.

    Unwraps the outer ``expr`` wrapper and inspects the inner expression.
    """
    if not expr_node.children:
        return False

    inner = expr_node.children[0]

    # Token: check for null literal
    if isinstance(inner, Token):
        return str(inner) == "null"

    inner_type = str(inner.data)

    # and/or chains → Variant
    if inner_type in _VARIANT_EXPR_TYPES:
        return True

    # Ternary: ``a if cond else b`` → AST node is test_expr
    # If either branch is null → Variant
    if inner_type == "test_expr":
        return _ternary_has_null_branch(inner)

    return False


def _ternary_has_null_branch(test_expr: Tree) -> bool:
    """Check if a test_expr (ternary) has a null branch.

    AST structure: test_expr -> [true_branch, "if", condition, "else", false_branch]
    """
    for child in test_expr.children:
        if isinstance(child, Token) and str(child) == "null":
            return True
        if isinstance(child, Tree) and str(child.data) == "expr":
            # Unwrap expr to check for null
            for subchild in child.children:
                if isinstance(subchild, Token) and str(subchild) == "null":
                    return True
    return False


def _get_line(node) -> int:
    """Get the line number of a tree node."""
    if isinstance(node, Token):
        return node.line
    for child in node.children:
        line = _get_line(child)
        if line is not None:
            return line
    return 0
