/**
 * Project-wide custom JavaScript. base.html loads it after jQuery,
 * DataTables and jQuery UI, so everything here can rely on all three.
 * It holds what more than one kind of page uses, plus the supplier page's
 * table; the other entities' functions live in customers.js, employees.js
 * and orders.js.
 *
 *   MakeListDataTable, MakeOrdersDataTable, MakeProductRevenueDataTable - DataTables
 *   ActivatePageTabs, LoadPageTab          - load each tab's content by AJAX
 *   ActivateChartControls, ShortErrorText  - the customer and supplier dashboard
 *                                            controls (Assignment 3)
 *   ActivateThemeToggle and helpers        - the light/dark toggle (dark mode)
 */

// #region DataTables

/**
 * Customer and product lists: 20 rows per page, search box top right,
 * page-size menu bottom left, and no sorting on the last (Actions)
 * column, which holds icons, not data.
 * @param {string} tableId - selector for the table, e.g. "#customer-table"
 */
function MakeListDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        columnDefs: [{ targets: -1, orderable: false }],
        layout: {
            topStart: "info",
            topEnd: "search",
            bottomStart: "pageLength",
            bottomEnd: "paging"
        }
    });
}

/**
 * Any table of orders (a customer's, a product's, a supplier's), newest
 * first. Column 1 is Order Date; DataTables' own default sorts column 0 ascending.
 * @param {string} tableId - selector for the table
 */
function MakeOrdersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[1, "desc"]]
    });
}

/**
 * A supplier's product revenue, biggest earners first (column 4).
 * @param {string} tableId - selector for the table
 */
function MakeProductRevenueDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[4, "desc"]]
    });
}

// #endregion

// #region Page tabs

/**
 * Wires up a Bootstrap tab control. Each tab's content is a partial
 * template fetched from the tab button's data-url and put into its pane,
 * the first time that tab is shown (see LoadPageTab).
 * @param {string} tabsSelector - selector for the tab list, e.g. "#employee-tabs"
 */
function ActivatePageTabs(tabsSelector) {
    const $tabs = $(tabsSelector);

    // Bootstrap fires shown.bs.tab on the button that just became active.
    $tabs.on("shown.bs.tab", "button[data-bs-toggle='tab']", function () {
        LoadPageTab($(this));
    });

    // The first tab is already active, so no event fires for it; load it directly.
    LoadPageTab($tabs.find("button.active"));
}

/**
 * Loads one tab's content (once), then switches on whatever it contains:
 * a DataTable for each known table id, and each dashboard control.
 * jQuery's .html() also runs the <script> inside each Plotly chart, which draws it.
 * @param {jQuery} $tabButton - the tab button that was shown
 */
function LoadPageTab($tabButton) {
    const $pane = $($tabButton.data("bs-target"));

    if ($pane.data("loaded")) {
        return;
    }
    $pane.text("Loading…");
    $.get($tabButton.data("url"))
        .done(function (html) {
            $pane.html(html).data("loaded", true);

            if ($pane.find("#orders-table").length) {
                MakeOrdersDataTable("#orders-table");
            }
            if ($pane.find("#supplier-orders-table").length) {
                MakeOrdersDataTable("#supplier-orders-table");
            }
            if ($pane.find("#product-revenue-table").length) {
                MakeProductRevenueDataTable("#product-revenue-table");
            }
            if ($pane.find("#employees-table").length) {
                MakeEmployeesDataTable("#employees-table");
            }
            if ($pane.find("#leaderboard-table").length) {
                MakeLeaderboardDataTable("#leaderboard-table");
            }

            ActivateYearDropdown($pane);
            ActivateBreakdownControls($pane);
            ActivateCustomerControls($pane);
            ActivateTeamComparison($pane);
            ActivateRevenueOverTime($pane);
            ActivateChartControls($pane);
        })
        .fail(function (xhr) {
            $pane.text(xhr.status === 403
                ? "This tab is only for the logged-in customer or supplier it belongs to, or an employee."
                : "Could not load this tab. Please try again.");
        });
}

// #endregion

// #region Dashboard chart controls (Assignment 3)

