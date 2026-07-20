const params = new URLSearchParams(location.search);
const attemptId = params.get("attempt");
const view = document.querySelector("#view");

const esc = (value) =>
  String(value ?? "").replace(/[&<>"]/g, (character) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character]),
  );

function num(value) {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

function clock(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(11, 19);
}

function durationSeconds(attempt) {
  const timing = attempt.timing || {};
  if (typeof timing.duration_seconds === "number") return timing.duration_seconds;
  const start = Date.parse(timing.started_at);
  const end = Date.parse(timing.finished_at);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.round((end - start) / 1000) : null;
}

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

async function load() {
  if (!attemptId) {
    view.innerHTML = `<p class="hint">No attempt id in the URL.</p>`;
    return;
  }
  let attempt;
  try {
    const response = await fetch(`../attempts/${attemptId}.json`);
    if (!response.ok) throw new Error(String(response.status));
    attempt = await response.json();
  } catch (error) {
    view.innerHTML = `<p class="hint">Could not load trajectory for <code>${esc(attemptId)}</code> (${esc(
      error.message,
    )}). It may not have been extracted for this study.</p>`;
    return;
  }
  renderHeader(attempt);
  const tabs = {
    chat: () => renderChat(attempt),
    environment: () => renderEnvironment(attempt),
    diff: () => renderDiff(attempt),
    verifier: () => renderVerifier(attempt),
    raw: () => renderRaw(attempt),
  };
  const buttons = [...document.querySelectorAll("#tabs button")];
  for (const button of buttons) {
    button.addEventListener("click", () => {
      for (const other of buttons) other.removeAttribute("aria-current");
      button.setAttribute("aria-current", "page");
      view.innerHTML = "";
      tabs[button.dataset.tab]();
    });
  }
  tabs.chat();
}

function renderHeader(attempt) {
  document.querySelector("#title").textContent = attempt.task || attemptId;
  document.title = `${attempt.task || "attempt"} · ${attempt.condition || ""}`;
  const badges = document.querySelector("#badges");
  const outcome = attempt.outcome || "unknown";
  const pass = outcome === "passed";
  badges.innerHTML = [
    `<span class="badge ${attempt.condition === "symnav" ? "symnav" : ""}">${esc(attempt.condition)}</span>`,
    `<span class="badge">rep ${esc(attempt.repetition)}</span>`,
    `<span class="badge ${pass ? "pass" : "fail"}">${esc(outcome)}</span>`,
    attempt.agent?.model ? `<span class="badge">${esc(attempt.agent.model)}</span>` : "",
    attempt.scored_failure_reason ? `<span class="badge fail">${esc(attempt.scored_failure_reason)}</span>` : "",
  ].join("");
  const totals = attempt.totals || {};
  const usage = attempt.usage || {};
  const rewards = attempt.rewards || {};
  const stats = [
    ["cost", totals.cost_usd != null ? `$${Number(totals.cost_usd).toFixed(3)}` : "—"],
    ["steps", num(totals.steps ?? usage.n_agent_steps)],
    ["output tok", num(totals.completion_tokens ?? usage.n_output_tokens)],
    ["input tok", num(totals.prompt_tokens ?? usage.n_input_tokens)],
    ["cached tok", num(totals.cached_tokens ?? usage.n_cache_tokens)],
    ["reasoning tok", num(totals.reasoning_tokens)],
    ["peak ctx", num(totals.peak_context_tokens ?? usage.peak_context_tokens)],
    ["duration", fmtDuration(durationSeconds(attempt))],
    ["f2p", rewards.f2p_total != null ? `${rewards.f2p_passed ?? "?"}/${rewards.f2p_total}` : "—"],
    ["p2p", rewards.p2p_total != null ? `${rewards.p2p_passed ?? "?"}/${rewards.p2p_total}` : "—"],
  ];
  document.querySelector("#stats").innerHTML = stats
    .map(([label, value]) => `<div class="stat"><small>${label}</small><strong>${esc(value)}</strong></div>`)
    .join("");
}

function tokenChip(tokens = {}) {
  const parts = [];
  if (tokens.completion) parts.push(`${num(tokens.completion)} out`);
  if (tokens.reasoning) parts.push(`${num(tokens.reasoning)} think`);
  if (tokens.cached) parts.push(`${num(tokens.cached)} cache`);
  return parts.join(" · ");
}

function firstLine(text) {
  const line = String(text || "").split("\n", 1)[0];
  return line.length > 200 ? line.slice(0, 200) + "…" : line;
}

function renderChat(attempt) {
  const container = document.createElement("div");
  for (const step of attempt.steps || []) {
    const source = step.source || "agent";
    const block = document.createElement("section");
    block.className = `step ${source}`;
    const tools = (step.tools || [])
      .map((tool) => {
        const isPatch = tool.tool === "apply_patch";
        const body = isPatch ? diffHtml(tool.command) : esc(tool.command);
        const out = tool.output
          ? `<pre class="block wrap">${esc(tool.output)}</pre>`
          : "";
        return `<details class="tool"${isPatch ? " open" : ""}>
          <summary><span class="tool-kind ${isPatch ? "patch" : ""}">${esc(tool.tool)}</span><span class="tool-cmd-inline">${esc(
            firstLine(isPatch ? "patch (" + (tool.command.match(/\*\*\* (Add|Update|Delete) File: (.*)/g) || []).length + " files)" : tool.command),
          )}</span></summary>
          <pre class="block ${isPatch ? "diff" : "wrap"}">${body}</pre>${out}</details>`;
      })
      .join("");
    block.innerHTML = `
      <div class="gutter">
        <span class="who ${source}">${esc(source)}</span>
        #${esc(step.i)} · ${esc(clock(step.t))}
        ${tokenChip(step.tokens) ? `<span class="chip">${esc(tokenChip(step.tokens))}</span>` : ""}
      </div>
      <div class="body">
        ${step.text ? `<pre class="msg">${esc(step.text)}</pre>` : ""}
        ${tools}
      </div>`;
    container.append(block);
  }
  if (!container.childElementCount) container.innerHTML = `<p class="hint">No steps recorded.</p>`;
  view.append(container);
}

function diffHtml(patch) {
  return String(patch || "")
    .split("\n")
    .map((line) => {
      if (line.startsWith("*** ")) return `<span class="file">${esc(line)}</span>`;
      if (line.startsWith("@@")) return `<span class="hunk">${esc(line)}</span>`;
      if (line.startsWith("+")) return `<span class="add">${esc(line)}</span>`;
      if (line.startsWith("-")) return `<span class="del">${esc(line)}</span>`;
      return esc(line);
    })
    .join("\n");
}

function renderEnvironment(attempt) {
  const harness = attempt.harness || {};
  const agent = attempt.agent || {};
  const rows = [
    ["agent", `${agent.name || "—"} ${agent.version || ""}`],
    ["model", agent.model],
    ["effort", harness.requested_effort],
    ["symnav sha", harness.symnav_sha],
    ["deep_swe sha", harness.deep_swe_sha],
    ["bundle hash", harness.bundle_hash],
    ["image digest", harness.image_digest],
    ["cwd", agent.cwd],
    ["git", agent.git ? `${agent.git.branch || ""} ${agent.git.commit_hash || ""}` : ""],
  ].filter(([, value]) => value);
  const info = `<div class="card"><h3>Environment</h3><dl class="kv">${rows
    .map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`)
    .join("")}</dl></div>`;
  const messages = (attempt.environment?.system_messages || [])
    .map(
      (message, index) =>
        `<div class="card"><h3>Injected instructions ${index + 1} (AGENTS.md · skills · permissions)</h3><pre class="block wrap">${esc(
          message,
        )}</pre></div>`,
    )
    .join("");
  view.innerHTML = info + (messages || `<p class="hint">No system instructions captured.</p>`);
}

function renderDiff(attempt) {
  const patches = attempt.patches || [];
  if (!patches.length) {
    view.innerHTML = `<p class="hint">No file edits (apply_patch calls) recorded for this attempt.</p>`;
    return;
  }
  view.innerHTML = patches
    .map((patch) => `<pre class="block diff">${diffHtml(patch)}</pre>`)
    .join("");
}

function renderVerifier(attempt) {
  const rewards = attempt.rewards || {};
  const tests = attempt.verifier?.tests || {};
  const failed = tests.failed || [];
  const summary = `<div class="card"><h3>Reward</h3><dl class="kv">
    <dt>reward</dt><dd>${esc(rewards.reward ?? "—")}</dd>
    <dt>fail-to-pass</dt><dd>${esc(rewards.f2p_passed ?? "?")} / ${esc(rewards.f2p_total ?? "?")}</dd>
    <dt>pass-to-pass</dt><dd>${esc(rewards.p2p_passed ?? "?")} / ${esc(rewards.p2p_total ?? "?")}</dd>
    <dt>partial</dt><dd>${esc(rewards.partial ?? "—")}</dd>
  </dl></div>`;
  const failing = failed.length
    ? `<div class="card"><h3>Failing tests (${failed.length})</h3><ul class="tests">${failed
        .map((name) => `<li class="failed">${esc(name)}</li>`)
        .join("")}</ul></div>`
    : `<p class="hint">No failing tests recorded${tests.passed ? ` · ${tests.passed} passed` : ""}.</p>`;
  view.innerHTML = summary + failing;
}

function renderRaw(attempt) {
  view.innerHTML = `<pre class="block wrap">${esc(JSON.stringify(attempt, null, 2))}</pre>`;
}

load();
