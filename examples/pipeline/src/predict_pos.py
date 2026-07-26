def branch_pos(score: float) -> dict:
    """高置信度正向预测分支。"""
    return {"label": "positive", "score": score}
