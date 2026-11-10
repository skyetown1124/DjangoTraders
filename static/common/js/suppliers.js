/*
    suppliers.js -- additional feature C (not part of the assignment): the
    supplier page's Price Changes tab, mirrored from the ALI App Central Cost
    tab (a separate project, cost_grid.js there).

    The server does the work: every filter or sort change asks
    supplier_prices_grid (views/suppliers.py) for a freshly rendered grid, and
    Export to Excel asks supplier_prices_export for a workbook built from the
    same query string, so the file always matches the screen. This file only:
      - reads the toolbar (search, status, flag) and keeps the sort
        (data-sort / data-sort2 on the grid) -- click a heading for the primary
        sort (asc <-> desc), double-click another heading (or Shift+Enter) for
        a secondary sort (asc -> desc -> off);
      - expands and collapses products (each row's arrow, or the heading arrow
        for all), keeping them open across reloads;
      - selects one row at a time (click; click again to clear) and opens the
        product page on double-click or Enter, but not while loading;
      - downloads the export, or shows "Error downloading file".
    Every handler is delegated from the document because the tab arrives by
    AJAX after this file has run.
*/

const PriceGrid = {
    expanded: new Set(),   // product ids whose price periods are showing
    selected: null,        // the selected product id, or null
    loading: false,
    clickTimer: null,      // tells a heading click from a double-click
    searchTimer: null,
};

function PriceToolbar() { return $(".js-price-toolbar"); }

function PriceParams() {
    const $toolbar = PriceToolbar();
    const $wrap = $($toolbar.data("target")).find(".dt-price-grid-wrap");
    const params = {
        q: $toolbar.find("[name=q]").val().trim(),
        status: $toolbar.find("[name=status]").val(),
        flag: $toolbar.find("[name=flag]").val(),
    };
    if ($wrap.data("sort")) { params.sort = $wrap.data("sort"); }
    if ($wrap.data("sort2")) { params.sort2 = $wrap.data("sort2"); }
    return params;
}

function PriceMessage(text) {
    $(".dt-price-message").text(text || "").toggleClass("alert alert-warning py-1 px-2 small", !!text);
}

function LoadPriceGrid(params, focusKey) {
    const $toolbar = PriceToolbar();
    const $target = $($toolbar.data("target"));
    PriceGrid.loading = true;
    $target.addClass("dt-chart-loading").attr("aria-busy", "true");
    $.get($toolbar.data("grid-url"), params)
        .done(function (html) {
            PriceMessage("");
            $target.html(html);
            ApplyPriceState($target);
            if (focusKey) { $target.find('th[data-key="' + focusKey + '"] .dt-th-label').trigger("focus"); }
        })
        .fail(function (xhr) { PriceMessage(ShortErrorText(xhr, "Could not load the price grid.")); })
        .always(function () {
            PriceGrid.loading = false;
            $target.removeClass("dt-chart-loading").removeAttr("aria-busy");
        });
}

// Re-applies the open rows and the selection after the grid is redrawn.
function ApplyPriceState($target) {
    $target.find(".dt-price-parent").each(function () {
        const id = String($(this).data("id"));
        SetPriceRowOpen($target, id, PriceGrid.expanded.has(id));
        $(this).toggleClass("dt-selected", PriceGrid.selected === id)
               .attr("aria-selected", PriceGrid.selected === id ? "true" : "false");
    });
    UpdateExpandAll($target);
}

function SetPriceRowOpen($target, id, open) {
    $target.find('[data-child="' + id + '"]').prop("hidden", !open);
    const $btn = $target.find('[data-expand="' + id + '"]');
    const name = $btn.attr("aria-label").replace(/^(Expand|Collapse) /, "");
    $btn.toggleClass("open", open).attr("aria-expanded", open ? "true" : "false")
        .attr("aria-label", (open ? "Collapse " : "Expand ") + name);
}

function UpdateExpandAll($target) {
    const ids = $target.find(".dt-price-parent").map(function () { return String($(this).data("id")); }).get();
    const allOpen = ids.length > 0 && ids.every(function (id) { return PriceGrid.expanded.has(id); });
    const label = allOpen ? "Collapse all" : "Expand all";
    $target.find(".js-price-expand-all").toggleClass("open", allOpen).attr({ title: label, "aria-label": label });
}

// Primary sort: the same heading flips asc <-> desc; a new heading starts asc
// (and stops being the secondary sort if it was one).
function PrimarySort(key) {
    const params = PriceParams();
    const [current, direction] = (params.sort || "").split(":");
    params.sort = key + ":" + (current === key && direction === "asc" ? "desc" : "asc");
    if (params.sort2 && params.sort2.split(":")[0] === key) { delete params.sort2; }
    LoadPriceGrid(params, key);
}

