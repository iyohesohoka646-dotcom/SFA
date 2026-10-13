"""复数、高维、空值与重复索引；所有数据来自这次实际运行。"""
import numpy as np
import pandas as pd

complex_matrix = np.array([[3+4j, -2-1j], [1+0j, 0+2j]])
tensor = np.arange(24).reshape(2,3,4)
empty_matrix = np.empty((0,4))
frame = pd.DataFrame({"数值":[1.0,np.nan], "email":["private@example.org","redacted@example.org"]}, index=["重复索引","重复索引"])
