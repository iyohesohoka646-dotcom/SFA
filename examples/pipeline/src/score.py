def score(features: list) -> dict:
    """计算归一化置信分数。"""
    avg = sum(features) / len(features)
    return {"score": avg / 100.0}
