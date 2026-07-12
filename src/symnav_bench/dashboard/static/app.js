import { createInitialState } from "./state.js";

const payload = JSON.parse(document.querySelector("#dashboard-payload").textContent);
const state = createInitialState(payload);
const view = document.querySelector("#view");

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

function render() {
  const heading = document.querySelector(`[data-view="${state.view}"]`).textContent;
  view.innerHTML = `<section class="panel"><h2>${heading}</h2><div id="view-content"></div></section>`;
  document.querySelector("#view-content").replaceChildren(
    Object.assign(document.createElement("p"), {
      textContent: `${payload.configurations.length} configuration conditions · ${payload.tasks.length} task rows`,
    }),
  );
}

function coverageLabel(coverage) {
  if (coverage.pilot) return "Pilot";
  if (coverage.provisional) return "Provisional";
  return "Complete";
}

render();
