"""
Chart helpers: they turn order lines into pandas DataFrames and DataFrames into
Plotly chart HTML, so the customer, employee and supplier pages all draw their
charts the same way. A model method (for example Customer.annual_orders_plot)
pulls its order lines out of the database with lines_frame, groups them with
pandas, and hands the result to bar_figure or line_figure.

Revenue is each line's unit_price * quantity * (1 - discount), the same formula
as OrderDetail.line_total -- not Product.unit_price, which is today's list price
and ignores discounts and any price change since the order was placed.
"""

import calendar

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import qualitative

# region [WHY] one fixed color per bar
# A bar chart gives each x value its own color, picked by position in a stable
# ordering (bar_figure), so the same category or product keeps its color in every
# chart. With more bars than colors, the colors repeat. Any of Plotly's built-in
# qualitative palettes works here; see https://plotly.com/python/colors/
# endregion
CHART_COLORS = qualitative.Set3


def lines_frame(lines):
    """
    Turns a queryset of OrderDetail rows into a DataFrame, one row per line, with
    the columns the charts group on: order_id, order_date, year, month,
    product_name, category_name, customer_name, customer_country, quantity and
    revenue (empty when there are no lines). .values() asks the database for
    just those columns as plain dicts instead of building a model object per row.

    Assignment 3, Requirement 4 (S2, "Where do my sales come from?") added
    customer_country, the ordering customer's country. It is only ever grouped
    and counted by country, never shown next to a customer's name.
    """
    rows = lines.values(
        "order_id",
        "order__order_date",
        "order__customer__company_name",
        "order__customer__country",
        "product__product_name",
        "product__category__category_name",
        "unit_price",
        "quantity",
        "discount",
    )
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    frame = frame.rename(columns={
        "order__order_date": "order_date",
        "order__customer__company_name": "customer_name",
        "order__customer__country": "customer_country",
        "product__product_name": "product_name",
        "product__category__category_name": "category_name",
    })
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    frame["year"] = frame["order_date"].dt.year
    frame["month"] = frame["order_date"].dt.month
    frame["revenue"] = frame["unit_price"] * frame["quantity"] * (1 - frame["discount"])
    frame["category_name"] = frame["category_name"].fillna("Uncategorized")
    frame["customer_name"] = frame["customer_name"].fillna("Unknown customer")
    frame["customer_country"] = frame["customer_country"].fillna("Unknown").replace("", "Unknown")
    return frame


def figure_html(figure):
    """
    Turns a Plotly figure into an HTML <div> plus the small <script> that draws
    it. include_plotlyjs=False leaves the ~4 MB plotly.js library out of every
    chart; the page loads it once itself.
    """
    # The chart title is styled like a card title in the page (Bootstrap's h5: 20px, dark
    # text, flush left in the card), so a chart and an HTML card heading look alike.
    figure.update_layout(
        template="plotly_white", margin={"l": 40, "r": 20, "t": 50, "b": 40},
        title={"x": 0, "xref": "container", "xanchor": "left", "font": {"size": 20, "color": "#212529", "family": '"Segoe UI", Tahoma, "Trebuchet MS", sans-serif'}},
    )
    return figure.to_html(full_html=False, include_plotlyjs=False)


def _color_map(names):
    """Maps each distinct name to a CHART_COLORS entry by its position in sorted order (repeating once the palette runs out)."""
    ordered = sorted(set(names), key=str)
    return {name: CHART_COLORS[i % len(CHART_COLORS)] for i, name in enumerate(ordered)}


