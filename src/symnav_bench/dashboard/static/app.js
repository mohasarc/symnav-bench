import { METRICS, createInitialState, filterTaskRows } from "./state.js";

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
  document.querySelector("#view-content").replaceChildren(
    Object.assign(document.createElement("p"), {
      textContent: `${taskRows.length} task rows match current filters`,
    }),
  );
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
