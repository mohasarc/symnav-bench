import {
  METRICS,
  buildMatrix,
  buildTrialDrawer,
  createInitialState,
  filterTaskRows,
} from "./state.js";

const payload = JSON.parse(document.querySelector("#dashboard-payload").textContent);
const state = createInitialState(payload);
const view = document.querySelector("#view");
const filters = document.querySelector("#filters");

document.querySelector("#study-title").textContent = payload.study.id;
document.querySelector("#study-subtitle").textContent =
  `${payload.coverage.scored_slots}/${payload.coverage.planned_slots} scored trials`;
document.querySelector("#coverage-badge").textContent = coverageLabel(payload.coverage);
document.querySelector("#tabs").addEventListener("click", ({ target }) => {
  const button = target.closest("button[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  for (const tab of document.querySelectorAll("#tabs button")) {
    tab.setAttribute("aria-current", tab === button ? "page" : "false");
  }
  render();
});

renderFilters();

function render() {
  const heading = document.querySelector(`[data-view="${state.view}"]`).textContent;
  view.innerHTML = `<section class="panel"><h2>${heading}</h2><div id="view-content"></div></section>`;
  const taskRows = filterTaskRows(payload.tasks, state);
  if (state.view === "matrix") {
    renderMatrix(document.querySelector("#view-content"), taskRows);
    return;
  }
  if (state.view === "overview") {
    renderOverview(document.querySelector("#view-content"));
    return;
  }
  if (state.view === "leaderboard") {
    renderLeaderboard(document.querySelector("#view-content"));
    return;
  }
  if (state.view === "statistics") {
    renderStatistics(document.querySelector("#view-content"));
    return;
  }
  if (state.view === "efficiency") {
    renderEfficiency(document.querySelector("#view-content"), taskRows);
    return;
  }
  if (state.view === "usage") {
    renderToolUsage(document.querySelector("#view-content"), taskRows);
    return;
  }
  document.querySelector("#view-content").replaceChildren(
    Object.assign(document.createElement("p"), {
      textContent: `${taskRows.length} task rows match current filters`,
    }),
  );
}

function renderToolUsage(container, taskRows) {
  const configurations = payload.configurations.filter(
    (item) =>
      item.adoption &&
      (state.configurationId === "all" || item.id === state.configurationId) &&
      (state.condition === "all" || item.condition === state.condition),
  );
  if (!configurations.length) {
    container.replaceChildren(emptyState("Tool event data is not available for selected runs."));
    return;
  }
  const cards = document.createElement("div");
  cards.className = "usage-cards";
  for (const item of configurations) {
    const card = document.createElement("article");
    card.className = item.full_symnav ? "usage-card full-symnav" : "usage-card";
    const heading = document.createElement("h3");
    heading.textContent = item.label;
    card.append(
      heading,
      definitionList({
        trials_using_symnav: formatMetric(item.adoption.used_symnav_rate, "performance_score"),
        trials_reading_skill: formatMetric(item.adoption.read_symnav_skill_rate, "performance_score"),
        mean_symnav_calls: item.adoption.mean_symnav_calls,
        calls_per_agent_step: item.adoption.mean_symnav_calls_per_agent_step,
        first_symnav_step: item.adoption.mean_first_symnav_step,
        symnav_failures: item.adoption.mean_symnav_failures,
        symnav_timeouts: item.adoption.mean_symnav_timeouts,
      }),
    );
    cards.append(card);
  }
  const substitution = document.createElement("section");
  substitution.className = "chart-section inset";
  const heading = document.createElement("h3");
  heading.textContent = "Navigation substitution";
  substitution.append(heading, substitutionChart(configurations));
  const commands = document.createElement("section");
  commands.className = "chart-section inset";
  const commandHeading = document.createElement("h3");
  commandHeading.textContent = "Mean symnav command mix";
  commands.append(commandHeading, commandTable(configurations));
  container.replaceChildren(cards, substitution, commands);
}

