"""Independent Clopper-Pearson oracle for the focused-loop lower bound.

The oracle never imports the production estimator to produce an expected value. It
re-derives the bound from the *defining* Clopper-Pearson property by bisecting the exact
binomial tail

    sum_{i=k}^{n} C(n, i) p^i (1 - p)^(n - i) = alpha

with ``math.comb`` and 80-digit ``decimal.Decimal`` arithmetic for the tail sum, and
independently checks the all-success closed form ``alpha ** (1 / n)`` with 60-digit
``decimal.Decimal`` arithmetic. Small cases are additionally cross-checked with exact
``fractions.Fraction`` rational arithmetic. The production module implements a different
code path entirely: a regularized-incomplete-beta continued fraction inverted by
bisection.

TOLERANCE. Both oracles terminate at a finite bisection bracket, and the production value
is an IEEE-754 double produced through ``lgamma``, ``exp``, ``log`` and a continued
fraction. Near p = 0.995 one double ULP is about 1.1e-16, and each path accumulates a
handful of rounding steps, so agreement can only be expected to a few ULP. Observed
disagreement is 0.0 on the three all-success answer keys and 2.220446e-16 (exactly one
ULP) on the n=598, k=597 case. ``TOLERANCE = 1e-12`` is therefore about four orders of
magnitude looser than anything observed, while still being roughly 5.4e+9 times tighter
than the 0.995 - 0.9949945920065333 = 5.4e-6 margin that the 597-versus-598 shot decision
turns on, so it cannot mask a decision-relevant error. The three answer keys themselves
are additionally asserted by exact float equality, not by tolerance.
"""

from decimal import Decimal, getcontext
from fractions import Fraction
import math
import unittest

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import FocusedLoopError
from qcoder.focused_loop.result_protocol import clopper_pearson_lower_bound

TOLERANCE = 1e-12

DECIMAL_PRECISION = 80
BISECTION_ITERATIONS = 100

ALPHA_DECIMAL = Decimal("0.05")
ALPHA_FRACTION = Fraction(1, 20)

#: Verified answer keys from the controlling product specification.
ANSWER_KEYS = {
    597: 0.9949945920065333,
    598: 0.9950029413057535,
    599: 0.9950112627972248,
}


def binomial_upper_tail(*, n: int, k: int, p: Decimal, coefficients=None) -> Decimal:
    """``P(X >= k)`` for ``X ~ Binomial(n, p)`` as an exact tail sum over ``math.comb``."""
    getcontext().prec = DECIMAL_PRECISION
    if coefficients is None:
        coefficients = [math.comb(n, i) for i in range(k, n + 1)]
    q = Decimal(1) - p
    p_power = p**k
    q_power = q ** (n - k)
    total = Decimal(0)
    for offset, coefficient in enumerate(coefficients):
        total += Decimal(coefficient) * p_power * q_power
        if offset < len(coefficients) - 1:
            p_power *= p
            q_power /= q
    return total


def binomial_upper_tail_rational(*, n: int, k: int, p: Fraction) -> Fraction:
    """Fully exact rational tail sum. Only tractable for small ``n``."""
    return sum(
        (math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)),
        Fraction(0),
    )


def oracle_lower_bound(*, n: int, k: int, iterations: int = BISECTION_ITERATIONS) -> float:
    """Bisect the exact binomial tail for the Clopper-Pearson lower bound.

    The lower bound is the ``p`` at which ``P(X >= k | p) == alpha``. The tail is
    increasing in ``p``, so plain bisection converges to the defining root.
    """
    if k == 0:
        return 0.0
    getcontext().prec = DECIMAL_PRECISION
    coefficients = [math.comb(n, i) for i in range(k, n + 1)]
    low = Decimal(0)
    high = Decimal(1)
    half = Decimal("0.5")
    for _ in range(iterations):
        middle = (low + high) * half
        if binomial_upper_tail(n=n, k=k, p=middle, coefficients=coefficients) > ALPHA_DECIMAL:
            high = middle
        else:
            low = middle
    return float((low + high) * half)


def oracle_lower_bound_rational(*, n: int, k: int, iterations: int = 70) -> float:
    """Bisect the fully exact rational tail. Independent of Decimal rounding entirely."""
    low = Fraction(0)
    high = Fraction(1)
    for _ in range(iterations):
        middle = (low + high) / 2
        if binomial_upper_tail_rational(n=n, k=k, p=middle) > ALPHA_FRACTION:
            high = middle
        else:
            low = middle
    return float((low + high) / 2)


