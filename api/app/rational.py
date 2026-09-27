"""Exact rational helpers: parsing of user input and JSON presentation.

All distances and times in the locator are handled as exact rationals
(:class:`fractions.Fraction`); nothing is ever sampled or rounded during
the computation.  Floats are only produced at the API boundary, next to
the exact fraction string, for display purposes.
"""
from __future__ import annotations

import math
from fractions import Fraction


class RationalParseError(ValueError):
    """Raised when a field cannot be interpreted as a rational number."""


def parse_rational(value, field: str) -> Fraction:
    """Parse an int/float/str into an exact :class:`Fraction`.

    Accepts JSON numbers and strings such as ``"2.5"``, ``"-3/4"`` or
    ``" 1 "``.  Floats are converted through their decimal text form so
    that ``0.1`` means exactly ``1/10``.  Booleans, non-finite floats and
    unparseable values are rejected with a human-readable message.
    """
    if isinstance(value, bool):
        raise RationalParseError(f"{field} 必须是有理数，不应为布尔值")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RationalParseError(f"{field} 必须是有限有理数")
        return Fraction(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise RationalParseError(f"{field} 不能为空")
        try:
            return Fraction(text)
        except (ValueError, ZeroDivisionError) as exc:
            raise RationalParseError(f"{field} 无法解析为有理数: {value!r}") from exc
    raise RationalParseError(
        f"{field} 必须是有理数（数字或字符串），收到类型 {type(value).__name__}"
    )


def rat_json(q: Fraction) -> dict:
    """JSON view of an exact rational: exact string plus decimal hint."""
    return {"exact": str(q), "decimal": float(q)}