function substitutionChart(configurations) {
  const values = configurations.flatMap((item) => [
    { label: `${item.condition} · search`, value: item.adoption.mean_search_calls, full: item.full_symnav },
    { label: `${item.condition} · read`, value: item.adoption.mean_read_calls, full: item.full_symnav },
    { label: `${item.condition} · patch`, value: item.adoption.mean_patch_calls, full: item.full_symnav },
    { label: `${item.condition} · symnav`, value: item.adoption.mean_symnav_calls, full: item.full_symnav },
  ]);
  const max = Math.max(...values.map((item) => item.value ?? 0), 1);
  const width = 700;
  const height = values.length * 28 + 20;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.classList.add("chart");
  values.forEach((item, index) => {
    const y = index * 28 + 18;
    const label = svgElement("text", { x: 4, y, class: "resource-label" });
    label.textContent = item.label;
    const bar = svgElement("rect", {
      x: 150,
      y: y - 12,
      width: ((item.value ?? 0) / max) * 520,
      height: 16,
      rx: 3,
      class: item.full ? "resource-bar primary" : "resource-bar",
    });
    const title = svgElement("title", {});
    title.textContent = `${item.label}: ${formatNumber(item.value ?? 0)}`;
    bar.append(title);
    svg.append(label, bar);
  });
  return svg;
}

function commandTable(configurations) {
  const commandNames = [
    ...new Set(
      configurations.flatMap((item) => Object.keys(item.adoption.mean_command_counts ?? {})),
    ),
  ].sort();
  if (!commandNames.length) return emptyState("No symnav command calls were recorded.");
  return dataTable(
    ["Configuration", ...commandNames],
    configurations.map((item) => [
      item.label,
      ...commandNames.map((command) => formatNumber(item.adoption.mean_command_counts[command] ?? 0)),
    ]),
    configurations.map((item) => (item.full_symnav ? "full-symnav" : "")),
  );
}

function renderEfficiency(container, taskRows) {
  const configurations = payload.configurations.filter(
    (item) =>
      (state.configurationId === "all" || item.id === state.configurationId) &&
      (state.condition === "all" || item.condition === state.condition),
  );
  const resources = configurations.map((configuration) => {
    const rows = taskRows.filter(
      (row) => row.configuration_id === configuration.id && row.condition === configuration.condition,
    );
    return {
      id: `${configuration.id}:${configuration.condition}`,
      label: configuration.label,
      full: configuration.full_symnav,
      score: configuration.metrics.performance_score,
      totalCost: configuration.metrics.cost,
      costPerSuccess: configuration.metrics.cost_per_success,
      meanCost: meanPresent(rows.map((row) => row.metrics.cost)),
      outputTokens: meanPresent(rows.map((row) => row.metrics.output_tokens)),
      steps: meanPresent(rows.map((row) => row.metrics.steps)),
      duration: meanPresent(rows.map((row) => row.metrics.duration)),
    };
  });
  const grid = document.createElement("div");
  grid.className = "efficiency-grid";
  const frontierSection = document.createElement("section");
  frontierSection.className = "chart-section inset";
  const frontierHeading = document.createElement("h3");
  frontierHeading.textContent = "Performance / cost frontier";
  frontierSection.append(frontierHeading, frontierPlot(resources));
  const distributionSection = document.createElement("section");
  distributionSection.className = "chart-section inset";
  const distributionHeading = document.createElement("h3");
  distributionHeading.textContent = "All-trial resource means";
  distributionSection.append(distributionHeading, resourcePlot(resources));
  grid.append(frontierSection, distributionSection);
  container.replaceChildren(grid);
}

