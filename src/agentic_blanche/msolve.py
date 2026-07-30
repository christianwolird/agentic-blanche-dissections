"""Exact and finite-field msolve backends."""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from time import perf_counter

import sympy

from agentic_blanche.polynomial import PolynomialSystem


def _decode_univariate(encoding: object) -> tuple[int, ...]:
    degree, coefficients = encoding  # type: ignore[misc]
    coefficients = tuple(int(coefficient) for coefficient in coefficients)
    if len(coefficients) != int(degree) + 1:
        raise ValueError("invalid univariate polynomial encoding")
    return coefficients


def _evaluate(coefficients: tuple[int, ...], value: Fraction) -> Fraction:
    result = Fraction(0)
    for coefficient in reversed(coefficients):
        result = result * value + coefficient
    return result


@dataclass(frozen=True)
class ExactRUR:
    variables: tuple[str, ...]
    linear_form: tuple[Fraction, ...]
    polynomial: tuple[int, ...]
    denominator: tuple[int, ...]
    parametrizations: tuple[tuple[tuple[int, ...], int], ...]

    @property
    def degree(self) -> int:
        return len(self.polynomial) - 1

    def rational_points(self) -> tuple[dict[str, Fraction], ...]:
        parameter = sympy.Symbol("t")
        polynomial = sympy.Poly(
            sum(
                coefficient * parameter**degree
                for degree, coefficient in enumerate(self.polynomial)
            ),
            parameter,
            domain=sympy.QQ,
        )
        roots = sympy.polys.polytools.ground_roots(polynomial)
        points: list[dict[str, Fraction]] = []
        for root in roots:
            root = Fraction(int(root.p), int(root.q))
            denominator = _evaluate(self.denominator, root)
            if not denominator:
                raise ValueError("RUR denominator vanishes at a root")
            coordinates = [
                -_evaluate(coefficients, root) / (divisor * denominator)
                for coefficients, divisor in self.parametrizations
            ]
            if len(coordinates) == len(self.variables) - 1:
                indices = [
                    index
                    for index, coefficient in enumerate(self.linear_form)
                    if coefficient
                ]
                if len(indices) != 1 or self.linear_form[indices[0]] != 1:
                    raise ValueError(
                        "non-coordinate RUR omitted the primitive coordinate"
                    )
                coordinates.insert(indices[0], root)
            elif len(coordinates) != len(self.variables):
                raise ValueError("unexpected number of RUR parametrizations")
            points.append(dict(zip(self.variables, coordinates, strict=True)))
        return tuple(points)


@dataclass(frozen=True)
class FiniteRUR:
    prime: int
    degree: int
    polynomial: tuple[int, ...]
    factor_degrees: tuple[int, ...]
    squarefree: bool

    @property
    def linear_factor_count(self) -> int:
        return self.factor_degrees.count(1)


@dataclass(frozen=True)
class SolveTiming:
    seconds: float
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ExactSolve:
    rur: ExactRUR | None
    timing: SolveTiming


@dataclass(frozen=True)
class FiniteSolve:
    rur: FiniteRUR | None
    timing: SolveTiming


def parse_exact_rur(output: str) -> ExactRUR | None:
    serialized = output.strip().rstrip(":")
    data = ast.literal_eval(serialized)
    if data == [-1]:
        return None
    payload = data[1]
    if payload[0] == 1 and len(payload) >= 3 and payload[2] == -1:
        raise ValueError("msolve reported a positive-dimensional system")
    if len(payload) < 6 or payload[0] != 0:
        raise ValueError("output is not a characteristic-zero RUR")
    count, parametrization = payload[5]
    if count != 1:
        raise ValueError("expected one RUR component")
    polynomial, denominator, coordinates = parametrization
    return ExactRUR(
        variables=tuple(payload[3]),
        linear_form=tuple(Fraction(value) for value in payload[4]),
        polynomial=_decode_univariate(polynomial),
        denominator=_decode_univariate(denominator),
        parametrizations=tuple(
            (_decode_univariate(encoding), int(divisor))
            for encoding, divisor in coordinates
        ),
    )


def parse_finite_rur(output: str) -> FiniteRUR | None:
    serialized = output.strip().rstrip(":")
    data = ast.literal_eval(serialized)
    if data == [-1]:
        return None
    payload = data[1]
    if len(payload) < 6:
        raise ValueError("output is not a finite-field RUR")
    prime = int(payload[0])
    degree, coefficients = payload[5][1][0]
    coefficients = tuple(int(coefficient) for coefficient in coefficients)
    parameter = sympy.Symbol("t")
    polynomial = sympy.Poly(
        sum(
            coefficient * parameter**index
            for index, coefficient in enumerate(coefficients)
        ),
        parameter,
        modulus=prime,
    )
    factors = sympy.factor_list(polynomial)[1]
    factor_degrees = tuple(
        sorted(
            factor.degree()
            for factor, multiplicity in factors
            for _ in range(multiplicity)
        )
    )
    squarefree = sympy.gcd(polynomial, polynomial.diff()).degree() == 0
    return FiniteRUR(
        prime=prime,
        degree=int(degree),
        polynomial=coefficients,
        factor_degrees=factor_degrees,
        squarefree=bool(squarefree),
    )


@dataclass(frozen=True)
class MSolve:
    executable: str = "msolve"
    threads: int = 1
    timeout: float | None = None

    def _path(self) -> str:
        path = shutil.which(self.executable)
        if path is None:
            raise RuntimeError(f"{self.executable!r} is not installed")
        return path

    def _run(
        self,
        system: PolynomialSystem,
        *,
        characteristic: int,
        threads: int | None = None,
    ) -> tuple[str, SolveTiming]:
        with tempfile.TemporaryDirectory(prefix="agentic-blanche-msolve-") as temp:
            directory = Path(temp)
            input_path = directory / "input.ms"
            output_path = directory / "output.ms"
            input_path.write_text(system.to_msolve(characteristic), encoding="utf-8")
            command = [
                self._path(),
                "-P",
                "2",
                "-v",
                "0",
                "-t",
                str(threads or self.threads),
                "-f",
                str(input_path),
                "-o",
                str(output_path),
            ]
            started = perf_counter()
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            elapsed = perf_counter() - started
            if completed.returncode:
                raise RuntimeError(
                    f"msolve failed with exit code {completed.returncode}:\n"
                    f"{completed.stderr}"
                )
            return (
                output_path.read_text(encoding="utf-8"),
                SolveTiming(elapsed, completed.stdout, completed.stderr),
            )

    def exact(
        self,
        system: PolynomialSystem,
        *,
        threads: int | None = None,
    ) -> ExactSolve:
        output, timing = self._run(system, characteristic=0, threads=threads)
        return ExactSolve(parse_exact_rur(output), timing)

    def finite(
        self,
        system: PolynomialSystem,
        prime: int,
    ) -> FiniteSolve:
        output, timing = self._run(system, characteristic=prime, threads=1)
        return FiniteSolve(parse_finite_rur(output), timing)
