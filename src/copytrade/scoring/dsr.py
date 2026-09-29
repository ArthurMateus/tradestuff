"""Deflated Sharpe ratio (F5, edge-hypothesis 10.2 M7): Bailey and Lopez de Prado (2014), null variance 1/T.

Floats: the normal CDF and its inverse (``statistics.NormalDist``) have no Decimal implementation in the standard
library. They are used only here, for these two functions. Their inputs and outputs are dimensionless statistics
(a Sharpe benchmark and a probability), never money, and every value crosses back to ``Decimal`` at the boundary.
"""

from __future__ import annotations

import math
from decimal import Decimal
from statistics import NormalDist

_NORMAL = NormalDist()
_EULER_MASCHERONI = Decimal("0.5772")  # gamma as pinned in edge-hypothesis 10.2 (M7)
_MIN_TRIALS = 2
_MIN_DAYS = 2


def _from_float(x: float) -> Decimal:
    return Decimal(repr(x))


def _check(t_days: int, n_trials: int) -> None:
    if n_trials < _MIN_TRIALS:
        raise ValueError(f"n_trials must be at least {_MIN_TRIALS}")
    if t_days < _MIN_DAYS:
        raise ValueError(f"t_days must be at least {_MIN_DAYS}")


def emax(n_trials: int) -> Decimal:
    """Expected maximum of ``n_trials`` independent standard-normal Sharpe estimates (the pinned approximation)."""
    if n_trials < _MIN_TRIALS:
        raise ValueError(f"n_trials must be at least {_MIN_TRIALS}")
    first = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    second = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return (1 - _EULER_MASCHERONI) * _from_float(first) + _EULER_MASCHERONI * _from_float(second)


def sr0(t_days: int, n_trials: int) -> Decimal:
    """``Emax(N) / sqrt(T)`` with ``Emax(N) = (1-g)*PhiInv(1-1/N) + g*PhiInv(1-1/(N*e))``, g = 0.5772.

    Raises:
        ValueError: ``n_trials`` < 2 or ``t_days`` < 2.
    """
    _check(t_days, n_trials)
    return emax(n_trials) / Decimal(t_days).sqrt()


def variance_term(*, sr_d: Decimal, skew: Decimal, kurt: Decimal) -> Decimal:
    """``1 - skew*sr + (kurt-1)/4 * sr**2``: the Sharpe estimator's variance factor. Valid only when positive."""
    return 1 - skew * sr_d + (kurt - 1) / 4 * sr_d * sr_d


def dsr_prob(*, sr_d: Decimal, skew: Decimal, kurt: Decimal, t_days: int, n_trials: int) -> Decimal:
    """``Phi((sr_d - SR0) * sqrt(T-1) / sqrt(1 - skew*sr_d + (kurt-1)/4 * sr_d**2))``.

    Raises:
        ValueError: ``n_trials`` < 2, ``t_days`` < 2, or the variance term is not positive.
    """
    _check(t_days, n_trials)
    variance = variance_term(sr_d=sr_d, skew=skew, kurt=kurt)
    if variance <= 0:
        raise ValueError("the variance term of the Sharpe estimate is not positive")
    z = (sr_d - sr0(t_days, n_trials)) * Decimal(t_days - 1).sqrt() / variance.sqrt()
    return _from_float(_NORMAL.cdf(float(z)))
