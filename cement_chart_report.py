"""In-memory diagnostic presentation of the prepared Round 8A model."""
from io import BytesIO

import numpy as np
from cement_chart_model import chart_job_kind

CHART_ANCHOR = "Pressure and fluid sequence charts: Not provided."
NOT_APPLICABLE = "Pressure and fluid sequence charts: Not applicable for this job type."
COLORS = {"Mud": "#C9C9C9", "Pre Flush": "#0066E0", "Spacer": "#00C000",
          "Spacer Ahead": "#00C000", "Scavenger": "#6E6E6E", "Main": "#6E6E6E",
          "Lead": "#ABABAB", "Lead #1": "#B8B8B8", "Lead #2": "#A2A2A2", "Tail": "#6E6E6E"}


def prepared_cement_report(state):
    """No UI-dependent engineering: preparation owns validation and rebuilding."""
    return {"kind": chart_job_kind(state.get("job_type")), "model": state.get("_cement_chart_model")}


def build_chart_figure(model):
    """Draw resolved psi/TVD and Hardware MD/diameters; never synthesize values."""
    if model is None:
        raise ValueError("A prepared Round 8A chart model is required.")
    if not model["static_security_ready"]:
        raise ValueError("Static Well Security is unsupported: TVD decreases along the continuous trajectory.")
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Rectangle
        from matplotlib.ticker import MaxNLocator
    except ImportError as exc:
        raise ValueError("Word chart rendering requires matplotlib==3.10.8.") from exc
    figure = Figure(figsize=(11.5, 8.4))
    FigureCanvasAgg(figure)
    try:
        left, right = figure.subplots(1, 2, gridspec_kw={"width_ratios": [1.12, 1]})
        figure.subplots_adjust(top=.91, bottom=.13, left=.09, right=.96, wspace=.28)
        left.set_facecolor("#EFEFEF")
        left.grid(color="white", linewidth=1.1)
        left.set_axisbelow(True)
        hydro, pressure = model["hydrostatic"], model["pore_frac"]
        for name, values, depths, color in (
                ("Hydrostatic", hydro["pressure_psi"], hydro["tvd_m"], "#FF0000"),
                ("Frac", pressure["frac_psi"], pressure["tvd_m"], "#0000FF"),
                ("Pore", pressure["pore_psi"], pressure["tvd_m"], "#00B040")):
            if not values or len(values) != len(depths) or not np.isfinite([*values, *depths]).all():
                raise ValueError("Prepared Round 8A pressure arrays must be finite and aligned.")
            line, = left.plot(np.asarray(values)/1000., depths, color=color, linewidth=3.8,
                             solid_capstyle="round", label=name)
            if name != "Hydrostatic" and pressure["kind"] == "markers":
                line.set_marker("o"); line.set_markersize(8)
                line.set_markeredgecolor("white"); line.set_markeredgewidth(1.2)
        left.set_ylim(max(hydro["tvd_m"])*1.04, 0)
        left.set_xlim(left=0)
        left.xaxis.set_major_locator(MaxNLocator(4))
        left.tick_params(axis="x", top=True, labeltop=True, bottom=False, labelbottom=False)
        left.xaxis.set_label_position("top")
        left.set_xlabel("(x 1000) psi")
        left.set_ylabel("TVD (m)")
        left.legend(loc="upper left", fontsize=9, framealpha=1, edgecolor="black", fancybox=False)
        left.set_title("Static Well Security", y=-.10)

        active, outer = model["active_string"], model["enclosing_string"]
        shoe = model["shoe_md"]
        scale = 2./max(s["od_in"] for s in outer)
        def half(segment, field):
            return segment[field]*scale/2.
        def rectangle(x, width, top, bottom, color, gid, hatch=None, edge="none", z=2):
            patch = Rectangle((x,top),width,bottom-top,facecolor=color,edgecolor=edge,
                              hatch=hatch,linewidth=.8,zorder=z)
            patch.set_gid(gid)
            right.add_patch(patch)
        # Split only drawing rectangles at the already-resolved geometry edges.
        # This is not another interval/capacity/placement resolver.
        for fluid in model["annular_intervals"]:
            color = COLORS[fluid["fluid"]]
            for inner in active:
                for enclosing in outer:
                    top = max(fluid["top_md"],inner["top_md"],enclosing["top_md"])
                    bottom = min(fluid["bottom_md"],inner["bottom_md"],enclosing["bottom_md"])
                    if bottom <= top:
                        continue
                    outer_field = "od_in" if enclosing["description"] == "Open Hole Size" else "id_in"
                    a, b = half(inner,"od_in"), half(enclosing,outer_field)
                    for side in (-1,1):
                        rectangle(-b if side<0 else a,b-a,top,bottom,color,"annulus:"+fluid["fluid"])
        # Interior above the collar is intentionally unfilled: Round 8A does not
        # resolve an inside-string fluid ladder. Do not invent a Mud interval.
        for segment in active:
            top, bottom = max(segment["top_md"],model["float_collar_md"]),segment["bottom_md"]
            if bottom>top:
                radius=half(segment,"id_in")
                rectangle(-radius,2*radius,top,bottom,COLORS[model["shoe_track_fluid"]],"shoe-track")
            od, inner = half(segment,"od_in"), half(segment,"id_in")
            for side in (-1,1):
                rectangle(-od if side<0 else inner,od-inner,segment["top_md"],segment["bottom_md"],
                          "white","active-wall",hatch="////",edge="black",z=3)
        for side in (-1,1):
            xs, ys = [], []
            for segment in outer:
                field="od_in" if segment["description"]=="Open Hole Size" else "id_in"
                radius=half(segment,field)
                xs.extend([side*radius,side*radius]);ys.extend([segment["top_md"],segment["bottom_md"]])
            right.plot(xs,ys,color="black",linewidth=1.2)
        deepest=outer[-1]
        radius=half(deepest,"od_in" if deepest["description"]=="Open Hole Size" else "id_in")
        right.plot([-radius,radius],[shoe,shoe],color="black",linewidth=1.6)
        right.plot([-1.1,1.1],[0,0],color="black",linewidth=1.2)
        right.axvline(0,color="gray",ls="--",lw=1,alpha=.55,zorder=1)
        # A compact key keeps very thin valid bands readable without overlapping
        # depth labels or inventing a minimum fluid interval for presentation.
        names=list(dict.fromkeys(row["fluid"] for row in model["annular_intervals"]))
        for index,name in enumerate(names):
            y=.97-index*.047
            right.text(1.03,y,name,transform=right.transAxes,fontsize=8,va="top",color="black")
            right.plot([.99,1.02],[y-.009,y-.009],transform=right.transAxes,color=COLORS[name],lw=5,clip_on=False)
        right.text(.5,-.055,"Shoe Track: "+model["shoe_track_fluid"],transform=right.transAxes,
                   ha="center",fontsize=8)
        right.set_ylim(shoe*1.04,-shoe*.025)
        right.set_xlim(-1.12,1.12)
        right.set_ylabel("MD (m)")
        right.set_xticks([])
        right.spines[["top","right","bottom"]].set_visible(False)
        right.set_title("Fluid Sequence",y=-.14)
        # Reserve room for the fluid key within the canvas.
        figure.subplots_adjust(right=.83)
        return figure
    except Exception:
        figure.clear()
        raise


def render_chart_png(model):
    figure=build_chart_figure(model)
    try:
        output=BytesIO()
        figure.savefig(output,format="png",dpi=200,facecolor="white")
        return output.getvalue()
    finally:
        figure.clear()