def decimal_all_success_bound(*, n: int) -> Decimal:
    """High-precision ``alpha ** (1 / n)`` for the all-success case."""
    getcontext().prec = DECIMAL_PRECISION
    return ALPHA_DECIMAL ** (Decimal(1) / Decimal(n))


class TestOracleSelfConsistency(unittest.TestCase):
    """The oracle is checked against itself before it is used to judge production."""

    def test_rational_tail_bisection_matches_the_decimal_closed_form(self):
        for n in (597, 598, 599):
            self.assertAlmostEqual(
                oracle_lower_bound(n=n, k=n),
                float(decimal_all_success_bound(n=n)),
                delta=TOLERANCE,
            )

    def test_bisected_point_actually_solves_the_defining_equation(self):
        for n, k in ((598, 597), (598, 590), (10, 5)):
            bound = Decimal(repr(oracle_lower_bound(n=n, k=k)))
            tail = binomial_upper_tail(n=n, k=k, p=bound)
            self.assertAlmostEqual(float(tail), 0.05, delta=1e-9)

    def test_tail_is_increasing_in_p(self):
        previous = -1.0
        for numerator in range(1, 20):
            tail = float(binomial_upper_tail(n=20, k=15, p=Decimal(numerator) / 20))
            self.assertGreater(tail, previous)
            previous = tail

    def test_decimal_and_exact_rational_oracles_agree_on_small_cases(self):
        for n, k in ((10, 5), (20, 19), (12, 12)):
            self.assertAlmostEqual(
                oracle_lower_bound(n=n, k=k),
                oracle_lower_bound_rational(n=n, k=k),
                delta=TOLERANCE,
                msg=f"n={n} k={k}",
            )


class TestAllSuccessAnswerKeys(unittest.TestCase):
    def test_production_matches_the_independent_oracle(self):
        for n in (597, 598, 599):
            self.assertAlmostEqual(
                clopper_pearson_lower_bound(successes=n, trials=n),
                oracle_lower_bound(n=n, k=n),
                delta=TOLERANCE,
            )

    def test_production_matches_the_high_precision_decimal_power(self):
        for n in (597, 598, 599):
            self.assertAlmostEqual(
                clopper_pearson_lower_bound(successes=n, trials=n),
                float(decimal_all_success_bound(n=n)),
                delta=TOLERANCE,
            )

    def test_production_reproduces_the_declared_answer_keys_exactly(self):
        for n, expected in ANSWER_KEYS.items():
            self.assertEqual(clopper_pearson_lower_bound(successes=n, trials=n), expected)

    def test_oracle_reproduces_the_declared_answer_keys_within_tolerance(self):
        for n, expected in ANSWER_KEYS.items():
            self.assertAlmostEqual(oracle_lower_bound(n=n, k=n), expected, delta=TOLERANCE)

    def test_observed_disagreement_is_far_tighter_than_the_tolerance(self):
        for n in (597, 598, 599):
            difference = abs(
                clopper_pearson_lower_bound(successes=n, trials=n)
                - float(decimal_all_success_bound(n=n))
            )
            self.assertLess(difference, 1e-15)

    def test_tolerance_cannot_mask_the_five_ninety_seven_decision(self):
        margin = identities.TARGET_LOWER_BOUND - ANSWER_KEYS[597]
        self.assertGreater(margin, 0.0)
        self.assertGreater(margin / TOLERANCE, 1e6)


class TestDecisionBoundary(unittest.TestCase):
    def test_five_ninety_seven_is_strictly_below_the_target(self):
        self.assertLess(oracle_lower_bound(n=597, k=597), identities.TARGET_LOWER_BOUND)
        self.assertLess(ANSWER_KEYS[597], 0.995)
        self.assertLess(clopper_pearson_lower_bound(successes=597, trials=597), 0.995)

    def test_five_ninety_eight_meets_the_target(self):
        self.assertGreaterEqual(
            oracle_lower_bound(n=598, k=598), identities.TARGET_LOWER_BOUND
        )
        self.assertGreaterEqual(ANSWER_KEYS[598], 0.995)
        self.assertGreaterEqual(clopper_pearson_lower_bound(successes=598, trials=598), 0.995)

    def test_five_ninety_nine_meets_the_target_and_exceeds_five_ninety_eight(self):
        self.assertGreaterEqual(oracle_lower_bound(n=599, k=599), 0.995)
        self.assertGreater(ANSWER_KEYS[599], ANSWER_KEYS[598])
        self.assertGreater(
            clopper_pearson_lower_bound(successes=599, trials=599),
            clopper_pearson_lower_bound(successes=598, trials=598),
        )

    def test_five_ninety_eight_is_the_smallest_all_success_sample_that_meets_the_target(self):
        self.assertLess(oracle_lower_bound(n=597, k=597), 0.995)
        self.assertGreaterEqual(oracle_lower_bound(n=598, k=598), 0.995)
        self.assertEqual(identities.FIXED_SHOTS, 598)


