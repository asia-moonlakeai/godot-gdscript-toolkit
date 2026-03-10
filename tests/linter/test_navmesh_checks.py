"""Tests for Godot-engine-specific linter checks."""

from gdtoolkit.parser import parser as gd_parser

from .common import simple_ok_check, simple_nok_check


def test_no_problems_on_empty_script():
    simple_ok_check("")


def test_no_problems_on_basic_class():
    code = """\
extends Node3D

var speed: float = 5.0

func _ready():
    print("hello")
"""
    simple_ok_check(code)


def test_parse_tree_csg_new():
    code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
"""
    tree = gd_parser.parse(code, gather_metadata=True)
    print(tree.pretty())
    assert tree is not None


def test_parse_tree_bake_call():
    code = """\
extends Node3D

var nav_region: NavigationRegion3D

func _setup():
    nav_region.bake_navigation_mesh()

func _deferred():
    call_deferred("_do_bake")
"""
    tree = gd_parser.parse(code, gather_metadata=True)
    assert tree is not None


class TestCsgDetection:
    def test_detects_csg_box_new(self):
        from gdtoolkit.linter.navmesh_checks import _tree_has_csg_reference

        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert _tree_has_csg_reference(tree)

    def test_detects_csg_cylinder_new(self):
        from gdtoolkit.linter.navmesh_checks import _tree_has_csg_reference

        code = """\
extends Node3D

func _ready():
    var cyl = CSGCylinder3D.new()
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert _tree_has_csg_reference(tree)

    def test_no_csg_in_basic_script(self):
        from gdtoolkit.linter.navmesh_checks import _tree_has_csg_reference

        code = """\
extends Node3D

func _ready():
    var mesh = MeshInstance3D.new()
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert not _tree_has_csg_reference(tree)

    def test_no_csg_in_empty_script(self):
        from gdtoolkit.linter.navmesh_checks import _tree_has_csg_reference

        code = ""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert not _tree_has_csg_reference(tree)


class TestBakeDetection:
    def test_finds_bake_call(self):
        from gdtoolkit.linter.navmesh_checks import _find_bake_tokens

        code = """\
extends Node3D

func _setup():
    nav_region.bake_navigation_mesh()
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        tokens = _find_bake_tokens(tree)
        assert len(tokens) >= 1
        assert any(t.line == 4 for t in tokens)

    def test_no_bake_in_basic_script(self):
        from gdtoolkit.linter.navmesh_checks import _find_bake_tokens

        code = """\
extends Node3D

func _ready():
    print("hello")
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert len(_find_bake_tokens(tree)) == 0

    def test_finds_call_deferred_target(self):
        from gdtoolkit.linter.navmesh_checks import _find_call_deferred_targets

        code = """\
extends Node3D

func _setup():
    call_deferred("_do_bake")
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        targets = _find_call_deferred_targets(tree)
        assert any(name == "_do_bake" for name, _ in targets)

    def test_no_call_deferred_in_basic_script(self):
        from gdtoolkit.linter.navmesh_checks import _find_call_deferred_targets

        code = """\
extends Node3D

func _ready():
    print("hello")
"""
        tree = gd_parser.parse(code, gather_metadata=True)
        assert len(_find_call_deferred_targets(tree)) == 0


class TestNavmeshCsgCheck:
    def test_csg_and_bake_in_same_ready(self):
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
    var nav = NavigationRegion3D.new()
    nav.bake_navigation_mesh()
"""
        simple_nok_check(code, "navmesh-bake-before-csg-ready", line=7)

    def test_csg_in_one_method_bake_in_another(self):
        code = """\
extends Node3D

func _build():
    var box = CSGBox3D.new()
    add_child(box)

func _setup_nav():
    nav_region.bake_navigation_mesh()
"""
        simple_nok_check(code, "navmesh-bake-before-csg-ready", line=8)

    def test_no_csg_bake_ok(self):
        code = """\
extends Node3D

func _ready():
    var nav = NavigationRegion3D.new()
    nav.bake_navigation_mesh()
"""
        simple_ok_check(code)

    def test_csg_no_bake_ok(self):
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
"""
        simple_ok_check(code)

    def test_no_csg_no_bake_ok(self):
        code = """\
extends Node3D

func _ready():
    print("hello")
"""
        simple_ok_check(code)

    def test_bake_in_physics_process_ok(self):
        code = """\
extends Node3D
var baked: bool = false

func _ready():
    var box = CSGBox3D.new()
    add_child(box)

func _physics_process(_delta):
    if not baked:
        nav.bake_navigation_mesh()
        baked = true
"""
        simple_ok_check(code)

    def test_bake_in_process_ok(self):
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()

func _process(_delta):
    nav.bake_navigation_mesh()
"""
        simple_ok_check(code)

    def test_deferred_to_bake_single_report(self):
        """call_deferred to bake method: exactly 1 problem at bake site."""
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
    call_deferred("_bake")

func _bake():
    nav.bake_navigation_mesh()
"""
        from gdtoolkit.linter import lint_code

        problems = lint_code(code)
        navmesh = [p for p in problems if p.name == "navmesh-bake-before-csg-ready"]
        assert len(navmesh) == 1
        assert navmesh[0].line == 9  # bake call site, not call_deferred site

    def test_bake_after_await_physics_frame_ok(self):
        """Bake after awaiting physics_frame is safe."""
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
    await get_tree().physics_frame
    await get_tree().physics_frame
    nav.bake_navigation_mesh()
"""
        simple_ok_check(code)

    def test_bake_without_await_still_flagged(self):
        """Bake without await is still flagged even with CSG."""
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
    nav.bake_navigation_mesh()
"""
        simple_nok_check(code, "navmesh-bake-before-csg-ready", line=6)

    def test_multiple_csg_types(self):
        """All CSG types should be detected."""
        for csg_type in ["CSGCylinder3D", "CSGSphere3D", "CSGPolygon3D", "CSGMesh3D"]:
            code = (
                "extends Node3D\n\n"
                "func _ready():\n"
                "    var shape = %s.new()\n"
                "    add_child(shape)\n"
                "    nav.bake_navigation_mesh()\n" % csg_type
            )
            simple_nok_check(code, "navmesh-bake-before-csg-ready", line=6)

    def test_csg_and_bake_via_call_deferred(self):
        code = """\
extends Node3D

func _ready():
    var box = CSGBox3D.new()
    add_child(box)
    call_deferred("_bake_nav")

func _bake_nav():
    nav_region.bake_navigation_mesh()
"""
        simple_nok_check(code, "navmesh-bake-before-csg-ready", line=9)