// Secondary sort: asc -> desc -> off. It needs a different primary sort first.
function SecondarySort(key) {
    const params = PriceParams();
    if (!params.sort) { return PrimarySort(key); }
    if (params.sort.split(":")[0] === key) { return; }
    const [current, direction] = (params.sort2 || "").split(":");
    if (current !== key) { params.sort2 = key + ":asc"; }
    else if (direction === "asc") { params.sort2 = key + ":desc"; }
    else { delete params.sort2; }
    LoadPriceGrid(params, key);
}

function TogglePriceSelection($row) {
    if (PriceGrid.loading) { return; }
    const id = String($row.data("id"));
    PriceGrid.selected = PriceGrid.selected === id ? null : id;
    ApplyPriceState($row.closest(".dt-price-grid-host"));
}

function OpenPriceRow($row) {
    if (!PriceGrid.loading) { window.location.href = $row.data("href"); }
}

function ExportPrices() {
    const $toolbar = PriceToolbar();
    const url = $toolbar.data("export-url") + "?" + $.param(PriceParams());
    const $button = $toolbar.find(".js-price-export").prop("disabled", true);
    fetch(url, { credentials: "same-origin" })
        .then(function (response) {
            if (!response.ok) { throw new Error(response.status); }
            const disposition = response.headers.get("Content-Disposition") || "";
            const match = /filename="([^"]+)"/.exec(disposition);
            return response.blob().then(function (blob) {
                return { blob: blob, name: match ? match[1] : "SupplierPriceChanges_Export.xlsx" };
            });
        })
        .then(function (file) {
            const link = document.createElement("a");
            link.href = URL.createObjectURL(file.blob);
            link.download = file.name;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
            PriceMessage("");
        })
        .catch(function () { PriceMessage("Error downloading file"); })
        .finally(function () { $button.prop("disabled", false); });
}

$(function () {
    const $doc = $(document);

    // Toolbar: filters reload the grid; typing waits for a pause.
    $doc.on("change", ".js-price-toolbar select", function () { LoadPriceGrid(PriceParams()); });
    $doc.on("input", ".js-price-toolbar [name=q]", function () {
        clearTimeout(PriceGrid.searchTimer);
        PriceGrid.searchTimer = setTimeout(function () { LoadPriceGrid(PriceParams()); }, 300);
    });
    $doc.on("click", ".js-price-reset", function () {
        const $toolbar = PriceToolbar();
        $toolbar.find("[name=q]").val("");
        $toolbar.find("[name=status]").val("");
        $toolbar.find("[name=flag]").val("any");
        PriceGrid.expanded.clear();
        PriceGrid.selected = null;
        LoadPriceGrid({});
    });
    $doc.on("click", ".js-price-export", ExportPrices);

    // Headings: click = primary sort, double-click = secondary sort.
    $doc.on("click", ".dt-price-grid .dt-th-label", function () {
        const key = $(this).closest("th").data("key");
        clearTimeout(PriceGrid.clickTimer);
        PriceGrid.clickTimer = setTimeout(function () { PrimarySort(key); }, 250);
    });
    $doc.on("dblclick", ".dt-price-grid .dt-th-label", function () {
        clearTimeout(PriceGrid.clickTimer);
        SecondarySort($(this).closest("th").data("key"));
    });
    $doc.on("keydown", ".dt-price-grid .dt-th-label", function (e) {
        if (e.key !== "Enter" && e.key !== " ") { return; }
        e.preventDefault();
        const key = $(this).closest("th").data("key");
        if (e.shiftKey) { SecondarySort(key); } else { PrimarySort(key); }
    });

    // Expand arrows: one row (without selecting it), or all from the heading.
    $doc.on("click", ".js-price-expand", function (e) {
        e.stopPropagation();
        const $target = $(this).closest(".dt-price-grid-host");
        const id = String($(this).data("expand"));
        if (PriceGrid.expanded.has(id)) { PriceGrid.expanded.delete(id); } else { PriceGrid.expanded.add(id); }
        SetPriceRowOpen($target, id, PriceGrid.expanded.has(id));
        UpdateExpandAll($target);
    });
    $doc.on("click", ".js-price-expand-all", function () {
        const $target = $(this).closest(".dt-price-grid-host");
        const ids = $target.find(".dt-price-parent").map(function () { return String($(this).data("id")); }).get();
        const open = !ids.every(function (id) { return PriceGrid.expanded.has(id); });
        ids.forEach(function (id) {
            if (open) { PriceGrid.expanded.add(id); } else { PriceGrid.expanded.delete(id); }
            SetPriceRowOpen($target, id, open);
        });
        UpdateExpandAll($target);
    });

    // Rows: click selects, double-click or Enter opens, Space selects.
    $doc.on("click", ".dt-price-parent", function () { TogglePriceSelection($(this)); });
    $doc.on("dblclick", ".dt-price-parent", function () { OpenPriceRow($(this)); });
    $doc.on("keydown", ".dt-price-parent", function (e) {
        if (e.target !== this) { return; }
        if (e.key === "Enter") { e.preventDefault(); OpenPriceRow($(this)); }
        else if (e.key === " ") { e.preventDefault(); TogglePriceSelection($(this)); }
    });
});
