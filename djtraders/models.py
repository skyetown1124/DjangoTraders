"""
The app's models, cleaned up from `manage.py inspectdb` (rev_engineer_models.py
has the raw output). Every model is managed=False, because this app reads a
database Django didn't create and must never migrate those tables. Names are
singular, models are ordered so each is defined before anything that references
it by bare class name, and every foreign key has a real on_delete (inspectdb
defaults to DO_NOTHING).

On top of that the models add computed @property values (e.g.
Order.order_total), search() classmethods that back the list pages,
authenticate() classmethods for the hand-rolled logins (no django.contrib.auth),
and, for the dashboards, methods that return Plotly charts built with the
helpers in charts.py.
"""

import calendar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from django.db import models
from django.db.models import Count, ExpressionWrapper, F, FloatField, Max, Sum
from django.utils import timezone

from .charts import (
    CHART_COLORS,
    TEAM_COLOR,
    bar_figure,
    category_charts,
    figure_html,
    filter_year,
    line_figure,
    lines_frame,
    monthly_chart,
    pie_figure,
    top_products_chart,
    top_with_other,
)


# ==========================================================================
# Assignment 3 -- numbers shared by the customer and supplier dashboards.
# The chart drawing lives in charts.py; these helpers work out the figures
# the summary tiles print.
# ==========================================================================

def data_horizon():
    """
    The last date the order data covers: the latest placed order's date, or
    today if that is earlier. The class database's orders stop on one day,
    so "this year to date" and the current year's monthly trend are measured
    up to that day; comparing with today's date instead would count months
    with no data as if sales had stopped.
    """
    today = timezone.localdate()
    last = Order.objects.filter(order_date__isnull=False).aggregate(last=Max("order_date"))["last"]
    return min(today, last) if last else today


# region [WHY] Extra Credit 2 -- the "Buy It Again" numbers, shared by the
# customer card (Customer.buy_again) and the employee table
# (Employee.buy_again_calls).
#   - Only products still on sale, bought on at least BUY_AGAIN_MIN_ORDERS (3)
#     different orders, count: with fewer there is no gap pattern to judge.
#   - gap: the median number of days between consecutive orders of the product
#     (orders on the same day count once). The median, not the mean, so one very
#     long or short wait does not move it much.
#   - days_since: days from the last of those orders to the data horizon.
#   - ratio = days_since / gap. Overdue when ratio >= BUY_AGAIN_OVERDUE_RATIO
#     (1.5). In this data a customer's gaps for one product typically vary by
#     about half their size around the median, so waiting a little past the
#     usual gap is normal; 1.5 gaps is beyond that ordinary variation, while
#     1.0 would flag about half of perfectly normal waits. Between 1.0 and 1.5 a
#     product is "Due": past its usual gap but not yet unusual.
#   - at_stake: the revenue of one typical reorder, the median revenue (after
#     discount) of the customer's orders of that product.
# endregion
BUY_AGAIN_MIN_ORDERS = 3
BUY_AGAIN_OVERDUE_RATIO = 1.5
BUY_AGAIN_STATUSES = ("Overdue", "Due", "Not yet")
# Show Top choices for both Extra Credit 2 cards: the lists are short, so 3 / 5 / All (All by default).
BUY_AGAIN_TOP_CHOICES = (("3", "3"), ("5", "5"), ("all", "All"))


def buy_again_rows(lines, horizon):
    """
    {customer_id: [row, ...]} for the given OrderDetail queryset (placed orders
    only, products not discontinued). Each row: product_id, name, category,
    orders, gap (days), last (date), days_since, days_over (days past the
    usual gap, 0 if not past it), ratio, status (BUY_AGAIN_STATUSES), at_stake,
    usual_qty (median quantity per order), price, in_stock and add_qty (the
    usual quantity capped at what is in stock). Rows are sorted Overdue, Due,
    Not yet, and by ratio within each, most overdue first.
    """
    values = (
        lines.filter(order__order_date__isnull=False, product__discontinued=0)
        .values("order__customer_id", "order_id", "order__order_date", "product_id",
                "product__product_name", "product__category__category_name",
                "product__unit_price", "product__units_in_stock",
                "unit_price", "quantity", "discount")
    )
    grouped = {}
    for line in values:
        key = (line["order__customer_id"], line["product_id"])
        entry = grouped.setdefault(key, {"line": line, "orders": {}})
        order = entry["orders"].setdefault(line["order_id"], {"date": line["order__order_date"], "qty": 0, "revenue": 0.0})
        order["qty"] += line["quantity"]
        order["revenue"] += line["unit_price"] * line["quantity"] * (1 - (line["discount"] or 0))

    rank = {name: i for i, name in enumerate(BUY_AGAIN_STATUSES)}
    result = {}
    for (customer_id, product_id), entry in grouped.items():
        orders = list(entry["orders"].values())
        if len(orders) < BUY_AGAIN_MIN_ORDERS:
            continue
        dates = sorted({order["date"] for order in orders})
        if len(dates) < 2:
            continue
        gap = float(np.median([(b - a).days for a, b in zip(dates, dates[1:])]))
        if gap <= 0:
            continue
        last = dates[-1]
        days_since = (horizon - last).days
        ratio = days_since / gap
        if ratio >= BUY_AGAIN_OVERDUE_RATIO:
            status = "Overdue"
        elif ratio >= 1:
            status = "Due"
        else:
            status = "Not yet"
        line = entry["line"]
        in_stock = line["product__units_in_stock"] or 0
        usual_qty = max(1, int(round(float(np.median([order["qty"] for order in orders])))))
        result.setdefault(customer_id, []).append({
            "product_id": product_id,
            "name": line["product__product_name"],
            "category": line["product__category__category_name"],
            "orders": len(orders),
            "gap": int(round(gap)),
            "last": last,
            "days_since": days_since,
            "days_over": max(0, int(round(days_since - gap))),
            "ratio": ratio,
            "status": status,
            "at_stake": float(np.median([order["revenue"] for order in orders])),
            "usual_qty": usual_qty,
            "price": line["product__unit_price"],
            "in_stock": in_stock,
            "add_qty": min(usual_qty, in_stock),
        })
    for rows in result.values():
        rows.sort(key=lambda row: (rank[row["status"]], -row["ratio"], row["name"]))
    return result


def _all_category_names():
    """Every category on record (plus "Uncategorized"), so each category keeps one color on every chart and portal."""
    return list(Category.objects.values_list("category_name", flat=True)) + ["Uncategorized"]


def _year_to_date(frame, horizon):
    """
    Revenue this year to date and over the same stretch of last year, for
    the Total Revenue tile. "To date" is horizon's month and day (see
    data_horizon): with data through 6 May, this year runs 1 Jan - 6 May
    and last year 1 Jan - 6 May of the year before, so the two periods are
    the same length and the comparison is fair part-way through a year.
    Returns (this_ytd, last_ytd, change_percent); change_percent is None
    when last year's figure is zero, since a change from nothing has no
    meaningful percent.
    """
    if frame.empty:
        return 0.0, 0.0, None
    day_of_year = frame["order_date"].dt.month * 100 + frame["order_date"].dt.day
    to_date = frame[day_of_year <= horizon.month * 100 + horizon.day]
    this_ytd = float(to_date.loc[to_date["year"] == horizon.year, "revenue"].sum())
    last_ytd = float(to_date.loc[to_date["year"] == horizon.year - 1, "revenue"].sum())
    change = (this_ytd / last_ytd - 1) * 100 if last_ytd > 0 else None
    return this_ytd, last_ytd, change


def _dashboard_summary(frame):
    """
    The four summary tiles' numbers from one portal's order lines: total
    revenue (all years), this year to date against the same dates last
    year, orders (distinct orders), units, average order, first and last
    order dates and days since the last order. None when there are no lines.
    """
    if frame.empty:
        return None
    horizon = data_horizon()
    this_ytd, last_ytd, change = _year_to_date(frame, horizon)
    orders = int(frame["order_id"].nunique())
    revenue = float(frame["revenue"].sum())
    last_order = frame["order_date"].max().date()
    return {
        "revenue": revenue,
        "this_ytd": this_ytd,
        "last_ytd": last_ytd,
        "ytd_change": change,
        "ytd_year": horizon.year,
        "ytd_through": horizon,
        "orders": orders,
        "units": int(frame["quantity"].sum()),
        "units_per_order": frame["quantity"].sum() / orders if orders else 0,
        "average_order": revenue / orders if orders else 0,
        "first_order": frame["order_date"].min().date(),
        "last_order": last_order,
        "days_since_last": (timezone.localdate() - last_order).days,
        "order_years": int(frame["year"].nunique()),
    }


class Category(models.Model):
    """A product category. Defined before Product so Product.category can use the bare class name."""
    category_id = models.SmallIntegerField(primary_key=True)
    category_name = models.CharField(max_length=15)
    description = models.TextField(blank=True, null=True)
    picture = models.BinaryField(blank=True, null=True)

    class Meta:
        """Meta configures the table, not a column. managed=False: the table exists, so Django must not migrate it. db_table: its real name."""
        managed = False
        db_table = 'categories'