function frontierPlot(rows) {
  const present = rows.filter((row) => row.totalCost != null && row.score != null);
  if (!present.length) return emptyState("Cost and performance data are not available yet.");
  const width = 620;
  const height = 330;
  const margin = { left: 56, right: 18, top: 18, bottom: 42 };
  const maxCost = Math.max(...present.map((row) => row.totalCost), 1);
  const x = (value) => margin.left + (value / maxCost) * (width - margin.left - margin.right);
  const y = (value) => height - margin.bottom - value * (height - margin.top - margin.bottom);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.classList.add("chart");
  svg.append(
    svgElement("line", { x1: margin.left, x2: width - margin.right, y1: height - margin.bottom, y2: height - margin.bottom, class: "axis" }),
    svgElement("line", { x1: margin.left, x2: margin.left, y1: margin.top, y2: height - margin.bottom, class: "axis" }),
  );
  const frontier = [];
  let best = -Infinity;
  for (const row of [...present].sort((left, right) => left.totalCost - right.totalCost)) {
    if (row.score > best) {
      frontier.push(row);
      best = row.score;
    }
  }
  if (frontier.length > 1) {
    svg.append(svgElement("polyline", {
      points: frontier.map((row) => `${x(row.totalCost)},${y(row.score)}`).join(" "),
      class: "frontier-line",
      fill: "none",
    }));
  }
  for (const row of present) {
    const point = svgElement("circle", {
      cx: x(row.totalCost),
      cy: y(row.score),
      r: row.full ? 8 : 6,
      class: row.full ? "frontier-point primary" : "frontier-point",
    });
    const title = svgElement("title", {});
    title.textContent = `${row.label}: ${formatMetric(row.score, "performance_score")} at $${row.totalCost.toFixed(2)}`;
    point.append(title);
    svg.append(point);
  }
  const xLabel = svgElement("text", { x: width / 2, y: height - 8, class: "axis-label" });
  xLabel.textContent = "Total cost (USD)";
  const yLabel = svgElement("text", { x: 8, y: 14, class: "axis-label" });
  yLabel.textContent = "Performance";
  svg.append(xLabel, yLabel);
  return svg;
}

function resourcePlot(rows) {
  const metrics = [
    ["meanCost", "Mean cost"],
    ["outputTokens", "Output tokens"],
    ["steps", "Agent steps"],
    ["duration", "Duration"],
  ];
  const width = 620;
  const height = Math.max(180, rows.length * metrics.length * 20 + 54);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.classList.add("chart");
  let index = 0;
  for (const [key, label] of metrics) {
    const max = Math.max(...rows.map((row) => row[key] ?? 0), 1);
    for (const row of rows) {
      const y = 20 + index * 20;
      const bar = svgElement("rect", {
        x: 160,
        y: y - 11,
        width: ((row[key] ?? 0) / max) * 430,
        height: 13,
        rx: 3,
        class: row.full ? "resource-bar primary" : "resource-bar",
      });
      const title = svgElement("title", {});
      title.textContent = `${label} · ${row.label}: ${row[key] == null ? "missing" : formatNumber(row[key])}`;
      bar.append(title);
      const text = svgElement("text", { x: 2, y, class: "resource-label" });
      text.textContent = `${label} · ${row.label}`;
      svg.append(text, bar);
      index += 1;
    }
  }
  return svg;
}

function meanPresent(values) {
  const present = values.filter((value) => value != null);
  return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null;
}

function renderOverview(container) {
  const comparisons = filteredComparisons().sort(
    (left, right) => (right.uplift?.value ?? -Infinity) - (left.uplift?.value ?? -Infinity),
  );
  const lead = comparisons.find((item) => item.primary) ?? comparisons[0];
  const cards = document.createElement("div");
  cards.className = "summary-grid";
  cards.append(
    summaryCard(
      "Symnav uplift",
      lead?.uplift ? formatMetric(lead.uplift.value, "uplift") : "Pending full coverage",
      lead?.uplift
        ? `95% CI ${formatMetric(lead.uplift.lower_95, "uplift")} to ${formatMetric(lead.uplift.upper_95, "uplift")}`
        : "Confirmatory statistics require complete task pairs.",
      true,
    ),
    summaryCard(
      "Scored trials",
      `${payload.coverage.scored_slots}/${payload.coverage.planned_slots}`,
      `${payload.coverage.complete_tasks}/${payload.coverage.total_tasks} complete tasks`,
    ),
    summaryCard(
      "Primary evidence",
      lead?.demonstrated_improvement ? "Demonstrated" : "Not demonstrated",
      lead?.randomization_p_value == null
        ? "Paired test pending"
        : `Paired randomization p=${lead.randomization_p_value.toFixed(4)}`,
    ),
  );
  container.replaceChildren(cards, forestPlot(comparisons));
}

