def branch_neg(score: float) -> dict:
    """低置信度负向预测分支。"""
    return {"label": "negative", "score": score}
