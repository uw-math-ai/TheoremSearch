# Top-20 non-gold random f→i matches

Pool: `nongold_random_f2i`. Each is a project formal (not in blueprint gold) and its rank-1 informal match from the 11.7M informal pool, sorted by cosine similarity.

## sim 0.974
- **formal** `ProbabilityTheory.measureMutualInfo_nonneg` (pfr, source=Lean Repo)
  > The mutual information between two random variables is always greater than or equal to zero. This means that the amount of shared information between the variables cannot be negative, reflecting that knowing one variable never increases uncertainty about the other.
- **informal** `2.17` (teorth/pfr, source=Lean Community)
  *blueprint `\lean{}` says:* `ProbabilityTheory.mutualInfo_nonneg`
  > The mutual information between two random variables X and Y is always greater than or equal to zero. This means that knowing one variable never reduces the expected information about the other. Mutual information being nonnegative reflects that it measures shared information, which cannot be negati…

## sim 0.963
- **formal** `Metric.epackingNum` (misc-yd, source=Lean Repo)
  > The epsilon-packing number of a set s is the largest number of points you can pick from s such that every pair of points is at least distance epsilon apart; if no such maximum exists, it is infinite. It counts how many well-separated points can fit inside the set.
- **informal** `9.8` (2310.19103, source=arXiv)
  > The epsilon packing number of a set S is the largest number of points you can choose from S so that every pair of points is more than epsilon distance apart.

## sim 0.954
- **formal** `MeasureTheory.capacity_iUnion` (brownian-motion, source=Lean Repo)
  > For an increasing sequence of sets, the capacity of their union equals the supremum of the capacities of the individual sets. This means the capacity function preserves limits of increasing sequences. The result holds for any capacity defined on a type with a suitable collection of sets.
- **informal** `5.3` (1104.0792, source=arXiv)
  > The capacity of the union of an increasing sequence of sets equals the limit of the capacities of the individual sets.

## sim 0.939
- **formal** `RS_prime.theorem_c` (PrimeNumberTheoremAnd, source=Lean Repo)
  > For any real number x greater than 1, the sum of the reciprocals of all prime numbers less than or equal to the floor of x is greater than the natural logarithm of the natural logarithm of x.
- **informal** `3.9` (1207.3480, source=arXiv)
  > For any x greater than 1, the sum of the reciprocals of all prime numbers up to x is at least the natural log of the natural log of x plus approximately 0.26149, minus a small correction term involving powers of the logarithm of x.

## sim 0.929
- **formal** `ProbabilityTheory.IdentDistrib.rdist_congr_left` (pfr, source=Lean Repo)
  > If two random variables X and Y have copies X' and Y that follow the same distributions, then the Ruzsa distance between X and Y is the same as the Ruzsa distance between X' and Y.
- **informal** `3.10` (teorth/pfr, source=Lean Community)
  *blueprint `\lean{}` says:* `ProbabilityTheory.IdentDistrib.rdist_congr`
  > If X' and Y' are copies of X and Y, then the Ruzsa distance between X' and Y' is the same as the Ruzsa distance between X and Y.

## sim 0.912
- **formal** `Cslib.ωLanguage.isRegular_iff` (cslib, source=Lean Repo)
  > An omega language is regular if and only if there exists a finite state space and a nondeterministic Buchi automaton over that state space which accepts exactly the language.
- **informal** `None` (1605.00186, source=arXiv)
  > A language is called omega-regular if a non-deterministic Buchi automaton can recognize it.

## sim 0.902
- **formal** `log_ge` (PrimeNumberTheoremAnd, source=Lean Repo)
  > For any real number t that is greater than or equal to zero, the natural logarithm of (1 + t) is at least t minus half of t squared. This gives a lower bound for the logarithm function near zero using a simple quadratic expression.
- **informal** `7.11` (2505.23152, source=arXiv)
  > For any non-negative number x, the natural logarithm of (1 plus x) is always greater than or equal to x minus half of x squared. This inequality provides a lower bound for the logarithm function when x is zero or positive. It is useful in approximations and proofs involving logarithmic expressions.

