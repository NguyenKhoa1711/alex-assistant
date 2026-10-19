"""Temporary local probe for Bionic's multi-step coding workflow."""


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def is_even(value: int) -> bool:
    return value % 2 == 0


def is_positive(value: int) -> bool:
    return value > 0