class Customer(models.Model):
    """A DjangoTraders customer. No foreign keys, so no on_delete concerns."""
    customer_id = models.CharField(primary_key=True, max_length=5)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    password = models.CharField(db_column='Password', max_length=64, blank=True, null=True)  # Field name made lowercase.
    inactive_date = models.DateField(blank=True, null=True)

    @property
    def formatted_address(self):
        """This customer's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    # region [WHY] charts built from a DataFrame
    # Each *_plot method pulls this customer's placed order lines into a DataFrame
    # (_order_lines_frame), groups and sums them with pandas, and hands the result to
    # bar_figure, which returns chart HTML a template prints with |safe.
    # endregion
    def _order_lines_frame(self):
        """
        Every line on this customer's placed orders as a DataFrame (see
        lines_frame in charts.py). An order with no order_date is an unplaced
        cart and is left out.
        """
        return lines_frame(OrderDetail.objects.filter(
            order__customer=self, order__order_date__isnull=False
        ))

    def order_years(self):
        """Distinct years this customer has placed orders in, newest first."""
        years = self.order_set.filter(order_date__isnull=False).dates("order_date", "year")
        return sorted((d.year for d in years), reverse=True)

    def annual_orders_plot(self):
        """Bar chart of this customer's total revenue for each year."""
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year", as_index=False)["revenue"].sum()
        annual["year"] = annual["year"].astype(str)
        return bar_figure(
            annual, "year", "revenue", "Revenue by year",
            {"year": "Year", "revenue": "Revenue ($)"},
        )

    def orders_placed_plot(self, year):
        """
        Bar chart of this customer's revenue for each month of one year (what the
        dashboard's year dropdown loads), or None when that year has no placed
        orders. All twelve months are on the chart, $0 for a month with no orders.

        Assignment 3: now drawn by monthly_chart (charts.py), the same helper as
        the supplier's monthly chart, so in the year the data ends the trend
        line stops at the last month on record instead of diving through the
        months that have not happened yet, and hovering a bar shows its orders.
        """
        return monthly_chart(self._order_lines_frame(), year, data_horizon())

    # region [WHY] Assignment 3, Requirement 2 -- the customer dashboard
    # Every method below starts from _order_lines_frame(), which is filtered to
    # this customer's own placed orders, so every number on the customer
    # dashboard is the customer's own. Which customer it is comes from the
    # session (customer_dashboard_denied in views/access.py); the URL's
    # customer_id is only accepted when it matches.
    # endregion
    def dashboard_summary(self):
        """
        The four summary tiles: Total Revenue (with this year to date against
        the same dates last year), Orders, Average Order and Last Order (with
        the days since). None when this customer has no placed orders.
        """
        return _dashboard_summary(self._order_lines_frame())

    def category_plots(self, year=None):
        """Revenue by category and unit share by category, for one year or all years (category_charts in charts.py)."""
        return category_charts(self._order_lines_frame(), year, _all_category_names())

    def top_product_plots(self, top=10, year=None):
        """Top products by revenue and by units, as a pair of chart HTML strings (top_products_chart in charts.py)."""
        frame = self._order_lines_frame()
        return (
            top_products_chart(frame, "revenue", top, year),
            top_products_chart(frame, "quantity", top, year),
        )

    # region [WHY] Additional feature A -- "Am I on pace with last year?"
    # Not part of the assignment. The Total Revenue tile gives one
    # year-to-date number; this card shows the whole path: the running total
    # month by month for the chosen year beside the year before, so a
    # customer can see when they pulled ahead or fell behind. The current
    # year stops at the last day the data covers (data_horizon), and the
    # headline compares both years at that same point.
    # endregion
    PACE_MEASURES = {"revenue": "Revenue", "units": "Units", "orders": "Orders"}

    def pace_comparison(self, year, measure="revenue"):
        """
        Running totals for year and year - 1, month by month, in measure
        ("revenue", "units" or "orders"): {"months", "this", "last" (None
        when the year before has no orders), "this_total", "last_total",
        "change" (percent, or None), "through" (the date both totals run to),
        "partial" (True when year is still in progress)}. None when the chosen
        year has no orders.
        """
        frame = self._order_lines_frame()
        if frame.empty or year not in set(frame["year"]):
            return None
        horizon = data_horizon()
        partial = horizon.year == year
        last_month = horizon.month if partial else 12

        def monthly(part):
            if measure == "orders":
                series = part.groupby("month")["order_id"].nunique()
            else:
                series = part.groupby("month")["revenue" if measure == "revenue" else "quantity"].sum()
            return series.reindex(range(1, 13), fill_value=0).cumsum()

        def to_point(part):
            """Total from 1 Jan up to horizon's month and day (or the whole year)."""
            if partial:
                day_of_year = part["order_date"].dt.month * 100 + part["order_date"].dt.day
                part = part[day_of_year <= horizon.month * 100 + horizon.day]
            if measure == "orders":
                return float(part["order_id"].nunique())
            return float(part["revenue" if measure == "revenue" else "quantity"].sum())

        this_part = frame[frame["year"] == year]
        last_part = frame[frame["year"] == year - 1]
        this_total = to_point(this_part)
        last_total = to_point(last_part) if not last_part.empty else None
        change = (this_total / last_total - 1) * 100 if last_total else None
        return {
            "year": year,
            "months": [calendar.month_abbr[m] for m in range(1, 13)],
            "this": list(monthly(this_part))[:last_month],
            "last": list(monthly(last_part)) if not last_part.empty else None,
            "this_total": this_total,
            "last_total": last_total,
            "change": change,
            "through": horizon if partial else None,
            "partial": partial,
            "measure": measure,
        }

    def pace_plot(self, year, measure="revenue"):
        """
        Two running-total lines (pace_comparison): the chosen year in the
        customer blue and the year before as a dashed gray line, so the gap
        between them at any month is how far ahead or behind the customer is.
        Returns (chart HTML, the pace_comparison dict); (None, None) when the
        year has no orders.
        """
        pace = self.pace_comparison(year, measure)
        if pace is None:
            return None, None
        money = measure == "revenue"
        number = "$%{y:,.0f}" if money else "%{y:,.0f}"
        word = self.PACE_MEASURES[measure].lower()
        figure = go.Figure()
        if pace["last"] is not None:
            figure.add_scatter(
                x=pace["months"], y=pace["last"], name=str(year - 1), mode="lines+markers",
                line={"color": TEAM_COLOR, "width": 2, "dash": "dash"}, marker={"size": 6},
                hovertemplate=f"<b>%{{x}} {year - 1}</b><br>Running total: {number}<extra></extra>",
            )
        figure.add_scatter(
            x=pace["months"][:len(pace["this"])], y=pace["this"], name=str(year), mode="lines+markers",
            line={"color": "steelblue", "width": 3}, marker={"size": 8},
            hovertemplate=f"<b>%{{x}} {year}</b><br>Running total: {number}<extra></extra>",
        )
        figure.update_layout(
            title=f"Running total of {word}: {year} vs. {year - 1}", height=380,
            yaxis_title=f"{self.PACE_MEASURES[measure]} so far this year",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0},
        )
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=pace["months"])
        figure.update_yaxes(rangemode="tozero", tickprefix="$" if money else "")
        return figure_html(figure), pace

    @classmethod
    def search(cls, company_name="", contact_name="", contact_title="", city="", country=""):
        """
        Filters customers by any combination of company name, contact name,
        contact title, city and country (every customer when none are given), for
        customer_list's search form. A @classmethod because it builds a new
        queryset from the class (cls) rather than acting on one Customer. The two
        free-text fields use "icontains" (case-insensitive substring); the others
        come from dropdowns, so they match exactly.
        """
        queryset = cls.objects.order_by("company_name")
        if company_name:
            queryset = queryset.filter(company_name__icontains=company_name)
        if contact_name:
            queryset = queryset.filter(contact_name__icontains=contact_name)
        if contact_title:
            queryset = queryset.filter(contact_title=contact_title)
        if city:
            queryset = queryset.filter(city=city)
        if country:
            queryset = queryset.filter(country=country)
        return queryset

    @classmethod
    def authenticate(cls, customer_id, password):
        """
        Checks a login: the customer with this ID, and a direct compare of the
        password column (unlike Employee, which has no password column). Returns
        the Customer on success, None otherwise.
        """
        customer = cls.objects.filter(pk=customer_id).first()
        if customer is None:
            return None
        if customer.password != password:
            return None
        return customer

    @classmethod
    def generate_customer_id(cls, company_name):
        """
        Builds a new, unique 5-letter customer_id from a company name, in the
        existing style ("Alfreds Futterkiste" -> ALFKI). Called by
        customer_create after the form validates; a customer never types an ID.
        It takes the name's first five letters (padded with "X"), and if that ID is
        taken, swaps in a trailing counter (ALFK1, ALFK2, ...). The primary key's own
        uniqueness is the final guarantee; the loop just avoids a rejected insert.
        """
        letters = "".join(char for char in company_name.upper() if char.isalpha())
        base = (letters + "XXXXX")[:5]

        if not cls.objects.filter(pk=base).exists():
            return base

        # base alone is taken: replace its trailing characters with a counter.
        suffix = 1
        while suffix < 100_000:
            digits = str(suffix)
            candidate = base[: 5 - len(digits)] + digits
            if not cls.objects.filter(pk=candidate).exists():
                return candidate
            suffix += 1

        # Practically unreachable for a dataset this size.
        raise ValueError(f"Could not generate a unique customer_id from {company_name!r}")

    # region [WHY] Extra Credit 2 -- "Buy It Again"
    # For one customer: every product still on sale that they bought on at
    # least BUY_AGAIN_MIN_ORDERS orders, the median gap in days between those
    # orders, the days since the last one, and whether that is overdue. The
    # numbers come from buy_again_rows (module level), which the employee's
    # table (Employee.buy_again_calls) uses too, so both always agree.
    # "Today" is the data horizon (the last order on record), like every other
    # "to date" figure on the dashboard.
    # endregion
    def buy_again(self):
        """
        This customer's repeat products (see buy_again_rows), most overdue first.
        Returns [] when nothing has been bought on BUY_AGAIN_MIN_ORDERS or more orders.
        """
        lines = OrderDetail.objects.filter(order__customer=self)
        return buy_again_rows(lines, data_horizon()).get(self.customer_id, [])

    class Meta:
        managed = False
        db_table = 'customers'


