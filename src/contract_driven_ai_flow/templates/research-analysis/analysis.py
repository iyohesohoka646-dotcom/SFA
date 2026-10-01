"""Standardisation, covariance and PCA with observable numerical failures."""
import argparse

import numpy as np
import pandas as pd


parser = argparse.ArgumentParser()
parser.add_argument("--failure", choices=("none", "constant", "nan", "dimension"), default="none")
options = parser.parse_args()
rng = np.random.default_rng(314159)
X = rng.normal(size=(120, 8))
if options.failure == "constant":
    X[:, 0] = 5
if options.failure == "nan":
    X[3, 2] = np.nan
frame = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(8)])
mu = X.mean(axis=0)
sigma = X.std(axis=0)
with np.errstate(divide="ignore", invalid="ignore"):
    Z = (X - mu) / sigma
C = Z.T @ Z / (X.shape[0] - 1)
if options.failure == "dimension":
    scores = Z @ np.zeros((7, 3))
elif options.failure == "none":
    eigenvalues, components = np.linalg.eigh(C)
    scores = Z @ components[:, -3:]
else:
    # A normal return does not imply finite/valid scientific results.
    scores = Z[:, :3]