## sim 0.901
- **formal** `SpherePacking.Dim24.Uniqueness.BS81.Thm15.Lemma21.CodingTheory.minDist_le_weight_of_nonzero_mem` (sphere-packing-math-inc, source=Lean Repo)
  > In a linear binary code, the minimum distance between any two distinct codewords is at most the number of nonzero bits in any nonzero codeword. This means the lightest nonzero codeword sets an upper bound on the code's minimum distance.
- **informal** `1.12` (1907.12754, source=arXiv)
  > For a linear code, the minimum distance between any two codewords equals the smallest weight among all non-zero codewords.

## sim 0.900
- **formal** `IGame.Impartial.of_mem_moves` (combinatorial-games, source=Lean Repo)
  > If a game is impartial, then every move available to either player leads to another impartial game. This means that after any move, the resulting position still has the same symmetry between the two players. The property of being impartial is preserved through all possible moves.
- **informal** `7.1` (math/0410026, source=arXiv)
  > An impartial game is a type of game where both players have the same moves available at every turn, and every possible move leads to another impartial game.

## sim 0.897
- **formal** `Metric.ecoveringNum` (misc-yd, source=Lean Repo)
  > The ecoveringNum is the smallest number of points needed to form a set within s such that every point in s is within distance ε of at least one of these points; if no such finite set exists, the value is infinity. It measures how many balls of radius ε are required to cover the set s, using centers…
- **informal** `3.1` (2012.01602, source=arXiv)
  > The covering number is the smallest number of points needed so that every point in a given set is within a distance epsilon of at least one of these points. It measures how many small balls of radius epsilon are required to cover the entire set.

## sim 0.891
- **formal** `serre_D_apply` (Sphere-Packing-Lean, source=Lean Repo)
  > The Serre derivative of weight k applied to a function F at a point z in the upper half-plane equals the derivative of F at z minus k times one twelfth times the value of the Eisenstein series E2 at z multiplied by F at z. This defines a modified derivative operator used in the theory of modular fo…
- **informal** `6.45` (thefundamentaltheor3m/Sphere-Packing-Lean, source=Lean Community)
  *blueprint `\lean{}` says:* `serre_D`
  > The weight k Serre derivative of a modular form F is given by the derivative of F minus (k divided by 12) times the product of the Eisenstein series E2 and F.

## sim 0.887
- **formal** `ProbabilityTheory.Kernel.isCondExp_iff` (gibbs-measure, source=Lean Repo)
  > A kernel π is the conditional expectation of a measure μ with respect to a sub-sigma-algebra 𝓑 if and only if, for every measurable set A, the conditional expectation of the indicator function of A given 𝓑 equals almost everywhere the real-valued function that maps each point a to the measure of A …
- **informal** `1.10` (YaelDillies/gibbs-measure, source=Lean Community)
  *blueprint `\lean{}` says:* `ProbabilityTheory.Kernel.condExp_ae_eq_integral_kernel`
  > If a kernel pi is a conditional expectation kernel for a measure mu, then the conditional expectation of any bounded measurable function f given a sigma-algebra B equals the integral of f with respect to pi, and this holds mu-almost everywhere.

## sim 0.887
- **formal** `OrderTheory.instCompleteLatticeDedekindMacNeilleCompletion` (HarderNarasimhan, source=Lean Repo)
  > The Dedekind-MacNeille completion of any partially ordered type forms a complete lattice, meaning that every collection of elements in this completion has both a least upper bound and a greatest lower bound. This structure is built from the closed subsets of the original type under the Dedekind-Mac…
- **informal** `4.22` (1909.01236, source=arXiv)
  > The Dedekind-MacNeille completion of a partially ordered set P is the collection of all subsets A of P such that the lower bound of the upper bound of A equals A itself, and this collection forms a complete lattice when ordered by subset inclusion.

