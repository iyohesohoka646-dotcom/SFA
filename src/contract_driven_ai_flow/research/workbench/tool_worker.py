"""Isolated fixed drawing adapter. No user code or expression evaluation."""

import json
import math
from pathlib import Path
import sys


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def main():
    request = json.loads(sys.stdin.buffer.read(1024 * 1024 + 1))
    matrix = request["values"]
    values = [[number(value) for value in row] for row in matrix]
    path = Path(request["output"])
    tool = request["tool"]
    chart = request["kind"]
    if chart not in ("heatmap", "line", "histogram"):
        raise ValueError("Unsupported chart kind")
    if tool in ("matplotlib", "seaborn"):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        data = np.array(values, dtype=float)
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120, layout="constrained")
        if chart == "histogram":
            ax.hist(data[np.isfinite(data)], bins=min(32, max(1, data.size)))
        elif chart == "line":
            ax.plot(data.reshape(-1))
            ax.set_xlabel("Captured cell index")
        elif tool == "seaborn":
            import seaborn as sns

            sns.heatmap(data, ax=ax, cmap="viridis")
        else:
            image = ax.imshow(data, aspect="auto", cmap="viridis")
            fig.colorbar(image, ax=ax)
        ax.set_title(request["title"])
        fig.savefig(path, format="png")
        plt.close(fig)
        mime = "image/png"
    elif tool == "plotly":
        import plotly.graph_objects as go

        flat = [v for row in values for v in row]
        trace = (
            go.Histogram(x=[v for v in flat if v is not None])
            if chart == "histogram"
            else (
                go.Scatter(
                    x=list(range(len(flat))), y=flat, mode="lines", connectgaps=False
                )
                if chart == "line"
                else go.Heatmap(z=values, colorscale="Viridis")
            )
        )
        fig = go.Figure(trace)
        fig.update_layout(title=request["title"], template="plotly_white")
        path.write_text(
            "<!doctype html>\n"
            + fig.to_html(
                include_plotlyjs=True,
                full_html=True,
                config={"responsive": True, "displaylogo": False},
            ),
            encoding="utf-8",
        )
        mime = "text/html"
    elif tool == "altair":
        import altair as alt

        rows = [
            {"row": i, "column": j, "value": value}
            for i, row in enumerate(values)
            for j, value in enumerate(row)
        ]
        for index, row in enumerate(rows):
            row["index"] = index
        base = alt.Chart(alt.Data(values=rows))
        chart_spec = (
            base.mark_line().encode(
                x=alt.X("index:Q", title="Captured cell index"), y="value:Q"
            )
            if chart == "line"
            else (
                base.mark_bar().encode(
                    x=alt.X("value:Q", bin=alt.Bin(maxbins=32)), y="count()"
                )
                if chart == "histogram"
                else base.mark_rect().encode(x="column:O", y="row:O", color="value:Q")
            )
        )
        chart_spec = chart_spec.properties(
            title=request["title"], width="container", height=360
        )
        path.write_text(chart_spec.to_json(), encoding="utf-8")
        mime = "application/vnd.vegalite.v5+json"
    else:
        raise ValueError("Unknown adapter")
    print(json.dumps({"mime": mime, "bytes": path.stat().st_size}))


if __name__ == "__main__":
    main()