function renderLeaderboard(container) {
  const rows = payload.configurations
    .filter(
      (item) =>
        (state.configurationId === "all" || item.id === state.configurationId) &&
        (state.condition === "all" || item.condition === state.condition),
    )
    .map((item) => ({
      label: item.label,
      condition: item.condition,
      score: item.metrics.performance_score,
      coverage: `${item.coverage.complete_tasks}/${item.coverage.total_tasks}`,
      harness: "symnav-bench",
      full: item.full_symnav,
    }));
  if (state.configurationId === "all" && state.condition === "all") {
    rows.push(
      ...payload.official_references.map((item) => ({
        label: `${item.model} · ${item.effort}`,
        condition: "official reference",
        score: item.performance_score,
        coverage: `${Object.keys(item.task_scores).length}/${Object.keys(item.task_scores).length}`,
        harness: "mini-swe-agent",
        full: false,
      })),
    );
  }
  rows.sort((left, right) => (right.score ?? -Infinity) - (left.score ?? -Infinity));
  const table = dataTable(
    ["Rank", "Configuration", "Condition", "Performance", "Coverage", "Harness"],
    rows.map((row, index) => [
      index + 1,
      row.label,
      row.condition,
      row.score == null ? "—" : formatMetric(row.score, "performance_score"),
      row.coverage,
      row.harness,
    ]),
    rows.map((row) => (row.full ? "full-symnav" : "")),
  );
  container.replaceChildren(table);
}

function renderStatistics(container) {
  const comparisons = filteredComparisons();
  if (!comparisons.length) {
    container.replaceChildren(emptyState("No compatible stock/treatment comparisons match these filters."));
    return;
  }
  const grid = document.createElement("div");
  grid.className = "statistics-grid";
  for (const comparison of comparisons) {
    const section = document.createElement("section");
    section.className = comparison.primary ? "stat-card primary" : "stat-card";
    const heading = document.createElement("h3");
    heading.textContent = comparison.condition === "symnav" ? "Full symnav vs stock" : `${comparison.condition} vs stock`;
    const evidence = definitionList({
      uplift_points: comparison.uplift?.value == null ? "Pending" : formatMetric(comparison.uplift.value, "uplift"),
      lower_95: comparison.uplift?.lower_95 == null ? "Pending" : formatMetric(comparison.uplift.lower_95, "uplift"),
      upper_95: comparison.uplift?.upper_95 == null ? "Pending" : formatMetric(comparison.uplift.upper_95, "uplift"),
      randomization_p: comparison.randomization_p_value ?? "Pending",
      wins: comparison.wins,
      ties: comparison.ties,
      losses: comparison.losses,
      demonstrated: comparison.demonstrated_improvement,
      material: comparison.material_improvement,
    });
    section.append(heading, evidence, deltaPlot(comparison));
    grid.append(section);
  }
  container.replaceChildren(grid);
}

function filteredComparisons() {
  return payload.comparisons.filter(
    (item) =>
      (state.configurationId === "all" || item.base_configuration_id === state.configurationId) &&
      (state.condition === "all" || item.condition === state.condition),
  );
}

function summaryCard(label, value, detail, lead = false) {
  const card = document.createElement("article");
  card.className = lead ? "summary-card lead" : "summary-card";
  const labelNode = document.createElement("p");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  const detailNode = document.createElement("small");
  detailNode.textContent = detail;
  card.append(labelNode, valueNode, detailNode);
  return card;
}

