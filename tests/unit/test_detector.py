import numpy as np

from config.reliability.drift.detector import cosine_distance, is_drifted_cosine


def test_cosine_distance_bounds():
    a = np.array([1.0, 0.0])
    b = np.array([1.0, 0.0])
    assert abs(cosine_distance(a, b)) < 1e-6


def test_is_drifted_cosine():
    ref = [np.array([1.0, 0.0]) for _ in range(10)]
    cur = [np.array([0.0, 1.0]) for _ in range(10)]
    assert is_drifted_cosine(ref, cur, threshold=0.1) is True
