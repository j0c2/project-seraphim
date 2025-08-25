"""Simple drift detection utilities.

- Embedding cosine distance threshold
- Probability distribution KL divergence
"""
from typing import List
import numpy as np


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a_n = a / (np.linalg.norm(a) + 1e-9)
    b_n = b / (np.linalg.norm(b) + 1e-9)
    return 1.0 - float(np.dot(a_n, b_n))


def kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    eps = 1e-9
    p = np.clip(p, eps, 1)
    q = np.clip(q, eps, 1)
    return float(np.sum(p * (np.log(p) - np.log(q))))


def is_drifted_cosine(ref: List[np.ndarray], cur: List[np.ndarray], threshold: float = 0.15) -> bool:
    dists = [cosine_distance(r, c) for r, c in zip(ref, cur)]
    return float(np.percentile(dists, 95)) > threshold
