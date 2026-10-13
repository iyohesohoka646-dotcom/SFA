"""Small NumPy cross-file example; --nan demonstrates a quality failure."""
import argparse
from prepare import build_dataset
from compute import covariance

parser = argparse.ArgumentParser()
parser.add_argument('--nan', action='store_true')
options = parser.parse_args()
X = build_dataset()
if options.nan:
    X[1, 2] = float('nan')
C = covariance(X)
print('shape:', C.shape)
