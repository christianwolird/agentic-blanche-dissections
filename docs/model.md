# Kirchhoff algebra model

Let \((G,e_0)\) be a rooted polyhedral graph, with root directed from source
\(s\) to sink \(t\). Write \(E'=E(G)\setminus\{e_0\}\) and
\(n=|E'|\). Canonically orient every non-root edge from its smaller endpoint
to its larger endpoint.

## Edge-current presentation

For \(e\in E'\), introduce a signed current \(x_e\). The equations are:

\[
\sum_{e\ni v}\epsilon(v,e)x_e=0
\quad(v\ne s,t),
\]

\[
\sum_{e\ni s}\epsilon(s,e)x_e=n,
\]

and, for every face not adjacent to \(e_0\),

\[
\sum_{e\in\partial f}\frac{\sigma(f,e)}{x_e}=0.
\]

The face equations are cleared locally. Coordinate-hyperplane artifacts are
removed by adjoining

\[
z\prod_{e\in E'}x_e-1.
\]

There are \(n+1\) variables and \(n+1\) equations.

## Fundamental-cycle presentation

Remove \(e_0\), choose a spanning tree \(T\), and send \(n\) units from \(s\)
to \(t\) along the tree path to obtain a particular flow \(x^{(0)}\).
For each chord of \(T\), take its oriented fundamental cycle. If \(C\) is the
resulting cycle matrix, every normalized KCL flow is uniquely

\[
x=x^{(0)}+Cz.
\]

The cycle dimension is

\[
|E'|-|V|+1=E-V=F-2.
\]

Substitution leaves only the face equations and saturation. Applying the
construction to the rooted dual uses \(V-2\) coordinates. The two saturated
algebras are related on the torus by

\[
x_e^*=\pm\frac{n}{x_e}.
\]

This preserves degree and rationality and gives the recovery map used by the
congruence filter.

## Rational and Mondrian points

An exact RUR supplies all rational points of the saturated Kirchhoff algebra.
At a rational point, recover every original current \(x_e\). A point survives
the Mondrian filter precisely when, for all distinct \(e,f\),

\[
x_e^2\ne x_f^2
\quad\text{and}\quad
x_e^2x_f^2\ne n^2.
\]

The first inequality excludes congruence in the same orientation. The second
excludes congruence after a quarter-turn following the \(n\times1\) to square
stretch.

## Modular evidence

Over \(\mathbf F_p\), an RUR has an \(\mathbf F_p\)-point exactly when its
separating univariate polynomial has a linear factor, subject to the usual
validity conditions on the parametrization.

The implementation records:

- special-fiber degree;
- factor-degree profile;
- squarefreeness;
- linear-factor count;
- comparison with an optional expected degree.

A rigorous rational-point obstruction additionally requires a good-reduction
argument controlling denominators and points at infinity. This is represented
by the `GoodReductionOracle` interface rather than assumed by the solver.

