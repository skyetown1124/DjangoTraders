"""
Supplier pages: the page shell, its tabs (Info, Order History, Product
Revenue, and the Dashboard added in Assignment 3) and the supplier login. A
supplier sees only their own page; employees may open any (see
supplier_access_denied in access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .. import price_export
from ..models import Supplier
from .access import supplier_access_denied
from .controls import BAD, read_choice, read_top, read_year


def supplier_login_view(request):
    """
    Supplier login: pick a company from a dropdown and enter the shared password
    (Supplier.authenticate, models.py). On success supplier_id goes into the
    session and the supplier lands on their own page. Like the other logins, it
    first logs out whoever was logged in.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        supplier = Supplier.authenticate(
            request.POST.get("supplier_id", ""), request.POST.get("password", "")
        )
        if supplier is not None:
            request.session["supplier_id"] = supplier.supplier_id
            return redirect("djtraders:supplier_detail", supplier_id=supplier.supplier_id)
        error = "Incorrect supplier/password combination."

    suppliers = Supplier.objects.order_by("company_name")
    return render(request, "djtraders/suppliers/supplier_login.html", {"suppliers": suppliers, "error": error})


def supplier_logout_view(request):
    """Clears "supplier_id" from the session and returns to the home page."""
    request.session.pop("supplier_id", None)
    return redirect("djtraders:home")


def supplier_detail(request, supplier_id):
    """
    The supplier page shell: a header and a tab control (Info, Order History,
    Product Revenue), each tab a partial loaded by AJAX like the customer page.
    A visitor goes to the supplier login; a supplier asking for another
    supplier's page is sent back to their own.
    """
    logged_in_supplier_id = request.session.get("supplier_id")
    if logged_in_supplier_id and logged_in_supplier_id != supplier_id:
        return redirect("djtraders:supplier_detail", supplier_id=logged_in_supplier_id)
    if supplier_access_denied(request, supplier_id):
        return redirect("djtraders:supplier_login")
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/supplier_detail.html", {"supplier": supplier})


def supplier_info(request, supplier_id):
    """Info tab: contact details and headline numbers."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_info.html", {
        "supplier": supplier,
        "summary": supplier.summary(),
    })


def supplier_orders(request, supplier_id):
    """Order History tab: placed orders that include this supplier's products."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_orders.html", {
        "supplier": supplier,
        "orders": supplier.order_history(),
    })


def supplier_products(request, supplier_id):
    """Product Revenue tab: a table of units and revenue per product."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_products.html", {
        "supplier": supplier,
        "rows": supplier.product_revenue(),
    })


# region [WHY] Assignment 3, Requirements 3 and 4 and Extra Credit 1 -- the Dashboard tab
# One view for the tab and one for each control, written like the provided
# tabs: supplier_access_denied first (the supplier comes from the session; any
# other supplier gets a 403), then each value from the browser is checked
# against the choices its control offers (a 400 for anything else), then a
# Supplier method draws the chart. Every method starts from this supplier's own
# placed order lines.
# endregion
def supplier_dashboard(request, supplier_id):
    """
    Dashboard tab: summary tiles, revenue by year (trend line) and by month,
    revenue and unit share by category, top products, top customers, the
    comparison with all suppliers, the Requirement 4 country chart, the Extra
    Credit 1 heatmap and the stock cover card (additional feature B).
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    order_years = supplier.order_years()
    category_revenue_plot, category_units_plot = supplier.category_plots()
    stock_plot, stock = supplier.stock_cover_plot(6)
    return render(request, "djtraders/suppliers/_supplier_dashboard.html", {
        "supplier": supplier,
        "summary": supplier.dashboard_summary(),
        "order_years": order_years,
        "annual_plot": supplier.annual_plot(),
        "monthly_plot": supplier.monthly_plot(order_years[0]) if order_years else None,
        "category_revenue_plot": category_revenue_plot,
        "category_units_plot": category_units_plot,
        "top_products_plot": supplier.top_products_plot(top=10),
        "top_customers": supplier.top_customers(10),
        "comparison": supplier.comparison(),
        "comparison_plot": supplier.comparison_plot(),
        "country_plot": supplier.country_plot("revenue"),
        "seasonality_plot": supplier.seasonality_plot("revenue", False),
        "seasonality_summary": supplier.seasonality_summary("revenue"),
        "stock_plot": stock_plot,
        "stock": stock,
        "stock_lookbacks": Supplier.STOCK_LOOKBACKS,
    })


def supplier_monthly_chart(request, supplier_id):
    """Revenue by Month card's Year dropdown: ?year= must be one of the supplier's order years (400 otherwise)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    year = read_year(request.GET.get("year", ""), supplier.order_years(), allow_all=False)
    if year is BAD:
        return HttpResponse("Choose a valid year.", status=400)
    return HttpResponse(supplier.monthly_plot(year) or "<p>No orders in this year.</p>")


def supplier_category_chart(request, supplier_id):
    """Revenue by Category card's Year dropdown: ?year= is one of the supplier's order years or "all"."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    year = read_year(request.GET.get("year", "all"), supplier.order_years())
    if year is BAD:
        return HttpResponse("Choose a valid year.", status=400)
    revenue_plot, units_plot = supplier.category_plots(year)
    return render(request, "djtraders/dashboards/_category_charts.html", {
        "revenue_plot": revenue_plot, "units_plot": units_plot,
    })


