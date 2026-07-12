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
  document.querySelector("#view-content").replaceChildren(
    Object.assign(document.createElement("p"), {
      textContent: `${taskRows.length} task rows match current filters`,
    }),
  );
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