## sim 0.886
- **formal** `RS_prime.meisselMertensConstant_identity` (PrimeNumberTheoremAnd, source=Lean Repo)
  > The sum of the reciprocals of all prime numbers up to x is equal to the natural log of the natural log of x, plus the Meissel-Mertens constant, plus a correction term involving the difference between Chebyshev's theta function and x, divided by x times the log of x, plus an integral from x to infin…
- **informal** `2.6` (2405.06139, source=arXiv)
  > The sum of the reciprocals of all prime numbers up to x is approximately log(log(x)) plus the Meissel-Mertens constant, and the difference between this sum and that expression is bounded by a small error term that decreases as x increases.

## sim 0.885
- **formal** `AlgebraicGeometry.Scheme.algΓAlgSpecAdjunction` (toric, source=Lean Repo)
  > The declaration defines an adjunction between two functors: one that turns a commutative R-algebra into a geometric object (a scheme over Spec R), and another that takes such a geometric object and returns its ring of functions. This adjunction expresses a fundamental correspondence between algebra…
- **informal** `2.0.2.5` (2305.16281, source=arXiv)
  > For any ring R, there is a pair of functors between the category of schemes over the spectrum of R and the opposite category of commutative R-algebras that form an adjunction; the functor from schemes to algebras assigns global sections relative to R, and the functor from algebras to schemes assign…

## sim 0.885
- **formal** `Dusart.corollary_5_3_c` (PrimeNumberTheoremAnd, source=Lean Repo)
  > For any real number x that is at least 468049, the number of primes less than or equal to x is at least x divided by (the natural logarithm of x minus 1 minus the reciprocal of the natural logarithm of x).
- **informal** `5.2` (2203.05917, source=arXiv)
  > For every number x that is at least 467,497, the count of prime numbers up to x is greater than x divided by a specific expression involving the logarithm of x and several correction terms.

## sim 0.883
- **formal** `MeasureTheory.lt_rearrangement_iff` (carleson, source=Lean Repo)
  > For a measurable function f and a measure μ, the value y is less than the decreasing rearrangement of f at t if and only if t is less than the measure of the set where the norm of f is at least y. This equivalence links the distribution function and the rearrangement function through their threshol…
- **informal** `11.4` (2209.14175, source=arXiv)
  > The distribution function of a measurable function f gives the measure of the set where the absolute value of f exceeds a given threshold. The decreasing rearrangement of f is the inverse-like function that, for each value t, returns the smallest threshold such that the distribution function is at …

## sim 0.878
- **formal** `measurable_limUnder_of_exists_tendsto` (brownian-motion, source=Lean Repo)
  > If a family of measurable functions from a measurable space X to a pseudo-metrizable Borel space E converges pointwise along a countably generated filter, then the pointwise limit function is also measurable. This means that under these conditions, taking limits preserves measurability. The existen…
- **informal** `2.1` (2204.10091, source=arXiv)
  > If a sequence of measurable functions from a measurable space into a metric space converges point by point to a limit function, then the limit function is also measurable.

## sim 0.877
- **formal** `ProbabilityTheory.Kernel.iIndepFun.finsets_comp` (pfr, source=Lean Repo)
  > If a family of random variables is mutually independent, and you group their indices into pairwise disjoint finite sets, then applying a measurable function to each group results in a new family of independent random variables.
- **informal** `4` (2411.06517, source=arXiv)
  > If you have independent random variables divided into separate groups, and you apply a measurable function to each group independently, then the resulting random variables are still independent.

## sim 0.875
- **formal** `ZetaNear1BndExact` (PrimeNumberTheoremAnd, source=Lean Repo)
  > There exists a positive constant c such that for all real numbers sigma between 1 and 2, the absolute value of the Riemann zeta function at sigma is less than or equal to c divided by (sigma minus 1).
- **informal** `3.4` (1809.02829, source=arXiv)
  > For every real number sigma greater than one half, the absolute difference between the Riemann zeta function at s and s divided by (s minus one) is bounded above by a constant multiple of the absolute value of s, where the constant depends on sigma and involves the logarithm of 2 pi, Euler's consta…

