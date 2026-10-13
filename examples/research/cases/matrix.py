import sys
import numpy as np

X = np.array([[-2., 0., 2.], [4., 6., 8.]])
if '--failure' in sys.argv:
    X[0, 0] = np.nan
