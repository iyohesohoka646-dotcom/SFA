def extract_features(rows: list, n: int) -> dict:
    """计算每行均值作为特征向量。"""
    features = [sum(row) / len(row) for row in rows]
    return {"features": features}
