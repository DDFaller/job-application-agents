from __future__ import annotations

from typing import Sequence

from .base import BaseFormDriver
from .lever import LeverFormDriver
from .ashby import AshbyFormDriver
from .greenhouse import GreenhouseFormDriver
from .generic import GenericFormDriver

BUILTIN_DRIVERS: list[BaseFormDriver] = [
    LeverFormDriver(),
    AshbyFormDriver(),
    GreenhouseFormDriver(),
    GenericFormDriver(),
]


class DriverRegistry:
    """Registry that matches target job URLs with the best ATS form driver."""

    def __init__(self, drivers: Sequence[BaseFormDriver] | None = None):
        self._drivers = list(drivers or BUILTIN_DRIVERS)
        self._drivers.sort(key=lambda d: d.priority, reverse=True)

    def resolve(self, url: str) -> BaseFormDriver:
        for driver in self._drivers:
            if driver.can_handle(url):
                return driver
        return GenericFormDriver()


default_registry = DriverRegistry()
