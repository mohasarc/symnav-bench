export const METRICS = [
  ["performance_score", "Performance score"],
  ["binary_trials", "Individual trials"],
  ["f2p", "F2P"],
  ["p2p", "P2P"],
  ["partial", "Partial"],
  ["uplift", "Uplift"],
  ["cost", "Cost"],
  ["output_tokens", "Output tokens"],
  ["steps", "Steps"],
  ["duration", "Duration"],
  ["failures", "Failures"],
].map(([id, label]) => ({ id, label }));

export const ADOPTION_FILTERS = [
  ["all", "All trials"],
  ["invoked", "symnav invoked"],
  ["idle", "symnav idle"],
].map(([id, label]) => ({ id, label }));

export function createInitialState(payload) {
  return {
    studyId: payload.study.id,
    view: "overview",
    metric: "performance_score",
    pivot: "tasks",
    configurationId: "all",
    condition: "all",
    adoptionFilter: "all",
    selectedCell: null,
  };
}

export function rowsWithAdoptionFilter(rows, attempts, mode) {
  if (!mode || mode === "all") {
    return rows;
  }
  const wantInvoked = mode === "invoked";
  return rows.map((row) => {
    const trials = attempts.filter(
      (attempt) =>
        attempt.configuration_id === row.configuration_id &&
        attempt.condition === row.condition &&
        attempt.task === row.task &&
        attempt.outcome !== "retryable_error" &&
        Boolean(attempt.adoption?.used_symnav) === wantInvoked,
    );
    return {
      ...row,
      trials: trials
        .map((attempt) => ({ outcome: attempt.outcome, repetition: attempt.repetition }))
        .sort((left, right) => left.repetition - right.repetition),
      metrics: {
        ...row.metrics,
        performance_score: meanReward(trials, (rewards) => rewards.reward),
        f2p: meanReward(trials, (rewards) => rewards.f2p),
      },
    };
  });
}

function meanReward(trials, select) {
  const values = trials
    .map((attempt) => select(attempt.rewards ?? {}))
    .filter((value) => typeof value === "number");
  if (values.length === 0) {
    return null;
  }
  return values.reduce((total, value) => total + value, 0) / values.length;
}

export function filterTaskRows(rows, state) {
  return rows.filter(
    (row) =>
      (state.configurationId === "all" || row.configuration_id === state.configurationId) &&
      (state.condition === "all" || row.condition === state.condition),
  );
}

export function formatPerformanceScore(value) {
  return `${(value * 100).toFixed(2)}%`;
}

export function orderConfigurations(configurations) {
  const conditionOrder = (condition) =>
    condition === "stock" ? 0 : condition === "symnav" ? 1 : 2;
  return [...configurations].sort(
    (left, right) =>
      left.configuration_key?.localeCompare(right.configuration_key ?? "") ||
      conditionOrder(left.condition) - conditionOrder(right.condition) ||
      left.condition.localeCompare(right.condition),
  );
}

export function buildMatrix(rows, metric, pivot = "tasks") {
  const rowKeys = [...new Set(rows.map((row) => row.task))].sort();
  const columnKeys = [
    ...new Set(
      orderConfigurations(rows).map(
        (row) => `${row.configuration_id}:${row.condition}`,
      ),
    ),
  ];
  const values = Object.fromEntries(
    rowKeys.map((task) => [task, Object.fromEntries(columnKeys.map((key) => [key, null]))]),
  );
  const rowsByCell = {};
  for (const row of rows) {
    const column = `${row.configuration_id}:${row.condition}`;
    values[row.task][column] =
      metric === "binary_trials"
        ? row.trials.map((trial) => trial.outcome)
        : (row.metrics[metric] ?? null);
    rowsByCell[`${row.task}\u0000${column}`] = row;
  }
  const matrix = { rowKeys, columnKeys, values, rowsByCell, pivot: "tasks" };
  return pivot === "configurations" ? pivotMatrix(matrix) : matrix;
}

export function pivotMatrix(matrix) {
  const values = Object.fromEntries(
    matrix.columnKeys.map((column) => [
      column,
      Object.fromEntries(matrix.rowKeys.map((row) => [row, matrix.values[row][column]])),
    ]),
  );
  return {
    rowKeys: matrix.columnKeys,
    columnKeys: matrix.rowKeys,
    values,
    rowsByCell: matrix.rowsByCell,
    pivot: matrix.pivot === "tasks" ? "configurations" : "tasks",
  };
}

export function buildTrialDrawer(taskRow, attempts) {
  const matching = attempts.filter(
    (attempt) =>
      attempt.configuration_id === taskRow.configuration_id &&
      attempt.condition === taskRow.condition &&
      attempt.task === taskRow.task,
  );
  const scoredTrials = matching
    .filter((attempt) => attempt.outcome !== "retryable_error")
    .sort((left, right) => left.repetition - right.repetition);
  const retryHistory = matching
    .filter((attempt) => attempt.outcome === "retryable_error")
    .sort((left, right) => left.written_at?.localeCompare(right.written_at ?? "") ?? 0);
  return {
    task: taskRow.task,
    condition: taskRow.condition,
    complete: taskRow.complete,
    metrics: taskRow.metrics,
    adoption: taskRow.adoption,
    scoredTrials,
    retryHistory,
    artifacts: matching.map((attempt) => attempt.artifacts).filter(Boolean),
  };
}

export function orderVersions(versions, firstParentPositions = {}) {
  return [...versions].sort((left, right) => {
    const leftGroup = left.kind === "main" ? 0 : 1;
    const rightGroup = right.kind === "main" ? 0 : 1;
    const leftPosition =
      left.kind === "main"
        ? (firstParentPositions[left.sha] ?? Number.MAX_SAFE_INTEGER)
        : left.evaluation_sequence;
    const rightPosition =
      right.kind === "main"
        ? (firstParentPositions[right.sha] ?? Number.MAX_SAFE_INTEGER)
        : right.evaluation_sequence;
    return leftGroup - rightGroup || leftPosition - rightPosition;
  });
}
