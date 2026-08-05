"use strict";

const fragment = new URLSearchParams(window.location.hash.slice(1));
const authority = fragment.get("token") || "";
window.history.replaceState(null, "", window.location.pathname + window.location.search);

const meta = document.getElementById("product-meta");
const taskList = document.getElementById("task-list");
const inventoryStatus = document.getElementById("inventory-status");
const inventoryDiagnostics = document.getElementById("inventory-diagnostics");
const detailTitle = document.getElementById("detail-title");
const detailStatus = document.getElementById("detail-status");
const detailBody = document.getElementById("detail-body");
const liveButton = document.getElementById("live-refresh");
const filterForm = document.getElementById("filters");
const queryInput = document.getElementById("query");
const statusInput = document.getElementById("status-filter");
const workflowInput = document.getElementById("workflow-filter");
const repositoryInput = document.getElementById("repository-filter");
const terminalInput = document.getElementById("terminal-filter");
const TIMELINE_LIMIT = 25;
let selectedTask = null;
let detailRequestGeneration = 0;
let detailRequestController = null;

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

async function api(path, {signal} = {}) {
  if (!authority) throw new Error("Launch authority is missing. Restart the Web UI from the CLI.");
  const response = await fetch(path, {
    method: "GET",
    credentials: "omit",
    cache: "no-store",
    headers: {"Authorization": "Bearer " + authority},
    signal
  });
  const value = await response.json();
  if (!response.ok || !value.ok) {
    const message = value.error && value.error.message ? value.error.message : "Request failed";
    const error = new Error(message);
    error.code = value.error && value.error.code ? value.error.code : "HTTP_FAILED";
    throw error;
  }
  return value;
}

function isCurrentDetailRequest(generation, taskId) {
  return generation === detailRequestGeneration && taskId === selectedTask;
}

function isAbortError(error) {
  return error && error.name === "AbortError";
}

function definitionList(entries) {
  const list = element("dl", "facts");
  for (const [term, value] of entries) {
    list.append(element("dt", null, term), element("dd", null, value == null ? "—" : value));
  }
  return list;
}

function booleanLabel(value) {
  return value == null ? null : value ? "Yes" : "No";
}

function compactList(container, heading, values) {
  if (!values.length) return;
  container.append(element("h4", null, heading));
  const list = element("ul", "compact-list");
  for (const value of values) list.append(element("li", null, value));
  container.append(list);
}

function budgetSummary(values) {
  if (!values) return null;
  return [
    ["verification", values.verification],
    ["review", values.review],
    ["rework", values.rework],
    ["total action", values.total_action]
  ].filter(([, value]) => value != null).map(([label, value]) => label + " " + value).join(" · ") || null;
}

function obligationSummary(obligation) {
  return [
    obligation.obligation_id,
    obligation.kind,
    obligation.state,
    obligation.attempts_used == null ? null : "attempts " + obligation.attempts_used,
    obligation.allowance == null ? null : "allowance " + obligation.allowance,
    obligation.remaining == null ? null : "remaining " + obligation.remaining
  ].filter(value => value !== null && value !== undefined && value !== "").join(" · ") || "Assurance obligation";
}

function timelineRecordSummary(record) {
  return [
    record.action_id || record.node || record.kind || "Recorded event",
    record.summary,
    record.recorded_at
  ].filter(Boolean).join(" · ");
}

function renderWhyNext(whyNext) {
  const section = element("section", "panel");
  const declaredAction = whyNext.declared_action;
  section.append(
    element("h3", null, "Why next"),
    element("p", null, whyNext.summary || "Current action readiness is unavailable."),
    definitionList([
      ["Outcome", whyNext.outcome],
      ["Readiness", whyNext.readiness],
      ["Status", whyNext.status],
      ["Terminal", booleanLabel(whyNext.terminal)],
      ["Node", whyNext.current_node],
      ["Declared action", declaredAction && declaredAction.action_id],
      ["Declared handler", declaredAction && declaredAction.handler],
      ["Action", whyNext.action_id],
      ["Handler", whyNext.handler],
      ["Blocked code", whyNext.blocked_code]
    ])
  );

  const blocker = whyNext.blocker;
  if (!blocker) return section;
  section.append(
    element("h4", null, "Blocker"),
    definitionList([
      ["Code", blocker.code],
      ["Reason", blocker.reason]
    ])
  );
  const drift = blocker.evidence && blocker.evidence.ambient_drift;
  if (drift) {
    section.append(definitionList([
      ["Ambient drift", booleanLabel(drift.present)],
      ["Changed paths", drift.path_count],
      ["Changed repository planes", drift.member_plane_count]
    ]));
    compactList(section, "Changed paths", (drift.paths || []).map(item => [
      item.repository_id,
      item.path,
      item.change_kind
    ].filter(Boolean).join(" · ")));
    compactList(section, "Changed repository planes", (drift.member_planes || []).map(item => [
      item.repository_id,
      (item.planes || []).join(", ")
    ].filter(Boolean).join(" · ")));
  }
  compactList(section, "Recovery choices", blocker.recovery_choices || []);
  return section;
}

