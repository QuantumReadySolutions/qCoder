"""Bounded, named-regime executors.

An executor in this package is not an arbitrary Python runner. Each module here may
execute exactly one frozen, validated plan shape for exactly one named regime, through
one injectable backend adapter, with no environment mutation, no dependency
installation, no shell, no network, and no evaluation of customer-supplied code.
"""

from __future__ import annotations
