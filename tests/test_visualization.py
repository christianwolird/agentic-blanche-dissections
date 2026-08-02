import json
import sqlite3
from pathlib import Path

import sympy

from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph
from agentic_blanche.msolve import ExactRUR
from agentic_blanche.visualization import (
    AlgebraicTiling,
    congruence_partition_label,
    exact_congruence_classes,
    load_task_entry,
    rectangle_geometry,
    render_task_svg,
    rur_coordinate_functions,
)


def cycle_task() -> RootedPlaneGraph:
    graph = PlaneGraph(
        (
            (1, 3),
            (2, 0),
            (3, 1),
            (0, 2),
        )
    )
    return RootedPlaneGraph(graph, (0, 1))


def test_rur_coordinate_functions_include_primitive_coordinate():
    parameter = sympy.Symbol("t")
    rur = ExactRUR(
        variables=("x", "y"),
        linear_form=(1, 0),
        polynomial=(-2, 0, 1),
        denominator=(1,),
        parametrizations=(((0, -3), 2),),
    )
    coordinates = rur_coordinate_functions(rur, parameter)
    assert coordinates == {"x": parameter, "y": 3 * parameter / 2}


def test_irrational_congruence_is_checked_exactly_modulo_minimal_factor():
    parameter = sympy.Symbol("t")
    factor = sympy.Poly(parameter**2 - 2, parameter, domain=sympy.QQ)
    currents = {
        (0, 1): parameter,
        (0, 2): 3 * parameter / 2,
        (1, 2): sympy.Integer(1),
    }
    classes = exact_congruence_classes(currents, 3, factor, parameter)
    assert classes == ((1, 2), (3,))
    assert congruence_partition_label(3, classes) == "3=2+1"


def test_partition_abbreviates_many_singletons():
    classes = tuple((index,) for index in range(1, 8))
    assert congruence_partition_label(7, classes) == "7=1+..."
    mixed = ((1, 2, 3, 4), (5,), (6,), (7,))
    assert congruence_partition_label(7, mixed) == "7=4+1+..."


def test_rectangle_geometry_tiles_the_square():
    rooted = cycle_task()
    currents = {
        (0, 3): 3.0,
        (1, 2): -3.0,
        (2, 3): -3.0,
    }
    rectangles = rectangle_geometry(rooted, currents)
    assert [rectangle.rectangle_id for rectangle in rectangles] == [1, 2, 3]
    assert all(abs(rectangle.width - 1.0) < 1e-12 for rectangle in rectangles)
    assert all(abs(rectangle.height - 1 / 3) < 1e-12 for rectangle in rectangles)
    area = sum(rectangle.width * rectangle.height for rectangle in rectangles)
    assert abs(area - 1) < 1e-12


def test_load_task_entry_and_render_svg(tmp_path: Path):
    rooted = cycle_task()
    database = tmp_path / "E4.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE tasks (
            sequence INTEGER PRIMARY KEY,
            task_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
        (
            7,
            "example-task",
            json.dumps({"rotations": rooted.graph.rotations, "root": rooted.root}),
            "completed",
            json.dumps({"presentation": "bilinear"}),
        ),
    )
    connection.commit()
    connection.close()

    entry = load_task_entry(database, "example-task")
    assert entry.sequence == 7
    assert entry.rooted == rooted
    rectangles = rectangle_geometry(
        rooted,
        {(0, 3): 3.0, (1, 2): -3.0, (2, 3): -3.0},
    )
    parameter = sympy.Symbol("t")
    tiling = AlgebraicTiling(
        algebraic_degree=1,
        parameter_approximation="1.0",
        factor=sympy.Poly(parameter - 1, parameter),
        congruence_classes=((1, 2, 3),),
        partition_label="3=3",
        rectangles=rectangles,
    )
    output = render_task_svg(entry, (tiling,), tmp_path / "tiling.svg")
    svg = output.read_text(encoding="utf-8")
    assert "Algebraic degree 1" in svg
    assert "Congruency 3=3" in svg
    assert "#268bd2" in svg
    assert "#fdf6e3" not in svg
    assert "Rectangle 1; edge 0-3" in svg