def supplier_top_products_chart(request, supplier_id):
    """Top Products card: ?top= (5, 10 or all) and ?year= (an order year or "all")."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    top = read_top(request.GET.get("top", "10"), allowed=("5", "10", "all"))
    year = read_year(request.GET.get("year", "all"), supplier.order_years())
    if top is BAD or year is BAD:
        return HttpResponse("Choose a valid number of products and year.", status=400)
    return HttpResponse(supplier.top_products_plot(top=top, year=year) or "<p>No sales in this year.</p>")


def supplier_comparison_chart(request, supplier_id):
    """Comparison card's Year dropdown: the chart and table for ?year= (an order year or "all")."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    year = read_year(request.GET.get("year", "all"), supplier.order_years())
    if year is BAD:
        return HttpResponse("Choose a valid year.", status=400)
    return render(request, "djtraders/suppliers/_supplier_comparison_body.html", {
        "comparison": supplier.comparison(year),
        "comparison_plot": supplier.comparison_plot(year),
    })


def supplier_country_chart(request, supplier_id):
    """Requirement 4 (S2): ?measure= (revenue, units or orders) and ?year= (an order year or "all")."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    measure = read_choice(request.GET.get("measure", "revenue"), Supplier.COUNTRY_MEASURES)
    year = read_year(request.GET.get("year", "all"), supplier.order_years())
    if measure is BAD or year is BAD:
        return HttpResponse("Choose a valid measure and year.", status=400)
    return HttpResponse(supplier.country_plot(measure, year) or "<p>No sales in this year.</p>")


def supplier_seasonality_chart(request, supplier_id):
    """Extra Credit 1 (S3): ?measure= (revenue or units) and the ?share= checkbox (on or off)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    measure = read_choice(request.GET.get("measure", "revenue"), Supplier.HEATMAP_MEASURES)
    share = read_choice(request.GET.get("share", "off"), ("on", "off"))
    if measure is BAD or share is BAD:
        return HttpResponse("Choose a valid measure.", status=400)
    return render(request, "djtraders/suppliers/_supplier_seasonality_body.html", {
        "seasonality_plot": supplier.seasonality_plot(measure, share == "on"),
        "seasonality_summary": supplier.seasonality_summary(measure),
    })


def supplier_stock_chart(request, supplier_id):
    """Additional feature B: ?lookback= (3, 6 or 12 months of sales to measure the pace over)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    lookback = read_choice(request.GET.get("lookback", "6"), [str(n) for n in Supplier.STOCK_LOOKBACKS])
    if lookback is BAD:
        return HttpResponse("Choose a valid number of months.", status=400)
    stock_plot, stock = supplier.stock_cover_plot(int(lookback))
    return render(request, "djtraders/suppliers/_supplier_stock_cover_body.html", {"stock_plot": stock_plot, "stock": stock})


# region [WHY] Additional feature C -- the Price Changes tab (mirrors the ALI Cost tab)
# The tab, its grid (reloaded by AJAX whenever a filter or sort changes) and
# its Excel export all read the same query string through read_price_query, so
# the server does the filtering and sorting once and the export always holds
# exactly the rows on screen. Every value is checked against the choices the
# grid offers; anything else gets a 400, like the dashboard controls.
# endregion
PRICE_SEARCH_MAX = 40


def read_price_query(params):
    """
    The grid's search (q), status, flag, sort and sort2 from a query string,
    as keyword arguments for Supplier.filter_and_sort_prices, or BAD.
    A sort is "key:asc" or "key:desc" with key one of Supplier.PRICE_SORTS.
    """
    search = params.get("q", "")
    if len(search) > PRICE_SEARCH_MAX:
        return BAD
    status = params.get("status", "")
    if status and read_choice(status, Supplier.PRICE_STATUSES) is BAD:
        return BAD
    flag = read_choice(params.get("flag", "any"), Supplier.PRICE_FLAGS)
    if flag is BAD:
        return BAD
    sorts = []
    for name in ("sort", "sort2"):
        value = params.get(name, "")
        if not value:
            sorts.append(None)
            continue
        key, _, direction = value.partition(":")
        if key not in Supplier.PRICE_SORTS or direction not in ("asc", "desc"):
            return BAD
        sorts.append((key, direction))
    if sorts[1] and not sorts[0]:
        return BAD
    return {"search": search, "status": status, "flag": flag, "sort": sorts[0], "sort2": sorts[1]}


def _price_context(supplier, query):
    rows = Supplier.filter_and_sort_prices(supplier.price_history(), **query)
    return {
        "supplier": supplier,
        "rows": rows,
        "query": query,
        "sorts": {key: (n, direction) for n, s in enumerate((query["sort"], query["sort2"]), 1)
                  if s for key, direction in [s]},
        "sort_columns": Supplier.PRICE_SORTS,
        "lapsed_months": Supplier.LAPSED_MONTHS,
    }


def supplier_prices(request, supplier_id):
    """Price Changes tab: toolbar, filters and the grid in its default order."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    context = _price_context(supplier, read_price_query({}))
    context.update({"statuses": Supplier.PRICE_STATUSES, "flags": Supplier.PRICE_FLAGS})
    return render(request, "djtraders/suppliers/_supplier_prices.html", context)


def supplier_prices_grid(request, supplier_id):
    """The grid alone, for ?q=&status=&flag=&sort=&sort2= (see read_price_query)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    query = read_price_query(request.GET)
    if query is BAD:
        return HttpResponse("Choose a valid filter or sort.", status=400)
    return render(request, "djtraders/suppliers/_supplier_prices_grid.html", _price_context(supplier, query))


def supplier_prices_export(request, supplier_id):
    """
    Export to Excel: built on the server from the same query as the grid, so it
    holds every row on screen in the same order, with each product's price
    periods on a second sheet (see price_export.py).
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    query = read_price_query(request.GET)
    if query is BAD:
        return HttpResponse("Choose a valid filter or sort.", status=400)
    rows = Supplier.filter_and_sort_prices(supplier.price_history(), **query)
    content, filename = price_export.build_workbook(supplier, rows)
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
