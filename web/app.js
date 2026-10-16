/* Static dashboard: no analytics, API tokens, framework, or third-party scripts. */
"use strict";
const DAY = 86400000;
const COLORS = [
  "var(--bsm-accent-strong)",
  "var(--bsm-chart-1)",
  "var(--bsm-chart-2)",
  "var(--bsm-chart-3)",
  "var(--bsm-info)",
];

function dayNumber(value) {
  return Date.parse(`${value}T00:00:00Z`);
}
function isoDay(value) {
  return new Date(value).toISOString().slice(0, 10);
}
function sourceStatus(source, now = Date.now()) {
  if (!source || source.count === null) return "unavailable";
  if (
    source.status !== "fresh" ||
    !source.sampled_at ||
    now - Date.parse(source.sampled_at) > 36 * 3600000
  )
    return "stale";
  return "fresh";
}
function dateRange(end, selection, from, through) {
  const last = through || end;
  const first =
    selection === "custom"
      ? from || last
      : selection === "all"
        ? "1970-01-01"
        : isoDay(dayNumber(last) - (Number(selection) - 1) * DAY);
  if (
    !Number.isFinite(dayNumber(first)) ||
    !Number.isFinite(dayNumber(last)) ||
    first > last
  )
    throw new Error("Choose a valid date range with From before Through.");
  return [first, last];
}
function chartSegments(history, projectId, sourceId, from, through) {
  const days = Object.keys(history)
    .filter((day) => day >= from && day <= through)
    .sort();
  const segments = [];
  let segment = [];
  let previousDay = null;
  let previousIdentity = null;
  for (const day of days) {
    const project = history[day].projects[projectId];
    const source = sourceId === "total" ? project : project?.sources[sourceId];
    const count = sourceId === "total" ? source?.total : source?.count;
    const identity =
      sourceId === "total"
        ? JSON.stringify(
            Object.entries(project?.sources || {})
              .map(([key, value]) => [key, value.identity])
              .sort(),
          )
        : JSON.stringify(source?.identity);
    const decreased =
      sourceId === "total"
        ? Object.values(project?.sources || {}).some((value) => value.decreased)
        : source?.decreased;
    const valid =
      source?.status === "fresh" && Number.isSafeInteger(count) && count >= 0;
    const last = segment.at(-1);
    if (
      !valid ||
      (previousDay && dayNumber(day) - dayNumber(previousDay) !== DAY) ||
      (last &&
        (count < last.count || identity !== previousIdentity || decreased))
    ) {
      if (segment.length) segments.push(segment);
      segment = [];
    }
    if (valid) segment.push({ day, count });
    previousDay = day;
    previousIdentity = identity;
  }
  if (segment.length) segments.push(segment);
  return segments;
}

if (typeof module !== "undefined")
  module.exports = { sourceStatus, dateRange, chartSegments };