function forestPlot(comparisons) {
  const section = document.createElement("section");
  section.className = "chart-section";
  const heading = document.createElement("h3");
  heading.textContent = "Paired symnav uplift by configuration";
  section.append(heading);
  if (!comparisons.some((item) => item.uplift)) {
    section.append(emptyState("Intervals appear after all planned trials for paired tasks are scored."));
    return section;
  }
  const width = 760;
  const left = 230;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${comparisons.length * 52 + 44}`, role: "img" });
  svg.classList.add("chart");
  const scale = (value) => left + ((value + 0.5) / 1) * (width - left - 24);
  svg.append(svgElement("line", { x1: scale(0), x2: scale(0), y1: 12, y2: comparisons.length * 52 + 22, class: "zero-line" }));
  comparisons.forEach((comparison, index) => {
    const y = 30 + index * 52;
    const label = svgElement("text", { x: 4, y: y + 5, class: "chart-label" });
    label.textContent = comparison.condition === "symnav" ? "Full symnav" : comparison.condition;
    svg.append(label);
    if (!comparison.uplift) return;
    svg.append(
      svgElement("line", {
        x1: scale(comparison.uplift.lower_95),
        x2: scale(comparison.uplift.upper_95),
        y1: y,
        y2: y,
        class: comparison.primary ? "interval primary" : "interval",
      }),
      svgElement("circle", {
        cx: scale(comparison.uplift.value),
        cy: y,
        r: 6,
        class: comparison.primary ? "point primary" : "point",
      }),
    );
  });
  section.append(svg);
  return section;
}

function deltaPlot(comparison) {
  const width = 520;
  const height = Math.max(90, comparison.task_deltas.length * 18 + 30);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.classList.add("chart", "delta-chart");
  const center = width / 2;
  svg.append(svgElement("line", { x1: center, x2: center, y1: 8, y2: height - 8, class: "zero-line" }));
  comparison.task_deltas.forEach((task, index) => {
    const y = 18 + index * 18;
    const bar = svgElement("line", {
      x1: center,
      x2: center + task.delta * (width / 2 - 18),
      y1: y,
      y2: y,
      class: task.delta >= 0 ? "delta positive" : "delta negative",
    });
    const title = svgElement("title", {});
    title.textContent = `${task.task}: ${formatMetric(task.delta, "uplift")}`;
    bar.append(title);
    svg.append(bar);
  });
  return svg;
}

function dataTable(headers, rows, rowClasses = []) {
  const table = document.createElement("table");
  table.className = "data-table";
  const header = table.createTHead().insertRow();
  for (const value of headers) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = value;
    header.append(cell);
  }
  const body = table.createTBody();
  rows.forEach((values, index) => {
    const row = body.insertRow();
    row.className = rowClasses[index] ?? "";
    for (const value of values) {
      const cell = row.insertCell();
      cell.textContent = String(value);
    }
  });
  return table;
}

function svgElement(name, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function emptyState(message) {
  const paragraph = document.createElement("p");
  paragraph.className = "empty-state";
  paragraph.textContent = message;
  return paragraph;
}

function renderMatrix(container, taskRows) {
  const enriched = taskRows.map((row) => ({
    ...row,
    metrics: { ...row.metrics, uplift: taskUplift(row) },
  }));
  const matrix = buildMatrix(enriched, state.metric, state.pivot);
  const table = document.createElement("table");
  table.className = "heatmap";
  const head = table.createTHead().insertRow();
  const corner = document.createElement("th");
  corner.scope = "col";
  corner.textContent = matrix.pivot === "tasks" ? "Task" : "Configuration";
  head.append(corner);
  for (const column of matrix.columnKeys) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = matrix.pivot === "tasks" ? configurationLabel(column) : column;
    if (column.endsWith(":symnav")) th.className = "full-symnav";
    head.append(th);
  }
  const body = table.createTBody();
  for (const rowKey of matrix.rowKeys) {
    const row = body.insertRow();
    const label = document.createElement("th");
    label.scope = "row";
    label.textContent = matrix.pivot === "tasks" ? rowKey : configurationLabel(rowKey);
    if (rowKey.endsWith(":symnav")) label.className = "full-symnav";
    row.append(label);
    for (const columnKey of matrix.columnKeys) {
      const value = matrix.values[rowKey][columnKey];
      const task = matrix.pivot === "tasks" ? rowKey : columnKey;
      const configuration = matrix.pivot === "tasks" ? columnKey : rowKey;
      const taskRow = enriched.find(
        (item) => item.task === task && `${item.configuration_id}:${item.condition}` === configuration,
      );
      const cell = row.insertCell();
      cell.className = "heat-cell";
      if (configuration.endsWith(":symnav")) cell.classList.add("full-symnav");
      if (value === null || value === undefined) {
        cell.classList.add("missing");
        cell.textContent = "—";
        cell.title = "Incomplete — no score assigned";
      } else if (Array.isArray(value)) {
        renderTrialDots(cell, value);
      } else {
        cell.textContent = formatMetric(value, state.metric);
        cell.style.setProperty("--heat", normalizedHeat(value, state.metric));
      }
      if (taskRow) {
        cell.tabIndex = 0;
        cell.setAttribute("role", "button");
        cell.setAttribute("aria-label", `Open ${task} · ${configuration}`);
        cell.addEventListener("click", () => openDrawer(taskRow));
        cell.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") openDrawer(taskRow);
        });
      }
    }
  }
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Select any cell to inspect scored trials, retries, resource use, and artifacts.";
  container.replaceChildren(hint, table);
}

function openDrawer(taskRow) {
  const drawer = document.querySelector("#drawer");
  const model = buildTrialDrawer(taskRow, payload.attempts);
  const heading = document.createElement("div");
  heading.className = "drawer-heading";
  const title = document.createElement("h2");
  title.textContent = model.task;
  const close = document.createElement("button");
  close.textContent = "Close";
  close.addEventListener("click", () => { drawer.hidden = true; });
  heading.append(title, close);
  const status = document.createElement("p");
  status.className = `status-line ${model.complete ? "complete" : "provisional"}`;
  status.textContent = `${model.condition} · ${model.complete ? "4/4 scored" : "incomplete"}`;
  const metrics = definitionList(model.metrics);
  const adoption = sectionWithList("Tool adoption", model.adoption ?? {});
  const scored = attemptSection("Scored trials", model.scoredTrials);
  const retries = attemptSection("Retry history", model.retryHistory);
  drawer.replaceChildren(heading, status, metrics, adoption, scored, retries);
  drawer.hidden = false;
}

function attemptSection(title, attempts) {
  const section = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  if (!attempts.length) {
    section.append(Object.assign(document.createElement("p"), { textContent: "None" }));
    return section;
  }
  for (const attempt of attempts) {
    const article = document.createElement("article");
    article.className = "attempt-card";
    const summary = document.createElement("strong");
    summary.textContent = `Rep ${attempt.repetition} · ${attempt.outcome}`;
    article.append(summary);
    if (attempt.retry_reason || attempt.scored_failure_reason) {
      article.append(` · ${attempt.retry_reason ?? attempt.scored_failure_reason}`);
    }
    const links = artifactLinks(attempt.artifacts);
    if (links.childElementCount) article.append(links);
    section.append(article);
  }
  return section;
}

function artifactLinks(artifacts = {}) {
  const links = document.createElement("div");
  links.className = "artifact-links";
  const values = {
    archive: artifacts.archive_url,
    ...artifacts.direct_urls,
  };
  for (const [label, url] of Object.entries(values)) {
    if (!url) continue;
    const link = document.createElement("a");
    link.href = url;
    link.textContent = label;
    link.target = "_blank";
    link.rel = "noreferrer";
    links.append(link);
  }
  return links;
}

function sectionWithList(title, values) {
  const section = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading, definitionList(values));
  return section;
}

function definitionList(values) {
  const list = document.createElement("dl");
  list.className = "metric-list";
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined || typeof value === "object") continue;
    const term = document.createElement("dt");
    term.textContent = key.replaceAll("_", " ");
    const definition = document.createElement("dd");
    definition.textContent = typeof value === "number" ? formatNumber(value) : String(value);
    list.append(term, definition);
  }
  return list;
}

function renderTrialDots(cell, outcomes) {
  cell.classList.add("trial-dots");
  for (const outcome of outcomes) {
    const dot = document.createElement("span");
    dot.className = `trial-dot ${outcome ?? "missing"}`;
    dot.title = outcome ?? "missing";
    cell.append(dot);
  }
}

function taskUplift(row) {
  if (row.condition === "stock") return null;
  const comparison = payload.comparisons.find(
    (item) => item.base_configuration_id === row.configuration_id && item.condition === row.condition,
  );
  return comparison?.task_deltas.find((item) => item.task === row.task)?.delta ?? null;
}

function configurationLabel(key) {
  const split = key.lastIndexOf(":");
  const configurationId = key.slice(0, split);
  const condition = key.slice(split + 1);
  const configuration = payload.configurations.find(
    (item) => item.id === configurationId && item.condition === condition,
  );
  return configuration?.label ?? key;
}

function formatMetric(value, metric) {
  if (["performance_score", "f2p", "p2p", "partial"].includes(metric)) {
    return `${Math.round(value * 100)}%`;
  }
  if (metric === "uplift") return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} pp`;
  if (metric === "cost") return `$${value.toFixed(2)}`;
  if (metric === "duration") return `${value.toFixed(0)}s`;
  return formatNumber(value);
}

