def load_data(seed: int) -> dict:
    """从种子生成确定性合成数据集。"""
    rows = [
        [seed, seed + 1, seed + 2],
        [seed * 2, seed * 2 + 1, seed * 2 + 2],
    ]
    return {"rows": rows, "n": len(rows)}
