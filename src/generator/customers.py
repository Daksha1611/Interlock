"""Synthetic customer pool generation."""

from __future__ import annotations

import numpy as np

from domain.customer import Customer
from generator.distributions import bernoulli

_FIRST = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Ananya", "Diya", "Saanvi", "Aadhya", "Kiara", "Myra",
    "Anika", "Ira", "Riya", "Priya",
]
_LAST = [
    "Sharma", "Verma", "Gupta", "Iyer", "Nair", "Reddy", "Rao", "Mehta",
    "Kapoor", "Joshi", "Patel", "Singh", "Kumar", "Chatterjee", "Das", "Bose",
]


def build_customers(rng: np.random.Generator, cfg: dict) -> list[Customer]:
    n = cfg["n_customers"]
    dnc_fraction = cfg["dnc_fraction"]
    risk_fraction = cfg["risk_flagged_fraction"]

    customers = []
    for i in range(n):
        first = _FIRST[rng.integers(0, len(_FIRST))]
        last = _LAST[rng.integers(0, len(_LAST))]
        customers.append(
            Customer(
                customer_id=f"cust_{i:05d}",
                name=f"{first} {last}",
                do_not_contact=bernoulli(rng, dnc_fraction),
                risk_flagged=bernoulli(rng, risk_fraction),
            )
        )
    return customers
