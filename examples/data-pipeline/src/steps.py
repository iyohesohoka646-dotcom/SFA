def ingest(values):
    return values


def normalize(values, scale):
    return [value / scale for value in values]


def summarize(values):
    return {"mean": sum(values) / len(values) if values else 0, "count": len(values)}


def report(summary):
    return f"{summary['count']} samples · mean {summary['mean']:.2f}"
