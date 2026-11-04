(() => {
  'use strict';

  const STORE = {
    apiBase: 'abacus.apiBase',
    recentRuns: 'abacus.recentRunIds',
    theme: 'abacus.theme',
  };
  const builtInProblems = [
    {
      problem_id: 'p01_true_sort',
      claim: 'The function returns every input integer in ascending order and preserves duplicates.',
      target_id: 'sort_correct',
      contract_id: 'integer-sort-preserves-multiplicity-v1',
      oracle_id: 'sorted_integer_list_v1',
    },
    {
      problem_id: 'p02_false_sort',
      claim: 'The function returns every input integer in ascending order and preserves duplicates.',
      target_id: 'sort_deduplicating',
      contract_id: 'integer-sort-preserves-multiplicity-v1',
      oracle_id: 'sorted_integer_list_v1',
    },
  ];
  const demoRuns = [
    {
      run_id: 'demo-7f2c9a', problem_id: 'p02_false_sort', state: 'finished', run_status: 'complete',
      created_at_utc: '2026-11-04T08:42:12+00:00', updated_at_utc: '2026-11-04T08:42:13+00:00',
      finished_at_utc: '2026-11-04T08:42:13+00:00', outcome: 'REFUTED',
      record: { run_status: 'complete', completion: { status: 'complete', scheduled_case_count: 12, completed_case_count: 12 },
        outcome: { outcome: 'REFUTED', reason: 'CONFIRMED_COUNTEREXAMPLE', message: 'A contract-valid counterexample was confirmed by replay.', test_count: 5, counterexample: { input: [4, 4], actual: [4], expected: [4, 4], test_id: 'fixed-4', replay_confirmed: true } },
        evidence: [
          { test_id: 'fixed-1', method: 'fixed', status: 'completed', input_value: [], actual: [], expected: [], replay_confirmed: null },
          { test_id: 'fixed-4', method: 'fixed', status: 'completed', input_value: [4, 4], actual: [4], expected: [4, 4], replay_confirmed: true, category: 'CASE_FAILED' },
          { test_id: 'proposal-1', method: 'proposals', status: 'completed', input_value: [5, 2, 5], actual: [2, 5], expected: [2, 5, 5], replay_confirmed: true, category: 'CASE_FAILED' },
        ],
        model_proposals: [{ source: 'offline_fixture', status: 'evaluated' }],
        generation: { scheduled_case_count: 12, case_counts_by_method: { fixed: 4, hypothesis: 6, proposals: 2 } },
        usage: { duration_seconds: 0.04, model_call_count: 0 },
      },
    },
    {
      run_id: 'demo-c18b40', problem_id: 'p01_true_sort', state: 'finished', run_status: 'complete',
      created_at_utc: '2026-11-03T16:18:07+00:00', updated_at_utc: '2026-11-03T16:18:08+00:00',
      finished_at_utc: '2026-11-03T16:18:08+00:00', outcome: 'TESTS_PASSED',
      record: { run_status: 'complete', completion: { status: 'complete', scheduled_case_count: 12, completed_case_count: 12 },
        outcome: { outcome: 'TESTS_PASSED', reason: 'NO_COUNTEREXAMPLE_FOUND', message: 'No counterexample was found in these tests.', test_count: 12, counterexample: null },
        evidence: [
          { test_id: 'fixed-1', method: 'fixed', status: 'completed', input_value: [], actual: [], expected: [], replay_confirmed: null },
          { test_id: 'fixed-3', method: 'fixed', status: 'completed', input_value: [3, -1, 3, 0], actual: [-1, 0, 3, 3], expected: [-1, 0, 3, 3], replay_confirmed: null },
        ],
        model_proposals: [], generation: { scheduled_case_count: 12, case_counts_by_method: { fixed: 4, hypothesis: 6, proposals: 2 } },
        usage: { duration_seconds: 0.03, model_call_count: 0 },
      },
    },
  ];

  const state = {
    view: 'overview', apiBase: localStorage.getItem(STORE.apiBase) || '', apiKey: '',
    problems: [...builtInProblems], apiReady: null, connectionError: '', connected: false,
    demo: false, search: '', currentRun: null, busy: false, error: '', clients: null,
    adminAllowed: false, adminForbidden: false, metrics: null, healthChecking: false,
    theme: localStorage.getItem(STORE.theme) || 'light',
  };
  let toastTimer;
  let introPending = true;
  const app = document.getElementById('app');

  const icons = {
    overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    problems: '<path d="M12 3 21 8v8l-9 5-9-5V8l9-5Z"/><circle cx="12" cy="12" r="2"/>',
    new: '<path d="M12 5v14M5 12h14"/>',
    runs: '<path d="M4 5h16M4 12h16M4 19h16"/><circle cx="7" cy="5" r="1"/><circle cx="7" cy="12" r="1"/><circle cx="7" cy="19" r="1"/>',
    admin: '<path d="M12 3 20 6v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6l8-3Z"/><path d="m9 12 2 2 4-4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.5 2.6-1.7-.7a8 8 0 0 1-1.5.9l-.3 1.8h-3l-.3-1.8a8 8 0 0 1-1.5-.9l-1.7.7-1.5-2.6 1.4-1.1a7 7 0 0 1 0-1.8l-1.4-1.1 1.5-2.6 1.7.7a8 8 0 0 1 1.5-.9l.3-1.8h3l.3 1.8a8 8 0 0 1 1.5.9l1.7-.7 1.5 2.6-1.4 1.1a7 7 0 0 1 0 1.7Z" transform="translate(-1 -1) scale(.97)"/>',
    search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="m16 16 4.5 4.5"/>',
    arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    moon: '<path d="M20.8 14.2A8.8 8.8 0 0 1 9.8 3.2 8.9 8.9 0 1 0 20.8 14.2Z"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 11.6-2L20 12M4 12l2.9 5a7 7 0 0 0 11.6-2"/>',
  };
  const icon = (name, cls = '') => `<span class="icon ${cls}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[name] || ''}</svg></span>`;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const jsonText = (value) => JSON.stringify(value ?? null, null, 2);
  const problemFor = (id) => state.problems.find((problem) => problem.problem_id === id) || builtInProblems.find((problem) => problem.problem_id === id) || { problem_id: id, claim: 'Supported evaluation problem' };
  const titleFor = (view) => ({ overview: 'Overview', problems: 'Problems', new: 'New evaluation', runs: 'Run history', run: 'Run details', admin: 'Admin', settings: 'Settings' }[view] || 'Overview');
  const navItems = [
    ['overview', 'Overview'], ['problems', 'Problems'], ['new', 'New evaluation'], ['runs', 'Run history'], ['admin', 'Admin'], ['settings', 'Settings'],
  ];
  const logo = () => `<svg class="brand-mark" viewBox="0 0 112 112" fill="none" aria-hidden="true"><path d="M56 7 96 30v52l-40 23L16 82V30L56 7Z" stroke="#191917" stroke-width="5" stroke-linejoin="round"/><circle cx="56" cy="56" r="8" fill="#ef583c"/></svg>`;
  const relativeDate = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  };
  const tinyId = (id) => String(id || '').startsWith('demo-') ? id : String(id || '').slice(0, 8);
  const badge = (value, extra = '') => `<span class="badge ${extra}">${esc(value || 'Unknown')}</span>`;
  const outcomeClass = (outcome) => ({ REFUTED: 'red', TESTS_PASSED: 'green', UNRESOLVED: 'amber', ERROR: 'red' }[outcome] || '');
  const outcomeSummary = (outcome) => ({
    REFUTED: 'A valid counterexample was confirmed and replayed.',
    TESTS_PASSED: 'No counterexample was found in these tests. This does not prove correctness.',
    UNRESOLVED: 'The available evidence did not settle the claim.',
    ERROR: 'The evaluation failed. This is not a verdict.',
  }[outcome] || 'The run has not produced a final verdict.');
  const statusSummary = (status) => ({ queued: 'Waiting in queue', running: 'Evaluation in progress', finished: 'Evaluation finished', failed: 'Evaluation failed', interrupted: 'Evaluation interrupted' }[status] || status || 'Unknown');
  const allRuns = () => state.demo ? demoRuns : readRecentIds().map((entry) => entry.summary).filter(Boolean);
  const readRecentIds = () => {
    try { const value = JSON.parse(localStorage.getItem(STORE.recentRuns) || '[]'); return Array.isArray(value) ? value : []; }
    catch { return []; }
  };
  const saveRecentRun = (run) => {
    if (state.demo || !run?.run_id) return;
    const rows = readRecentIds().filter((entry) => entry.id !== run.run_id);
    rows.unshift({ id: run.run_id, summary: { run_id: run.run_id, problem_id: run.problem_id, state: run.state, outcome: run.outcome, created_at_utc: run.created_at_utc, run_status: run.run_status } });
    localStorage.setItem(STORE.recentRuns, JSON.stringify(rows.slice(0, 20)));
  };

  function render() {
    document.body.classList.toggle('dark', state.theme === 'dark');
    const connectionText = state.demo ? 'Demo data' : state.connected ? 'API connected' : state.apiReady === false ? 'API unavailable' : 'Not connected';
    const connectionState = state.demo ? 'demo' : state.connected ? 'ready' : state.apiReady === false ? 'error' : '';
    app.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <a class="brand ${introPending ? 'logo-intro' : ''}" href="#overview" aria-label="Abacus overview">${logo()}<span class="brand-word">ABACUS</span></a>
          <div class="nav-label">Workspace</div>
          <nav class="nav" aria-label="Main navigation">
            ${navItems.filter(([key]) => key !== 'admin' || (state.connected && state.adminAllowed && !state.demo)).map(([key, label]) => `<button type="button" class="nav-button ${state.view === key || (state.view === 'run' && key === 'runs') ? 'active' : ''}" data-view="${key}" aria-label="${label}">${icon(key)}<span>${label}</span></button>`).join('')}
          </nav>
          <div class="sidebar-bottom">
            <div class="pilot-note"><div class="pilot-note-title"><i class="pilot-dot"></i>Focused pilot</div><p>Two built-in sorting problems. Finite test results are evidence, not a proof.</p></div>
            <div class="profile"><div class="profile-icon">A</div><div class="profile-copy"><div class="profile-name">Abacus operator</div><div class="profile-state">${state.connected ? 'Connected for this tab' : state.demo ? 'Preview mode' : 'Local workspace'}</div></div></div>
          </div>
        </aside>
        <div class="main-wrap">
          <header class="topbar">
            <div class="breadcrumbs"><span>Abacus</span><span class="crumb-sep">/</span><strong class="crumb-current">${esc(titleFor(state.view))}</strong></div>
            <div class="top-actions"><span class="connection"><i class="status-dot ${connectionState}"></i>${esc(connectionText)}</span><button class="theme-toggle" data-action="theme" type="button" aria-label="Toggle dark mode">${icon('moon')}</button></div>
          </header>
          <main class="content" id="main-content">${state.demo ? demoBanner() : ''}${viewContent()}</main>
        </div>
      </div><div id="toast-slot" aria-live="polite"></div>`;
    introPending = false;
    if (!state.connected && !state.demo && state.apiReady === null) checkPublicHealth();
  }

  function demoBanner() {
    return `<div class="demo-banner"><span><strong>Demo data.</strong> These sample records are illustrative and are not connected to your API.</span><button class="button small" type="button" data-action="exit-demo">Exit demo</button></div>`;
  }

  function heading(kicker, title, description, actions = '') {
    return `<div class="page-heading"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
  }

  function viewContent() {
    if (state.view === 'problems') return problemsView();
    if (state.view === 'new') return newRunView();
    if (state.view === 'runs') return runsView();
    if (state.view === 'run') return runView();
    if (state.view === 'admin') return adminView();
    if (state.view === 'settings') return settingsView();
    return overviewView();
  }

  function overviewView() {
    const runs = allRuns().slice(0, 3);
    const readiness = state.demo ? 'Demo preview' : state.apiReady === true ? 'Ready' : state.apiReady === false ? 'Unavailable' : 'Checking';
    const readinessCopy = state.demo ? 'Sample data only; no API requests are being made.' : state.apiReady === true ? 'The API and its database answered the readiness check.' : state.apiReady === false ? 'Start the API, then check its status again.' : 'Checking the API readiness endpoint.';
    const action = state.connected ? `<button class="button primary" data-view="new">Start an evaluation ${icon('arrow')}</button>` : `<button class="button primary" data-view="settings">Connect API ${icon('arrow')}</button>`;
    return `${heading('Evidence workspace', 'Understand what the tests show.', 'Abacus checks the supported claim against a trusted oracle and keeps the evidence attached to each run.')}
      <div class="overview-grid">
        <section class="card welcome"><div class="welcome-content"><div class="eyebrow">Python claim evaluation</div><h2>Small claims. Careful evidence.</h2><p>Inspect a supported sorting claim, run the checked evaluation, then review the evidence and any replay-confirmed counterexample.</p><div class="welcome-actions">${action}<button class="button" data-view="problems">Browse problems</button></div></div></section>
        <section class="card readiness-card"><div class="readiness-main"><div class="eyebrow">Service status</div><div class="readiness-value"><i class="readiness-indicator ${state.apiReady === true ? 'ready' : ''}"></i>${esc(readiness)}</div><div class="readiness-sub">${esc(readinessCopy)}</div></div><div class="readiness-foot"><span>${state.demo ? 'Preview workspace' : 'GET /health/ready'}</span><button class="button ghost small" data-action="refresh-health">${icon('refresh')} Refresh</button></div></section>
      </div>
      <div class="overview-lower">
        <section class="card"><div class="card-head"><div><h2>Supported problems</h2><p>Two built-in integer sorting claims</p></div><button class="button ghost small" data-view="problems">View all ${icon('arrow')}</button></div><div class="problem-mini-list">${state.problems.map((problem) => `<div class="problem-mini"><div class="problem-mini-copy"><h3>${esc(problem.problem_id === 'p01_true_sort' ? 'Ascending sort, preserving duplicates' : 'Ascending sort, duplicate handling')}</h3><p>${esc(problem.target_id)} · ${esc(problem.claim)}</p></div><span class="mono">${esc(problem.problem_id)}</span></div>`).join('')}</div></section>
        <section class="card"><div class="card-head"><div><h2>Recent activity</h2><p>Stored in this browser only</p></div></div>${runs.length ? `<div class="problem-mini-list">${runs.map((run) => `<div class="problem-mini"><div class="problem-mini-copy"><h3><button class="run-link" data-run="${esc(run.run_id)}">${esc(tinyId(run.run_id))}</button></h3><p>${esc(run.problem_id)}</p></div>${badge(run.outcome || statusSummary(run.state), outcomeClass(run.outcome))}</div>`).join('')}</div>` : `<div class="empty-state"><div><strong>No recent runs</strong><p>Start an evaluation; its run ID will appear here for this browser.</p></div></div>`}</section>
      </div>
      ${state.metrics !== null ? `<section class="card section-spacer"><div class="card-head"><div><h2>Service requests</h2><p>Aggregate HTTP requests recorded by the API; not evaluation totals.</p></div><span class="eyebrow">Admin metrics</span></div><div class="metric-content"><div class="metric-num">${Number.isFinite(state.metrics) ? esc(state.metrics.toLocaleString()) : '—'}</div><div class="metric-label">Persisted API requests</div></div></section>` : ''}`;
  }

  function problemsView() {
    const query = state.search.trim().toLowerCase();
    const matches = state.problems.filter((problem) => JSON.stringify(problem).toLowerCase().includes(query));
    return `${heading('Problem catalogue', 'Supported problems', 'The pilot evaluates two built-in integer sorting problems. Search filters the problems already loaded from the API.', `<label class="search-box">${icon('search')}<input aria-label="Search supported problems" id="problem-search" value="${esc(state.search)}" placeholder="Search problems" autocomplete="off" /></label>`)}
      ${matches.length ? `<div class="problem-grid">${matches.map(problemCard).join('')}</div>` : `<section class="card empty-state"><div><strong>No matching problem</strong><p>Try another search term.</p></div></section>`}
      <p class="form-hint section-spacer">There is no endpoint for custom problems, code uploads, or user-defined inputs.</p>`;
  }

  function problemCard(problem) {
    const duplicateNote = problem.problem_id === 'p02_false_sort' ? 'This built-in target intentionally drops duplicate values.' : 'This built-in target sorts integers while keeping duplicates.';
    return `<article class="card problem-card"><div class="problem-card-top"><div class="problem-card-topline"><span class="problem-number">${esc(problem.problem_id)}</span><span class="problem-tag">Integer sorting</span></div><h3>${problem.problem_id === 'p01_true_sort' ? 'Preserve every value' : 'Check duplicate handling'}</h3><p class="problem-claim">${esc(problem.claim)}</p><p class="form-hint">${esc(duplicateNote)}</p></div><div class="problem-meta"><div class="meta-cell"><span>Target</span><code title="${esc(problem.target_id)}">${esc(problem.target_id)}</code></div><div class="meta-cell"><span>Contract</span><code title="${esc(problem.contract_id)}">${esc(problem.contract_id)}</code></div><div class="meta-cell"><span>Oracle</span><code title="${esc(problem.oracle_id)}">${esc(problem.oracle_id)}</code></div></div><div class="card-body" style="padding:12px 20px"><button class="button small" data-action="choose-problem" data-problem="${esc(problem.problem_id)}">Evaluate this problem ${icon('arrow')}</button></div></article>`;
  }

  function newRunView() {
    const selected = state.selectedProblem || 'p01_true_sort';
    const problemChoices = state.problems.map((problem) => `<button type="button" class="problem-option ${selected === problem.problem_id ? 'selected' : ''}" data-action="select-problem" data-problem="${esc(problem.problem_id)}" aria-pressed="${selected === problem.problem_id}"><i class="radio"></i><span class="option-copy"><strong>${problem.problem_id === 'p01_true_sort' ? 'Preserve every value' : 'Check duplicate handling'} <span class="mono muted">· ${esc(problem.problem_id)}</span></strong><span>${esc(problem.claim)}</span></span></button>`).join('');
    const alert = state.error ? `<div class="inline-alert" role="alert">${esc(state.error)}${state.retryAvailable ? ` <button class="button small" data-action="retry-run">Retry after ${Math.min(10, Math.max(1, Number(state.retryAfter) || 1))} sec</button>` : ''}</div>` : '';
    return `${heading('Run setup', 'Start an evaluation', 'Choose one built-in problem. The API runs its predefined, bounded evaluation and stores the authoritative result.')}
      <section class="card form-card"><div class="form-section"><h2>1. Select a problem</h2><p>Only the checked-in problem IDs are accepted by the current API.</p>${problemChoices}</div><div class="form-section"><h2>2. Review the run boundary</h2><p>This request sends only the selected problem ID. No code or custom input is uploaded.</p><div class="note-box">A <strong>TESTS_PASSED</strong> result means the scheduled finite tests passed. It does not prove the claim for every possible input.</div>${alert}</div><div class="form-footer"><span>${state.busy ? `<span class="loader"><svg class="loader-mark" viewBox="0 0 112 112" fill="none"><path d="M56 7 96 30v52l-40 23L16 82V30L56 7Z" stroke="#191917" stroke-width="6" stroke-linejoin="round"/><circle cx="56" cy="56" r="9" fill="#ef583c"/></svg>${state.busyMessage || 'Submitting and checking run…'}</span>` : `<span class="form-hint">${state.demo ? 'Demo mode creates a labeled sample record only.' : state.connected ? 'The API key stays in memory for this tab.' : 'Connect your API key in Settings before submitting.'}</span>`}</span><button class="button primary" data-action="submit-run" ${state.busy || (!state.connected && !state.demo) ? 'disabled' : ''}>${state.busy ? 'Working…' : 'Run evaluation'} ${icon('arrow')}</button></div></section>`;
  }

  function runsView() {
    const query = state.search.trim().toLowerCase();
    const rows = allRuns().filter((run) => JSON.stringify(run).toLowerCase().includes(query));
    return `${heading('Browser activity', 'Run history', 'Recent run IDs are kept in this browser only. Each full record is fetched from the API when you open it.', `<label class="search-box">${icon('search')}<input aria-label="Search local run history" id="runs-search" value="${esc(state.search)}" placeholder="Search run IDs" autocomplete="off" /></label>`)}
      <section class="card">${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Run ID</th><th>Problem</th><th>Outcome / state</th><th>Created</th><th></th></tr></thead><tbody>${rows.map((run) => `<tr><td><button class="run-link" data-run="${esc(run.run_id)}">${esc(tinyId(run.run_id))}</button></td><td><span class="mono">${esc(run.problem_id)}</span></td><td>${badge(run.outcome || statusSummary(run.state), outcomeClass(run.outcome))}</td><td>${esc(relativeDate(run.created_at_utc))}</td><td><button class="button small" data-run="${esc(run.run_id)}">Open</button></td></tr>`).join('')}</tbody></table></div>` : `<div class="empty-state"><div><strong>${query ? 'No matching run IDs' : 'No runs saved in this browser'}</strong><p>${query ? 'Try another query.' : 'Completed evaluations will appear here after you start a run.'}</p></div></div>`}</section>`;
  }

  function runView() {
    const run = state.currentRun;
    if (!run) return `${heading('Run record', 'Run details', 'Open a run from browser history to load its authoritative record.')}
      <section class="card empty-state"><div><strong>No run selected</strong><p>Choose a recent run to view its current API record and evidence.</p><button class="button" data-view="runs">Open run history</button></div></section>`;
    const problem = problemFor(run.problem_id);
    const record = run.record || {};
    const outcome = (record.outcome && record.outcome.outcome) || run.outcome;
    const completion = record.completion || {};
    const evidence = Array.isArray(record.evidence) ? record.evidence : [];
    const ce = record.outcome?.counterexample;
    const resultTitle = ({ REFUTED: 'Counterexample confirmed', TESTS_PASSED: 'Scheduled tests passed', UNRESOLVED: 'Evidence is unresolved', ERROR: 'Evaluation error' }[outcome] || statusSummary(run.state));
    const metricHint = outcome === 'TESTS_PASSED' ? 'A finite test pass is not a formal proof.' : outcome === 'ERROR' ? 'An error is not a verdict.' : outcome === 'REFUTED' ? 'The candidate was checked against the trusted oracle and replayed.' : 'Review the evidence and completion status together.';
    const evidenceRows = evidence.map((item) => `<tr><td><span class="evidence-method ${item.method === 'proposals' ? 'proposal' : ''}">${item.method === 'proposals' ? 'OFFLINE SUGGESTION' : esc(item.method || '—')}</span></td><td class="mono">${esc(item.test_id || '—')}</td><td><span class="evidence-json">${esc(jsonText(item.input_value))}</span></td><td><span class="evidence-json">${esc(jsonText(item.actual))}</span></td><td><span class="evidence-json">${esc(jsonText(item.expected))}</span></td><td>${badge(item.status, item.status === 'completed' ? 'green' : item.status === 'internal_error' ? 'red' : 'amber')}</td><td>${esc(item.failure_category || item.category || '—')}</td><td>${item.replay_confirmed === true ? badge('Replayed', 'green') : item.replay_confirmed === false ? badge('Not confirmed', 'red') : '—'}</td></tr>`).join('');
    const busyMessage = ['queued', 'running'].includes(run.state) ? `<div class="inline-alert" role="status">This run is ${esc(run.state)}. Refresh the record to check its current status. <button class="button small" data-action="refresh-run">${icon('refresh')} Refresh</button></div>` : '';
    return `${heading('Run record', 'Run details', 'The evidence and verdict below come from the run record stored by the API.', `<button class="button small" data-action="copy" data-copy="${esc(run.run_id)}">${icon('copy')} Copy run ID</button>`)}
      ${busyMessage}
      <div class="run-layout"><div>
        <section class="card result-summary"><div class="result-top"><div><div class="eyebrow">${esc(problem.problem_id)}</div><h2>${esc(resultTitle)}</h2><p>${esc((record.outcome && record.outcome.message) || outcomeSummary(outcome))} ${esc(metricHint)}</p></div>${badge(outcome || statusSummary(run.state), outcomeClass(outcome))}</div>
          <div class="result-facts"><div class="fact"><span>Run completion</span><strong>${esc(completion.status || run.run_status || '—')}</strong></div><div class="fact"><span>Cases completed</span><strong>${completion.completed_case_count ?? run.outcome?.test_count ?? '—'} / ${completion.scheduled_case_count ?? record.generation?.scheduled_case_count ?? '—'}</strong></div><div class="fact"><span>Error category</span><strong>${esc(run.error_category || record.outcome?.failure_category || 'None')}</strong></div></div>
        </section>
        ${ce && ce.replay_confirmed === true ? `<section class="counterexample section-spacer"><div style="display:flex;align-items:center;justify-content:space-between;gap:10px"><h3>Replay-confirmed counterexample</h3><button class="button small" data-action="copy" data-copy="${esc(JSON.stringify(ce))}">${icon('copy')} Copy JSON</button></div><pre>${esc(jsonText(ce))}</pre></section>` : ''}
        <section class="card section-spacer"><div class="card-head"><div><h2>Evidence reviewed</h2><p>${evidence.length} evidence record${evidence.length === 1 ? '' : 's'} · proposals are offline suggestions checked separately</p></div></div>${evidence.length ? `<div class="table-wrap"><table class="evidence-table"><thead><tr><th>Method</th><th>Case</th><th>Input</th><th>Candidate output</th><th>Expected / oracle</th><th>Case status</th><th>Failure category</th><th>Replay</th></tr></thead><tbody>${evidenceRows}</tbody></table></div>` : `<div class="empty-state"><div><strong>Evidence not included</strong><p>The API has not returned a finished record for this run yet.</p></div></div>`}</section>
        ${record.generation || record.usage || record.provenance || record.errors?.length ? `<details class="card section-spacer"><summary class="card-head" style="cursor:pointer;list-style:none"><h2>Run provenance and settings</h2><span class="muted">Expand</span></summary><div class="card-body"><pre class="json-block">${esc(jsonText({ generation: record.generation, usage: record.usage, provenance: record.provenance, budget: record.budget, errors: Array.isArray(record.errors) ? record.errors.map((item) => ({ step: item.step, error_id: item.error_id })) : undefined }))}</pre></div></details>` : ''}
      </div><aside class="side-facts"><div class="card side-fact"><span>Problem claim</span><strong style="font-family:var(--sans);font-size:11px;line-height:1.55">${esc(problem.claim)}</strong></div><div class="card side-fact"><span>Run ID</span><strong>${esc(run.run_id)}</strong></div><div class="card side-fact"><span>Created</span><strong>${esc(relativeDate(run.created_at_utc))}</strong></div><div class="card side-fact"><span>Finished</span><strong>${esc(relativeDate(run.finished_at_utc))}</strong></div></aside></div>`;
  }

  function adminView() {
    if (state.demo) return `${heading('Access-controlled', 'Admin overview', 'Admin policy and usage are never simulated in demo mode.')}<section class="card empty-state"><div><strong>No demo admin data</strong><p>Connect to the API with an admin key to view actual client limits and usage.</p></div></section>`;
    if (!state.connected) return `${heading('Access-controlled', 'Admin overview', 'This read-only page requires an admin API key.')}<section class="card empty-state"><div><strong>Connect as an administrator</strong><p>Enter the operator key in Settings. The API determines your role.</p><button class="button" data-view="settings">Open settings</button></div></section>`;
    if (state.adminForbidden) return `${heading('Access-controlled', 'Admin overview', 'This read-only page requires an admin API key.')}<section class="card empty-state"><div><strong>Admin access required</strong><p>The connected API key does not have permission to list client policies.</p></div></section>`;
    if (!state.clients) return `${heading('Access-controlled', 'Admin overview', 'Read-only client policy and aggregate quota usage from the API.')}<section class="card empty-state"><div><span class="loader">${loaderMark()} Loading admin data…</span></div></section>`;
    return `${heading('Access-controlled', 'Admin overview', 'Client roles, limits, and current usage returned by the API. Keys are never included.', `<button class="button small" data-action="refresh-admin">${icon('refresh')} Refresh</button>`)}
      ${state.clients.length ? `<div class="admin-grid">${state.clients.map((client) => `<article class="card admin-client"><h3>${esc(client.client_id)}</h3><div class="admin-row"><span>Role</span><strong>${esc(client.role)}</strong></div><div class="admin-row"><span>Active</span><strong>${client.is_active ? 'Yes' : 'No'}</strong></div><div class="admin-row"><span>Daily limit</span><strong>${esc(client.daily_run_limit)}</strong></div><div class="admin-row"><span>Runs today</span><strong>${esc(client.runs_today)}</strong></div><div class="admin-row"><span>Active runs</span><strong>${esc(client.active_runs)} / ${esc(client.max_active_runs)}</strong></div></article>`).join('')}</div>` : `<section class="card empty-state"><div><strong>No API clients configured</strong><p>The API returned an empty client list.</p></div></section>`}`;
  }

  function settingsView() {
    const base = state.apiBase || window.location.origin;
    const connectionState = state.demo ? 'Demo mode is active. No secret is stored or sent.' : state.connected ? `Connected to ${state.apiBase || window.location.origin}. The key is held in memory for this tab only.` : 'The API key is held in page memory only. It is never saved to local storage.';
    const form = state.busy ? `<div class="loader">${loaderMark()} Connecting to the API…</div>` : state.connected ? `<div class="note-box">${esc(connectionState)}</div><div style="display:flex;gap:9px;margin-top:13px"><button class="button" data-action="disconnect">Disconnect and clear key</button><button class="button primary" data-action="refresh-health">Refresh connection</button></div>` : `<form id="connection-form"><label class="form-label" for="api-base">API base URL</label><input class="input mono" id="api-base" name="apiBase" value="${esc(base)}" placeholder="http://localhost:8000" autocomplete="url" /><div class="form-hint">Same-origin is recommended. When served by FastAPI, this is already set to the API origin.</div><label class="form-label" for="api-key" style="margin-top:15px">Your API key</label><input class="input mono" id="api-key" name="apiKey" type="password" required minlength="32" autocomplete="off" placeholder="Paste your operator key" /><div class="form-hint">Do not paste a shared admin key into a public site. This local connection form keeps it in memory only and clears it when you disconnect or close the tab.</div><div style="display:flex;gap:9px;align-items:center;margin-top:16px"><button class="button primary" type="submit">Connect to API ${icon('arrow')}</button><button class="button" type="button" data-action="demo">Preview demo</button></div>${state.error ? `<div class="inline-alert" role="alert">${esc(state.error)}</div>` : ''}</form>`;
    return `${heading('Connection', 'Settings', 'Connect the interface to your Abacus API or open the labeled sample preview.')}
      <div class="settings-grid"><section class="card form-card"><div class="form-section"><h2>API connection</h2><p>Calls use the existing backend. The frontend does not connect directly to the database.</p>${form}</div></section>
      <aside class="card settings-info"><h3>Safe by default</h3><ul><li>API keys stay in page memory and are cleared on disconnect.</li><li>Run history stores only IDs and labels in this browser.</li><li>Serving the interface from FastAPI keeps requests same-origin.</li><li>Never expose a shared admin key in a public frontend.</li></ul><h3>Current pilot scope</h3><p>Two integer sorting problems. No custom code or inputs are uploaded. Offline suggestions are not an AI service call.</p><button class="button small" data-action="demo">Preview labeled demo data</button></aside></div>`;
  }

  function loaderMark() { return `<svg class="loader-mark" viewBox="0 0 112 112" fill="none"><path d="M56 7 96 30v52l-40 23L16 82V30L56 7Z" stroke="#191917" stroke-width="6" stroke-linejoin="round"/><circle cx="56" cy="56" r="9" fill="#ef583c"/></svg>`; }

  async function checkPublicHealth() {
    if (state.healthChecking || state.demo || state.connected) return;
    state.healthChecking = true;
    try {
      const response = await fetch(`${getBase()}/health/ready`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      state.apiReady = response.ok;
    } catch {
      state.apiReady = false;
    } finally {
      state.healthChecking = false;
    }
    if (state.view !== 'run') render();
  }

  function getBase() {
    const raw = state.apiBase || window.location.origin;
    return raw.replace(/\/+$/, '');
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');
    if (state.apiKey) headers.set('X-API-Key', state.apiKey);
    const response = await fetch(`${getBase()}${path}`, { ...options, headers, cache: 'no-store' });
    let data = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try { data = await response.json(); } catch { data = null; }
    }
    if (!response.ok) {
      const error = new Error(errorMessage(response.status, data));
      error.status = response.status;
      error.retryAfter = Number(response.headers.get('Retry-After')) || 1;
      throw error;
    }
    return { response, data };
  }

  function errorMessage(status, data) {
    if (status === 401) return 'That API key was not accepted. Check it and connect again.';
    if (status === 403) return 'This key does not have permission for that page or action.';
    if (status === 404) return 'The run or problem could not be found for this API key.';
    if (status === 409) return 'This run request conflicts with an earlier idempotency key. Start a fresh evaluation.';
    if (status === 429) return 'The configured run limit has been reached. Wait for the quota window to reset.';
    if (status === 500) return 'The API could not complete this request. Check the service and try again later.';
    if (status === 503) return 'The API or its database is temporarily unavailable. Check readiness, then retry.';
    if (status === 400) return 'The API rejected the request format. Refresh the app and try again.';
    if (data?.detail && typeof data.detail === 'string') return data.detail;
    return `The API returned HTTP ${status}. Try again after checking the service.`;
  }

  function apiBaseFromForm(raw) {
    const value = raw.trim().replace(/\/+$/, '');
    let url;
    try { url = new URL(value); } catch { throw new Error('Enter a complete API URL, such as http://localhost:8000.'); }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Use an HTTP(S) API base URL without credentials, query values, or fragments.');
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if (url.protocol === 'http:' && !local) throw new Error('Remote API connections must use HTTPS. Plain HTTP is allowed only for localhost.');
    return url.origin + url.pathname.replace(/\/+$/, '');
  }

  async function connect(form) {
    state.error = '';
    const data = new FormData(form);
    let base;
    try { base = apiBaseFromForm(String(data.get('apiBase') || '')); }
    catch (error) { state.error = error.message; render(); return; }
    const key = String(data.get('apiKey') || '').trim();
    if (key.length < 32) { state.error = 'API keys must be at least 32 characters.'; render(); return; }
    state.apiBase = base;
    state.apiKey = key;
    state.connected = false;
    state.demo = false;
    state.clients = null;
    state.adminForbidden = false;
    state.busy = true;
    state.busyMessage = 'Checking API readiness and access…';
    localStorage.setItem(STORE.apiBase, base);
    render();
    try {
      const health = await fetch(`${getBase()}/health/ready`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      state.apiReady = health.ok;
      if (!health.ok) throw new Error('The API is not ready yet. Start the API and database, then reconnect.');
      const { data: problems } = await apiRequest('/v1/problems');
      if (!Array.isArray(problems) || problems.length === 0) throw new Error('The API did not return any supported problems.');
      state.problems = problems;
      state.connected = true;
      state.adminAllowed = false;
      try {
        const { data: clients } = await apiRequest('/v1/admin/clients');
        state.clients = Array.isArray(clients) ? clients : [];
        state.adminAllowed = true;
      } catch (error) {
        state.adminForbidden = error.status === 403;
      }
      state.connectionError = '';
      state.error = '';
      state.busy = false;
      state.view = 'overview';
      await loadMetrics();
      toast('Connected. Your API key remains in this tab only.');
    } catch (error) {
      state.connected = false;
      state.busy = false;
      state.apiKey = '';
      state.error = error.status ? error.message : (error.message.includes('Failed to fetch') ? 'Could not reach the API. Check its address, that it is running, and same-origin/CORS setup.' : error.message);
      render();
      return;
    }
    render();
  }

  async function loadMetrics() {
    if (!state.connected || state.demo) return;
    try {
      const response = await fetch(`${getBase()}/metrics`, { headers: { Accept: 'text/plain', 'X-API-Key': state.apiKey }, cache: 'no-store' });
      if (response.status === 403) return;
      if (!response.ok) return;
      const body = await response.text();
      const match = body.match(/^abacus_http_requests_total\s+(\d+(?:\.\d+)?)/m);
      state.metrics = match ? Number(match[1]) : null;
    } catch { state.metrics = null; }
  }

  async function loadAdmin() {
    if (!state.connected || state.demo) return;
    state.clients = null;
    state.adminForbidden = false;
    render();
    try {
      const { data } = await apiRequest('/v1/admin/clients');
      state.clients = Array.isArray(data) ? data : [];
    } catch (error) {
      if (error.status === 403) { state.adminForbidden = true; state.adminAllowed = false; }
      else toast(error.message, 'error');
    }
    render();
  }

  async function openRun(runId) {
    state.view = 'run';
    state.currentRun = null;
    state.search = '';
    render();
    if (state.demo) {
      state.currentRun = demoRuns.find((run) => run.run_id === runId) || null;
      render();
      return;
    }
    if (!state.connected) {
      toast('Connect with the same API key that created this run to fetch its record.', 'error');
      return;
    }
    try {
      const { data } = await apiRequest(`/v1/runs/${encodeURIComponent(runId)}`);
      state.currentRun = data;
      saveRecentRun(data);
      render();
    } catch (error) {
      state.currentRun = null;
      render();
      toast(error.message, 'error');
    }
  }

  function randomIdempotencyKey() {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  }

  function wait(ms) { return new Promise((resolve) => window.setTimeout(resolve, ms)); }
  const retryDelay = (seconds) => Math.min(10, Math.max(1, Number(seconds) || 1)) * 1000;

  async function submitRun() {
    if (state.busy) return;
    state.error = '';
    state.retryAvailable = false;
    state.busy = true;
    state.busyMessage = state.demo ? 'Opening labeled sample record…' : 'Submitting evaluation…';
    render();
    const selected = state.selectedProblem || 'p01_true_sort';
    if (state.demo) {
      await wait(450);
      const run = demoRuns.find((item) => item.problem_id === selected) || demoRuns[0];
      state.currentRun = run;
      state.busy = false;
      state.view = 'run';
      render();
      return;
    }
    try {
      const { response, data } = await apiRequest('/v1/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomIdempotencyKey() },
        body: JSON.stringify({ problem_id: selected }),
      });
      if (!data?.run_id) throw new Error('The API accepted the request but did not return a run ID.');
      let latest = data;
      const runId = data.run_id;
      saveRecentRun(latest);
      state.view = 'run';
      state.currentRun = latest;
      state.busyMessage = 'Fetching the authoritative run record…';
      render();
      let delay = retryDelay(response.headers.get('Retry-After'));
      const start = Date.now();
      while (Date.now() - start < 120000) {
        const result = await apiRequest(`/v1/runs/${encodeURIComponent(runId)}`);
        latest = result.data;
        state.currentRun = latest;
        saveRecentRun(latest);
        if (!['queued', 'running'].includes(latest.state)) break;
        state.busyMessage = latest.state === 'queued' ? 'Waiting for the worker…' : 'Checking the evaluation…';
        render();
        await wait(delay);
        delay = retryDelay(result.response.headers.get('Retry-After'));
      }
      state.currentRun = latest;
      state.busy = false;
      state.busyMessage = '';
      render();
    } catch (error) {
      state.busy = false;
      state.busyMessage = '';
      state.error = error.message;
      state.retryAvailable = error.status === 503;
      state.retryAfter = error.retryAfter || 1;
      if (state.view === 'run' && state.currentRun) {
        render();
        toast(error.message, 'error');
      } else {
        state.view = 'new';
        render();
      }
    }
  }

  async function refreshCurrentRun() {
    if (state.demo || !state.connected || !state.currentRun) return;
    try {
      const { data } = await apiRequest(`/v1/runs/${encodeURIComponent(state.currentRun.run_id)}`);
      state.currentRun = data;
      saveRecentRun(data);
      render();
    } catch (error) { toast(error.message, 'error'); }
  }

  function disconnect() {
    state.apiKey = '';
    state.connected = false;
    state.demo = false;
    state.clients = null;
    state.metrics = null;
    state.adminAllowed = false;
    state.adminForbidden = false;
    state.error = '';
    state.problems = [...builtInProblems];
    state.apiReady = null;
    render();
    toast('Disconnected; the key was cleared from memory.');
  }

  function enterDemo() {
    state.apiKey = '';
    state.connected = false;
    state.demo = true;
    state.apiReady = null;
    state.clients = null;
    state.adminAllowed = false;
    state.metrics = null;
    state.problems = [...builtInProblems];
    state.search = '';
    state.error = '';
    state.view = 'overview';
    render();
  }

  function toast(message, kind = '') {
    const slot = document.getElementById('toast-slot');
    if (!slot) return;
    slot.innerHTML = `<div class="toast ${kind}" role="status">${esc(message)}</div>`;
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { const node = document.querySelector('.toast'); if (node) node.remove(); }, 4200);
  }

  async function copyText(value) {
    try { await navigator.clipboard.writeText(value); toast('Copied to clipboard.'); }
    catch { toast('Clipboard access is unavailable in this browser.', 'error'); }
  }

  document.addEventListener('click', async (event) => {
    const viewButton = event.target.closest('[data-view]');
    if (viewButton) {
      state.search = '';
      state.view = viewButton.dataset.view;
      state.error = '';
      render();
      if (state.view === 'admin' && state.connected && !state.adminForbidden) loadAdmin();
      return;
    }
    const runButton = event.target.closest('[data-run]');
    if (runButton) { await openRun(runButton.dataset.run); return; }
    const actionButton = event.target.closest('[data-action]');
    if (!actionButton) return;
    const action = actionButton.dataset.action;
    if (action === 'theme') {
      state.theme = state.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem(STORE.theme, state.theme);
      render();
    } else if (action === 'refresh-health') {
      if (state.demo) {
        toast('Demo mode shows sample status only; no API request was made.');
      } else if (state.connected) {
        try {
          const health = await fetch(`${getBase()}/health/ready`, { cache: 'no-store' });
          state.apiReady = health.ok;
          if (!health.ok) toast('The API is not ready. Check its database and service status.', 'error');
          else { await loadMetrics(); toast('API readiness refreshed.'); }
        } catch { state.apiReady = false; toast('The API could not be reached.', 'error'); }
        render();
      } else checkPublicHealth();
    } else if (action === 'choose-problem') {
      state.selectedProblem = actionButton.dataset.problem;
      state.view = 'new';
      render();
    } else if (action === 'select-problem') {
      state.selectedProblem = actionButton.dataset.problem;
      render();
    } else if (action === 'submit-run') {
      await submitRun();
    } else if (action === 'retry-run') {
      actionButton.disabled = true;
      await wait(retryDelay(state.retryAfter));
      await submitRun();
    } else if (action === 'refresh-run') {
      await refreshCurrentRun();
    } else if (action === 'refresh-admin') {
      await loadAdmin();
    } else if (action === 'disconnect') {
      disconnect();
    } else if (action === 'demo') {
      enterDemo();
    } else if (action === 'exit-demo') {
      state.demo = false;
      state.view = 'overview';
      state.currentRun = null;
      render();
      checkPublicHealth();
    } else if (action === 'copy') {
      await copyText(actionButton.dataset.copy || '');
    }
  });

  document.addEventListener('submit', async (event) => {
    if (event.target.id === 'connection-form') {
      event.preventDefault();
      await connect(event.target);
    }
  });

  document.addEventListener('input', (event) => {
    if (event.target.id === 'problem-search' || event.target.id === 'runs-search') {
      const position = event.target.selectionStart;
      state.search = event.target.value;
      const view = state.view;
      render();
      const replacement = document.getElementById(event.target.id);
      if (replacement) { replacement.focus(); replacement.setSelectionRange(position, position); }
      if (state.view !== view) state.view = view;
    }
  });

  state.selectedProblem = 'p01_true_sort';
  render();
})();
