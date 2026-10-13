import sys

total = 0
for i in range(8):
    if i % 2 == 0:
        total += i
    else:
        total -= i
X = total
if '--failure' in sys.argv:
    X = 100
