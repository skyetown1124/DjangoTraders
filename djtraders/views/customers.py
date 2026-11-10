"""
Customer pages: the list, the detail page and its three tabs, edit / create /
deactivate, and the customer login.

A logged-in customer may only see and edit their own record (and build their own
cart); an employee may act on any customer's (see access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from django.contrib import messages

from ..forms import CustomerEditForm, OrderDetailForm
from ..models import BUY_AGAIN_MIN_ORDERS, BUY_AGAIN_OVERDUE_RATIO, BUY_AGAIN_TOP_CHOICES, Customer
from .access import (
    customer_access_denied,
    customer_dashboard_denied,
    customer_tab_denied,
    own_customer_redirect,
)
from .controls import BAD, read_choice, read_top, read_year


def customer_list(request):
    """
    The customer list, searchable by company name, contact name, contact title,
    city and country. The five search values come from GET parameters ("" when
    not submitted) and Customer.search (models.py) turns them into the filter.
    Choosing a country narrows the city dropdown to that country's cities.

    A logged-in customer is sent straight to their own page instead
    (own_customer_redirect); employees and visitors see the full list.
    """
    redirect_response = own_customer_redirect(request, customer_id=None)
    if redirect_response:
        return redirect_response

    search_company_name = request.GET.get("company_name", "")
    search_contact_name = request.GET.get("contact_name", "")
    search_contact_title = request.GET.get("contact_title", "")
    search_city = request.GET.get("city", "")
    search_country = request.GET.get("country", "")

    # The dropdowns list the distinct, non-blank values on record.
    # Cities are narrowed to the selected country, if there is one.
    cities_queryset = Customer.objects.exclude(city__isnull=True).exclude(city__exact="")
    if search_country:
        cities_queryset = cities_queryset.filter(country=search_country)
    cities = cities_queryset.order_by("city").values_list("city", flat=True).distinct()

    countries = (
        Customer.objects.exclude(country__isnull=True)
        .exclude(country__exact="")
        .order_by("country")
        .values_list("country", flat=True)
        .distinct()
    )

    contact_titles = (
        Customer.objects.exclude(contact_title__isnull=True)
        .exclude(contact_title__exact="")
        .order_by("contact_title")
        .values_list("contact_title", flat=True)
        .distinct()
    )

    # A city left over from a different country would match nothing, so drop it.
    if search_city and search_city not in cities:
        search_city = ""

    customers = Customer.search(
        company_name=search_company_name,
        contact_name=search_contact_name,
        contact_title=search_contact_title,
        city=search_city,
        country=search_country,
    )

    context = {
        "customers": customers,
        "cities": cities,
        "countries": countries,
        "contact_titles": contact_titles,
        "search_company_name": search_company_name,
        "search_contact_name": search_contact_name,
        "search_contact_title": search_contact_title,
        "search_city": search_city,
        "search_country": search_country,
    }
    return render(request, "djtraders/customers/customer_list.html", context)


def customer_detail(request, customer_id):
    """
    A customer's page shell: the header and a Dashboard / Customer Info / Order
    History tab control. customer_id comes from the URL (see urls.py). A
    logged-in customer is redirected to their own page if the URL asks for
    another; employees and visitors may view any customer.
    """
    redirect_response = own_customer_redirect(request, customer_id)
    if redirect_response:
        return redirect_response

    customer = get_object_or_404(Customer, pk=customer_id)

    # Only the shell is built here; each tab's content comes from one of the
    # tab views below, loaded by AJAX once the page is open.
    return render(request, "djtraders/customers/customer_detail.html", {"customer": customer})


def customer_edit(request, customer_id):
    """
    Edits a customer with CustomerEditForm (forms.py); customer_edit.html draws
    it with django-crispy-forms. Open to an employee, or to that customer's own
    login (customer_access_denied).
    """
    customer = get_object_or_404(Customer, pk=customer_id)

    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
    else:
        form = CustomerEditForm(instance=customer)

    # ?confirm_delete=1 (the Delete icon on the list) shows an in-page "are you
    # sure?" prompt instead of the form; its Confirm button posts to customer_delete.
    confirm_delete = request.GET.get("confirm_delete") == "1"

    context = {"customer": customer, "form": form, "confirm_delete": confirm_delete}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_create(request):
    """
    Creates a customer on the same page and form as customer_edit, for a Customer
    that is not in the database yet. Employees only. GET shows a blank form
    (new_customer=True, so the page says "New Customer"). A valid POST asks
    Customer.generate_customer_id (models.py) for a new ID built from the company
    name, saves once, and returns to the list.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=Customer())
        if form.is_valid():
            # The ID needs the validated company name, so it is made after validation.
            form.instance.customer_id = Customer.generate_customer_id(
                form.cleaned_data["company_name"]
            )
            form.save()
            return redirect("djtraders:customer_list")
    else:
        form = CustomerEditForm(instance=Customer())

    context = {"customer": form.instance, "form": form, "new_customer": True}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_delete(request, customer_id):
    """
    Marks a customer inactive (inactive_date = today) instead of deleting the
    row, which keeps their order history. Employees only, and POST only because
    it changes data.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=customer_id)
        customer.inactive_date = timezone.now().date()
        customer.save()

    return redirect("djtraders:customer_list")


# region [CONCEPT] the customer page's tabs are partial pages
# customer_detail renders only the shell. Each tab's content comes from a view
# below, fetched by AJAX (LoadPageTab in DjangoTraders.js) and returned as an
# HTML fragment with no base.html around it. A logged-in customer only gets
# their own tabs (another customer's gets a 403); employees and visitors may
# view any customer's.
# endregion
def customer_dashboard(request, customer_id):
    """
    Dashboard tab: the four summary tiles, revenue by year and by month (the
    provided charts), revenue and unit share by category, the top products by
    revenue and by units (Assignment 3, Requirement 2) and the "On pace with
    last year" card (additional feature A), or a message when there are no
    placed orders. Only the customer's own login or an employee may see it
    (customer_dashboard_denied).
    """
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    order_years = customer.order_years()
    category_revenue_plot, category_units_plot = customer.category_plots()
    top_revenue_plot, top_units_plot = customer.top_product_plots(top=10)
    pace_plot, pace = customer.pace_plot(order_years[0], "revenue") if order_years else (None, None)

    context = {
        "customer": customer,
        "summary": customer.dashboard_summary(),
        "annual_plot": customer.annual_orders_plot(),
        "order_years": order_years,
        "category_revenue_plot": category_revenue_plot,
        "category_units_plot": category_units_plot,
        "top_revenue_plot": top_revenue_plot,
        "top_units_plot": top_units_plot,
        "pace_plot": pace_plot,
        "pace": pace,
        "pace_measures": Customer.PACE_MEASURES,
        **_buy_again_context(customer, None),
    }
    return render(request, "djtraders/customers/_customer_dashboard.html", context)


def customer_monthly_chart(request, customer_id):
    """
    The dashboard's year dropdown: Customer.orders_placed_plot for ?year=, as
    just the chart HTML that fills #dashboard-monthly. The year comes from the
    browser, so it is checked: 400 unless it is one of this customer's order years.
    """
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponse("Choose a valid year.", status=400)
    if year not in customer.order_years():
        return HttpResponse("Choose a valid year.", status=400)
    plot = customer.orders_placed_plot(year)
    return HttpResponse(plot or "<p>No orders on record.</p>")


def customer_category_chart(request, customer_id):
    """
    The Revenue by Category card's Year dropdown (Requirement 2): both category
    charts for ?year= (one of the customer's order years, or "all"), as the
    card's chart fragment. A bad year gets a 400.
    """
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    year = read_year(request.GET.get("year", "all"), customer.order_years())
    if year is BAD:
        return HttpResponse("Choose a valid year.", status=400)
    revenue_plot, units_plot = customer.category_plots(year)
    return render(request, "djtraders/dashboards/_category_charts.html", {
        "revenue_plot": revenue_plot, "units_plot": units_plot,
    })


def customer_top_products_chart(request, customer_id):
    """
    The Top Products card's controls (Requirement 2): ?top= (5, 10 or all)
    and ?year= (one of the customer's order years, or "all"). Both charts, by
    revenue and by units, come back together so they always show the same
    products and period. A bad value gets a 400.
    """
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    top = read_top(request.GET.get("top", "10"))
    year = read_year(request.GET.get("year", "all"), customer.order_years())
    if top is BAD or year is BAD:
        return HttpResponse("Choose a valid number of products and year.", status=400)
    revenue_plot, units_plot = customer.top_product_plots(top=top, year=year)
    return render(request, "djtraders/dashboards/_top_products_charts.html", {
        "revenue_plot": revenue_plot, "units_plot": units_plot,
    })


def customer_pace_chart(request, customer_id):
    """
    Additional feature A's controls: ?measure= (revenue, units or orders) and
    ?year= (one of the customer's order years; no "all", since the chart
    compares one year with the year before). A bad value gets a 400.
    """
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    measure = read_choice(request.GET.get("measure", "revenue"), Customer.PACE_MEASURES)
    year = read_year(request.GET.get("year", ""), customer.order_years(), allow_all=False)
    if measure is BAD or year is BAD:
        return HttpResponse("Choose a valid measure and year.", status=400)
    pace_plot, pace = customer.pace_plot(year, measure)
    return render(request, "djtraders/customers/_customer_pace_body.html", {"pace_plot": pace_plot, "pace": pace})


def customer_info(request, customer_id):
    """
    Customer Info tab: the contact details and the Order Summary card, with its
    Start New Order button for an employee or the customer's own login.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    # order_set is the reverse accessor for this customer's orders. An order with
    # no order_date is a cart that was never committed, so it is left out.
    orders = customer.order_set.filter(order_date__isnull=False)
    total_quantity = sum(
        line.quantity for order in orders for line in order.orderdetail_set.all()
    )
    total_revenue = sum(order.order_total for order in orders)

    context = {
        "customer": customer,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "can_start_order": not customer_access_denied(request, customer.customer_id),
    }
    return render(request, "djtraders/customers/_customer_info.html", context)


def customer_orders(request, customer_id):
    """Order History tab: the customer's placed orders, newest first, in a DataTable."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = customer.order_set.filter(order_date__isnull=False).order_by("-order_date")
    return render(request, "djtraders/customers/_customer_orders.html", {
        "customer": customer,
        "orders": orders,
    })


def customer_login_view(request):
    """
    Customer login: pick a company from a dropdown (Customer.authenticate,
    models.py). On success customer_id goes into the session and the customer
    lands on their own page. Landing here first logs out whoever was logged in,
    so there is only ever one login at a time.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        customer_id = request.POST.get("customer_id", "")
        password = request.POST.get("password", "")
        customer = Customer.authenticate(customer_id, password)
        if customer is not None:
            request.session["customer_id"] = customer.customer_id
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
        error = "Incorrect customer/password combination."

    customers = Customer.objects.order_by("company_name")
    context = {"customers": customers, "error": error}
    return render(request, "djtraders/customers/customer_login.html", context)


def customer_logout_view(request):
    """Clears "customer_id" from the session and returns to the home page."""
    request.session.pop("customer_id", None)
    return redirect("djtraders:home")


# region [WHY] Extra Credit 2 -- the "Buy It Again" card
# The card lists this customer's overdue and due repeat products
# (Customer.buy_again, which uses buy_again_rows in models.py). Show Top reloads
# it by AJAX like the other cards. Beyond what Extra Credit 2 asks, each row has
# an Add to Order button: a real POST (it changes the session cart), so it is a
# small form rather than a link. It opens the same session cart order_create
# does and adds the line the way order_add_line does, with OrderDetailForm doing
# the checks (product still on sale, quantity at least 1 and within stock), then
# shows the cart. Nothing is written to the database until the order is placed.
# endregion
def _buy_again_context(customer, top):
    rows = customer.buy_again()
    flagged = [row for row in rows if row["status"] in ("Overdue", "Due")]
    overdue = [row for row in rows if row["status"] == "Overdue" and row["add_qty"] > 0]
    return {
        "buy_again_rows": flagged if top is None else flagged[:top],
        "buy_again_flagged": len(flagged),
        "buy_again_repeat": len(rows),
        "buy_again_overdue_count": len(overdue),
        "buy_again_min_orders": BUY_AGAIN_MIN_ORDERS,
        "buy_again_ratio": BUY_AGAIN_OVERDUE_RATIO,
        "buy_again_top_choices": BUY_AGAIN_TOP_CHOICES,
    }


def customer_buy_again_card(request, customer_id):
    """The Buy It Again card's body for ?top= (3, 5 or all)."""
    if customer_dashboard_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    top = read_top(request.GET.get("top", "all"), allowed=[value for value, _ in BUY_AGAIN_TOP_CHOICES])
    if top is BAD:
        return HttpResponse("Choose 3, 5 or All.", status=400)
    context = {"customer": customer, **_buy_again_context(customer, top)}
    return render(request, "djtraders/customers/_customer_buy_again_body.html", context)


def customer_buy_again_add(request, customer_id):
    """
    POST from an Add to Order button (product and quantity) or from Add All
    Overdue (all=overdue): puts the product(s) in this customer's session cart and opens the
    cart page. Each line is checked by OrderDetailForm; a line that fails is
    skipped with a message saying why, and the rest are still added. Adding a
    product already in the cart raises its quantity and keeps its discount.
    """
    if customer_access_denied(request, customer_id):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse("Use the Add to Order button.", status=405)
    customer = get_object_or_404(Customer, pk=customer_id)

    if request.POST.get("all") == "overdue":
        wanted = [(row["product_id"], row["add_qty"]) for row in customer.buy_again()
                  if row["status"] == "Overdue" and row["add_qty"] > 0]
    else:
        wanted = [(request.POST.get("product", ""), request.POST.get("quantity", ""))]
    if not wanted:
        messages.info(request, "Nothing is overdue right now, so nothing was added.")
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        cart = {"customer_id": customer_id, "lines": {}}
    employee_initiated = bool(request.session.get("current_user"))
    added = []
    for product_id, quantity in wanted:
        form = OrderDetailForm(
            {"product": product_id, "quantity": quantity, "discount_percent": 0},
            employee_initiated=employee_initiated,
        )
        if not form.is_valid():
            if "product" in form.errors:
                reason = "that product is no longer on sale."
            else:
                reason = " ".join(error for errors in form.errors.values() for error in errors)
            messages.warning(request, f"Not added: {reason}")
            continue
        product = form.cleaned_data["product"]
        key = str(product.product_id)
        existing = cart["lines"].get(key, {"quantity": 0, "discount": 0.0})
        # The form checks this quantity against stock; the cart may already hold
        # some of the same product, so check the total too.
        total = existing["quantity"] + form.cleaned_data["quantity"]
        if product.units_in_stock is not None and total > product.units_in_stock:
            messages.warning(
                request,
                f"Not added: only {product.units_in_stock} of {product.product_name} in stock, "
                f"and your cart already has {existing['quantity']}.",
            )
            continue
        cart["lines"][key] = {
            "quantity": existing["quantity"] + form.cleaned_data["quantity"],
            "discount": existing["discount"],
        }
        added.append(f"{form.cleaned_data['quantity']} x {product.product_name}")
    request.session["cart"] = cart
    request.session.modified = True
    if added:
        messages.success(request, "Added to your cart from Buy It Again: " + ", ".join(added) + ".")
    return redirect("djtraders:order_build", customer_id=customer_id)