function renderRecoveryAssurance(recovery) {
  const retry = recovery.retry;
  const assurance = recovery.assurance;
  const outstanding = recovery.outstanding_assurance || [];
  const exhausted = recovery.exhausted_assurance || [];
  if (!retry && !assurance && !outstanding.length && !exhausted.length) return null;
  const budget = assurance && assurance.budget;
  const section = element("section", "panel");
  section.append(
    element("h3", null, "Retry and assurance"),
    definitionList([
      ["Retry state", retry && retry.state],
      ["Attempts used", retry && (retry.attempts_used == null ? retry.used : retry.attempts_used)],
      ["Retry allowance", retry && (retry.max_attempts == null ? retry.allowance : retry.max_attempts)],
      ["Retry remaining", retry && retry.remaining],
      ["Assurance policy", assurance && assurance.policy],
      ["Assurance profile", assurance && assurance.profile],
      ["Assurance plan", assurance && assurance.plan_id],
      ["Assurance confidence", assurance && assurance.confidence],
      ["Maximum remaining actions", assurance && assurance.maximum_remaining_actions],
      ["Budget remaining", budget && budgetSummary(budget.remaining)],
      ["Budget used", budget && budgetSummary(budget.used)],
      ["Outstanding obligations", outstanding.length],
      ["Exhausted obligations", exhausted.length]
    ])
  );
  compactList(section, "Outstanding assurance", outstanding.map(obligationSummary));
  compactList(section, "Exhausted assurance", exhausted.map(obligationSummary));
  return section;
}

function renderRecoveryEvidence(recovery) {
  const freshness = recovery.freshness;
  const review = recovery.review;
  if (!freshness && !review) return null;
  const counts = freshness && freshness.counts;
  const section = element("section", "panel");
  section.append(
    element("h3", null, "Evidence status"),
    definitionList([
      ["Fresh artifacts", counts && counts.current],
      ["Stale artifacts", counts && counts.stale],
      ["Unknown freshness", counts && counts.unknown],
      ["Review outcome", review && (review.outcome || review.claimed_outcome)],
      ["Review status", review && review.status],
      ["Review current", review && booleanLabel(review.current)],
      ["Reviewer available", review && booleanLabel(review.reviewer_available)],
      ["Review findings", review && review.finding_count]
    ])
  );
  return section;
}

function renderRecovery(recovery) {
  const section = element("section", "panel");
  const state = recovery.state;
  const repositories = recovery.repositories;
  const recentTimeline = recovery.recent_timeline;
  section.append(
    element("h3", null, "Continue in Codex"),
    definitionList([
      ["Outcome", state && state.outcome],
      ["Status", state && state.status],
      ["Current node", state && state.current_node],
      ["Terminal", state && booleanLabel(state.terminal)],
      ["Repository set", repositories && repositories.repository_set_id],
      ["Repositories", repositories && repositories.count],
      ["Recent timeline", recentTimeline && (recentTimeline.returned + " of " + recentTimeline.total)]
    ])
  );
  compactList(section, "Repository identities", repositories ? repositories.repository_ids || [] : []);
  compactList(section, "Recent timeline", recentTimeline ? (recentTimeline.records || []).map(timelineRecordSummary) : []);
  const prompt = element("code", "prompt", recovery.prompt);
  const copy = element("button", null, "Copy prompt");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(recovery.prompt);
      detailStatus.textContent = "Follow-up prompt copied.";
    } catch (error) {
      detailStatus.textContent = "Clipboard access was unavailable; select the visible prompt to copy it.";
    }
  });
  section.append(prompt, copy);
  return section;
}

