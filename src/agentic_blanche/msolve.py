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


def _literal_eval_with_fractions(serialized: str) -> object:
    """Parse msolve's list syntax, including characteristic-zero ``a/b``."""

    def convert(node: ast.AST) -> object:
        if isinstance(node, ast.Expression):
            return convert(node.body)
        if isinstance(node, ast.List):
            return [convert(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(convert(item) for item in node.elts)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = convert(node.operand)
            if not isinstance(value, (int, Fraction)):
                raise ValueError("invalid unary operand in msolve output")
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            numerator = convert(node.left)
            denominator = convert(node.right)
            if not isinstance(numerator, (int, Fraction)) or not isinstance(
                denominator, (int, Fraction)
            ):
                raise ValueError("invalid fraction in msolve output")
            return Fraction(numerator, denominator)
        raise ValueError("unsupported expression in msolve output")

    return convert(ast.parse(serialized, mode="eval"))


def _decode_univariate(encoding: object) -> tuple[int, ...]:
    degree, coefficients = encoding  # type: ignore[misc]
    coefficients = tuple(int(coefficient) for coefficient in coefficients)
    if len(coefficients) != int(degree) + 1:
        raise ValueError("invalid univariate polynomial encoding")
    return coefficients


def _decode_parametrization(
    encoding: object,
) -> tuple[tuple[int, ...], int]:
    """Accept both the legacy ``[poly, divisor]`` and v0.10 ``[poly]`` forms."""
    values = tuple(encoding)  # type: ignore[arg-type]
    if len(values) == 1:
        return _decode_univariate(values[0]), 1
    if len(values) == 2:
        return _decode_univariate(values[0]), int(values[1])
    raise ValueError("invalid coordinate parametrization encoding")


def _rur_variables(
    variables: tuple[str, ...],
    linear_form: tuple[object, ...],
    coordinate_count: int,
    expected_variables: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], tuple[object, ...]]:
    """Remove msolve's appended primitive-element variable when present."""
    if expected_variables is not None:
        expected = set(expected_variables)
        returned = set(variables)
        if len(variables) == len(expected_variables) and returned == expected:
            return variables, linear_form
        if (
            len(variables) == len(expected_variables) + 1
            and expected < returned
            and coordinate_count == len(expected_variables)
        ):
            auxiliary_indices = [
                index
                for index, variable in enumerate(variables)
                if variable not in expected
            ]
            if len(auxiliary_indices) == 1:
                auxiliary = auxiliary_indices[0]
                return (
                    variables[:auxiliary] + variables[auxiliary + 1 :],
                    linear_form[:auxiliary] + linear_form[auxiliary + 1 :],
                )
        raise ValueError("RUR variables do not match the input system")
    if variables and variables[-1] == "A" and coordinate_count == len(variables) - 1:
        return variables[:-1], linear_form[:-1]
    return variables, linear_form


def _evaluate(coefficients: tuple[int, ...], value: Fraction) -> Fraction:
    result = Fraction(0)
    for coefficient in reversed(coefficients):
        result = result * value + coefficient
    return result


def _evaluate_mod(coefficients: tuple[int, ...], value: int, prime: int) -> int:
    result = 0
    for coefficient in reversed(coefficients):
        result = (result * value + coefficient) % prime
    return result


def _poly_pow_mod(
    base: sympy.Poly,
    exponent: int,
    modulus: sympy.Poly,
) -> sympy.Poly:
    """Exponentiate in ``F_p[t]/(modulus)`` without constructing ``t**p``."""
    parameter = modulus.gens[0]
    result = sympy.Poly(1, parameter, modulus=modulus.get_modulus())
    base = base.rem(modulus)
    while exponent:
        if exponent & 1:
            result = (result * base).rem(modulus)
        exponent >>= 1
        if exponent:
            base = (base * base).rem(modulus)
    return result


def _finite_linear_roots(polynomial: sympy.Poly, prime: int) -> tuple[int, ...]:
    """Find all roots in ``F_p`` using ``gcd(f, t**p-t)``.

    This avoids factoring the entire RUR polynomial.  Only the split linear
    part is factored, which is the information the modular sieve needs.
    """
    if polynomial.degree() <= 0:
        return ()
    parameter = polynomial.gens[0]
    coordinate = sympy.Poly(parameter, parameter, modulus=prime)
    frobenius = _poly_pow_mod(coordinate, prime, polynomial)
    linear_part = sympy.gcd(polynomial, frobenius - coordinate)
    if linear_part.degree() <= 0:
        return ()
    roots: list[int] = []
    for root, multiplicity in sympy.polys.polytools.ground_roots(linear_part).items():
        roots.extend([int(root) % prime] * multiplicity)
    if len(roots) != linear_part.degree():
        raise ValueError("Frobenius gcd contained a non-linear factor")
    return tuple(sorted(roots))


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
    variables: tuple[str, ...]
    linear_form: tuple[int, ...]
    degree: int
    polynomial: tuple[int, ...]
    denominator: tuple[int, ...]
    parametrizations: tuple[tuple[tuple[int, ...], int], ...]
    factor_degrees: tuple[int, ...]
    unfactored_degree: int
    squarefree: bool
    linear_roots: tuple[int, ...]

    @property
    def linear_factor_count(self) -> int:
        return len(self.linear_roots)

    def finite_points(self) -> tuple[dict[str, int], ...]:
        points: list[dict[str, int]] = []
        for root in self.linear_roots:
            denominator = _evaluate_mod(self.denominator, root, self.prime)
            if not denominator:
                continue
            coordinates = [
                (
                    -_evaluate_mod(coefficients, root, self.prime)
                    * pow(divisor * denominator % self.prime, -1, self.prime)
                )
                % self.prime
                for coefficients, divisor in self.parametrizations
            ]
            if len(coordinates) == len(self.variables) - 1:
                indices = [
                    index
                    for index, coefficient in enumerate(self.linear_form)
                    if coefficient % self.prime
                ]
                if len(indices) != 1 or self.linear_form[indices[0]] % self.prime != 1:
                    raise ValueError(
                        "non-coordinate finite RUR omitted the primitive coordinate"
                    )
                coordinates.insert(indices[0], root)
            elif len(coordinates) != len(self.variables):
                raise ValueError("unexpected number of finite RUR parametrizations")
            points.append(dict(zip(self.variables, coordinates, strict=True)))
        return tuple(points)


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


class SolveTimeout(RuntimeError):
    """Raised when an msolve stage exceeds its per-task wall-clock budget."""

    def __init__(self, seconds: float):
        super().__init__(f"msolve exceeded the {seconds:g}s timeout")
        self.seconds = seconds


def parse_exact_rur(
    output: str,
    *,
    expected_variables: tuple[str, ...] | None = None,
) -> ExactRUR | None:
    serialized = output.strip().rstrip(":")
    data = _literal_eval_with_fractions(serialized)
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
    variables, linear_form = _rur_variables(
        tuple(payload[3]),
        tuple(Fraction(value) for value in payload[4]),
        len(coordinates),
        expected_variables,
    )
    return ExactRUR(
        variables=variables,
        linear_form=linear_form,
        polynomial=_decode_univariate(polynomial),
        denominator=_decode_univariate(denominator),
        parametrizations=tuple(_decode_parametrization(item) for item in coordinates),
    )


def parse_finite_rur(
    output: str,
    *,
    expected_variables: tuple[str, ...] | None = None,
) -> FiniteRUR | None:
    serialized = output.strip().rstrip(":")
    data = ast.literal_eval(serialized)
    if data == [-1]:
        return None
    payload = data[1]
    if len(payload) < 6:
        raise ValueError("output is not a finite-field RUR")
    prime = int(payload[0])
    count, parametrization = payload[5]
    if count != 1:
        raise ValueError("expected one finite-field RUR component")
    polynomial_encoding, denominator_encoding, coordinate_encodings = parametrization
    variables, linear_form = _rur_variables(
        tuple(payload[3]),
        tuple(int(value) for value in payload[4]),
        len(coordinate_encodings),
        expected_variables,
    )
    degree, coefficients = polynomial_encoding
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
    roots = _finite_linear_roots(polynomial, prime)
    residual_degree = int(degree) - len(roots)
    factor_degrees = (1,) * len(roots)
    squarefree = sympy.gcd(polynomial, polynomial.diff()).degree() == 0
    return FiniteRUR(
        prime=prime,
        variables=variables,
        linear_form=linear_form,
        degree=int(degree),
        polynomial=coefficients,
        denominator=_decode_univariate(denominator_encoding),
        parametrizations=tuple(
            _decode_parametrization(item) for item in coordinate_encodings
        ),
        factor_degrees=factor_degrees,
        unfactored_degree=residual_degree,
        squarefree=bool(squarefree),
        linear_roots=roots,
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
        timeout: float | None = None,
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
            budget = self.timeout if timeout is None else timeout
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=budget,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise SolveTimeout(float(budget)) from error
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
        timeout: float | None = None,
    ) -> ExactSolve:
        output, timing = self._run(
            system,
            characteristic=0,
            threads=threads,
            timeout=timeout,
        )
        return ExactSolve(
            parse_exact_rur(output, expected_variables=system.variables),
            timing,
        )

    def finite(
        self,
        system: PolynomialSystem,
        prime: int,
        *,
        timeout: float | None = None,
    ) -> FiniteSolve:
        output, timing = self._run(
            system,
            characteristic=prime,
            threads=1,
            timeout=timeout,
        )
        return FiniteSolve(
            parse_finite_rur(output, expected_variables=system.variables),
            timing,
        )