def bar_figure(data, category, value, title, labels, color_names=None,
               horizontal=False, height=None, trend=True, text=None, hover=None,
               trend_points=None):
    """
    Builds one bar chart with Plotly Express: a bar per row of data, each bar its
    own color (CHART_COLORS) and labeled with its value, plus (trend=True) a
    dashed least-squares trend line over the bars.

    data is a DataFrame already in display order; category is the column of bar
    names and value the column of bar lengths. labels names the axes, and
    color_names is the full set of names to take colors from, so a chart showing
    only the top ten products keeps the colors it has in a chart showing all of
    them.

    The trend line (np.polyfit, degree 1, clamped at zero) says something about
    time-ordered bars such as months or years; bars sorted by size pass
    trend=False. trend_points (Assignment 3) fits and draws the trend over only
    the first N bars: a monthly chart of the current year passes the number of
    months the data covers, so months that have not happened yet (shown as $0)
    do not drag the line down as if sales had collapsed. text replaces the bar labels, and hover replaces the hover box's
    text (one string per bar, with <br> for line breaks). height is always
    explicit: left unset, Plotly sizes to its container, and inside an
    equal-height card the chart would collapse.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    names = list(data[category])
    values = list(data[value])
    if text is None:
        text = [f"{v:,.0f}" if value == "quantity" else f"${v:,.0f}" for v in values]

    # px.bar draws the bars and names the axes from labels.
    x, y = (value, category) if horizontal else (category, value)
    figure = px.bar(data, x=x, y=y, orientation="h" if horizontal else "v",
                    title=title, labels=labels, height=height or 420)

    # One color per bar, a label at the end of each bar, and a hover box that shows
    # the bar's name and label (without a hovertemplate Plotly prints raw axis numbers).
    tip = "<b>%{y}</b><br>%{text}<extra></extra>" if horizontal else "<b>%{x}</b><br>%{text}<extra></extra>"
    figure.update_traces(
        marker_color=[colors[name] for name in names], text=text, textposition="outside",
        cliponaxis=False, textfont_size=11, customdata=hover,
        hovertemplate="%{customdata}<extra></extra>" if hover is not None else tip,
    )

    trend_names, trend_values = names, values
    if trend_points is not None:
        trend_names, trend_values = names[:trend_points], values[:trend_points]
    if trend and len(trend_values) >= 2:
        slope, intercept = np.polyfit(np.arange(len(trend_values)), trend_values, 1)
        fitted = list(np.maximum(slope * np.arange(len(trend_values)) + intercept, 0))
        prefix = "" if value == "quantity" else "$"
        line = {"mode": "lines", "name": "Trend", "line": {"color": "#444444", "width": 2, "dash": "dash"},
                "hovertemplate": "Trend: " + prefix + "%{y:,.0f}<extra></extra>"}
        figure.add_scatter(**({"x": fitted, "y": trend_names} if horizontal else {"x": trend_names, "y": fitted}), **line)

    # Stretch the value axis past the longest bar so the labels fit; long labels
    # ("$56,526 (10.7%)") need more room than short ones.
    room = 1.25 if max(len(label) for label in text) <= 8 else 1.55
    if not horizontal and room > 1.25:
        # Plotly shrinks a label that is wider than its bar (constraintext), which makes
        # long labels on narrow columns unreadable; tilt them and let them overhang.
        figure.update_traces(textangle=-45, constraintext="none", textfont_size=13, selector={"type": "bar"})
        room = 1.9
        figure.update_xaxes(range=[-0.9, len(names) - 0.4])  # room at the left so the first label clears the axis
    (figure.update_xaxes if horizontal else figure.update_yaxes)(range=[0, max(values) * room])
    figure.update_layout(bargap=0.2, legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0})
    if not horizontal:
        figure.update_xaxes(type="category")
    return figure_html(figure)


def line_figure(data, x, y, title, labels, height=360, hover=None):
    """
    Builds one line chart with Plotly Express, with a marker on each point, for
    values in time order such as revenue by month (bars suit separate groups, a
    line suits a sequence). data is a DataFrame already in time order; x is the
    column of point names and y the column of values.

    The line is smoothed (line_shape="spline"), so between two markers it can dip
    a little; the markers stay on the real values. Like bar_figure it takes hover
    text and ends in figure_html. The value axis starts at zero so a quiet month
    looks quiet, and the x names are categories so Plotly keeps them in the order
    given.
    """
    figure = px.line(data, x=x, y=y, markers=True, line_shape="spline", title=title, labels=labels, height=height)
    figure.update_traces(line={"color": CHART_COLORS[0], "width": 3, "smoothing": 0.8}, marker={"size": 7},
                         customdata=hover, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero", tickprefix="$")
    return figure_html(figure)


def top_with_other(data, category, value, count):
    """
    The `count` largest rows of data by value, largest first, plus one "Other" row
    adding up the rest when there are any. A pie is only readable with a few
    slices, so pie_figure is fed this.
    """
    ordered = data.sort_values(value, ascending=False)
    top = ordered.head(count)
    if len(ordered) > count:
        other = pd.DataFrame({category: ["Other"], value: [ordered[value].iloc[count:].sum()]})
        top = pd.concat([top, other], ignore_index=True)
    return top


def pie_figure(data, category, value, title, color_names=None, height=420):
    """
    Builds one pie chart with Plotly Express: a slice per row of data, colored like
    the bar charts (a name keeps its color; "Other" is gray) and labeled with its
    percent. The hover box shows the name, its dollars and its percent, so value
    should be a dollar amount. Use top_with_other first so there are few slices.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    colors["Other"] = "lightgray"
    figure = px.pie(data, names=category, values=value, title=title, height=height,
                    color=category, color_discrete_map=colors)
    figure.update_traces(sort=False, textinfo="percent",
                         hovertemplate="<b>%{label}</b><br>$%{value:,.0f} (%{percent})<extra></extra>")
    return figure_html(figure)