class Employee(models.Model):
    """A DjangoTraders employee. Has a self-referencing FK for its manager (reports_to)."""
    employee_id = models.SmallIntegerField(primary_key=True)
    last_name = models.CharField(max_length=20)
    first_name = models.CharField(max_length=10)
    title = models.CharField(max_length=30, blank=True, null=True)
    title_of_courtesy = models.CharField(max_length=25, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    hire_date = models.DateField(blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    home_phone = models.CharField(max_length=24, blank=True, null=True)
    extension = models.CharField(max_length=4, blank=True, null=True)
    photo = models.BinaryField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    photo_path = models.CharField(max_length=255, blank=True, null=True)
    # region [CONCEPT] self-referencing FK (reports_to)
    # FK to Employee itself, for the manager hierarchy: gives us
    # employee.reports_to.first_name (up to the manager) and
    # employee.employee_set.all() (down to their reports).
    # SET_NULL so deleting a manager just clears the link, not their reports.
    # endregion
    reports_to = models.ForeignKey('self', models.SET_NULL, db_column='reports_to', blank=True, null=True)

    @property
    def formatted_address(self):
        """This employee's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    @property
    def is_manager(self):
        """
        True when at least one employee reports to this one. A manager may open
        any employee's page; employee_set is the reverse side of reports_to
        (every employee whose manager is this one).
        """
        return self.employee_set.exists()

    def _order_lines_frame(self):
        """Every line on the placed orders this employee handled, as a DataFrame (see lines_frame in charts.py)."""
        return lines_frame(OrderDetail.objects.filter(
            order__employee=self, order__order_date__isnull=False
        ))

    def revenue_years(self):
        """The years in which this employee handled placed orders, oldest first (for the year dropdown)."""
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        return sorted(int(year) for year in frame["year"].unique())

    def revenue_over_time(self, level="year", year=None, height=360):
        """
        The dashboard's revenue-over-time chart, as chart HTML (None when this
        employee has no orders). Each bar's hover shows the period, its revenue
        and its number of orders.

        level "year": one bar per year (year is ignored).
        level "month" with a year: the twelve months of that year, as a line chart.
        level "month" with year=None: every month from the first order to the last,
        across all years, as a line chart, so it reads as revenue over time.

        Orders are distinct orders. Months with no orders are filled in with zero
        (reindex over a full period range), so a quiet month shows as an empty
        slot instead of vanishing.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        if level == "year":
            grouped = frame.groupby("year").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            table = grouped.reset_index()
            table["label"] = table["year"].astype(str)
            table["full_label"] = table["label"]
            title, axis = "Revenue by year", "Year"
        else:
            if year is not None:
                frame = frame[frame["year"] == year]
            frame = frame.assign(period=frame["order_date"].dt.to_period("M"))
            grouped = frame.groupby("period").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            if year is None:
                full_range = pd.period_range(grouped.index.min(), grouped.index.max(), freq="M")
                title = "Revenue by month, all years"
            else:
                full_range = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
                title = f"Revenue by month, {year}"
            grouped = grouped.reindex(full_range, fill_value=0)
            table = grouped.reset_index(names="period")
            table["label"] = table["period"].dt.strftime("%b" if year is not None else "%b %Y")
            table["full_label"] = table["period"].dt.strftime("%B %Y")
            axis = "Month"
        hover = [
            f"<b>{row.full_label}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}"
            for row in table.itertuples()
        ]
        labels = {"label": axis, "revenue": "Revenue ($)"}
        if level == "year":
            return bar_figure(table, "label", "revenue", title, labels, height=height, hover=hover)
        # Months run in time order, so a line reads better than bars.
        return line_figure(table, "label", "revenue", title, labels, height=height, hover=hover)

    def period_detail(self, key):
        """
        What the Details modal shows for one period of this employee's orders: key
        is "1997" (a year) or "1997-03" (a month). Returns a dict with label,
        revenue, orders and products (the five products with the most revenue in
        that period, each with units and revenue). For a whole year it also returns
        months_plot, that year's revenue by month; for a single month it is None.
        The view has already checked that key is a real period.
        """
        year, _, month = key.partition("-")
        frame = self._order_lines_frame()
        in_period = frame["year"] == int(year)
        label = year
        if month:
            in_period &= frame["month"] == int(month)
            label = pd.Timestamp(year=int(year), month=int(month), day=1).strftime("%B %Y")
        part = frame[in_period]
        products = (
            part.groupby("product_name", as_index=False)
            .agg(units=("quantity", "sum"), revenue=("revenue", "sum"))
            .sort_values("revenue", ascending=False).head(5)
        )
        months_plot = None
        if not month:
            months_plot = self.revenue_over_time("month", int(year), height=300)
        return {
            "label": label,
            "revenue": part["revenue"].sum(),
            "orders": part["order_id"].nunique(),
            "products": products.to_dict("records"),
            "months_plot": months_plot,
        }

    @classmethod
    def _performance_frame(cls):
        """
        One row per employee who handled at least one placed order:
        revenue, orders (distinct orders), customers (distinct customers),
        average_order, revenue_per_customer, share (percent of all company
        revenue), and a rank for each measure (revenue_rank, orders_rank,
        average_order_rank, customers_rank, revenue_per_customer_rank;
        1 = best, ties share a rank). The database does the grouping with
        values()/annotate(); pandas adds the derived columns. Sorted by
        revenue_rank. The base for performance(), team_comparison() and
        leaderboard().
        """
        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False)
            .values(employee_key=F("order__employee_id"))
            .annotate(
                revenue=Sum(Supplier._line_revenue()),
                orders=Count("order", distinct=True),
                customers=Count("order__customer", distinct=True),
            )
        )
        frame = pd.DataFrame(list(rows)).dropna(subset=["employee_key"]) if rows else pd.DataFrame()
        if frame.empty:
            return frame
        frame["employee_key"] = frame["employee_key"].astype(int)
        frame["average_order"] = frame["revenue"] / frame["orders"]
        frame["revenue_per_customer"] = frame["revenue"] / frame["customers"].where(frame["customers"] > 0)
        frame["share"] = frame["revenue"] / frame["revenue"].sum() * 100
        for measure in ("revenue", "orders", "average_order", "customers", "revenue_per_customer"):
            frame[f"{measure}_rank"] = frame[measure].rank(ascending=False, method="min")
        return frame.sort_values("revenue_rank")

    def performance(self):
        """
        This employee compared with the other employees, for the
        dashboard's summary tiles: a dict with their revenue, orders,
        average_order, share of company revenue, revenue_rank and
        orders_rank, employee_count (how many employees have orders),
        colleagues_behind, team_share (an even split, 100 / employee_count),
        team_average_order (the mean of the employees' average orders, the same
        figure the "vs. the team" table shows) and
        average_order_diff (percent above or below that team figure).
        Returns None when this employee has no placed orders.
        """
        frame = self._performance_frame()
        if frame.empty:
            return None
        mine = frame[frame["employee_key"] == self.employee_id]
        if mine.empty:
            return None
        row = mine.iloc[0]
        count = len(frame)
        team_average_order = frame["average_order"].mean()
        return {
            "revenue": row["revenue"],
            "orders": int(row["orders"]),
            "average_order": row["average_order"],
            "share": row["share"],
            "revenue_rank": int(row["revenue_rank"]),
            "orders_rank": int(row["orders_rank"]),
            "employee_count": count,
            "colleagues_behind": count - int(row["revenue_rank"]),
            "team_share": 100 / count,
            "team_average_order": team_average_order,
            "average_order_diff": (row["average_order"] / team_average_order - 1) * 100,
        }

    # What the team comparison chart's dropdown can compare: the key and its label.
    TEAM_MEASURES = {
        "revenue": "Revenue",
        "orders": "Orders",
        "customers": "Customers served",
    }

    def team_comparison(self):
        """
        This employee against the team on the three TEAM_MEASURES, as a list of
        dicts for the dashboard's comparison table and chart: measure, label, kind
        ("money" or "count", for formatting), you, team_average (the mean across
        employees), vs_average (you as a percent above or below that average), best
        (the highest employee, nameless), rank and employee_count.
        Returns [] when this employee has no placed orders.
        """
        frame = self._performance_frame()
        mine = frame[frame["employee_key"] == self.employee_id] if not frame.empty else frame
        if mine.empty:
            return []
        row = mine.iloc[0]
        comparison = []
        for measure, label in self.TEAM_MEASURES.items():
            team_average = frame[measure].mean()
            comparison.append({
                "measure": measure,
                "label": label,
                "kind": "money" if measure == "revenue" else "count",
                "you": row[measure],
                "team_average": team_average,
                "vs_average": (row[measure] / team_average - 1) * 100,
                "best": frame[measure].max(),
                "rank": int(row[f"{measure}_rank"]),
                "employee_count": len(frame),
            })
        return comparison

    def team_comparison_plot(self, measure="revenue", you_label="You"):
        """
        Bar chart for one measure (a TEAM_MEASURES key): this employee, the team
        average and the best employee, in real units. The best bar is nameless.
        This one is built with Plotly's graph_objects (go) rather than Express, so
        each bar is added by hand. Returns None when there is nothing to compare.
        """
        row = next((r for r in self.team_comparison() if r["measure"] == measure), None)
        if row is None:
            return None

        names = [you_label, "Team average", "Best"]
        values = [row["you"], row["team_average"], row["best"]]
        is_money = row["kind"] == "money"
        text = [f"${v:,.0f}" if is_money else f"{v:,.0f}" for v in values]

        figure = go.Figure(go.Bar(
            x=names, y=values, text=text, textposition="outside", cliponaxis=False,
            marker_color=[CHART_COLORS[0], "#5f6b76", CHART_COLORS[2]],
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        ))
        figure.update_layout(
            title=f"{row['label']}: {you_label} compared with the team", height=340,
            yaxis_title="Revenue ($)" if is_money else row["label"],
        )
        figure.update_yaxes(range=[0, max(values) * 1.25])
        return figure_html(figure)

    # region [WHY] Assignment 3, Requirement 1 -- category mix vs. the team
    # The team side is ONE combined figure per category: every employee's
    # placed-order revenue added together. No colleague is ever split out,
    # and only percentages leave this method -- not the team's dollars --
    # so the page source carries nothing about any other employee. (The
    # provided breakdown chart answers a different question: this
    # employee's share of each category's total.)
    # endregion
    @staticmethod
    def _category_revenue(lines):
        """Revenue per category name for a queryset of order lines, as a Series (empty when there are none)."""
        rows = (
            lines.values(category_name=F("product__category__category_name"))
            .annotate(revenue=Sum(Supplier._line_revenue()))
        )
        frame = pd.DataFrame(list(rows))
        if frame.empty:
            return pd.Series(dtype=float)
        frame["category_name"] = frame["category_name"].fillna("Uncategorized")
        return frame.groupby("category_name")["revenue"].sum()

    def category_mix(self):
        """
        For each category: this employee's revenue in it as a percent of
        their OWN total revenue (you_pct), and that category's share of
        the whole team's combined revenue (team_pct). Each column adds up
        to 100. Sorted by the team's share, largest first, so the order is
        stable from one employee to the next. Returns [] when this employee
        has no placed orders. Only the employee's own dollars are returned
        (you_revenue, for the hover box); the team's dollars are not.
        """
        placed = OrderDetail.objects.filter(order__order_date__isnull=False, order__employee__isnull=False)
        team = self._category_revenue(placed)
        mine = self._category_revenue(placed.filter(order__employee=self))
        if mine.empty or mine.sum() <= 0 or team.empty:
            return []
        table = pd.DataFrame({"team": team}).join(pd.DataFrame({"you": mine}), how="left").fillna(0)
        table["team_pct"] = table["team"] / table["team"].sum() * 100
        table["you_pct"] = table["you"] / table["you"].sum() * 100
        table = table.sort_values("team_pct", ascending=False)
        return [
            {"category": name, "you_pct": row.you_pct, "team_pct": row.team_pct,
             "you_revenue": row.you, "diff": row.you_pct - row.team_pct}
            for name, row in table.iterrows()
        ]

    def category_mix_plot(self, you_label="You"):
        """
        Grouped bar chart of category_mix(): two bars per category -- this
        employee's percent of their own revenue, and the team's percent of
        its combined revenue -- in the same style as the team comparison
        chart. Both sets of bars add up to 100%. None when there is nothing
        to compare (an employee with no placed orders).
        """
        mix = self.category_mix()
        if not mix:
            return None
        names = [row["category"] for row in mix]
        figure = go.Figure()
        figure.add_bar(
            x=names, y=[r["you_pct"] for r in mix], name=you_label, marker_color=CHART_COLORS[0],
            text=[f"{r['you_pct']:.1f}%" for r in mix], textposition="outside", cliponaxis=False, textfont_size=10,
            customdata=[f"${r['you_revenue']:,.0f}" for r in mix],
            hovertemplate="%{x}<br>" + you_label + ": %{y:.1f}% of your revenue (%{customdata})<extra></extra>",
        )
        figure.add_bar(
            x=names, y=[r["team_pct"] for r in mix], name="Team", marker_color=TEAM_COLOR,
            text=[f"{r['team_pct']:.1f}%" for r in mix], textposition="outside", cliponaxis=False, textfont_size=10,
            hovertemplate="%{x}<br>Team: %{y:.1f}% of the team's combined revenue<extra></extra>",
        )
        top = max(max(r["you_pct"], r["team_pct"]) for r in mix)
        figure.update_layout(
            title="Category mix: you vs. the team", barmode="group", bargap=0.25,
            yaxis_title="Percent of revenue", height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        )
        figure.update_yaxes(range=[0, top * 1.25], ticksuffix="%")
        figure.update_xaxes(type="category")
        return figure_html(figure)

    # Stretch: a product only counts when it has some volume, so one tiny
    # order cannot make a product look "far above" or "far below".
    OUTLIER_MIN_ORDERS = 5
    OUTLIER_RATIO = 1.5

    def product_share_outliers(self, limit=5):
        """
        Requirement 1 stretch: products where this employee's share of the
        product's sales is well above or well below their share of company
        revenue overall. "Well" means at least OUTLIER_RATIO (1.5) times
        their overall share, or at most 1/1.5 of it, on products sold on at
        least OUTLIER_MIN_ORDERS orders. Returns {"overall": share %,
        "above": [...], "below": [...]}, each row a product name, this
        employee's share of its sales (%) and the gap in percentage points.
        Only shares are returned -- never a product's total or anyone
        else's figures. None when this employee has no placed orders.
        """
        placed = OrderDetail.objects.filter(order__order_date__isnull=False, order__employee__isnull=False)
        totals = pd.DataFrame(list(
            placed.values(product_name=F("product__product_name"))
            .annotate(revenue=Sum(Supplier._line_revenue()), orders=Count("order", distinct=True))
        ))
        mine = pd.DataFrame(list(
            placed.filter(order__employee=self)
            .values(product_name=F("product__product_name"))
            .annotate(mine=Sum(Supplier._line_revenue()))
        ))
        if totals.empty or mine.empty:
            return None
        overall = mine["mine"].sum() / totals["revenue"].sum() * 100
        table = totals.merge(mine, on="product_name", how="left").fillna({"mine": 0})
        table = table[(table["orders"] >= self.OUTLIER_MIN_ORDERS) & (table["revenue"] > 0)]
        table["share"] = table["mine"] / table["revenue"] * 100
        table["gap"] = table["share"] - overall
        above = table[table["share"] >= overall * self.OUTLIER_RATIO].sort_values("gap", ascending=False).head(limit)
        below = table[table["share"] <= overall / self.OUTLIER_RATIO].sort_values("gap").head(limit)

        def rows(part):
            return [{"product": r.product_name, "share": r.share, "gap": r.gap} for r in part.itertuples()]

        return {"overall": overall, "above": rows(above), "below": rows(below)}

    def leaderboard(self):
        """
        Every employee ranked by revenue, as a list of dicts for the
        manager-only leaderboard table: rank, name, orders, revenue,
        average_order, share, is_self (True on this page's employee).
        Names and dollars for every employee, so the view only calls
        this for a manager; everyone else gets team_comparison(), which
        shows averages and a nameless best instead of other people.
        """
        frame = self._performance_frame()
        if frame.empty:
            return []
        names = {e.employee_id: f"{e.first_name} {e.last_name}" for e in Employee.objects.all()}
        return [
            {
                "rank": int(row.revenue_rank),
                "name": names.get(row.employee_key, "Unknown"),
                "orders": row.orders,
                "revenue": row.revenue,
                "average_order": row.average_order,
                "share": row.share,
                "is_self": row.employee_key == self.employee_id,
            }
            for row in frame.itertuples()
        ]

    def customer_revenue_plot(self, top=10, kind="bar"):
        """
        Revenue on this employee's orders by customer, as kind="bar" (horizontal bars,
        largest at the top; the default), "column" (vertical bars, largest first) or
        "pie". top=10 keeps the ten biggest customers and top=None charts every
        customer; each bar is labeled with its dollars and the percentage of this
        employee's total revenue (all customers, not just the ones charted). A pie
        shows each customer's share, the largest ten at most plus the rest as "Other".
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        by_customer = (
            frame.groupby("customer_name", as_index=False)["revenue"].sum()
            .sort_values("revenue")
        )
        total = by_customer["revenue"].sum()
        if kind == "pie":
            slices = top_with_other(by_customer, "customer_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "customer_name", "revenue", "Share of revenue by customer",
                              color_names=frame["customer_name"])
        if top:
            by_customer = by_customer.tail(top)
        # Horizontal bars list the largest at the top; columns run largest first, left to right.
        horizontal = kind != "column"
        if not horizontal:
            by_customer = by_customer.iloc[::-1]
        text = [f"${row.revenue:,.0f} ({row.revenue / total * 100:.1f}%)" for row in by_customer.itertuples()]
        # Same sizing rule as revenue_breakdown_plot, so the two charts sharing a dashboard row match.
        per_bar = 32 if len(by_customer) <= 12 else 24
        return bar_figure(
            by_customer, "customer_name", "revenue",
            f"Top {top} customers by revenue" if top else "Revenue by customer",
            {"customer_name": "Customer", "revenue": "Revenue ($)"},
            color_names=frame["customer_name"], horizontal=horizontal,
            height=max(420, per_bar * len(by_customer) + 100) if horizontal else 420, trend=False, text=text,
        )

    # What the dashboard's "Revenue by" dropdown can group by: the key, the
    # singular word used in chart titles, and the OrderDetail field to group on.
    BREAKDOWNS = {
        "supplier": ("supplier", "product__supplier__company_name"),
        "product": ("product", "product__product_name"),
        "category": ("category", "product__category__category_name"),
    }

    def revenue_breakdown_plot(self, by="supplier", all_orders=False, top=None, kind="bar"):
        """
        Horizontal bar chart of revenue by supplier, product or category
        (by = "supplier", "product" or "category"), largest at the top. What it
        shows depends on who is looking (the view passes
        all_orders=viewer.is_manager):

        all_orders=True (a manager): each group's revenue across every placed
        order, labeled with its dollars and its percentage of all revenue.

        all_orders=False (anyone else): the share of each group's revenue that came
        from this employee's own orders, as a percentage. Only the percentage is
        charted, never the group's total, so an employee sees what they brought in
        without seeing what the group earns overall.

        top limits the chart to the largest N bars; None shows every group. Colors
        come from the full list of groups, so a group keeps its color whichever top
        is chosen. The rows are grouped in the database with values()/annotate().

        kind is "bar" (horizontal, the default), "column" (vertical) or "pie". A pie is
        for a manager only, because an employee's bars are shares of different totals
        that don't add up to a whole; it shows each group's share of all revenue, the
        largest ten at most plus the rest as "Other".
        """
        word, field = self.BREAKDOWNS[by]
        placed = OrderDetail.objects.filter(order__order_date__isnull=False)
        revenue = Sum(Supplier._line_revenue())

        def revenue_by_group(lines):
            rows = lines.values(group_name=F(field)).annotate(revenue=revenue)
            frame = pd.DataFrame(list(rows))
            if frame.empty:
                return frame
            frame["group_name"] = frame["group_name"].fillna(f"Unknown {word}")
            return frame.groupby("group_name", as_index=False)["revenue"].sum()

        totals = revenue_by_group(placed)
        if totals.empty:
            return None

        if all_orders:
            chart_data = totals.copy()
            chart_data["percent"] = chart_data["revenue"] / chart_data["revenue"].sum() * 100
            chart_data = chart_data.sort_values("revenue", ascending=False)
            value, title = "revenue", f"Revenue by {word} (all orders)"
            labels = {"group_name": word.capitalize(), "revenue": "Revenue ($)"}
        else:
            mine = revenue_by_group(placed.filter(order__employee=self))
            chart_data = totals.merge(mine, on="group_name", how="left", suffixes=("_all", "_mine"))
            chart_data["revenue_mine"] = chart_data["revenue_mine"].fillna(0)
            chart_data = chart_data[chart_data["revenue_all"] > 0]
            chart_data["share"] = chart_data["revenue_mine"] / chart_data["revenue_all"] * 100
            chart_data["percent"] = chart_data["share"]
            chart_data = chart_data.sort_values("share", ascending=False)
            value, title = "share", f"Your share of each {word}'s revenue (%)"
            labels = {"group_name": word.capitalize(), "share": f"Share of {word} revenue (%)"}

        if kind == "pie" and all_orders:
            slices = top_with_other(chart_data, "group_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "group_name", "revenue", f"Share of revenue by {word}",
                              color_names=totals["group_name"])

        if top:
            chart_data = chart_data.head(top)
            title = f"{title} -- top {top}"
        # Plotly draws the first horizontal bar at the bottom, so bars flip to put the largest
        # on top; columns already run largest first, left to right.
        horizontal = kind != "column"
        if horizontal:
            chart_data = chart_data.iloc[::-1]

        if all_orders:
            text = [f"${row.revenue:,.0f} ({row.percent:.1f}%)" for row in chart_data.itertuples()]
        else:
            text = [f"{row.percent:.1f}%" for row in chart_data.itertuples()]

        per_bar = 32 if len(chart_data) <= 12 else 24
        return bar_figure(
            chart_data, "group_name", value, title, labels,
            color_names=totals["group_name"], horizontal=horizontal,
            height=max(420, per_bar * len(chart_data) + 100) if horizontal else 420, trend=False, text=text,
        )

    @classmethod
    def authenticate(cls, employee_id, password):
        """
        Looks up the employee picked in the login form and checks their
        password: the 4-digit year of their own birth_date, as a string
        (e.g. birth_date of 1985-03-12 -> password "1985"). Returns the
        matching Employee on success, or None if the employee_id doesn't
        exist, has no birth_date on record, or the password is wrong.
        """
        employee = cls.objects.filter(pk=employee_id).first()
        if employee is None or employee.birth_date is None:
            return None
        if str(employee.birth_date.year) != password:
            return None
        return employee

    # region [WHY] Extra Credit 2 -- the employee's "Buy It Again" call list
    # The same numbers as the customer's card (buy_again_rows), for every
    # customer this employee handles. A customer is handled by the employee who
    # took their most recent placed order: one owner per customer, so two
    # employees never get the same call. Each customer's gaps come from that
    # customer's own orders. No other employee's customers are read, so nothing
    # about them can reach the page.
    # endregion
    def handled_customer_ids(self):
        """IDs of the customers whose most recent placed order this employee handled."""
        latest = {}
        placed = (
            Order.objects.filter(order_date__isnull=False, customer__isnull=False)
            .order_by("customer_id", "order_date", "order_id")
            .values_list("customer_id", "employee_id")
        )
        for customer_id, employee_id in placed:
            latest[customer_id] = employee_id  # ordered by date, so the last one wins
        return {customer_id for customer_id, employee_id in latest.items() if employee_id == self.employee_id}

    def buy_again_calls(self):
        """
        One row per overdue product across this employee's customers (see
        buy_again_rows), with customer_id and customer_name added, the most
        revenue at stake first. Also returns the number of customers handled.
        """
        customer_ids = self.handled_customer_ids()
        by_customer = buy_again_rows(
            OrderDetail.objects.filter(order__customer_id__in=customer_ids), data_horizon()
        )
        names = dict(Customer.objects.filter(pk__in=by_customer).values_list("customer_id", "company_name"))
        rows = [
            dict(row, customer_id=customer_id, customer_name=names.get(customer_id, customer_id))
            for customer_id, rows in by_customer.items()
            for row in rows
            if row["status"] == "Overdue"
        ]
        rows.sort(key=lambda row: (-row["at_stake"], row["customer_name"], row["name"]))
        return rows, len(customer_ids)

    class Meta:
        managed = False
        db_table = 'employees'


class OrderDetail(models.Model):
    """
    A single line item on an order (composite primary key: order_id + product_id).
    """
    # region [WARNING] order+product form the composite PK, not a separate id column
    # order and product below are ordinary FKs, but they're ALSO the two
    # columns making up this table's primary key (CompositePrimaryKey, not
    # a separate id column) - a product can only appear once per order.
    # endregion
    pk = models.CompositePrimaryKey('order_id', 'product_id')

    # FK to Order (order_detail.order.order_date, order.orderdetail_set.all()).
    # CASCADE: a line item is meaningless without its order.
    order = models.ForeignKey('Order', models.CASCADE)

    # FK to Product (order_detail.product.product_name, product.orderdetail_set.all()).
    # PROTECT: refuse to delete a product still on a historical order line.
    product = models.ForeignKey('Product', models.PROTECT)
    unit_price = models.FloatField()
    quantity = models.SmallIntegerField()
    discount = models.FloatField()

    @property
    def line_total(self):
        """
        This line's own revenue: unit_price times quantity, minus the
        discount fraction. A @property, not a field, since it's derived
        from the three fields above rather than stored -- Order.order_total
        sums this same property across every line instead of repeating
        the formula.
        """
        return self.unit_price * self.quantity * (1 - self.discount)

    class Meta:
        managed = False
        db_table = 'order_details'


class Order(models.Model):
    """
    A customer order. The customer/employee/shipper links are all nullable, so
    on_delete=SET_NULL keeps the order history intact even if one of those
    related records is later removed.
    """
    # region [WHY] AutoField only for order_id
    # SmallAutoField, unlike this app's other primary keys: order_id's
    # database column is backed by a real auto-incrementing sequence, so
    # the other models' IDs (category_id, etc.) aren't - they're fixed
    # reference IDs the database won't generate for you.
    # endregion
    order_id = models.SmallAutoField(primary_key=True)
    order_date = models.DateField(blank=True, null=True)
    required_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateField(blank=True, null=True)
    freight = models.FloatField(blank=True, null=True)
    ship_name = models.CharField(max_length=40, blank=True, null=True)
    ship_address = models.CharField(max_length=60, blank=True, null=True)
    ship_city = models.CharField(max_length=15, blank=True, null=True)
    ship_region = models.CharField(max_length=15, blank=True, null=True)
    ship_postal_code = models.CharField(max_length=10, blank=True, null=True)
    ship_country = models.CharField(max_length=15, blank=True, null=True)

    # FK to Customer (order.customer.company_name, customer.order_set.all()).
    customer = models.ForeignKey(Customer, models.SET_NULL, blank=True, null=True)

    # FK to Employee (order.employee.last_name, employee.order_set.all()).
    employee = models.ForeignKey(Employee, models.SET_NULL, blank=True, null=True)

    # FK to Shipper, stored in a column named ship_via (db_column below) --
    # that's the existing table's column name, not shipper_id.
    ship_via = models.ForeignKey('Shipper', models.SET_NULL, db_column='ship_via', blank=True, null=True)

    @property
    def order_total(self):
        """This order's total: every line item's line_total (OrderDetail.line_total) added together."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def formatted_ship_address(self):
        """This order's ship_* address fields joined into one line, blanks skipped."""
        parts = [self.ship_address, self.ship_city, self.ship_region, self.ship_postal_code, self.ship_country]
        return ", ".join(part for part in parts if part)

    class Meta:
        managed = False
        db_table = 'orders'


