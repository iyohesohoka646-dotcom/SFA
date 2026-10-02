import sys
import pandas as pd

T = pd.DataFrame({'time': [0., 1., 2.], 'signal': [2., 4., 6.]})
if '--failure' in sys.argv:
    T = T.iloc[:2]
