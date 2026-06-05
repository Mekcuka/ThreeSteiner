"""Full Steiner tree length via roots of unity (Uteshev & Semenova 2102.03303)."""

from __future__ import annotations

import math

# Third roots of unity (paper 1.3)
EPS0 = 1.0 + 0j
EPS1 = -0.5 + 1j * math.sqrt(3) / 2
EPS2 = -0.5 - 1j * math.sqrt(3) / 2

# Sixth roots v1, v5, v4, v2
V1 = EPS2  # -epsilon_2
V5 = EPS1  # -epsilon_1
V4 = -1.0 + 0j
V2 = EPS1


def _z(x: float, y: float) -> complex:
    return complex(x, y)


def full_tree_length_3(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> float:
    """|v4 z1 + v2 z2 + z3| for CCW-ordered terminals (2102.03303 eq. 2.2)."""
    z1, z2, z3 = _z(*p1), _z(*p2), _z(*p3)
    return abs(V4 * z1 + V2 * z2 + z3)


def full_tree_length_4_pairing(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
    *,
    pairing: tuple[tuple[int, int], tuple[int, int]],
) -> float:
    """
    Length for topology pairing (0,1)-(2,3) style.
    pairing: ((i,j),(k,l)) first pair connected to S1, second to S2.
    Uses eq. 2.3: |(z_i - z_k) + (z_j - z_l) * eps2| and alternate.
    """
    (i, j), (k, l) = pairing
    pts = [p1, p2, p3, p4]
    zi, zj, zk, zl = _z(*pts[i]), _z(*pts[j]), _z(*pts[k]), _z(*pts[l])
    l1 = abs((zi - zk) + (zj - zl) * EPS2)
    l2 = abs((zj - zl) + (zi - zk) * EPS1)
    return min(l1, l2)


def full_tree_length_n(
    points: list[tuple[float, float]],
    root_indices: list[int],
) -> float | None:
    """
    General length |sum z_j U_j| for assigned 6th-root weights.
    root_indices[j] in 0..5 selects upsilon_k.
    """
    upsilon = [
        1.0 + 0j,
        EPS2,
        EPS1,
        -1.0 + 0j,
        -EPS2,
        -EPS1,
    ]
    if len(points) != len(root_indices):
        return None
    total = 0.0 + 0.0j
    for (x, y), ri in zip(points, root_indices, strict=True):
        total += _z(x, y) * upsilon[ri % 6]
    return abs(total)
