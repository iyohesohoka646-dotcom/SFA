"""Explicit, bounded introspection of public plotting methods in an owned process."""

import contextlib
import importlib
import inspect
import io
import json
import sys

METHODS = {
    "matplotlib": [
        "matplotlib.pyplot:imshow",
        "matplotlib.pyplot:plot",
        "matplotlib.pyplot:hist",
    ],
    "seaborn": ["seaborn:heatmap", "seaborn:lineplot", "seaborn:histplot"],
    "plotly": [
        "plotly.express:imshow",
        "plotly.express:line",
        "plotly.express:histogram",
    ],
    "altair": ["altair:Chart"],
    "bokeh": ["bokeh.plotting:figure"],
    "pyvista": ["pyvista:Plotter"],
    "holoviews": ["holoviews:Curve", "holoviews:HeatMap"],
}

if __name__ == "__main__":
    key = json.load(sys.stdin)["tool"]
    results = []
    with contextlib.redirect_stdout(io.StringIO()):
        for entry in METHODS[key]:
            module, symbol = entry.split(":")
            value = getattr(importlib.import_module(module), symbol)
            try:
                signature = str(inspect.signature(value))[:4096]
            except (ValueError, TypeError):
                signature = "unavailable"
            results.append(
                {
                    "entry": entry,
                    "signature": signature,
                    "documentation": (inspect.getdoc(value) or "")[:4096],
                }
            )
    print(
        json.dumps(
            {"tool": key, "methods": results, "method": "isolated-introspection"},
            ensure_ascii=False,
        )
    )
