from typing import Dict

def add_risk_reward_shapes(fig, entry: float, stop: float, target: float):
    if stop and entry and target:
        fig.add_hrect(y0=stop, y1=entry, fillcolor="red", opacity=0.1, line_width=0)
        fig.add_hrect(y0=entry, y1=target, fillcolor="green", opacity=0.1, line_width=0)
        fig.add_hline(y=entry, line_color="orange", line_dash="dot")
        fig.add_hline(y=stop, line_color="red", line_dash="dot")
        fig.add_hline(y=target, line_color="green", line_dash="dot")

def add_levels(fig, levels: Dict[str, float]):
    for name, value in levels.items():
        if value is None: 
            continue
        fig.add_hline(y=value, annotation_text=name, annotation_position="top left",
                      line_dash="dash", line_color="#666")