class Product(models.Model):
    """
    A DjangoTraders product. Supplier and category are both nullable, so removing
    either one just clears the link (SET_NULL) instead of touching the product.
    """
    product_id = models.SmallIntegerField(primary_key=True)
    product_name = models.CharField(max_length=40)
    quantity_per_unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price = models.FloatField(blank=True, null=True)
    units_in_stock = models.SmallIntegerField(blank=True, null=True)
    units_on_order = models.SmallIntegerField(blank=True, null=True)
    reorder_level = models.SmallIntegerField(blank=True, null=True)
    discontinued = models.IntegerField()
    date_discontinued = models.DateField(blank=True, null=True)

    # FK to Supplier (product.supplier.company_name, supplier.product_set.all()).
    supplier = models.ForeignKey('Supplier', models.SET_NULL, blank=True, null=True)

    # FK to Category (product.category.category_name, category.product_set.all()).
    category = models.ForeignKey(Category, models.SET_NULL, blank=True, null=True)

    @property
    def is_discontinued(self):
        """discontinued is a plain 1/0 column; this maps it to a real bool. A @property is computed on each access, so it needs no migration."""
        return bool(self.discontinued)

    @classmethod
    def search(cls, product_name="", category_id="", show_all=False):
        """
        Filters products by an optional name (case-insensitive substring) and
        category (exact, since it comes from a dropdown), for product_list's search
        form. Discontinued products are left out unless show_all is True; the
        filter uses the raw 1/0 column, because the database can't filter on the
        is_discontinued property.
        """
        queryset = cls.objects.order_by("product_name")
        if product_name:
            queryset = queryset.filter(product_name__icontains=product_name)

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if not show_all:
            queryset = queryset.filter(discontinued=0)

        return queryset

    @property
    def total_revenue(self):
        """Total revenue from this product: every line it appears on, each line_total added together (orderdetail_set is the reverse side of OrderDetail.product)."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def units_sold(self):
        """Total quantity of this product sold, across every order line it appears on."""
        return sum(line.quantity for line in self.orderdetail_set.all())

    class Meta:
        managed = False
        db_table = 'products'


class Shipper(models.Model):
    """A shipping carrier. No foreign keys."""
    shipper_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    phone = models.CharField(max_length=24, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'shippers'


class Supplier(models.Model):
    """A product supplier. No foreign keys."""
    supplier_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    homepage = models.TextField(blank=True, null=True)

    # region [WHY] a fixed shared password for suppliers
    # The suppliers table has no password column, and this app's tables are unmanaged,
    # so there is nowhere to store one per supplier. Every supplier logs in with this
    # one demo password. A real app would store a hashed password per supplier.
    # endregion
    SHARED_PASSWORD = "pass"

    @classmethod
    def authenticate(cls, supplier_id, password):
        """Checks a login: the supplier picked in the dropdown and the shared password. An unknown or non-numeric supplier_id is a failed login, not a crash."""
        try:
            supplier = cls.objects.filter(pk=int(supplier_id)).first()
        except (TypeError, ValueError):
            return None
        if supplier is None or password != cls.SHARED_PASSWORD:
            return None
        return supplier

    @property
    def formatted_address(self):
        """Address, city, region, postal_code, and country joined into one line (blank ones skipped)."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    def _placed_lines(self):
        """Every line on a placed order for one of this supplier's products (product__supplier=self follows OrderDetail -> Product -> Supplier in one query)."""
        return OrderDetail.objects.filter(
            product__supplier=self, order__order_date__isnull=False
        )

    @staticmethod
    def _line_revenue():
        """The database-side version of OrderDetail.line_total, for Sum(): unit_price * quantity * (1 - discount)."""
        return ExpressionWrapper(
            F("unit_price") * F("quantity") * (1 - F("discount")),
            output_field=FloatField(),
        )

    def summary(self):
        """Headline numbers for the Info tab: products, units sold, revenue, orders (revenue and units from placed orders only)."""
        totals = self._placed_lines().aggregate(
            units=Sum("quantity"),
            revenue=Sum(self._line_revenue()),
            orders=Count("order_id", distinct=True),
        )
        return {
            "product_count": self.product_set.count(),
            "units": totals["units"] or 0,
            "revenue": totals["revenue"] or 0,
            "orders": totals["orders"],
        }

    def order_history(self):
        """
        One row per placed order that includes at least one of this
        supplier's products, newest first: order_id, order_date, the
        customer's company name, how many of this supplier's products
        were on the order, and the units and revenue for those lines
        only -- never the rest of the order, which belongs to other
        suppliers too. values() picks the columns to group by and
        annotate() adds the per-group totals.
        """
        return (
            self._placed_lines()
            .values("order_id", "order__order_date", "order__customer__company_name")
            .annotate(
                products=Count("product_id", distinct=True),
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
            )
            .order_by("-order__order_date", "-order_id")
        )

    def product_revenue(self):
        """
        One row per product this supplier provides (including products
        with no sales yet, shown as zeros), largest revenue first:
        product_id, product_name, category_name, units, revenue, orders.
        """
        sales = {
            row["product_id"]: row
            for row in self._placed_lines()
            .values("product_id")
            .annotate(
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
                orders=Count("order_id", distinct=True),
            )
        }
        rows = []
        for product in self.product_set.select_related("category"):
            sold = sales.get(product.product_id, {})
            rows.append({
                "product_id": product.product_id,
                "product_name": product.product_name,
                "category_name": product.category.category_name if product.category else "—",
                "units": sold.get("units", 0),
                "revenue": sold.get("revenue", 0),
                "orders": sold.get("orders", 0),
            })
        return sorted(rows, key=lambda row: row["revenue"], reverse=True)

    # region [WHY] Assignment 3, Requirement 3 -- the supplier dashboard
    # Every chart starts from _placed_lines() (only this supplier's
    # products, only placed orders) turned into a DataFrame, the same
    # pipeline as the customer dashboard with a different filter. The one
    # method that looks at other suppliers, comparison(), returns only
    # this supplier's own figures, the average and the best as bare
    # numbers -- never a row, a name or an id.
    # endregion
    def _order_lines_frame(self):
        """This supplier's placed order lines as a DataFrame (lines_frame in charts.py), written like Customer._order_lines_frame."""
        return lines_frame(self._placed_lines())

    def order_years(self):
        """Years in which this supplier's products were on a placed order, newest first (for the year dropdowns)."""
        years = self._placed_lines().dates("order__order_date", "year")
        return sorted((d.year for d in years), reverse=True)

    def dashboard_summary(self):
        """
        The four summary cards: Total Revenue (with this year to date vs.
        the same period last year), Orders, Units Sold and Last Order. See
        _dashboard_summary. None when none of this supplier's products has
        been ordered.
        """
        return _dashboard_summary(self._order_lines_frame())

    def annual_plot(self):
        """
        Revenue by year with a dashed trend line (bar_figure's
        least-squares fit over the years, in order), so the line shows
        whether this supplier's yearly revenue is rising or falling.
        Hovering a bar shows its revenue and order count.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique")).reset_index()
        hover = [f"<b>{row.year}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}" for row in annual.itertuples()]
        annual["year"] = annual["year"].astype(str)
        return bar_figure(
            annual, "year", "revenue", "Revenue by year (dashed line = trend)",
            {"year": "Year", "revenue": "Revenue ($)"}, hover=hover,
        )

    def monthly_plot(self, year):
        """Revenue for each month of one year, all twelve months shown (zero for a month with no orders)."""
        return monthly_chart(self._order_lines_frame(), year, data_horizon())

    def category_plots(self, year=None):
        """Revenue by category and unit share by category, for one year or all (category_charts in charts.py)."""
        return category_charts(self._order_lines_frame(), year, _all_category_names())

    def top_products_plot(self, top=10, year=None):
        """This supplier's top products by revenue (top_products_chart in charts.py)."""
        return top_products_chart(self._order_lines_frame(), "revenue", top, year)

    def top_customers(self, top=10):
        """
        The customers who bought the most of this supplier's products, by
        revenue: company name, number of orders that included this
        supplier's products, revenue and that revenue's share of this
        supplier's total. Only this supplier's lines are counted, so
        nothing is shown about what else these customers buy. top=None
        returns every customer.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        table = (
            frame.groupby("customer_name", as_index=False)
            .agg(orders=("order_id", "nunique"), revenue=("revenue", "sum"))
            .sort_values(["revenue", "customer_name"], ascending=[False, True])
        )
        total = table["revenue"].sum()
        table["share"] = table["revenue"] / total * 100 if total else 0
        if top:
            table = table.head(top)
        return [
            {"rank": i, "customer": r.customer_name, "orders": int(r.orders), "revenue": r.revenue, "share": r.share}
            for i, r in enumerate(table.itertuples(), start=1)
        ]

    # What the comparison measures: label, column, kind (for formatting).
    COMPARISON_MEASURES = [
        ("Revenue", "revenue", "money"),
        ("Orders", "orders", "count"),
        ("Units sold", "units", "count"),
        ("Revenue per order", "revenue_per_order", "money"),
        ("Customers reached", "customers", "count"),
    ]

    def comparison(self, year=None):
        """
        This supplier against all suppliers with placed sales, on five
        measures: revenue, orders, units sold, revenue per order and
        customers reached. For each: you, average (the mean across all
        suppliers), best (the highest supplier's figure, nameless), rank
        and supplier_count, plus you_index/best_index as a percent of the
        average, so one chart can show dollars and counts together.

        The database groups every supplier's lines once; pandas then keeps
        only three numbers per measure. The best is taken with .max() on
        the column -- a number -- never by picking the best row, because a
        row would carry that supplier's id with it. Nothing about any other
        supplier is returned, so nothing about them reaches the page.
        year limits it to one year (None = all years). Returns [] when this
        supplier has no sales in that period.
        """
        placed = OrderDetail.objects.filter(order__order_date__isnull=False, product__supplier__isnull=False)
        if year:
            placed = placed.filter(order__order_date__year=year)
        rows = (
            placed.values(supplier_key=F("product__supplier_id"))
            .annotate(
                revenue=Sum(Supplier._line_revenue()),
                orders=Count("order", distinct=True),
                units=Sum("quantity"),
                customers=Count("order__customer", distinct=True),
            )
        )
        frame = pd.DataFrame(list(rows))
        if frame.empty or self.supplier_id not in set(frame["supplier_key"]):
            return []
        frame["revenue_per_order"] = frame["revenue"] / frame["orders"]
        mine = frame[frame["supplier_key"] == self.supplier_id].iloc[0]
        result = []
        for label, column, kind in self.COMPARISON_MEASURES:
            average = float(frame[column].mean())
            best = float(frame[column].max())
            you = float(mine[column])
            result.append({
                "label": label,
                "kind": kind,
                "you": you,
                "average": average,
                "best": best,
                "rank": int((frame[column] > you).sum()) + 1,
                "supplier_count": int(len(frame)),
                "you_index": you / average * 100 if average else 0,
                "best_index": best / average * 100 if average else 0,
            })
        return result

    def comparison_plot(self, year=None):
        """
        Grouped bar chart of comparison(): for each measure, this supplier,
        the average supplier (always 100%) and the best supplier
        (unnamed), as a percent of the average -- the same design as the
        employee team comparison chart. The hover box shows the real figure
        behind each bar. None when there is nothing to compare.
        """
        comparison = self.comparison(year)
        if not comparison:
            return None

        def show(row, key):
            return f"${row[key]:,.0f}" if row["kind"] == "money" else f"{row[key]:,.0f}"

        measures = [r["label"].replace(" ", "<br>", 1) if len(r["label"]) > 8 else r["label"] for r in comparison]
        series = [
            ("You", [r["you_index"] for r in comparison], [show(r, "you") for r in comparison], CHART_COLORS[0]),
            ("Average supplier", [100] * len(comparison), [show(r, "average") for r in comparison], TEAM_COLOR),
            ("Best supplier", [r["best_index"] for r in comparison], [show(r, "best") for r in comparison], CHART_COLORS[2]),
        ]
        figure = go.Figure()
        for name, indexes, actuals, color in series:
            figure.add_bar(
                x=measures, y=indexes, name=name, marker_color=color, customdata=actuals,
                text=[f"{v:.0f}%" if name != "Average supplier" else "" for v in indexes],
                textposition="outside", cliponaxis=False, textfont_size=11,
                hovertemplate="%{x}<br>" + name + ": %{customdata} (%{y:.0f}% of average)<extra></extra>",
            )
        when = f", {year}" if year else ""
        figure.update_layout(
            title=f"You vs. all suppliers{when}", barmode="group", bargap=0.25,
            yaxis_title="Percent of the average supplier", height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        )
        figure.update_yaxes(range=[0, max(max(r["best_index"], r["you_index"]) for r in comparison) * 1.2])
        return figure_html(figure)

    # region [WHY] Assignment 3, Requirement 4 -- S2 "Where do my sales come from?"
    # Revenue (or units, or orders) grouped by the ordering customer's
    # country. customer_country was added to _lines_frame for this; the
    # chart groups by country only and never shows a customer's name.
    # endregion
    COUNTRY_MEASURES = {
        "revenue": ("revenue", "Revenue ($)"),
        "units": ("quantity", "Units"),
        "orders": ("order_id", "Orders"),
    }

    def country_plot(self, measure="revenue", year=None):
        """
        Horizontal bar chart answering "Where do my sales come from?": one
        bar per customer country, largest on top, for revenue, units or
        orders (measure) in one year or all years. Each bar is labeled with
        its value and its share of the total, and its hover adds how many
        customers in that country bought (a count, never names). None when
        there are no sales in that year.
        """
        frame = filter_year(self._order_lines_frame(), year)
        if frame.empty:
            return None
        column, axis_label = self.COUNTRY_MEASURES[measure]
        agg = {"revenue": ("revenue", "sum"), "quantity": ("quantity", "sum"),
               "order_id": ("order_id", "nunique"), "customers": ("customer_name", "nunique")}
        table = frame.groupby("customer_country", as_index=False).agg(**agg)
        total = table[column].sum()
        table = table.sort_values([column, "customer_country"], ascending=[True, False])
        if column == "revenue":
            text = [f"${v:,.0f} ({v / total * 100:.1f}%)" for v in table[column]]
        else:
            text = [f"{v:,.0f} ({v / total * 100:.1f}%)" for v in table[column]]
        hover = [
            f"<b>{r.customer_country}</b><br>{label}<br>{r.customers} customer{'s' if r.customers != 1 else ''}"
            for r, label in zip(table.itertuples(), text)
        ]
        when = f"in {year}" if year else "all years"
        word = {"revenue": "revenue", "units": "units", "orders": "orders"}[measure]
        return bar_figure(
            table, "customer_country", column, f"Where my {word} came from, by customer country ({when})",
            {"customer_country": "Customer country", column: axis_label},
            horizontal=True, height=max(380, 26 * len(table) + 120), trend=False, text=text, hover=hover,
        )


    # region [WHY] Extra Credit 1 -- S3 "Is my year steady, or bunched into a few months?"
    # A heatmap: one row per year, one column per month, each cell colored
    # by that month's revenue (or units). Every month of every year is a
    # cell, so a missing month shows as an empty (zero) square rather than
    # disappearing. The "Show each year as % of its total" checkbox
    # rescales each row to percentages of that year, so a small year and a
    # big year can be read for SHAPE (steady vs. bunched) on the same scale.
    # endregion
    HEATMAP_MEASURES = {"revenue": ("revenue", "Revenue"), "units": ("quantity", "Units")}

    def seasonality_plot(self, measure="revenue", as_share=False):
        """
        Heatmap of this supplier's sales by month (columns) and year (rows),
        all twelve months always shown. measure is "revenue" or "units";
        as_share=True shows each cell as a percent of its year's total.
        Hover shows the month, the value and its share of the year. Below
        the chart, the template adds how many months it takes to reach half
        of the year (see seasonality_summary). None when there are no sales.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        column, word = self.HEATMAP_MEASURES[measure]
        grid = (
            frame.pivot_table(index="year", columns="month", values=column, aggfunc="sum", fill_value=0)
            .reindex(columns=range(1, 13), fill_value=0)
            .sort_index()
        )
        totals = grid.sum(axis=1).replace(0, np.nan)
        shares = grid.div(totals, axis=0).fillna(0) * 100
        values = shares if as_share else grid
        months = [calendar.month_abbr[m] for m in range(1, 13)]
        years = [str(y) for y in grid.index]
        money = column == "revenue"
        cell_text = [
            [(f"{shares.loc[y, m]:.0f}%" if as_share else (f"${grid.loc[y, m] / 1000:,.1f}k" if money else f"{grid.loc[y, m]:,.0f}"))
             if grid.loc[y, m] else "" for m in range(1, 13)]
            for y in grid.index
        ]
        hover = [
            [f"<b>{calendar.month_name[m]} {y}</b><br>{word}: " + (f"${grid.loc[y, m]:,.0f}" if money else f"{grid.loc[y, m]:,.0f}")
             + f"<br>{shares.loc[y, m]:.1f}% of {y}" for m in range(1, 13)]
            for y in grid.index
        ]
        figure = go.Figure(go.Heatmap(
            z=values.values.tolist(), x=months, y=years, text=cell_text, texttemplate="%{text}",
            customdata=hover, hovertemplate="%{customdata}<extra></extra>", xgap=3, ygap=3,
            colorscale=[[0, "#f5f5f0"], [0.35, "#c5d98a"], [1, "#556b2f"]], zmin=0,
            colorbar=dict(title="% of year" if as_share else word, ticksuffix="%" if as_share else ""),
        ))
        figure.update_layout(
            title=f"{word} by month and year" + (" (each year as % of its total)" if as_share else ""),
            height=150 + 70 * len(years), xaxis_title="Month", yaxis_title="Year",
        )
        figure.update_yaxes(type="category", autorange="reversed")
        figure.update_xaxes(type="category", side="bottom")
        return figure_html(figure)

    def seasonality_summary(self, measure="revenue"):
        """
        One line per year that puts the heatmap into words: how many of the
        year's best months it takes to reach half of that year's total, and
        the busiest month. 6 of 12 months means a steady year; 2 or 3 means
        sales are bunched. Years with no sales are left out.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        column, _ = self.HEATMAP_MEASURES[measure]
        rows = []
        for year, part in frame.groupby("year"):
            monthly = part.groupby("month")[column].sum().reindex(range(1, 13), fill_value=0)
            total = monthly.sum()
            if total <= 0:
                continue
            ordered = monthly.sort_values(ascending=False)
            months_to_half = int((ordered.cumsum() < total / 2).sum()) + 1
            active = int((monthly > 0).sum())
            rows.append({
                "year": int(year), "months_to_half": months_to_half, "active_months": active,
                "busiest": calendar.month_name[int(ordered.index[0])],
                "busiest_share": ordered.iloc[0] / total * 100,
            })
        return rows

    # region [WHY] Additional feature B -- "Do I need to restock?"
    # Not part of the assignment. For each of this supplier's products still
    # on sale: units in stock plus units already on order, divided by how many
    # units a month have been selling lately, gives "months of cover" -- how
    # long the stock lasts at the recent pace. The pace is measured over the
    # last 3, 6 or 12 months of order data (the control), ending at the last
    # day the data covers (data_horizon). Only this supplier's own products
    # and sales are used.
    # endregion
    STOCK_LOOKBACKS = (3, 6, 12)
    # Months of cover below which a product needs attention.
    REORDER_MONTHS = 1
    WATCH_MONTHS = 2

    def stock_cover(self, lookback=6):
        """
        One row per product this supplier still sells (not discontinued):
        in_stock, on_order, reorder_level, monthly_pace (average units sold per
        month over the last lookback months), cover (months the stock plus what
        is on order lasts at that pace; None with no recent sales) and status:
          "Reorder now" -- under REORDER_MONTHS of cover, or stock plus on-order
                           at or below the product's own reorder level;
          "Watch"       -- under WATCH_MONTHS of cover;
          "OK"          -- more than that;
          "No recent sales" -- nothing sold in the window, so no pace to divide by.
        Sorted with the most urgent first. Also returns the window's first and
        last dates. Returns {"rows": [], ...} when there are no such products.
        """
        horizon = data_horizon()
        start = (pd.Timestamp(horizon) - pd.DateOffset(months=lookback)).date()
        frame = self._order_lines_frame()
        sold = {}
        if not frame.empty:
            recent = frame[(frame["order_date"].dt.date > start) & (frame["order_date"].dt.date <= horizon)]
            sold = recent.groupby("product_name")["quantity"].sum().to_dict()

        order = {"Reorder now": 0, "Watch": 1, "OK": 2, "No recent sales": 3}
        rows = []
        for product in self.product_set.filter(discontinued=0).order_by("product_name"):
            in_stock = product.units_in_stock or 0
            on_order = product.units_on_order or 0
            reorder_level = product.reorder_level or 0
            pace = sold.get(product.product_name, 0) / lookback
            available = in_stock + on_order
            cover = available / pace if pace > 0 else None
            if cover is None:
                status = "No recent sales"
            elif cover < self.REORDER_MONTHS or (reorder_level > 0 and available <= reorder_level):
                status = "Reorder now"
            elif cover < self.WATCH_MONTHS:
                status = "Watch"
            else:
                status = "OK"
            rows.append({
                "product": product.product_name, "in_stock": in_stock, "on_order": on_order,
                "reorder_level": reorder_level, "monthly_pace": pace, "cover": cover, "status": status,
            })
        rows.sort(key=lambda r: (order[r["status"]], r["cover"] if r["cover"] is not None else 0, r["product"]))
        return {"rows": rows, "start": start, "end": horizon, "lookback": lookback}

    # Status colors for the stock chart; each bar's label also names its
    # status, so the color is never the only way to tell.
    STOCK_COLORS = {"Reorder now": "#c0392b", "Watch": "#d4a017", "OK": "#6b8e23", "No recent sales": "#9aa5b1"}
    # Bars longer than this are drawn at this length (their label says "12+").
    STOCK_CHART_CAP = 12

    def stock_cover_plot(self, lookback=6):
        """
        Horizontal bars of months of cover per product (stock_cover), most
        urgent at the top, colored and labeled by status, with dotted lines
        at REORDER_MONTHS and WATCH_MONTHS. Returns (chart HTML, the
        stock_cover dict); the chart is None when there are no products.
        """
        cover = self.stock_cover(lookback)
        rows = cover["rows"]
        if not rows:
            return None, cover
        drawn = list(reversed(rows))  # Plotly draws the first horizontal bar at the bottom.
        cap = self.STOCK_CHART_CAP
        lengths = [min(r["cover"], cap) if r["cover"] is not None else 0 for r in drawn]
        labels = []
        for r in drawn:
            if r["cover"] is None:
                labels.append("No recent sales")
            else:
                months = f"{cap}+ months" if r["cover"] > cap else f"{r['cover']:.1f} months"
                labels.append(f"{months} · {r['status']}")
        hover = [
            f"<b>{r['product']}</b><br>In stock: {r['in_stock']:,} · On order: {r['on_order']:,}"
            f"<br>Selling about {r['monthly_pace']:,.1f} a month<br>{label}"
            for r, label in zip(drawn, labels)
        ]
        figure = go.Figure(go.Bar(
            x=lengths, y=[r["product"] for r in drawn], orientation="h",
            marker_color=[self.STOCK_COLORS[r["status"]] for r in drawn],
            text=labels, textposition="outside", cliponaxis=False, textfont_size=11,
            customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        ))
        for months, label in ((self.REORDER_MONTHS, "1 month"), (self.WATCH_MONTHS, "2 months")):
            figure.add_vline(x=months, line_dash="dot", line_color="#888888",
                             annotation_text=label, annotation_position="top")
        figure.update_layout(
            title=f"Months of stock left at the last {lookback} months' sales pace",
            height=max(320, 34 * len(drawn) + 130), xaxis_title="Months of cover (stock + on order)",
            showlegend=False,
        )
        # Fit the axis to the longest bar (at least past the 2-month line), with room for the labels.
        longest = max(max(lengths), self.WATCH_MONTHS * 1.5)
        figure.update_xaxes(range=[0, longest * 1.6])
        figure.update_yaxes(type="category")
        return figure_html(figure), cover

    class Meta:
        managed = False
        db_table = 'suppliers'
    # region [WHY] Additional feature C -- the Price Changes tab, mirrored from the ALI Cost tab
    # The ALI App Central Cost tab (a separate project) lists one parent row per
    # cost record with its lines underneath, shows the current price dimmed above
    # the new one with a coloured percent change, a status pill, orange Yes flags
    # (Overlap, Lapsed), server-side filters and a primary/secondary sort, and a
    # server-built two-sheet Excel export. DjangoTraders has no cost records, but
    # every order line keeps the unit price the product sold at, so a product's
    # price history can be rebuilt from its lines: each run of orders at one
    # price is a "price period" (the child rows). Only this supplier's own
    # products and placed orders are used, like every other supplier view.
    # endregion
    PRICE_STATUSES = ("Raised", "Cut", "Unchanged", "No sales", "Discontinued")
    PRICE_SORTS = {
        "product": "Product", "category": "Category", "status": "Status",
        "price": "Latest Price", "change": "Change", "since": "Price Since",
        "last_sold": "Last Sold", "units": "Units Sold",
    }
    PRICE_FLAGS = {"any": "Any", "off_list": "Off list", "lapsed": "Lapsed"}
    LAPSED_MONTHS = 6

    def price_history(self):
        """
        One dict per product this supplier offers (discontinued ones included):
        product_id, name, category, quantity_per_unit, list_price (the price
        on the product today), discontinued, periods, previous_price,
        sold_price (the price on its latest period), change (latest period's
        price against the period before, as a fraction; None with fewer than
        two periods), since (when the latest price started), last_sold, units,
        orders, revenue, shown_price, status, off_list and lapsed.

        periods: one dict per run of consecutive placed orders at one unit
        price, oldest first -- price, start, end, orders, units, revenue (after
        discount), avg_discount and change (against the period before).

        status: Discontinued; No sales (never ordered); otherwise Raised, Cut
        or Unchanged from the latest change.
        off_list: Yes when the latest price sold differs from today's list price.
        lapsed:   Yes when nothing has sold in the LAPSED_MONTHS up to the
                  data horizon. Both are None (shown "-") with no sales,
                  like the Cost tab's flags when there is nothing to evaluate.
        """
        horizon = data_horizon()
        lapse_start = (pd.Timestamp(horizon) - pd.DateOffset(months=self.LAPSED_MONTHS)).date()
        lines = (
            OrderDetail.objects
            .filter(product__supplier=self, order__order_date__isnull=False)
            .values("product_id", "order_id", "order__order_date", "unit_price", "quantity", "discount")
            .order_by("product_id", "order__order_date", "order_id")
        )
        by_product = {}
        for line in lines:
            by_product.setdefault(line["product_id"], []).append(line)

        rows = []
        for product in self.product_set.select_related("category").order_by("product_name"):
            periods = []
            for line in by_product.get(product.product_id, []):
                price = round(float(line["unit_price"]), 2)
                if not periods or periods[-1]["price"] != price:
                    periods.append({"price": price, "start": line["order__order_date"], "end": None,
                                    "order_ids": set(), "units": 0, "revenue": 0.0, "gross": 0.0})
                period = periods[-1]
                period["end"] = line["order__order_date"]
                period["order_ids"].add(line["order_id"])
                period["units"] += line["quantity"]
                gross = price * line["quantity"]
                period["gross"] += gross
                period["revenue"] += gross * (1 - float(line["discount"] or 0))
            previous = None
            for period in periods:
                period["orders"] = len(period.pop("order_ids"))
                gross = period.pop("gross")
                period["avg_discount"] = round(1 - period["revenue"] / gross, 6) if gross else 0.0
                period["change"] = round((period["price"] - previous) / previous, 6) if previous else None
                # Percent versions for the template (it cannot multiply).
                period["change_pct"] = period["change"] * 100 if period["change"] is not None else None
                period["discount_pct"] = period["avg_discount"] * 100
                previous = period["price"]

            list_price = round(float(product.unit_price), 2) if product.unit_price is not None else None
            latest = periods[-1] if periods else None
            change = latest["change"] if latest else None
            if product.discontinued:
                status = "Discontinued"
            elif not periods:
                status = "No sales"
            elif change is None or change == 0:
                status = "Unchanged"
            else:
                status = "Raised" if change > 0 else "Cut"
            rows.append({
                "product_id": product.product_id,
                "name": product.product_name,
                "category": product.category.category_name if product.category else None,
                "quantity_per_unit": product.quantity_per_unit,
                "list_price": list_price,
                "discontinued": bool(product.discontinued),
                "periods": periods,
                "previous_price": periods[-2]["price"] if len(periods) > 1 else None,
                "sold_price": latest["price"] if latest else None,
                # The grid's "Latest Price": what it last sold at, or today's
                # list price for a product that has never sold.
                "shown_price": latest["price"] if latest else list_price,
                "change": change,
                "change_pct": change * 100 if change is not None else None,
                "since": latest["start"] if latest else None,
                "last_sold": latest["end"] if latest else None,
                "units": sum(p["units"] for p in periods),
                "orders": sum(p["orders"] for p in periods),
                "revenue": sum(p["revenue"] for p in periods),
                "status": status,
                "off_list": (latest["price"] != list_price) if latest and list_price is not None else None,
                "lapsed": (latest["end"] <= lapse_start) if latest else None,
            })
        return rows

    @classmethod
    def filter_and_sort_prices(cls, rows, search="", status="", flag="any", sort=None, sort2=None):
        """
        The Price Changes grid's server-side filters and sort, shared by the grid
        and its Excel export so the export always matches what is on screen.
        search: product name or number contains; status: one of PRICE_STATUSES
        or "" for all; flag: a PRICE_FLAGS key. sort / sort2 are (key, "asc" or
        "desc") or None. With no sort the default order is the Cost tab's:
        status priority, then the latest price change newest first.
        """
        search = search.strip().lower()
        if search:
            rows = [r for r in rows if search in r["name"].lower() or search == str(r["product_id"])]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if flag in ("off_list", "lapsed"):
            rows = [r for r in rows if r[flag]]

        priority = {name: i for i, name in enumerate(cls.PRICE_STATUSES)}

        def value(row, key):
            if key == "product":
                return row["name"].lower()
            if key == "category":
                return (row["category"] or "").lower()
            if key == "status":
                return priority[row["status"]]
            if key == "price":
                return row["shown_price"]
            return row[key]

        if not sort:
            rows = sorted(rows, key=lambda r: r["since"].toordinal() if r["since"] else 0, reverse=True)
            return sorted(rows, key=lambda r: priority[r["status"]])

        # Stable sorts: the secondary key first, then the primary. Blank values
        # always go last, whichever direction.
        for key, direction in [s for s in (sort2, sort) if s]:
            present = [r for r in rows if value(r, key) is not None]
            blank = [r for r in rows if value(r, key) is None]
            present.sort(key=lambda r: value(r, key), reverse=(direction == "desc"))
            rows = present + blank
        return rows