# ==========================================================================
# Assignment 3 -- chart helpers shared by the customer and supplier
# dashboards. Each takes one portal's order lines as a lines_frame()
# DataFrame (already limited to that customer's or supplier's own lines by
# the model method that calls it), groups it with pandas and returns chart
# HTML -- or None when there is nothing to draw, so the card template can
# show a short message instead of an error.
# ==========================================================================

# Muted gray for a "team" or "average" series, matching the "Team average"
# bar of the provided team comparison chart.
TEAM_COLOR = "#5f6b76"


def filter_year(frame, year):
    """frame limited to one year, or unchanged when year is None ("All years")."""
    if frame.empty or year is None:
        return frame
    return frame[frame["year"] == year]


def category_charts(frame, year=None, color_names=None):
    """
    The two charts of a Revenue by Category card, as a pair of chart HTML
    strings (either may be None when there is nothing to draw):

      1. Revenue by category -- horizontal bars, largest on top, each
         labeled with its dollars and its percent of the total.
      2. Unit share by category -- a donut (a pie with a hole) of units,
         labeled with percents. A pie suits it because the slices are parts
         of one whole (all the units bought or sold), and with eight
         categories at most it stays readable.

    year limits both to one year (None = all years). color_names is every
    category on record, so a category keeps one color in both charts and on
    every portal, whichever categories this customer or supplier has.
    """
    frame = filter_year(frame, year)
    if frame.empty:
        return None, None
    when = f", {year}" if year else ", all years"
    by_category = (
        frame.groupby("category_name", as_index=False)
        .agg(revenue=("revenue", "sum"), quantity=("quantity", "sum"))
    )
    names = color_names if color_names is not None else by_category["category_name"]
    colors = _color_map(names)
    height = max(360, 40 * len(by_category) + 120)

    total = by_category["revenue"].sum()
    revenue_rows = by_category.sort_values("revenue")  # Plotly draws the first horizontal bar at the bottom.
    text = [f"${r.revenue:,.0f} ({r.revenue / total * 100:.1f}%)" if total else "$0" for r in revenue_rows.itertuples()]
    revenue_plot = bar_figure(
        revenue_rows, "category_name", "revenue", f"Revenue by category{when}",
        {"category_name": "Category", "revenue": "Revenue ($)"},
        color_names=names, horizontal=True, height=height, trend=False, text=text,
    )

    units_rows = by_category[by_category["quantity"] > 0].sort_values("quantity", ascending=False)
    units_plot = None
    if not units_rows.empty:
        figure = go.Figure(go.Pie(
            labels=list(units_rows["category_name"]), values=list(units_rows["quantity"]),
            hole=0.45, sort=False, direction="clockwise",
            marker={"colors": [colors[name] for name in units_rows["category_name"]]},
            textinfo="percent", textposition="inside", insidetextorientation="horizontal",
            hovertemplate="<b>%{label}</b><br>%{value:,} units<br>%{percent}<extra></extra>",
        ))
        figure.update_layout(
            title=f"Unit share by category{when}", height=height,
            legend={"orientation": "v", "x": 1.02, "y": 0.5},
            annotations=[{"text": f"{int(units_rows['quantity'].sum()):,}<br>units", "showarrow": False, "font_size": 14}],
        )
        units_plot = figure_html(figure)
    return revenue_plot, units_plot


