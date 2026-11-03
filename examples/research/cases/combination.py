import sys
import numpy as np

A = np.arange(6.).reshape(2, 3)
B = np.arange(6.).reshape(3, 2)
if '--failure' in sys.argv:
    B = np.ones((4, 2))