function renderTimeline(timeline, taskId) {
  const section = element("section", "panel");
  section.append(element("h3", null, "Timeline"));
  if (!timeline.records.length) {
    section.append(element("p", "muted", "No sealed records on this page."));
  } else {
    const list = element("ol", "timeline");
    list.start = timeline.page.offset + 1;
    for (const record of timeline.records) {
      const item = element("li");
      item.append(element("strong", null, record.action_id || record.node || "Recorded event"));
      if (record.summary) item.append(element("p", null, record.summary));
      const transition = record.transition && [record.transition.from, record.transition.to].filter(Boolean).join(" → ");
      item.append(element("span", "muted", [record.kind, transition, record.artifact_type, record.recorded_at].filter(Boolean).join(" · ") || "Details unavailable"));
      list.append(item);
    }
    section.append(list);
  }
  const actions = element("div", "timeline-actions");
  if (timeline.page.offset > 0) {
    const previous = element("button", "secondary", "Previous page");
    previous.type = "button";
    previous.addEventListener("click", () => loadDetail(taskId, false, Math.max(0, timeline.page.offset - timeline.page.limit)));
    actions.append(previous);
  }
  if (timeline.page.next_offset != null) {
    const next = element("button", null, "Next page");
    next.type = "button";
    next.addEventListener("click", () => loadDetail(taskId, false, timeline.page.next_offset));
    actions.append(next);
  }
  if (actions.childElementCount) section.append(actions);
  return section;
}

function renderDossier(dossier) {
  const section = element("section", "panel");
  section.append(element("h3", null, "Delivery Dossier"));
  if (!dossier) {
    section.append(element("p", "muted", "No terminal Delivery Dossier is available."));
    return section;
  }
  section.append(definitionList([
    ["Outcome", dossier.outcome],
    ["Current", dossier.current == null ? "Unknown" : dossier.current ? "Yes" : "No"],
    ["Schema", dossier.schema],
    ["Repository set", dossier.repository_set_id],
    ["Digest", dossier.digest]
  ]));
  const table = element("table", "coverage-table");
  const caption = element("caption", null, "Verification coverage");
  const head = element("tr");
  const body = element("tr");
  for (const label of ["Proven", "Waived", "Unverified"]) head.append(element("th", null, label));
  for (const key of ["proven", "waived", "unverified"]) body.append(element("td", null, dossier.coverage[key] || 0));
  table.append(caption, head, body);
  section.append(table);
  return section;
}

function renderDetail(response) {
  const result = response.result;
  const task = result.task;
  const recovery = result.recovery || {};
  detailBody.replaceChildren();
  detailTitle.textContent = task.task_id;
  detailStatus.textContent = "Health: " + result.health + ". " + result.why_next.summary;

  const overview = element("section", "panel");
  overview.append(
    element("h3", null, "Overview"),
    definitionList([
      ["Requirement", task.requirement],
      ["Workflow", task.workflow],
      ["Status", task.status],
      ["Current node", task.current_node],
      ["Revision", task.revision],
      ["Updated", task.updated_at]
    ])
  );

  const repositories = element("section", "panel");
  repositories.append(element("h3", null, "Repositories"));
  const repoList = element("ul", "compact-list");
  for (const repositoryId of task.repository_ids) repoList.append(element("li", null, repositoryId));
  if (!task.repository_ids.length) repoList.append(element("li", "muted", "No repositories recorded."));
  repositories.append(repoList);

  const contract = element("section", "panel");
  contract.append(
    element("h3", null, "Delivery contract"),
    element("p", null, task.contract.summary || "Summary unavailable"),
    definitionList([
      ["Contract revision", task.contract.revision],
      ["Acceptance criteria", task.contract.criterion_ids.length],
      ["Constraints", task.contract.constraint_count],
      ["Risks", task.contract.risk_count],
      ["Open questions", task.contract.open_question_count]
    ])
  );

  const whyNext = renderWhyNext(result.why_next);
  const recoveryAssurance = renderRecoveryAssurance(recovery);
  const recoveryEvidence = renderRecoveryEvidence(recovery);
  const renderedRecovery = renderRecovery(recovery);

  const artifacts = element("section", "panel");
  artifacts.append(element("h3", null, "Stored artifacts"));
  const artifactList = element("ul", "compact-list");
  for (const artifact of result.artifacts) {
    artifactList.append(element("li", null, [artifact.type, artifact.record_id].filter(Boolean).join(" · ")));
  }
  if (!result.artifacts.length) artifactList.append(element("li", "muted", "No stored artifacts yet."));
  artifacts.append(artifactList);

  detailBody.append(overview, repositories, contract, whyNext);
  if (recoveryAssurance) detailBody.append(recoveryAssurance);
  if (recoveryEvidence) detailBody.append(recoveryEvidence);
  detailBody.append(artifacts);
  if (result.live) {
    const live = element("section", "panel live-panel");
    live.append(element("h3", null, "Live observation"));
    if (result.live.action) {
      const obligation = result.live.action.current_obligation;
      const snapshot = result.live.snapshot_summary;
      const freshness = result.live.freshness;
      const review = result.live.review;
      const assurance = result.live.action.assurance;
      const retry = result.live.action.retry;
      live.append(definitionList([
        ["Snapshot", result.live.snapshot],
        ["Snapshot digest", snapshot && snapshot.digest],
        ["Observed repositories", snapshot && snapshot.repositories.length],
        ["Action", result.live.action.action_id],
        ["Handler", result.live.action.handler],
        ["Blocked", result.live.action.blocked ? "Yes" : "No"],
        ["Blocker code", result.live.action.blocked_details && result.live.action.blocked_details.code],
        ["Obligation", obligation && obligation.obligation_id],
        ["Obligation state", obligation && obligation.state],
        ["Retry remaining", retry && retry.remaining],
        ["Assurance profile", assurance && assurance.profile],
        ["Assurance confidence", assurance && assurance.confidence],
        ["Maximum remaining actions", assurance && assurance.maximum_remaining_actions],
        ["Fresh artifacts", freshness && freshness.counts.current],
        ["Stale artifacts", freshness && freshness.counts.stale],
        ["Review status", review && (review.outcome || review.claimed_outcome || review.status)],
        ["Review findings", review && review.finding_count]
      ]));
    } else {
      live.append(element("p", "muted", result.live.error ? result.live.error.code : "No current action"));
    }
    detailBody.append(live);
  }
  detailBody.append(
    renderTimeline(result.timeline, task.task_id),
    renderDossier(recovery.dossier || result.dossier),
    renderedRecovery
  );
}

