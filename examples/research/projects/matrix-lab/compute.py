def covariance(X):
    mu = X.mean(axis=0)
    Z = X - mu
    C = Z.T @ Z / (X.shape[0] - 1)
    return C