if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const number = (value) =>
    value === null || value === undefined ? "—" : value.toLocaleString("en-US");
  const state = {
    stats: null,
    history: {},
    hidden: new Set(),
    exportUrl: null,
  };
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function svgElement(tag, attributes, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attributes))
      node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function card(label, value, detail) {
    const node = element("article", undefined, "card");
    node.append(
      element("div", label, "label"),
      element("div", value, "value"),
      element("div", detail, "detail"),
    );
    return node;
  }
  function drawChart(projectId, project, from, through) {
    const chart = $("chart");
    chart.replaceChildren();
    const all = [
      { id: "total", label: "Combined", color: COLORS[0] },
      ...Object.entries(project.sources).map(([id, source], index) => ({
        id,
        label: source.label,
        color: COLORS[(index + 1) % COLORS.length],
      })),
    ];
    $("legend").replaceChildren();
    for (const item of all) {
      const button = element("button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(!state.hidden.has(item.id)));
      const swatch = element("i");
      swatch.style.backgroundColor = item.color;
      swatch.setAttribute("aria-hidden", "true");
      button.append(swatch, document.createTextNode(item.label));
      button.addEventListener("click", () => {
        state.hidden.has(item.id)
          ? state.hidden.delete(item.id)
          : state.hidden.add(item.id);
        render();
      });
      $("legend").append(button);
    }
    const series = all
      .filter((item) => !state.hidden.has(item.id))
      .map((item) => ({
        ...item,
        segments: chartSegments(
          state.history,
          projectId,
          item.id,
          from,
          through,
        ),
      }));
    const points = series.flatMap((item) => item.segments.flat());
    $("chart-empty").hidden = points.length !== 0;
    if (!points.length) return;
    const width = Math.max(300, chart.clientWidth),
      height = width < 600 ? 260 : 340,
      left = 68,
      right = 16,
      top = 20,
      bottom = 44;
    const minDate = Math.min(...points.map((point) => dayNumber(point.day)));
    const maxDate = Math.max(...points.map((point) => dayNumber(point.day)));
    const maxCount = Math.max(1, ...points.map((point) => point.count));
    const x = (day) =>
      maxDate === minDate
        ? (left + width - right) / 2
        : left +
          ((dayNumber(day) - minDate) / (maxDate - minDate)) *
            (width - left - right);
    const y = (count) =>
      height - bottom - (count / maxCount) * (height - top - bottom);
    const svg = svgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      "aria-hidden": "true",
    });
    for (let tick = 0; tick <= 4; tick++) {
      const value = (maxCount * tick) / 4;
      svg.append(
        svgElement("line", {
          x1: left,
          x2: width - right,
          y1: y(value),
          y2: y(value),
          stroke: "var(--bsm-border)",
        }),
      );
      svg.append(
        svgElement(
          "text",
          { x: left - 10, y: y(value) + 4, "text-anchor": "end" },
          Math.round(value).toLocaleString("en-US"),
        ),
      );
    }
    const ticks =
      maxDate === minDate
        ? [minDate]
        : [minDate, (minDate + maxDate) / 2, maxDate];
    for (const [index, time] of ticks.entries())
      svg.append(
        svgElement(
          "text",
          {
            x: x(isoDay(time)),
            y: height - 12,
            "text-anchor":
              ticks.length === 1
                ? "middle"
                : index === 0
                  ? "start"
                  : index === ticks.length - 1
                    ? "end"
                    : "middle",
          },
          isoDay(time),
        ),
      );
    for (const item of series) {
      for (const segment of item.segments) {
        svg.append(
          svgElement("polyline", {
            points: segment
              .map((point) => `${x(point.day)},${y(point.count)}`)
              .join(" "),
            fill: "none",
            stroke: item.color,
            "stroke-width": item.id === "total" ? 3 : 2,
          }),
        );
        for (const point of segment) {
          const dot = svgElement("circle", {
            cx: x(point.day),
            cy: y(point.count),
            r: segment.length === 1 ? 4 : 2.5,
            fill: item.color,
          });
          dot.append(
            svgElement(
              "title",
              {},
              `${item.label}: ${number(point.count)} on ${point.day}`,
            ),
          );
          svg.append(dot);
        }
      }
    }
    chart.append(svg);
  }
  function render() {
    try {
      const projectId = $("project").value;
      const project = state.stats.projects[projectId];
      const now = Date.now();
      const stale = Object.values(project.sources).some(
        (source) => sourceStatus(source, now) !== "fresh",
      );
      const expired = now - Date.parse(state.stats.collected_at) > 36 * 3600000;
      $("notice").className = stale || expired ? "warning" : "";
      $("notice").textContent =
        stale || expired
          ? "Collection is delayed or a source is unavailable. Counts may include preserved values; check source health below."
          : "All configured sources for this project were collected successfully.";
      const end = state.stats.collected_at.slice(0, 10);
      const [from, through] = dateRange(
        end,
        $("range").value,
        $("from").value,
        $("through").value,
      );
      $("overview").replaceChildren(
        card(
          "Downloads + pulls",
          number(project.total),
          `${project.name} · ${stale ? "includes stale or unavailable sources" : "all sources fresh"}`,
        ),
        ...[
          ["daily", "1-day growth"],
          ["weekly", "7-day growth"],
          ["monthly", "30-day growth"],
        ].map(([key, label]) =>
          card(
            label,
            stale || expired || project.growth[key] === null
              ? "—"
              : `+${number(project.growth[key])}`,
            "Requires complete comparable daily observations",
          ),
        ),
        card(
          "Next milestone",
          number(project.milestones.next),
          project.milestones.reached
            ? `${number(project.milestones.reached)} reached in the latest known count`
            : "No milestone reached yet",
        ),
      );
      $("source-cards").replaceChildren(
        ...Object.values(project.sources).map((source) =>
          card(
            source.label,
            number(source.count),
            sourceStatus(source, now) +
              (source.decreased
                ? " · provider corrected the counter"
                : " · last known count"),
          ),
        ),
      );
      $("sources").replaceChildren();
      for (const source of Object.values(project.sources)) {
        const row = element("tr");
        const health = sourceStatus(source, now);
        row.append(
          element("td", source.label),
          element("td", number(source.count)),
          element(
            "td",
            health + (source.decreased ? " · counter corrected" : ""),
            `status ${health}`,
          ),
          element(
            "td",
            source.sampled_at
              ? source.sampled_at.slice(0, 16).replace("T", " ") + " UTC"
              : "Never",
          ),
          element(
            "td",
            source.basis === "provider_lifetime"
              ? "Provider total"
              : source.basis?.startsWith("since:")
                ? "Since " + source.basis.slice(6)
                : "Unavailable",
          ),
        );
        $("sources").append(row);
      }
      $("freshness").textContent =
        `Last collection attempt: ${state.stats.collected_at}. A source is shown as stale after 36 hours without a successful observation.`;
      $("history-caption").textContent =
        `${from === "1970-01-01" ? "First observation" : from} → ${through} · UTC`;
      drawChart(projectId, project, from, through);
      $("observations").replaceChildren();
      const selected = Object.fromEntries(
        Object.entries(state.history)
          .filter(([day]) => day >= from && day <= through)
          .sort(([a], [b]) => b.localeCompare(a)),
      );
      for (const [day, entry] of Object.entries(selected)) {
        const observed = entry.projects[projectId];
        if (!observed) continue;
        for (const [id, source] of Object.entries(observed.sources)) {
          const row = element("tr");
          row.append(
            element("td", day),
            element("td", project.sources[id]?.label || id),
            element("td", number(source.count)),
            element("td", source.status, `status ${source.status}`),
          );
          $("observations").append(row);
        }
      }
      if (state.exportUrl) URL.revokeObjectURL(state.exportUrl);
      const exportData = {
        schema_version: 1,
        project: projectId,
        from,
        through,
        days: Object.fromEntries(
          Object.entries(selected)
            .filter(([, entry]) => entry.projects[projectId])
            .map(([day, entry]) => [
              day,
              {
                collected_at: entry.collected_at,
                projects: { [projectId]: entry.projects[projectId] },
              },
            ]),
        ),
      };
      state.exportUrl = URL.createObjectURL(
        new Blob([JSON.stringify(exportData, null, 2)], {
          type: "application/json",
        }),
      );
      $("export-history").href = state.exportUrl;
      $("export-history").download = `${projectId}-history.json`;
    } catch (error) {
      $("notice").textContent = error.message;
      $("notice").className = "warning";
    }
  }
  async function getJson(path) {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok)
      throw new Error(`Could not load ${path} (HTTP ${response.status}).`);
    return response.json();
  }
  async function start() {
    try {
      state.stats = await getJson("stats.json");
      if (state.stats.schema_version !== 1)
        throw new Error("Unsupported statistics format.");
      const months = await Promise.all(
        state.stats.history.map((path) => getJson(path)),
      );
      for (const month of months) {
        if (month.schema_version !== 1)
          throw new Error("Unsupported history format.");
        Object.assign(state.history, month.days);
      }
      for (const [id, project] of Object.entries(state.stats.projects)) {
        const option = element("option", project.name);
        option.value = id;
        $("project").append(option);
      }
      $("project").value = state.stats.primary_project;
      for (const id of ["project", "range", "from", "through"])
        $(id).addEventListener("change", () => {
          if (id === "from" || id === "through") $("range").value = "custom";
          if (id === "project") state.hidden.clear();
          if (id === "range" && $("range").value !== "custom") {
            $("from").value = "";
            $("through").value = "";
          }
          render();
        });
      render();
      let resizeTimer;
      window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(render, 100);
      });
      setInterval(render, 60000);
    } catch (error) {
      $("notice").className = "warning";
      $("notice").textContent =
        `${error.message} Published statistics may not be available yet. Serve this folder over HTTP to preview locally.`;
    }
  }
  start();
}
