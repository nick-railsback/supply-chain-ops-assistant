"""The closed root-cause taxonomy for a stuck order."""

from enum import StrEnum


class RootCause(StrEnum):
    INVENTORY = "inventory"
    CARRIER = "carrier"
    ADDRESS_EXCEPTION = "address_exception"