class TestNonAllSuccessCases(unittest.TestCase):
    def test_five_ninety_eight_shots_with_one_violation(self):
        expected = oracle_lower_bound(n=598, k=597)
        self.assertAlmostEqual(
            clopper_pearson_lower_bound(successes=597, trials=598), expected, delta=TOLERANCE
        )
        self.assertLess(expected, 0.995)
        self.assertLess(
            abs(clopper_pearson_lower_bound(successes=597, trials=598) - expected), 3e-16
        )

    def test_additional_partial_success_cases(self):
        for n, k in ((598, 590), (598, 300), (598, 1), (10, 5), (20, 19), (100, 99)):
            self.assertAlmostEqual(
                clopper_pearson_lower_bound(successes=k, trials=n),
                oracle_lower_bound(n=n, k=k),
                delta=TOLERANCE,
                msg=f"n={n} k={k}",
            )

    def test_zero_successes_is_a_zero_bound_on_both_paths(self):
        self.assertEqual(oracle_lower_bound(n=598, k=0), 0.0)
        self.assertEqual(clopper_pearson_lower_bound(successes=0, trials=598), 0.0)

    def test_partial_bound_solves_the_defining_equation(self):
        bound = Decimal(repr(clopper_pearson_lower_bound(successes=597, trials=598)))
        tail = binomial_upper_tail(n=598, k=597, p=bound)
        self.assertAlmostEqual(float(tail), 0.05, delta=1e-9)


class TestFailClosedNegatives(unittest.TestCase):
    def test_zero_and_negative_sample_sizes(self):
        for trials in (0, -1, -598):
            with self.assertRaises(FocusedLoopError) as caught:
                clopper_pearson_lower_bound(successes=0, trials=trials)
            self.assertEqual(
                caught.exception.category, "result_protocol_sample_size_invalid"
            )

    def test_non_integer_success_count(self):
        for successes in (597.0, 597.5, "597", None, True, Fraction(597, 1)):
            with self.assertRaises(FocusedLoopError):
                clopper_pearson_lower_bound(successes=successes, trials=598)

    def test_non_integer_sample_size(self):
        for trials in (598.0, "598", None, False):
            with self.assertRaises(FocusedLoopError):
                clopper_pearson_lower_bound(successes=1, trials=trials)

    def test_successes_greater_than_trials(self):
        with self.assertRaises(FocusedLoopError) as caught:
            clopper_pearson_lower_bound(successes=599, trials=598)
        self.assertEqual(
            caught.exception.category, "result_protocol_success_count_exceeds_sample"
        )

    def test_negative_success_count(self):
        with self.assertRaises(FocusedLoopError) as caught:
            clopper_pearson_lower_bound(successes=-1, trials=598)
        self.assertEqual(
            caught.exception.category, "result_protocol_success_count_invalid"
        )

    def test_wrong_confidence_level(self):
        for level in (0.9, 0.99, 0.975, 1.0, 0.0, "0.95", None):
            with self.assertRaises(FocusedLoopError) as caught:
                clopper_pearson_lower_bound(
                    successes=598, trials=598, confidence_level=level
                )
            self.assertEqual(
                caught.exception.category, "result_protocol_confidence_level_unsupported"
            )

    def test_malformed_ordering_and_unsupported_protocol_identity(self):
        from qcoder.focused_loop import fixtures, result_protocol

        answer_key = fixtures.build_answer_key(fixtures.PRIMARY_FAMILY_PARAMETERS)
        allowed = fixtures.allowed_outcomes(fixtures.PRIMARY_FAMILY_PARAMETERS)
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.evaluate_predicate_satisfaction(
                counts={allowed[0]: 598},
                answer_key=answer_key,
                bitstring_ordering="little_endian_maybe",
            )
        self.assertEqual(
            caught.exception.category, "result_protocol_bitstring_ordering_unsupported"
        )
        foreign = dict(answer_key)
        foreign["schema_id"] = "qcoder.focused_loop.answer_key.v2"
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.evaluate_predicate_satisfaction(
                counts={allowed[0]: 598},
                answer_key=foreign,
                bitstring_ordering=fixtures.COUNTS_BITSTRING_ORDERING,
            )
        self.assertEqual(
            caught.exception.category, "result_protocol_answer_key_invalid"
        )


if __name__ == "__main__":
    unittest.main()
