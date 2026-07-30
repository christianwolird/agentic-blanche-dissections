"""A small sparse polynomial layer tailored to msolve input."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import reduce
from operator import mul

Exponent = tuple[int, ...]


@dataclass(frozen=True)
class SparsePolynomial:
    """An integer polynomial represented by nonzero monomial coefficients."""

    variable_count: int
    terms: Mapping[Exponent, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[Exponent, int] = {}
        for exponent, coefficient in self.terms.items():
            exponent = tuple(exponent)
            coefficient = int(coefficient)
            if len(exponent) != self.variable_count:
                raise ValueError("monomial has the wrong number of variables")
            if any(power < 0 for power in exponent):
                raise ValueError("negative exponents are not polynomial")
            if coefficient:
                normalized[exponent] = normalized.get(exponent, 0) + coefficient
        object.__setattr__(
            self,
            "terms",
            {
                exponent: coefficient
                for exponent, coefficient in normalized.items()
                if coefficient
            },
        )

    @classmethod
    def zero(cls, variable_count: int) -> SparsePolynomial:
        return cls(variable_count)

    @classmethod
    def constant(cls, value: int, variable_count: int) -> SparsePolynomial:
        if not value:
            return cls.zero(variable_count)
        return cls(variable_count, {(0,) * variable_count: int(value)})

    @classmethod
    def variable(cls, index: int, variable_count: int) -> SparsePolynomial:
        if not 0 <= index < variable_count:
            raise IndexError("variable index out of range")
        exponent = [0] * variable_count
        exponent[index] = 1
        return cls(variable_count, {tuple(exponent): 1})

    @classmethod
    def affine(
        cls,
        constant: int,
        coefficients: Mapping[int, int],
        variable_count: int,
    ) -> SparsePolynomial:
        terms: dict[Exponent, int] = {}
        if constant:
            terms[(0,) * variable_count] = int(constant)
        for index, coefficient in coefficients.items():
            if not 0 <= index < variable_count:
                raise IndexError("variable index out of range")
            if coefficient:
                exponent = [0] * variable_count
                exponent[index] = 1
                terms[tuple(exponent)] = int(coefficient)
        return cls(variable_count, terms)

    @property
    def term_count(self) -> int:
        return len(self.terms)

    @property
    def degree(self) -> int:
        return max((sum(exponent) for exponent in self.terms), default=-1)

    def _check_ring(self, other: SparsePolynomial) -> None:
        if self.variable_count != other.variable_count:
            raise ValueError("polynomials belong to different rings")

    def __add__(self, other: SparsePolynomial) -> SparsePolynomial:
        self._check_ring(other)
        terms = dict(self.terms)
        for exponent, coefficient in other.terms.items():
            terms[exponent] = terms.get(exponent, 0) + coefficient
        return SparsePolynomial(self.variable_count, terms)

    def __sub__(self, other: SparsePolynomial) -> SparsePolynomial:
        return self + other.scale(-1)

    def __mul__(self, other: SparsePolynomial) -> SparsePolynomial:
        self._check_ring(other)
        terms: dict[Exponent, int] = {}
        for left_exponent, left_coefficient in self.terms.items():
            for right_exponent, right_coefficient in other.terms.items():
                exponent = tuple(
                    left + right
                    for left, right in zip(left_exponent, right_exponent, strict=True)
                )
                terms[exponent] = (
                    terms.get(exponent, 0) + left_coefficient * right_coefficient
                )
        return SparsePolynomial(self.variable_count, terms)

    def scale(self, coefficient: int) -> SparsePolynomial:
        return SparsePolynomial(
            self.variable_count,
            {exponent: coefficient * value for exponent, value in self.terms.items()},
        )

    def evaluate(self, values: Iterable[object]) -> object:
        values = tuple(values)
        if len(values) != self.variable_count:
            raise ValueError("wrong number of coordinate values")
        result = 0
        for exponent, coefficient in self.terms.items():
            monomial = coefficient
            for value, power in zip(values, exponent, strict=True):
                if power:
                    monomial *= value**power
            result += monomial
        return result

    def to_msolve(self, variable_names: tuple[str, ...]) -> str:
        if len(variable_names) != self.variable_count:
            raise ValueError("wrong number of variable names")
        if not self.terms:
            return "0"
        ordered = sorted(
            self.terms.items(),
            key=lambda item: (sum(item[0]), item[0]),
            reverse=True,
        )
        pieces: list[str] = []
        for exponent, coefficient in ordered:
            factors: list[str] = []
            magnitude = abs(coefficient)
            for variable, power in zip(variable_names, exponent, strict=True):
                if power == 1:
                    factors.append(variable)
                elif power > 1:
                    factors.append(f"{variable}^{power}")
            if magnitude != 1 or not factors:
                factors.insert(0, str(magnitude))
            monomial = "*".join(factors)
            if not pieces:
                pieces.append(monomial if coefficient > 0 else f"-{monomial}")
            else:
                pieces.append(("+" if coefficient > 0 else "-") + monomial)
        return "".join(pieces)


def polynomial_product(
    polynomials: Iterable[SparsePolynomial],
    *,
    variable_count: int,
) -> SparsePolynomial:
    return reduce(
        mul,
        polynomials,
        SparsePolynomial.constant(1, variable_count),
    )


@dataclass(frozen=True)
class PolynomialSystem:
    variables: tuple[str, ...]
    polynomials: tuple[SparsePolynomial, ...]

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("a polynomial system needs variables")
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("variable names must be distinct")
        if not self.polynomials:
            raise ValueError("a polynomial system needs equations")
        if any(
            polynomial.variable_count != len(self.variables)
            for polynomial in self.polynomials
        ):
            raise ValueError("equations belong to the wrong polynomial ring")

    @property
    def term_count(self) -> int:
        return sum(polynomial.term_count for polynomial in self.polynomials)

    @property
    def maximum_term_count(self) -> int:
        return max(polynomial.term_count for polynomial in self.polynomials)

    def to_msolve(self, characteristic: int = 0) -> str:
        if characteristic < 0:
            raise ValueError("characteristic must be nonnegative")
        equations = ",\n".join(
            polynomial.to_msolve(self.variables) for polynomial in self.polynomials
        )
        return f"{','.join(self.variables)}\n{characteristic}\n{equations}\n"