function normalizedHeat(value, metric) {
  if (metric === "uplift") return String(Math.max(0, Math.min(1, value + 0.5)));
  if (["performance_score", "f2p", "p2p", "partial"].includes(metric)) return String(value);
  return String(Math.min(1, Math.log10(Math.max(0, value) + 1) / 4));
}

function formatNumber(value) {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function renderFilters() {
  const configurationOptions = [
    ["all", "All configurations"],
    ...uniqueBy(payload.configurations, "id").map((item) => [
      item.id,
      `${item.agent} · ${item.model} · ${item.effort}`,
    ]),
  ];
  const conditionOptions = [
    ["all", "All conditions"],
    ...[...new Set(payload.configurations.map((item) => item.condition))].map((condition) => [
      condition,
      condition === "symnav" ? "symnav (full)" : condition,
    ]),
  ];
  filters.replaceChildren(
    selectFilter("Configuration", "configurationId", configurationOptions),
    selectFilter("Condition", "condition", conditionOptions),
    selectFilter("Metric", "metric", METRICS.map(({ id, label }) => [id, label])),
    selectFilter("Matrix axes", "pivot", [
      ["tasks", "Tasks as rows"],
      ["configurations", "Configurations as rows"],
    ]),
  );
}

function selectFilter(label, stateKey, options) {
  const wrapper = document.createElement("label");
  wrapper.className = "filter";
  wrapper.append(label);
  const select = document.createElement("select");
  select.dataset.stateKey = stateKey;
  for (const [value, text] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.selected = state[stateKey] === value;
    select.append(option);
  }
  select.addEventListener("change", () => {
    state[stateKey] = select.value;
    render();
  });
  wrapper.append(select);
  return wrapper;
}

function uniqueBy(items, key) {
  return [...new Map(items.map((item) => [item[key], item])).values()];
}

function coverageLabel(coverage) {
  if (coverage.pilot) return "Pilot";
  if (coverage.provisional) return "Provisional";
  return "Complete";
}

render();