async function loadDetail(taskId, live, offset = 0) {
  selectedTask = taskId;
  const requestGeneration = ++detailRequestGeneration;
  if (detailRequestController) detailRequestController.abort();
  const controller = new AbortController();
  detailRequestController = controller;
  liveButton.disabled = true;
  detailStatus.textContent = live ? "Capturing one live repository observation…" : "Loading stored detail…";
  try {
    const suffix = live ? "/live" : "";
    const page = "?offset=" + encodeURIComponent(offset) + "&limit=" + TIMELINE_LIMIT;
    const response = await api("/api/tasks/" + encodeURIComponent(taskId) + suffix + page, {signal: controller.signal});
    if (!isCurrentDetailRequest(requestGeneration, taskId)) return;
    renderDetail(response);
  } catch (error) {
    if (isAbortError(error) || !isCurrentDetailRequest(requestGeneration, taskId)) return;
    detailStatus.textContent = (error.code ? error.code + ": " : "") + error.message;
  } finally {
    if (requestGeneration === detailRequestGeneration) {
      detailRequestController = null;
      liveButton.disabled = !selectedTask;
    }
  }
}

function renderTasks(response) {
  taskList.replaceChildren();
  inventoryDiagnostics.replaceChildren();
  const result = response.result;
  inventoryStatus.textContent = result.page.total + " task(s); inventory health " + result.health + ".";
  for (const diagnostic of result.diagnostics) {
    const identity = diagnostic.task_id || diagnostic.entry || "unidentified entry";
    inventoryDiagnostics.append(element("li", null, diagnostic.code + ": " + identity));
  }
  for (const task of result.tasks) {
    const item = element("li", "task-card");
    const button = element("button", "task-select");
    button.type = "button";
    button.append(
      element("strong", null, task.task_id),
      element("span", null, task.workflow + " · " + task.status),
      element("span", "muted", task.contract.summary || "No contract summary")
    );
    button.addEventListener("click", () => loadDetail(task.task_id, false));
    item.append(button);
    taskList.append(item);
  }
  if (!result.tasks.length) taskList.append(element("li", "empty", "No matching current tasks."));
}

function inventoryQuery() {
  const query = new URLSearchParams();
  for (const [name, input] of [
    ["q", queryInput],
    ["status", statusInput],
    ["workflow", workflowInput],
    ["repository", repositoryInput],
    ["terminal", terminalInput]
  ]) {
    const value = input.value.trim();
    if (value) query.append(name, value);
  }
  return query.toString();
}

async function loadTasks() {
  inventoryStatus.textContent = "Loading stored task inventory…";
  try {
    const query = inventoryQuery();
    renderTasks(await api("/api/tasks" + (query ? "?" + query : "")));
  } catch (error) {
    taskList.replaceChildren();
    inventoryDiagnostics.replaceChildren();
    inventoryStatus.textContent = (error.code ? error.code + ": " : "") + error.message;
  }
}

async function initialize() {
  try {
    const response = await api("/api/meta");
    meta.textContent = response.result.product + " " + response.result.version;
  } catch (error) {
    meta.textContent = error.message;
  }
  await loadTasks();
}

filterForm.addEventListener("submit", event => { event.preventDefault(); loadTasks(); });
document.getElementById("clear-filters").addEventListener("click", () => { filterForm.reset(); loadTasks(); });
document.getElementById("refresh-tasks").addEventListener("click", loadTasks);
liveButton.addEventListener("click", () => { if (selectedTask) loadDetail(selectedTask, true); });
initialize();
