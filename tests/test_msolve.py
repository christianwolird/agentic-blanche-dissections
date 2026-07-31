import shutil
from fractions import Fraction

from agentic_blanche.msolve import MSolve, parse_exact_rur, parse_finite_rur
from agentic_blanche.polynomial import PolynomialSystem, SparsePolynomial


def test_parse_exact_rur_and_rational_point():
    output = (
        repr(
            [
                0,
                [
                    0,
                    2,
                    1,
                    ["x", "y"],
                    [0, 1],
                    [
                        1,
                        [
                            [1, [-1, 1]],
                            [0, [1]],
                            [[[0, [-2]], 1]],
                        ],
                    ],
                ],
            ]
        )
        + ":"
    )
    rur = parse_exact_rur(output)
    assert rur is not None
    assert rur.rational_points() == ({"x": Fraction(2), "y": Fraction(1)},)


def test_parse_finite_rur_factor_degrees():
    output = (
        repr(
            [
                0,
                [
                    101,
                    3,
                    2,
                    ["x", "y", "z"],
                    [0, 0, 1],
                    [
                        1,
                        [
                            [2, [-1, 0, 1]],
                            [0, [1]],
                            [
                                [[0, [0]], 1],
                                [[0, [0]], 1],
                            ],
                        ],
                    ],
                ],
            ]
        )
        + ":"
    )
    rur = parse_finite_rur(output)
    assert rur is not None
    assert rur.degree == 2
    assert rur.factor_degrees == (1, 1)
    assert rur.unfactored_degree == 0
    assert rur.linear_factor_count == 2


def test_finite_rur_recovers_linear_root_coordinates():
    output = (
        repr(
            [
                0,
                [
                    101,
                    2,
                    1,
                    ["x", "y"],
                    [0, 1],
                    [
                        1,
                        [
                            [1, [-7, 1]],
                            [0, [1]],
                            [[[0, [-3]], 1]],
                        ],
                    ],
                ],
            ]
        )
        + ":"
    )
    rur = parse_finite_rur(output)
    assert rur is not None
    assert rur.finite_points() == ({"x": 3, "y": 7},)


def test_parse_empty_variety():
    assert parse_exact_rur("[-1]:") is None
    assert parse_finite_rur("[-1]:") is None
    if shutil.which("msolve"):
        variable = SparsePolynomial.variable(0, 1)
        system = PolynomialSystem(
            ("x",),
            (variable - SparsePolynomial.constant(1, 1),),
        )
        solve = MSolve(timeout=5).exact(system)
        assert solve.rur is not None
        assert solve.rur.rational_points() == ({"x": Fraction(1)},)
