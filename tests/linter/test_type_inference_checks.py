"""Tests for type-inference-on-variant lint rule.

Godot 4.6 cannot infer types via := when the RHS expression evaluates to
Variant. This includes and/or chains with nullable operands, null literals,
and ternary expressions where one branch is null.
"""

import pytest

from gdtoolkit.linter import lint_code


RULE = "type-inference-on-variant"


class TestAndOrChains:
    """`:= x and y` or `:= x or y` produce Variant when x can be null."""

    def test_inferred_and_chain_flagged(self):
        code = """\
extends Node3D

var _controller = null

func _ready():
    var blocking := _controller and _controller.is_active()
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 6

    def test_inferred_or_chain_flagged(self):
        code = """\
extends Node3D

var _anim = null

func _ready():
    var fallback := _anim or get_node("Fallback")
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 6

    def test_inferred_mixed_and_or_flagged(self):
        code = """\
extends Node3D

var _a = null
var _b = null

func _ready():
    var result := _a and _b or false
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1

    def test_explicit_type_not_flagged(self):
        """var x: bool = a and b is fine — explicit type annotation."""
        code = """\
extends Node3D

var _controller = null

func _ready():
    var blocking: bool = _controller and _controller.is_active()
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_no_infer_equals_not_flagged(self):
        """var x = a and b (no :=) is fine — Godot treats as Variant."""
        code = """\
extends Node3D

var _controller = null

func _ready():
    var blocking = _controller and _controller.is_active()
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0


class TestNullLiteral:
    """`:= null` has no type to infer."""

    def test_inferred_null_flagged(self):
        code = """\
extends Node3D

func _ready():
    var x := null
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 4

    def test_explicit_null_not_flagged(self):
        code = """\
extends Node3D

func _ready():
    var x: Node3D = null
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0


class TestTernaryWithNull:
    """`:= x if cond else null` — null branch makes type ambiguous."""

    def test_ternary_with_null_branch_flagged(self):
        code = """\
extends Node3D

func _ready():
    var node := get_node("path") if has_node("path") else null
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 4

    def test_ternary_without_null_not_flagged(self):
        code = """\
extends Node3D

func _ready():
    var val := 10 if true else 20
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0


class TestClassVariables:
    """Rule should also apply to class-level := declarations."""

    def test_class_var_and_chain_flagged(self):
        code = """\
extends Node3D

var _a = null
var result := _a and true
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 4

    def test_class_var_null_flagged(self):
        code = """\
extends Node3D

var x := null
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 1
        assert problems[0].line == 3


class TestSafeInference:
    """Patterns that should NOT be flagged — type is resolvable."""

    def test_int_literal(self):
        code = """\
extends Node3D

func _ready():
    var x := 42
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_float_literal(self):
        code = """\
extends Node3D

func _ready():
    var x := 3.14
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_string_literal(self):
        code = """\
extends Node3D

func _ready():
    var x := "hello"
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_bool_literal(self):
        code = """\
extends Node3D

func _ready():
    var x := true
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_constructor_call(self):
        code = """\
extends Node3D

func _ready():
    var vec := Vector3(1, 2, 3)
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_dotted_new(self):
        code = """\
extends Node3D

func _ready():
    var node := Node3D.new()
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_comparison_ok(self):
        """Comparisons produce bool, which is a concrete type."""
        code = """\
extends Node3D

func _ready():
    var x := 1 == 2
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_not_expr_ok(self):
        """not produces bool."""
        code = """\
extends Node3D

func _ready():
    var x := not true
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_array_literal(self):
        code = """\
extends Node3D

func _ready():
    var arr := [1, 2, 3]
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0

    def test_dict_literal(self):
        code = """\
extends Node3D

func _ready():
    var d := {"a": 1}
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0


class TestDisable:
    """Rule can be disabled via config."""

    def test_disabled_via_config(self):
        from types import MappingProxyType
        from gdtoolkit.linter import DEFAULT_CONFIG

        config = dict(DEFAULT_CONFIG)
        config["disable"] = [RULE]
        config = MappingProxyType(config)

        code = """\
extends Node3D

func _ready():
    var x := null
"""
        problems = [p for p in lint_code(code, config) if p.name == RULE]
        assert len(problems) == 0

    def test_disabled_via_inline_ignore(self):
        code = """\
extends Node3D

func _ready():
    var x := null  # gdlint: ignore=type-inference-on-variant
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 0


class TestMultipleProblemsInOneFile:
    """Multiple := issues in a single file should all be reported."""

    def test_multiple_problems(self):
        code = """\
extends Node3D

var _ctrl = null

func _ready():
    var a := _ctrl and _ctrl.active()
    var b := null
    var c := get_node("x") if true else null
"""
        problems = [p for p in lint_code(code) if p.name == RULE]
        assert len(problems) == 3
        assert problems[0].line == 6
        assert problems[1].line == 7
        assert problems[2].line == 8
