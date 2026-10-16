const { test } = require("node:test");
const assert = require("node:assert/strict");
const { sourceStatus, dateRange, chartSegments } = require("../web/app.js");
const now = Date.parse("2026-10-16T12:00:00Z");
function entry(
  count,
  status = "fresh",
  identity = { kind: "pypi", package: "bsm" },
  decreased = false,
) {
  return {
    projects: {
      bsm: {
        total: count,
        status,
        sources: { pypi: { count, status, identity, decreased } },
      },
    },
  };
}
test("freshness expires even when the scheduled publisher stops", () => {
  assert.equal(
    sourceStatus(
      { count: 100, status: "fresh", sampled_at: "2026-10-16T11:00:00Z" },
      now,
    ),
    "fresh",
  );
  assert.equal(
    sourceStatus(
      { count: 100, status: "fresh", sampled_at: "2026-10-14T11:00:00Z" },
      now,
    ),
    "stale",
  );
  assert.equal(
    sourceStatus({ count: null, status: "unavailable" }, now),
    "unavailable",
  );
});
test("date filters use inclusive UTC days and reject reversed ranges", () => {
  assert.deepEqual(dateRange("2026-10-16", "30", "", ""), [
    "2026-09-17",
    "2026-10-16",
  ]);
  assert.deepEqual(
    dateRange("2026-10-16", "custom", "2026-10-01", "2026-10-03"),
    ["2026-10-01", "2026-10-03"],
  );
  assert.throws(() =>
    dateRange("2026-10-16", "custom", "2026-10-20", "2026-10-01"),
  );
});
test("chart does not connect across missing days or failed sources", () => {
  const history = {
    "2026-10-10": entry(10),
    "2026-10-11": entry(10, "stale"),
    "2026-10-12": entry(20),
    "2026-10-14": entry(30),
  };
  const segments = chartSegments(
    history,
    "bsm",
    "pypi",
    "2026-10-01",
    "2026-10-16",
  );
  assert.deepEqual(
    segments.map((segment) => segment.map((point) => point.count)),
    [[10], [20], [30]],
  );
});
test("counter corrections and package changes split a chart series", () => {
  const history = {
    "2026-10-10": entry(100),
    "2026-10-11": entry(90, "fresh", undefined, true),
    "2026-10-12": entry(120),
    "2026-10-13": entry(130, "fresh", { kind: "pypi", package: "other" }),
  };
  assert.deepEqual(
    chartSegments(history, "bsm", "pypi", "2026-10-01", "2026-10-16").map(
      (segment) => segment.length,
    ),
    [1, 2, 1],
  );
});
test("combined series is unavailable until every source is known", () => {
  const history = {
    "2026-10-10": entry(null, "unavailable"),
    "2026-10-11": entry(10),
  };
  assert.deepEqual(
    chartSegments(history, "bsm", "total", "2026-10-01", "2026-10-16"),
    [[{ day: "2026-10-11", count: 10 }]],
  );
});
