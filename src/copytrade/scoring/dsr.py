"""Deflated Sharpe ratio (F5, edge-hypothesis 10.2 M7). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from decimal import Decimal


def sr0(t_days: int, n_trials: int) -> Decimal:
    """``Emax(N) / sqrt(T)`` with ``Emax(N) = (1-g)*PhiInv(1-1/N) + g*PhiInv(1-1/(N*e))``, g = 0.5772.

    Raises:
        ValueError: ``n_trials`` < 2 or ``t_days`` < 2.
    """
    raise NotImplementedError


def dsr_prob(*, sr_d: Decimal, skew: Decimal, kurt: Decimal, t_days: int, n_trials: int) -> Decimal:
    """``Phi((sr_d - SR0) * sqrt(T-1) / sqrt(1 - skew*sr_d + (kurt-1)/4 * sr_d**2))``.

    Raises:
        ValueError: ``n_trials`` < 2, ``t_days`` < 2, or the variance term is not positive.
    """
    raise NotImplementedError