/**
 * The short plain-text message a chart view sends with a 400 ("Choose a
 * valid year."), or fallback when the response is empty or is a whole HTML
 * error page.
 * @param {jqXHR} xhr - the failed request
 * @param {string} fallback - the message to show otherwise
 * @returns {string}
 */
function ShortErrorText(xhr, fallback) {
    const text = (xhr && xhr.responseText) || "";
    return text && text.length < 200 && text.indexOf("<") === -1 ? text : fallback;
}

/**
 * Every control bar marked js-chart-controls on the customer and supplier
 * dashboards: when any dropdown, radio button or checkbox inside it changes,
 * all of the bar's values go to its data-url, and the HTML that comes back
 * replaces its data-target. One function covers every card, so each control
 * behaves the same way. Each input sends its data-param (or its name) as the
 * query parameter; a checkbox sends "on" or "off". A value the view refuses
 * (a 400) shows its message in place of the chart.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateChartControls($pane) {
    $pane.find(".js-chart-controls").each(function () {
        const $controls = $(this);
        const $target = $($controls.data("target"));
        const $inputs = $controls.find("select[name], input[name]");
        function values() {
            const params = {};
            $inputs.each(function () {
                const $input = $(this);
                // data-param lets two radio groups on one page send the same
                // query parameter (measure) while keeping separate names, so
                // checking one group never unchecks the other.
                const param = $input.data("param") || this.name;
                if ($input.is(":radio")) {
                    if ($input.is(":checked")) { params[param] = $input.val(); }
                } else if ($input.is(":checkbox")) {
                    params[param] = $input.is(":checked") ? "on" : "off";
                } else {
                    params[param] = $input.val();
                }
            });
            return params;
        }
        $inputs.on("change", function () {
            $target.addClass("dt-chart-loading");
            $.get($controls.data("url"), values())
                .done(function (html) { $target.html(html); })
                .fail(function (xhr) {
                    $target.empty().append(
                        $("<div>").addClass("alert alert-warning mb-0")
                            .text(ShortErrorText(xhr, "Could not load the chart."))
                    );
                })
                .always(function () { $target.removeClass("dt-chart-loading"); });
        });
    });
}

// #endregion

// #region Dark mode -- the navbar toggle and chart colors
/*
    Dark mode, step 2 of 2 (step 1 is theme-init.js, which applies the
    saved choice in <head> before the page paints).

    ActivateThemeToggle wires the navbar's #theme-toggle button (base.html)
    on every page: a click flips data-bs-theme on <html>, saves the choice
    in localStorage, and updates the button's icon and label.

    Page colors switch on their own: Bootstrap reads data-bs-theme, and
    DjangoTraders.css redefines the --dt-* tokens under it. Plotly charts
    are different -- the server draws them with fixed light colors
    (_figure_html, models.py) -- so ThemeChart recolors each one in the
    browser with Plotly.relayout: transparent background, light text, dim
    grid lines, and a light trend line. It saves each chart's original
    light colors the first time, so switching back restores them exactly.
    Charts arrive later by AJAX (tabs, year dropdowns, chart controls), so
    a MutationObserver themes any chart that appears in the page; a chart
    already in the current theme is skipped, which also stops the
    observer from reacting to its own relayout.
*/
const DT_DARK_CHART = {
    background: "rgba(0,0,0,0)",
    text: "#dee2e6",
    grid: "#3b4148",
    axisLine: "#6c757d",
    trend: "#ced4da",
    // Heatmaps: the light scale starts at near-white, which glares on a dark
    // page, so dark mode runs from the card color to a bright olive instead.
    heatmapScale: [[0, "#2b3138"], [0.35, "#56702a"], [1, "#b5d36a"]],
};

function CurrentTheme() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
}

function LayoutValue(layout, path) {
    // Reads a dotted path like "xaxis.gridcolor" from a chart's own layout;
    // null when the chart didn't set it.
    let value = layout;
    for (const part of path.split(".")) {
        if (value === null || value === undefined || typeof value !== "object") {
            return null;
        }
        value = value[part];
    }
    return value === undefined ? null : value;
}

function ChartAxisNames(fullLayout) {
    return Object.keys(fullLayout).filter(function (key) {
        return /^[xy]axis\d*$/.test(key);
    });
}