def top_products_chart(frame, measure="revenue", top=10, year=None):
    """
    Horizontal bars of the top products in one portal's lines, by revenue
    (measure="revenue") or by units (measure="quantity"), largest on top.
    top limits the number of bars (None = every product). Each bar is
    labeled with its value and its percent of the total, so "Top 10" still
    says how much of the whole those ten products are. None when there are
    no lines in the chosen year.
    """
    frame = filter_year(frame, year)
    if frame.empty:
        return None
    by_product = frame.groupby("product_name", as_index=False).agg(
        revenue=("revenue", "sum"), quantity=("quantity", "sum")
    )
    total = by_product[measure].sum()
    rows = by_product.sort_values([measure, "product_name"], ascending=[False, True])
    if top:
        rows = rows.head(top)
    rows = rows.iloc[::-1]
    money = measure == "revenue"
    text = [(f"${v:,.0f}" if money else f"{v:,.0f}") + (f" ({v / total * 100:.1f}%)" if total else "") for v in rows[measure]]
    word = "revenue" if money else "units"
    when = f", {year}" if year else ""
    title = (f"Top {top} products by {word}" if top else f"Products by {word}") + when
    per_bar = 32 if len(rows) <= 12 else 24
    return bar_figure(
        rows, "product_name", measure, title,
        {"product_name": "Product", "revenue": "Revenue ($)", "quantity": "Units"},
        color_names=by_product["product_name"], horizontal=True,
        height=max(380, per_bar * len(rows) + 110), trend=False, text=text,
    )


def monthly_chart(frame, year, horizon, title="Revenue by month"):
    """
    Revenue for each month of one year as bars, all twelve months always
    shown: reindex(range(1, 13), fill_value=0) puts a month with no orders on
    the chart as $0 instead of leaving it out. horizon is the last date the
    data covers (see data_horizon in models.py); in that year the trend line
    stops at horizon's month and the title says how far the data goes. None
    when the year has no lines at all.
    """
    frame = filter_year(frame, year)
    if frame.empty:
        return None
    monthly = (
        frame.groupby("month")
        .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
        .reindex(range(1, 13), fill_value=0)
        .reset_index()
    )
    hover = [
        f"<b>{calendar.month_name[row.month]} {year}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}"
        for row in monthly.itertuples()
    ]
    monthly["month"] = [calendar.month_abbr[m] for m in monthly["month"]]
    trend_points = horizon.month if horizon.year == year else None
    title = f"{title}, {year}"
    if trend_points is not None and trend_points < 12:
        title += f" (data through {calendar.month_abbr[horizon.month]} {horizon.day})"
    return bar_figure(
        monthly, "month", "revenue", title,
        {"month": "Month", "revenue": "Revenue ($)"}, hover=hover, trend_points=trend_points,
    )
