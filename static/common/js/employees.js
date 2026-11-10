/**
 * Employees: the employee and leaderboard tables and the dashboard controls
 * that reload one chart. Loaded by base.html after DjangoTraders.js.
 */

/**
 * The employees list, alphabetical by name (column 0).
 * @param {string} tableId - selector for the table
 */
function MakeEmployeesDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[0, "asc"]]
    });
}

/**
 * The manager's leaderboard: best rank first (column 0), with no search
 * box, paging or "Showing X of Y" text, since the list is short.
 * @param {string} tableId - selector for the table
 */
function MakeLeaderboardDataTable(tableId) {
    $(tableId).DataTable({
        paging: false,
        searching: false,
        info: false,
        order: [[0, "asc"]]
    });
}

/**
 * Employee dashboard: the "Revenue by" dropdown (supplier, product, category),
 * the "Show Top" radio buttons (5, 10, All) and the "Chart" dropdown
 * (Bar, Column, and for a manager Pie) all reload the chart in #dashboard-breakdown. The first
 * chart arrives already drawn.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateBreakdownControls($pane) {
    const $by = $pane.find("#breakdown-by");
    const $top = $pane.find("input[name='breakdown-top']");
    const $kind = $pane.find("#breakdown-kind");
    if ($by.length === 0) {
        return;
    }
    function loadBreakdown() {
        $.get($by.data("url"), { by: $by.val(), top: $top.filter(":checked").val(), kind: $kind.val() || "bar" })
            .done(function (html) { $("#dashboard-breakdown").html(html); })
            .fail(function () { $("#dashboard-breakdown").text("Could not load the chart."); });
    }
    $by.on("change", loadBreakdown);
    $top.on("change", loadBreakdown);
    $kind.on("change", loadBreakdown);
}

/**
 * Employee dashboard: the team comparison chart's "Compare" dropdown (Revenue,
 * Orders, Customers served) reloads the chart in #dashboard-team.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateTeamComparison($pane) {
    const $controls = $pane.find("#team-controls");
    if ($controls.length === 0) {
        return;
    }
    const $measure = $controls.find("#team-measure");
    $measure.on("change", function () {
        $.get($controls.data("url"), { measure: $measure.val() })
            .done(function (html) { $("#dashboard-team").html(html); })
            .fail(function () { $("#dashboard-team").text("Could not load the chart."); });
    });
}

/**
 * Employee dashboard: the top-customers "Show Top" radio buttons and "Chart"
 * dropdown (Bar, Column, Pie) reload the chart in #dashboard-customers.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateCustomerControls($pane) {
    const $controls = $pane.find("#customer-controls");
    if ($controls.length === 0) {
        return;
    }
    const $top = $controls.find("input[name='customer-top']");
    const $kind = $controls.find("#customer-kind");
    function loadCustomers() {
        $.get($controls.data("url"), { top: $top.filter(":checked").val(), kind: $kind.val() })
            .done(function (html) { $("#dashboard-customers").html(html); })
            .fail(function () { $("#dashboard-customers").text("Could not load the chart."); });
    }
    $top.on("change", loadCustomers);
    $kind.on("change", loadCustomers);
}

/**
 * Employee dashboard: the revenue-over-time card. "View by" (Year or
 * Month) changes the chart in #dashboard-revenue. The year dropdown does
 * different things per level: at Month it filters the chart to that year;
 * at Year it is labeled "Details for" and opens a modal for the chosen year.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateRevenueOverTime($pane) {
    const $controls = $pane.find("#revenue-controls");
    if ($controls.length === 0) {
        return;
    }
    const $level = $controls.find("input[name='revenue-level']");
    const $year = $controls.find("#revenue-year");
    const $yearLabel = $controls.find("label[for='revenue-year']");
    const $firstOption = $year.find("option[value='all']");

    function currentLevel() {
        return $level.filter(":checked").val();
    }

    function loadRevenue() {
        $.get($controls.data("url"), { level: currentLevel(), year: $year.val() })
            .done(function (html) { $("#dashboard-revenue").html(html); })
            .fail(function () { $("#dashboard-revenue").text("Could not load the chart."); });
    }

    function showDetails(period) {
        const $modal = $("#revenue-modal");
        // A modal left inside a tab pane can end up behind its backdrop.
        if ($modal.parent()[0] !== document.body) {
            $modal.appendTo("body");
        }

        function showModal(html) {
            $("#revenue-modal-content").html(html);
            // A chart drawn while hidden has no width; resize it once the modal is open.
            $modal.one("shown.bs.modal", function () {
                $modal.find(".js-plotly-plot").each(function () { Plotly.Plots.resize(this); });
            });
            bootstrap.Modal.getOrCreateInstance($modal[0]).show();
        }

        $.get($controls.data("detail-url"), { period: period })
            .done(showModal)
            .fail(function () { showModal("<div class='modal-body'>Could not load the details.</div>"); });
    }

    $level.on("change", function () {
        const atYear = currentLevel() === "year";
        $yearLabel.text(atYear ? "Details for" : "Year");
        $firstOption.text(atYear ? "Choose a year" : "All years");
        $year.val("all");
        loadRevenue();
    });

    $year.on("change", function () {
        if (currentLevel() === "year") {
            if ($year.val() !== "all") {
                showDetails($year.val());
                $year.val("all");
            }
            return;
        }
        loadRevenue();
    });
}
