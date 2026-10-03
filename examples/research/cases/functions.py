def normalize(values):
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    return centered

X = normalize([1., 2., 3.])
Y = normalize([2., 4., 6.])
