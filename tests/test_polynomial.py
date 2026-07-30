from agentic_blanche.polynomial import (
    PolynomialSystem,
    SparsePolynomial,
    polynomial_product,
)


def test_sparse_polynomial_arithmetic_and_serialization():
    x = SparsePolynomial.variable(0, 2)
    y = SparsePolynomial.variable(1, 2)
    polynomial = (x + y) * (x - y)
    assert polynomial.term_count == 2
    assert polynomial.evaluate((3, 2)) == 5
    assert polynomial.to_msolve(("x", "y")) == "x^2-y^2"


def test_product_and_msolve_system():
    x = SparsePolynomial.variable(0, 2)
    y = SparsePolynomial.variable(1, 2)
    product = polynomial_product((x, y), variable_count=2)
    system = PolynomialSystem(("x", "y"), (product,))
    assert system.to_msolve(101) == "x,y\n101\nx*y\n"