function ThemeChart(chart) {
    const theme = CurrentTheme();
    if (!window.Plotly || !chart._fullLayout || chart._dtTheme === theme) {
        return;
    }
    const full = chart._fullLayout;
    const axes = ChartAxisNames(full);

    // First visit: remember the colors the server set on this chart itself
    // (chart.layout, not the computed _fullLayout). Anything the server left
    // to the template is saved as null, and relayout with null removes the
    // dark override so the template's own light color comes back exactly.
    if (!chart._dtLight) {
        const light = {
            paper_bgcolor: LayoutValue(chart.layout, "paper_bgcolor"),
            plot_bgcolor: LayoutValue(chart.layout, "plot_bgcolor"),
            "font.color": LayoutValue(chart.layout, "font.color"),
            "title.font.color": LayoutValue(chart.layout, "title.font.color"),
        };
        axes.forEach(function (axis) {
            ["gridcolor", "linecolor", "zerolinecolor"].forEach(function (part) {
                light[axis + "." + part] = LayoutValue(chart.layout, axis + "." + part);
            });
        });
        chart._dtLight = light;
        chart._dtTrend = [];
        chart._dtHeatmaps = [];
        (chart.data || []).forEach(function (trace, index) {
            if (trace.name === "Trend" && trace.line) {
                chart._dtTrend.push({ index: index, color: trace.line.color });
            }
            if (trace.type === "heatmap") {
                chart._dtHeatmaps.push({ index: index, colorscale: trace.colorscale });
            }
        });
    }

    let update;
    if (theme === "dark") {
        update = {
            paper_bgcolor: DT_DARK_CHART.background,
            plot_bgcolor: DT_DARK_CHART.background,
            "font.color": DT_DARK_CHART.text,
            "title.font.color": DT_DARK_CHART.text,
        };
        axes.forEach(function (axis) {
            if (full[axis].showgrid) {
                update[axis + ".gridcolor"] = DT_DARK_CHART.grid;
            }
            update[axis + ".linecolor"] = DT_DARK_CHART.axisLine;
            update[axis + ".zerolinecolor"] = DT_DARK_CHART.axisLine;
        });
    } else {
        update = chart._dtLight;
    }
    chart._dtTheme = theme;
    Plotly.relayout(chart, update);
    chart._dtTrend.forEach(function (trend) {
        Plotly.restyle(chart, { "line.color": theme === "dark" ? DT_DARK_CHART.trend : trend.color }, [trend.index]);
    });
    chart._dtHeatmaps.forEach(function (heatmap) {
        Plotly.restyle(chart, { colorscale: [theme === "dark" ? DT_DARK_CHART.heatmapScale : heatmap.colorscale] }, [heatmap.index]);
    });
}

function ThemeAllCharts() {
    document.querySelectorAll(".js-plotly-plot").forEach(ThemeChart);
}

function UpdateThemeToggle() {
    const dark = CurrentTheme() === "dark";
    const $toggle = $("#theme-toggle");
    $toggle.attr("aria-pressed", dark ? "true" : "false")
        .attr("title", dark ? "Switch to light mode" : "Switch to dark mode");
    $toggle.find("i").toggleClass("fa-moon", !dark).toggleClass("fa-sun", dark);
    $toggle.find(".js-theme-label").text(dark ? "Light mode" : "Dark mode");
}

function SetTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
        window.localStorage.setItem("dt-theme", theme);
    } catch (e) {
        // Storage unavailable (private window, blocked site data): the switch
        // still works for this page, it just isn't remembered.
    }
    UpdateThemeToggle();
    ThemeAllCharts();
}

function ActivateThemeToggle() {
    UpdateThemeToggle();
    $("#theme-toggle").on("click", function () {
        SetTheme(CurrentTheme() === "dark" ? "light" : "dark");
    });

    let pending = null;
    const observer = new MutationObserver(function () {
        if (pending === null) {
            pending = window.setTimeout(function () {
                pending = null;
                ThemeAllCharts();
            }, 50);
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    ThemeAllCharts();
}

$(ActivateThemeToggle);
// #endregion
