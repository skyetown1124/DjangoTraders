"""
Employee pages: the page shell and its three tabs (Dashboard, Employee Info,
Employees), the AJAX charts behind the dashboard's controls, and the employee
login.

An employee sees only their own page; a manager (see access.py) may open any
employee's page and sees the Employees tab.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import BUY_AGAIN_MIN_ORDERS, BUY_AGAIN_OVERDUE_RATIO, BUY_AGAIN_TOP_CHOICES, Employee
from .access import employee_access_denied
from .controls import BAD, read_top


def _you_label(request, employee):
    """"You" when the viewer is looking at their own page, otherwise the employee's first name."""
    viewer_id = request.session["current_user"]
    return "You" if viewer_id == employee.employee_id else employee.first_name


def login_view(request):
    """
    Employee login: pick a name from a dropdown and enter the 4-digit year of
    that employee's birth_date as the password (Employee.authenticate,
    models.py). On success employee_id goes into the session under
    "current_user" -- Django's session framework remembers it across requests
    without django.contrib.auth -- and the employee lands on their own page.
    Landing here first logs out whoever was logged in, so there is only ever one
    login at a time.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        employee_id = request.POST.get("employee_id", "")
        password = request.POST.get("password", "")
        employee = Employee.authenticate(employee_id, password)
        if employee is not None:
            request.session["current_user"] = employee.employee_id
            return redirect("djtraders:employee_detail", employee_id=employee.employee_id)
        error = "Incorrect employee/password combination."

    employees = Employee.objects.order_by("last_name", "first_name")
    context = {"employees": employees, "error": error}
    return render(request, "djtraders/login.html", context)


def logout_view(request):
    """Clears "current_user" from the session and returns to the home page."""
    request.session.pop("current_user", None)
    return redirect("djtraders:home")


def employee_detail(request, employee_id):
    """
    The employee page shell: a header with quick links to Customers and Products,
    and a tab control (Dashboard, Employee Info and, for a manager, Employees).
    Each tab is a partial loaded by AJAX, the same pattern as the customer and
    supplier pages. A visitor who is not an employee goes to the employee login;
    an employee asking for someone else's page goes back to their own, unless
    they are a manager.
    """
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return redirect("djtraders:login")
    if employee_access_denied(request, employee_id):
        return redirect("djtraders:employee_detail", employee_id=viewer_id)

    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/employee_detail.html", {"employee": employee})


def employee_dashboard(request, employee_id):
    """
    Dashboard tab, for the orders this employee handled: the rank tiles, a team
    comparison chart and table, revenue over time (by year or month, with a Details
    modal per period), revenue by customer, and a revenue breakdown by supplier,
    product or category. A manager also gets a leaderboard naming every employee,
    and sees every group's revenue in the breakdown; anyone else sees their own
    share of each group (Employee.revenue_breakdown_plot).
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    you_label = _you_label(request, employee)
    return render(request, "djtraders/employees/_employee_dashboard.html", {
        "employee": employee,
        "viewer_is_manager": viewer.is_manager,
        "performance": employee.performance(),
        "you_label": you_label,
        "comparison": employee.team_comparison(),
        "team_measures": Employee.TEAM_MEASURES,
        "comparison_plot": employee.team_comparison_plot("revenue", you_label),
        "leaderboard": employee.leaderboard() if viewer.is_manager else [],
        "revenue_plot": employee.revenue_over_time(),
        "revenue_years": employee.revenue_years(),
        "customer_plot": employee.customer_revenue_plot(top=10),
        "breakdown_plot": employee.revenue_breakdown_plot("supplier", all_orders=viewer.is_manager, top=10),
        # Assignment 3, Requirement 1: the category mix against the team, and the stretch table.
        "category_mix_plot": employee.category_mix_plot(you_label),
        "share_outliers": employee.product_share_outliers(),
        # Extra Credit 2: overdue repeat products across the customers this employee handles.
        **_buy_again_calls_context(employee, None),
    })


