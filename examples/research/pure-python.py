"""A dependency-free analysis: scalar observations and inferred relationships."""
samples = [2, 4, 6, 8]
count = len(samples)
total = sum(samples)
mean = total / count
variance = sum((value - mean) ** 2 for value in samples) / count
assert mean == 5 and variance == 5
