import assert from "node:assert/strict";
import test from "node:test";

import {
  ADOPTION_FILTERS,
  METRICS,
  buildMatrix,
  buildTrialDrawer,
  createInitialState,
  filterTaskRows,
  formatPerformanceScore,
  orderConfigurations,
  orderVersions,
  pivotMatrix,
  rowsWithAdoptionFilter,
} from "../src/symnav_bench/dashboard/static/state.js";

const tasks = [
  task("stock", "alpha", 0.25),
  task("symnav", "alpha", 0.75),
  task("stock", "beta", null, false),
  task("symnav", "beta", 0.5),
];

test("metric selector exposes effectiveness, resources, and failures", () => {
  assert.deepEqual(
    METRICS.map(({ id }) => id),
    [
      "performance_score",
      "binary_trials",
      "f2p",
      "p2p",
      "partial",
      "uplift",
      "cost",
      "output_tokens",
      "steps",
      "duration",
      "failures",
    ],
  );
});

test("performance scores preserve two decimal places", () => {
  assert.equal(formatPerformanceScore(0.357142857), "35.71%");
  assert.equal(formatPerformanceScore(0), "0.00%");
});

test("task matrix defaults to task rows with adjacent stock and full symnav", () => {
  const state = createInitialState({ study: { id: "study" }, tasks });
  const configurations = orderConfigurations([
    { id: "config", condition: "symnav", full_symnav: true },
    { id: "config", condition: "stock", full_symnav: false },
  ]);
  const matrix = buildMatrix(tasks, state.metric, state.pivot);

  assert.equal(state.studyId, "study");
  assert.equal(state.metric, "performance_score");
  assert.equal(state.pivot, "tasks");
  assert.deepEqual(configurations.map(({ condition }) => condition), ["stock", "symnav"]);
  assert.equal(configurations[1].full_symnav, true);
  assert.deepEqual(matrix.rowKeys, ["alpha", "beta"]);
  assert.deepEqual(matrix.columnKeys, ["config:stock", "config:symnav"]);
  assert.equal(matrix.values["alpha"]["config:symnav"], 0.75);
  assert.equal(matrix.values["beta"]["config:stock"], null);
});

test("filters retain explicit study, configuration, and condition", () => {
  const state = {
    ...createInitialState({ study: { id: "study" }, tasks }),
    configurationId: "config",
    condition: "symnav",
  };

  const filtered = filterTaskRows(tasks, state);

  assert.equal(state.studyId, "study");
  assert.equal(state.configurationId, "config");
  assert.equal(state.condition, "symnav");
  assert.deepEqual(filtered.map(({ task }) => task), ["alpha", "beta"]);
});

test("pivot swaps axes without changing cell values", () => {
  const original = buildMatrix(tasks, "performance_score", "tasks");
  const pivoted = pivotMatrix(original);

  assert.deepEqual(pivoted.rowKeys, original.columnKeys);
  assert.deepEqual(pivoted.columnKeys, original.rowKeys);
  assert.equal(pivoted.values["config:symnav"].alpha, 0.75);
  assert.equal(pivoted.values["config:stock"].beta, null);
});

test("cell drawer contains scored trials, retries, metrics, and artifact links", () => {
  const attempts = [
    attempt("passed", "scored-1", 1),
    attempt("failed", "scored-2", 2),
    { ...attempt("retryable_error", "retry-1", 2), retry_reason: "provider" },
  ];

  const drawer = buildTrialDrawer(tasks[1], attempts);

  assert.deepEqual(drawer.scoredTrials.map(({ attempt_id }) => attempt_id), ["scored-1", "scored-2"]);
  assert.deepEqual(drawer.retryHistory.map(({ retry_reason }) => retry_reason), ["provider"]);
  assert.equal(drawer.metrics.partial, 0.75);
  assert.equal(drawer.adoption.mean_symnav_calls, 2);
  assert.equal(drawer.artifacts[0].direct_urls.patch, "patch.diff");
  assert.equal(drawer.artifacts[0].archive_path, "attempts/scored-1");
  assert.equal(drawer.scoredTrials[0].artifacts.archive_sha256, "a".repeat(64));
});

test("adoption filter recomputes task score from only symnav-invoked or idle trials", () => {
  const row = task("symnav", "alpha", 0.75);
  const attempts = [
    adoptionAttempt(1, true, 1),
    adoptionAttempt(2, true, 0),
    adoptionAttempt(3, false, 1),
    adoptionAttempt(4, false, 1),
  ];

  assert.equal(rowsWithAdoptionFilter([row], attempts, "all")[0], row);

  const invoked = rowsWithAdoptionFilter([row], attempts, "invoked")[0];
  assert.equal(invoked.metrics.performance_score, 0.5);
  assert.equal(invoked.trials.length, 2);

  const idle = rowsWithAdoptionFilter([row], attempts, "idle")[0];
  assert.equal(idle.metrics.performance_score, 1);
  assert.equal(idle.trials.length, 2);
});

test("adoption filter yields no scored trials for stock rows under invoked", () => {
  const row = task("stock", "alpha", 0.5);
  const attempts = [
    { ...adoptionAttempt(1, false, 1), condition: "stock" },
    { ...adoptionAttempt(2, false, 0), condition: "stock" },
  ];

  const invoked = rowsWithAdoptionFilter([row], attempts, "invoked")[0];

  assert.equal(invoked.metrics.performance_score, null);
  assert.equal(invoked.trials.length, 0);
});

test("adoption filter selector exposes all, invoked, and idle", () => {
  assert.deepEqual(
    ADOPTION_FILTERS.map(({ id }) => id),
    ["all", "invoked", "idle"],
  );
});

test("version ordering uses first parent for main and sequence for previews", () => {
  const versions = orderVersions(
    [
      { sha: "preview-2", kind: "pull_request", evaluation_sequence: 5 },
      { sha: "main-2", kind: "main", evaluation_sequence: 9 },
      { sha: "preview-1", kind: "pull_request", evaluation_sequence: 3 },
      { sha: "main-1", kind: "main", evaluation_sequence: 8 },
    ],
    { "main-1": 1, "main-2": 2 },
  );

  assert.deepEqual(versions.map(({ sha }) => sha), ["main-1", "main-2", "preview-1", "preview-2"]);
});

function task(condition, name, score, complete = true) {
  return {
    configuration_id: "config",
    configuration_key: "codex:terra:medium:0.31.0",
    condition,
    full_symnav: condition === "symnav",
    task: name,
    complete,
    metrics: {
      performance_score: score,
      f2p: score,
      p2p: 1,
      partial: 0.75,
      cost: 2,
      output_tokens: 10,
      steps: 3,
      duration: 4,
      failures: score === 0 ? 1 : 0,
    },
    trials: [],
    adoption: { mean_symnav_calls: condition === "symnav" ? 2 : 0 },
  };
}

function adoptionAttempt(repetition, usedSymnav, reward) {
  return {
    configuration_id: "config",
    condition: "symnav",
    task: "alpha",
    repetition,
    outcome: reward === 1 ? "passed" : "failed",
    rewards: { reward, f2p: reward },
    adoption: { used_symnav: usedSymnav },
  };
}

function attempt(outcome, attemptId, repetition) {
  return {
    configuration_id: "config",
    condition: "symnav",
    task: "alpha",
    repetition,
    attempt_id: attemptId,
    outcome,
    artifacts: {
      archive_url: "https://example.test/batch.tar.gz",
      archive_sha256: "a".repeat(64),
      archive_path: `attempts/${attemptId}`,
      direct_urls: { patch: "patch.diff" },
    },
  };
}