def employee_customer_chart(request, employee_id):
    """
    The top-customers chart for ?top= (5, 10 or all) and ?kind= (bar, column or pie), as
    just the chart HTML. Both values are checked against fixed lists. It covers this
    employee's own customers, as in employee_dashboard.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    top = request.GET.get("top", "10")
    kind = request.GET.get("kind", "bar")
    if top not in ("5", "10", "all") or kind not in ("bar", "column", "pie"):
        return HttpResponse("Choose a valid top and chart.", status=400)
    plot = employee.customer_revenue_plot(top=None if top == "all" else int(top), kind=kind)
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_team_chart(request, employee_id):
    """
    The team comparison chart for ?measure= (revenue, orders or customers), as
    just the chart HTML. The value is checked against Employee.TEAM_MEASURES.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    measure = request.GET.get("measure", "revenue")
    if measure not in Employee.TEAM_MEASURES:
        return HttpResponse("Choose a valid measure.", status=400)
    plot = employee.team_comparison_plot(measure, _you_label(request, employee))
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_breakdown_chart(request, employee_id):
    """
    The revenue breakdown for ?by= (supplier, product or category), ?top= (5, 10 or
    all) and ?kind= (bar, column or pie), as just the chart HTML. All three are checked
    against fixed lists, and who is asking decides what the chart shows, as in
    employee_dashboard; only a manager gets a pie.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    by = request.GET.get("by", "supplier")
    top = request.GET.get("top", "10")
    kind = request.GET.get("kind", "bar")
    if by not in Employee.BREAKDOWNS or top not in ("5", "10", "all") or kind not in ("bar", "column", "pie"):
        return HttpResponse("Choose a valid breakdown, top and chart.", status=400)
    plot = employee.revenue_breakdown_plot(
        by, all_orders=viewer.is_manager, top=None if top == "all" else int(top), kind=kind
    )
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_revenue_chart(request, employee_id):
    """
    The revenue-over-time chart and table for ?level= ("year" or "month") and
    ?year= ("all" or a year this employee has orders in), as the fragment that
    fills #dashboard-revenue. Both values are checked, and the year is ignored at
    the year level.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)

    employee = get_object_or_404(Employee, pk=employee_id)
    level = request.GET.get("level", "year")
    year = request.GET.get("year", "all")
    years = employee.revenue_years()

    if level not in ("year", "month") or (year != "all" and not (year.isdigit() and int(year) in years)):
        return HttpResponse("Choose a valid level and year.", status=400)

    plot = employee.revenue_over_time(level, None if year == "all" else int(year))
    return render(request, "djtraders/employees/_employee_revenue_chart.html", {
        "revenue_plot": plot,
    })


def employee_period_detail(request, employee_id):
    """
    The Details modal for one period of the revenue table: ?period= is "1997" or
    "1997-03", checked against the years this employee has orders in (and months
    01 to 12). Returns just the modal's contents.
    """
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    period = request.GET.get("period", "")
    year, _, month = period.partition("-")
    valid_year = year.isdigit() and len(year) == 4 and int(year) in employee.revenue_years()
    valid_month = month == "" or (month.isdigit() and len(month) == 2 and 1 <= int(month) <= 12)
    if not (valid_year and valid_month):
        return HttpResponse("Choose a valid period.", status=400)
    return render(request, "djtraders/employees/_employee_period_detail.html", {
        "detail": employee.period_detail(period),
    })


def employee_info(request, employee_id):
    """Employee Info tab: title, manager, hire date, phone, address."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/_employee_info.html", {"employee": employee})


def employee_list(request, employee_id):
    """Employees tab: every employee, linked to their page. Managers only."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    viewer = Employee.objects.filter(pk=request.session.get("current_user")).first()
    if viewer is None or not viewer.is_manager:
        return HttpResponse(status=403)
    employees = Employee.objects.select_related("reports_to").order_by("last_name", "first_name")
    return render(request, "djtraders/employees/_employee_list.html", {"employees": employees})


# region [WHY] Extra Credit 2 -- the employee's "Buy It Again" call list
# The table lists the overdue repeat products of the customers this employee
# handles (Employee.buy_again_calls), the most revenue at stake first. Show Top
# reloads it by AJAX. employee_access_denied is the same check as the rest of
# the dashboard: an employee sees their own list (a manager may open any
# employee's page, as with every other card), and no one else's customers are
# ever read for it.
# endregion
def _buy_again_calls_context(employee, top):
    rows, customers = employee.buy_again_calls()
    return {
        "calls": rows if top is None else rows[:top],
        "calls_total": len(rows),
        "calls_customers": customers,
        "calls_at_stake": sum(row["at_stake"] for row in rows),
        "calls_shown_at_stake": sum(row["at_stake"] for row in (rows if top is None else rows[:top])),
        "buy_again_min_orders": BUY_AGAIN_MIN_ORDERS,
        "buy_again_ratio": BUY_AGAIN_OVERDUE_RATIO,
        "buy_again_top_choices": BUY_AGAIN_TOP_CHOICES,
    }


def employee_buy_again_chart(request, employee_id):
    """The call list's body for ?top= (3, 5 or all)."""
    if employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    top = read_top(request.GET.get("top", "all"), allowed=[value for value, _ in BUY_AGAIN_TOP_CHOICES])
    if top is BAD:
        return HttpResponse("Choose 3, 5 or All.", status=400)
    context = {"employee": employee, **_buy_again_calls_context(employee, top)}
    return render(request, "djtraders/employees/_employee_buy_again_body.html", context)
