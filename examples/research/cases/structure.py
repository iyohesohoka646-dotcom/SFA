import sys

def safe_square(value):
    return value * value

if '--failure' in sys.argv:
    callback = safe_square
    X = callback(3)
else:
    X = safe_square(3)
