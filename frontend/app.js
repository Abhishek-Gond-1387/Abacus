(() => {
  'use strict';

  const STORE = {
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
    view: 'overview', problems: [...builtInProblems], apiReady: null, connectionError: '', connected: false,
    demo: false, search: '', currentRun: null, nextPollAt: 0, busy: false, error: '', clients: null,
    adminAllowed: false, adminForbidden: false, healthChecking: false,
    qaAvailable: false, qaReason: 'not_connected', qaBusy: false, qaError: '', qaMessages: [], questionText: '',
    customAvailable: false, customReason: 'not_connected', customBusy: false, customError: '', customResult: null,
    customSource: 'def candidate(values):\n    return sorted(values)\n', customInput: '[]',
    theme: localStorage.getItem(STORE.theme) || 'light',
  };
  let toastTimer;
  let introPending = true;
  const app = document.getElementById('app');

  const icons = {
    overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    problems: '<path d="M12 3 21 8v8l-9 5-9-5V8l9-5Z"/><circle cx="12" cy="12" r="2"/>',
    new: '<path d="M12 5v14M5 12h14"/>',
    ask: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z"/><path d="M8 11h.01M12 11h.01M16 11h.01"/>',
    custom: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
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
  const titleFor = (view) => ({ overview: 'Overview', problems: 'Problems', new: 'New evaluation', ask: 'Ask AI', custom: 'My code', runs: 'Run history', run: 'Run details', admin: 'Admin', settings: 'Settings' }[view] || 'Overview');
  const navItems = [
    ['overview', 'Overview'], ['problems', 'Problems'], ['new', 'Built-in runs'], ['custom', 'My code'], ['ask', 'Ask AI'], ['runs', 'Run history'], ['admin', 'Admin'], ['settings', 'Settings'],
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
    const connectionText = state.demo ? 'Demo data' : state.connected ? 'API connected' : state.apiReady === false ? 'API unavailable' : 'Checking API';
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
    if (!state.connected && !state.demo && state.apiReady === null) checkApiConnection();
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
    if (state.view === 'ask') return askView();
    if (state.view === 'custom') return customView();
    if (state.view === 'runs') return runsView();
    if (state.view === 'run') return runView();
    if (state.view === 'admin') return adminView();
    if (state.view === 'settings') return settingsView();
    return overviewView();
  }

  function overviewView() {
    const runs = allRuns().slice(0, 3);
    const readiness = state.demo ? 'Demo preview' : state.apiReady === true ? 'Ready' : state.apiReady === false ? 'Unavailable' : 'Checking';
    const readinessCopy = state.demo ? 'Sample data only; no API requests are being made.' : state.apiReady === true ? 'The configured API and its database answered the readiness check.' : state.apiReady === false ? state.connectionError || 'The server-side API proxy or backend is unavailable.' : 'Checking the server-side proxy and API readiness.';
    const action = state.connected ? `<button class="button primary" data-view="new">Start an evaluation ${icon('arrow')}</button>` : `<button class="button primary" data-view="settings">Check API connection ${icon('arrow')}</button>`;
    const problemSource = state.demo ? 'Illustrative demo fixtures; not API data' : state.connected ? 'Loaded live from the API' : 'Built-in IDs shown locally; live catalogue not loaded';
    return `${heading('Evidence workspace', 'Understand what the tests show.', 'Abacus checks the supported claim against a trusted oracle and keeps the evidence attached to each run.')}
      <div class="overview-grid">
        <section class="card welcome"><div class="welcome-content"><div class="eyebrow">Python claim evaluation</div><h2>Small claims. Careful evidence.</h2><p>Inspect a supported sorting claim, run the checked evaluation, then review the evidence and any replay-confirmed counterexample.</p><div class="welcome-actions">${action}<button class="button" data-view="problems">Browse problems</button></div></div></section>
        <section class="card readiness-card"><div class="readiness-main"><div class="eyebrow">Service status</div><div class="readiness-value"><i class="readiness-indicator ${state.apiReady === true ? 'ready' : ''}"></i>${esc(readiness)}</div><div class="readiness-sub">${esc(readinessCopy)}</div></div><div class="readiness-foot"><span>${state.demo ? 'Preview workspace' : 'Server-side proxy'}</span><button class="button ghost small" data-action="refresh-health">${icon('refresh')} Refresh</button></div></section>
      </div>
      <div class="overview-lower">
        <section class="card"><div class="card-head"><div><h2>Supported problems</h2><p>${esc(problemSource)}</p></div><button class="button ghost small" data-view="problems">View all ${icon('arrow')}</button></div><div class="problem-mini-list">${state.problems.map((problem) => `<div class="problem-mini"><div class="problem-mini-copy"><h3>${esc(problem.problem_id === 'p01_true_sort' ? 'Ascending sort, preserving duplicates' : 'Ascending sort, duplicate handling')}</h3><p>${esc(problem.target_id)} · ${esc(problem.claim)}</p></div><span class="mono">${esc(problem.problem_id)}</span></div>`).join('')}</div></section>
        <section class="card"><div class="card-head"><div><h2>Recent activity</h2><p>Stored in this browser only</p></div></div>${runs.length ? `<div class="problem-mini-list">${runs.map((run) => `<div class="problem-mini"><div class="problem-mini-copy"><h3><button class="run-link" data-run="${esc(run.run_id)}">${esc(tinyId(run.run_id))}</button></h3><p>${esc(run.problem_id)}</p></div>${badge(run.outcome || statusSummary(run.state), outcomeClass(run.outcome))}</div>`).join('')}</div>` : `<div class="empty-state"><div><strong>No recent runs</strong><p>Start an evaluation; its run ID will appear here for this browser.</p></div></div>`}</section>
      </div>
      `;
  }

  function problemsView() {
    const query = state.search.trim().toLowerCase();
    const matches = state.problems.filter((problem) => JSON.stringify(problem).toLowerCase().includes(query));
    const source = state.demo ? 'Demo fixture catalogue; not connected to the API.' : state.connected ? 'Live catalogue returned by the API.' : 'Showing the two built-in IDs for reference; a live catalogue has not loaded.';
    return `${heading('Problem catalogue', 'Supported problems', `${source} Search filters the currently displayed problems.`, `<label class="search-box">${icon('search')}<input aria-label="Search supported problems" id="problem-search" value="${esc(state.search)}" placeholder="Search problems" autocomplete="off" /></label>`)}
      ${matches.length ? `<div class="problem-grid">${matches.map(problemCard).join('')}</div>` : `<section class="card empty-state"><div><strong>No matching problem</strong><p>Try another search term.</p></div></section>`}
      <p class="form-hint section-spacer">Custom code checks use a separate, verified sandbox and currently cover one integer-sort input at a time. Arbitrary problem definitions are not supported.</p>`;
  }

  function problemCard(problem) {
    const duplicateNote = problem.problem_id === 'p02_false_sort' ? 'This built-in target intentionally drops duplicate values.' : 'This built-in target sorts integers while keeping duplicates.';
    return `<article class="card problem-card"><div class="problem-card-top"><div class="problem-card-topline"><span class="problem-number">${esc(problem.problem_id)}</span><span class="problem-tag">Integer sorting</span></div><h3>${problem.problem_id === 'p01_true_sort' ? 'Preserve every value' : 'Check duplicate handling'}</h3><p class="problem-claim">${esc(problem.claim)}</p><p class="form-hint">${esc(duplicateNote)}</p></div><div class="problem-meta"><div class="meta-cell"><span>Target</span><code title="${esc(problem.target_id)}">${esc(problem.target_id)}</code></div><div class="meta-cell"><span>Contract</span><code title="${esc(problem.contract_id)}">${esc(problem.contract_id)}</code></div><div class="meta-cell"><span>Oracle</span><code title="${esc(problem.oracle_id)}">${esc(problem.oracle_id)}</code></div></div><div class="card-body" style="padding:12px 20px"><button class="button small" data-action="choose-problem" data-problem="${esc(problem.problem_id)}">Evaluate this problem ${icon('arrow')}</button></div></article>`;
  }

  function newRunView() {
    const selected = state.selectedProblem || 'p01_true_sort';
    const problemChoices = state.problems.map((problem) => `<button type="button" class="problem-option ${selected === problem.problem_id ? 'selected' : ''}" data-action="select-problem" data-problem="${esc(problem.problem_id)}" aria-pressed="${selected === problem.problem_id}"><i class="radio"></i><span class="option-copy"><strong>${problem.problem_id === 'p01_true_sort' ? 'Preserve every value' : 'Check duplicate handling'} <span class="mono muted">· ${esc(problem.problem_id)}</span></strong><span>${esc(problem.claim)}</span></span></button>`).join('');
    const alert = state.error ? `<div class="inline-alert" role="alert">${esc(state.error)}${state.retryAvailable ? ` <button class="button small" data-action="retry-run">Retry after ${Math.max(1, Number(state.retryAfter) || 1)} sec</button>` : ''}</div>` : '';
    return `${heading('Run setup', 'Start an evaluation', 'Choose one built-in problem. The API runs its predefined, bounded evaluation and stores the authoritative result.')}
      <section class="card form-card"><div class="form-section"><h2>1. Select a problem</h2><p>Only the checked-in problem IDs are accepted by the current API.</p>${problemChoices}</div><div class="form-section"><h2>2. Review the run boundary</h2><p>This request sends only the selected problem ID. No code or custom input is uploaded.</p><div class="note-box">A <strong>TESTS_PASSED</strong> result means the scheduled finite tests passed. It does not prove the claim for every possible input.</div>${alert}</div><div class="form-footer"><span>${state.busy ? `<span class="loader"><svg class="loader-mark" viewBox="0 0 112 112" fill="none"><path d="M56 7 96 30v52l-40 23L16 82V30L56 7Z" stroke="#191917" stroke-width="6" stroke-linejoin="round"/><circle cx="56" cy="56" r="9" fill="#ef583c"/></svg>${state.busyMessage || 'Submitting and checking run…'}</span>` : `<span class="form-hint">${state.demo ? 'Demo mode creates a labeled sample record only.' : state.connected ? 'The server-side proxy submits this request with its protected API key.' : 'Enable the server-side proxy in FastAPI Settings before submitting.'}</span>`}</span><button class="button primary" data-action="submit-run" ${state.busy || (!state.connected && !state.demo) ? 'disabled' : ''}>${state.busy ? 'Working…' : 'Run evaluation'} ${icon('arrow')}</button></div></section>`;
  }

  function askView() {
    const availability = state.demo
      ? 'Demo mode does not send questions to an AI provider.'
      : state.qaAvailable
        ? 'Live Gemini connection is configured on the backend.'
        : `AI answers are unavailable: ${featureReason(state.qaReason)}.`;
    const messages = state.qaMessages.map((item) => `<article class="qa-message"><div class="qa-question"><span class="eyebrow">You asked</span><p>${esc(item.question)}</p></div><div class="qa-answer"><span class="eyebrow">${esc(item.provider)} · ${esc(item.model)}</span><p>${esc(item.answer)}</p><small>${esc(item.disclaimer)}</small></div></article>`).join('');
    const alert = state.qaError ? `<div class="inline-alert" role="alert">${esc(state.qaError)}</div>` : '';
    return `${heading('General questions', 'Ask Abacus', 'Ask a general question and get a live answer from the configured AI provider.')}
      <section class="card form-card"><form id="question-form"><div class="form-section"><h2>Your question</h2><p>${esc(availability)} Questions are sent to the configured provider only after you submit. Do not include passwords, API keys, or private data.</p>
      <label class="form-label" for="question-text">Question</label><textarea class="input textarea" id="question-text" name="question" rows="5" maxlength="2000" placeholder="Ask a question…" required>${esc(state.questionText)}</textarea>
      <div class="form-hint">Maximum 2,000 characters. Provider quota applies; there is no automatic paid-provider fallback.</div>${alert}</div>
      <div class="form-footer"><span class="form-hint">${state.qaBusy ? 'Waiting for the configured AI provider…' : state.demo ? 'Demo data stays separate; no request is made.' : state.qaAvailable ? 'API key stays on the backend.' : 'Enable a provider on the backend to use live AI answers.'}</span><button class="button primary" type="submit" ${!state.connected || !state.qaAvailable || state.qaBusy || state.demo ? 'disabled' : ''}>${state.qaBusy ? 'Thinking…' : 'Ask'} ${icon('arrow')}</button></div></form></section>
      ${messages ? `<section class="card section-spacer"><div class="card-head"><div><h2>This session</h2><p>Question history is kept in memory in this browser tab only.</p></div></div><div class="qa-history">${messages}</div></section>` : ''}`;
  }

  function customView() {
    const availability = state.demo
      ? 'Demo mode does not execute code.'
      : state.customAvailable
        ? 'Verified isolated sandbox is ready.'
        : `Code execution is blocked: ${featureReason(state.customReason)}.`;
    const result = state.customResult ? `<section class="card section-spacer"><div class="card-head"><div><h2>Live sandbox result</h2><p>One custom input checked against the built-in integer-sort contract.</p></div>${badge(state.customResult.outcome, outcomeClass(state.customResult.outcome))}</div><div class="card-body"><p>${esc(state.customResult.claim || state.customResult.error_category || 'The sandbox returned an evaluation result.')}</p>${state.customResult.evidence ? `<pre class="json-block">${esc(jsonText(state.customResult.evidence))}</pre>` : ''}<div class="form-hint">${esc(state.customResult.evidence?.scope || 'This is one input check, not a proof.')}</div></div></section>` : '';
    const alert = state.customError ? `<div class="inline-alert" role="alert">${esc(state.customError)}</div>` : '';
    return `${heading('Custom Python', 'Check your own code', 'Submit a Python function named candidate(values) and one integer-array input. Abacus compares it with the built-in ascending-sort claim.')}
      <section class="card form-card"><form id="custom-form"><div class="form-section"><h2>Python function</h2><p>${esc(availability)} Source is sent only to the server-side API and is not saved in browser storage.</p>
      <label class="form-label" for="custom-source">Python source</label><textarea class="input textarea code-input" id="custom-source" name="source" rows="11" spellcheck="false" autocapitalize="off" autocomplete="off">${esc(state.customSource)}</textarea>
      <div class="form-hint">Define <code>candidate(values)</code>. The verified sandbox runs it in an isolated, network-disabled container.</div></div>
      <div class="form-section"><h2>One input to check</h2><p>Enter a JSON array of up to 100 integers.</p><label class="form-label" for="custom-input">Integer array (JSON)</label><textarea class="input textarea code-input" id="custom-input" name="input" rows="3" spellcheck="false">${esc(state.customInput)}</textarea>${alert}</div>
      <div class="form-footer"><span class="form-hint">${state.customBusy ? 'Running in the verified sandbox…' : state.customAvailable ? 'One input only; results are not stored as a full run.' : 'The server will refuse to run code until sandbox verification passes.'}</span><button class="button primary" type="submit" ${!state.connected || !state.customAvailable || state.customBusy || state.demo ? 'disabled' : ''}>${state.customBusy ? 'Checking…' : 'Check code'} ${icon('arrow')}</button></div></form></section>${result}`;
  }

  function featureReason(reason) {
    return ({
      not_connected: 'the backend is not connected',
      qa_disabled: 'AI questions are disabled by the server operator',
      qa_requires_gemini: 'the server is configured for a provider this free-tier pilot does not allow',
      gemini_not_configured: 'a Gemini key is not configured on the backend',
      execution_flag_disabled: 'server-side execution is off; verified Docker checks are also required',
      day37_verification_not_passed: 'Docker isolation probes have not passed',
      docker_runtime_unavailable: 'Docker Desktop is not installed or running',
      verification_report_unavailable: 'sandbox verification report is missing',
      verified_image_unavailable: 'the verified sandbox image is not built',
    }[reason] || String(reason || 'server capability is unavailable'));
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
      <section class="card empty-state"><div>${state.busy ? `<span class="loader" role="status">${loaderMark()} ${esc(state.busyMessage || 'Loading the run record…')}</span>` : `<strong>No run selected</strong><p>Choose a recent run to view its current API record and evidence.</p><button class="button" data-view="runs">Open run history</button>`}</div></section>`;
    const problem = problemFor(run.problem_id);
    const record = run.record || {};
    const outcome = (record.outcome && record.outcome.outcome) || run.outcome;
    const completion = record.completion || {};
    const evidence = Array.isArray(record.evidence) ? record.evidence : [];
    const ce = record.outcome?.counterexample;
    const resultTitle = ({ REFUTED: 'Counterexample confirmed', TESTS_PASSED: 'Scheduled tests passed', UNRESOLVED: 'Evidence is unresolved', ERROR: 'Evaluation error' }[outcome] || statusSummary(run.state));
    const metricHint = outcome === 'TESTS_PASSED' ? 'A finite test pass is not a formal proof.' : outcome === 'ERROR' ? 'An error is not a verdict.' : outcome === 'REFUTED' ? 'The candidate was checked against the trusted oracle and replayed.' : 'Review the evidence and completion status together.';
    const evidenceRows = evidence.map((item) => `<tr><td><span class="evidence-method ${item.method === 'proposals' ? 'proposal' : ''}">${item.method === 'proposals' ? 'OFFLINE SUGGESTION' : esc(item.method || '—')}</span></td><td class="mono">${esc(item.test_id || '—')}</td><td><span class="evidence-json">${esc(jsonText(item.input_value))}</span></td><td><span class="evidence-json">${esc(jsonText(item.actual))}</span></td><td><span class="evidence-json">${esc(jsonText(item.expected))}</span></td><td>${badge(item.status, item.status === 'completed' ? 'green' : item.status === 'internal_error' ? 'red' : 'amber')}</td><td>${esc(item.failure_category || item.category || '—')}</td><td>${item.replay_confirmed === true ? badge('Replayed', 'green') : item.replay_confirmed === false ? badge('Not confirmed', 'red') : '—'}</td></tr>`).join('');
    const nextPollSeconds = Math.max(0, Math.ceil((state.nextPollAt - Date.now()) / 1000));
    const busyMessage = state.busy ? `<div class="inline-alert" role="status"><span class="loader">${loaderMark()} ${esc(state.busyMessage || 'Loading the run record…')}</span></div>` : ['queued', 'running'].includes(run.state) ? `<div class="inline-alert" role="status">This run is ${esc(run.state)}.${nextPollSeconds ? ` Next poll in about ${nextPollSeconds} second${nextPollSeconds === 1 ? '' : 's'} (Retry-After).` : ''} <button class="button small" data-action="refresh-run">${icon('refresh')} Check run</button></div>` : '';
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
    if (state.demo) return `${heading('Access-controlled', 'Admin overview', 'Admin policy and usage are never simulated in demo mode.')}<section class="card empty-state"><div><strong>No demo admin data</strong><p>Exit demo mode to view client limits and usage returned by the server-side API proxy.</p></div></section>`;
    if (!state.connected) return `${heading('Access-controlled', 'Admin overview', 'This read-only page requires an admin API key.')}<section class="card empty-state"><div><strong>Connect as an administrator</strong><p>Configure the server-side API key on the FastAPI host. The API determines its role.</p><button class="button" data-view="settings">Open settings</button></div></section>`;
    if (state.adminForbidden) return `${heading('Access-controlled', 'Admin overview', 'This read-only page requires an admin API key.')}<section class="card empty-state"><div><strong>Admin access required</strong><p>The connected API key does not have permission to list client policies.</p></div></section>`;
    if (!state.clients) return `${heading('Access-controlled', 'Admin overview', 'Read-only client policy and aggregate quota usage from the API.')}<section class="card empty-state"><div><span class="loader">${loaderMark()} Loading admin data…</span></div></section>`;
    return `${heading('Access-controlled', 'Admin overview', 'Client roles, limits, and current usage returned by the API. Keys are never included.', `<button class="button small" data-action="refresh-admin">${icon('refresh')} Refresh</button>`)}
      ${state.clients.length ? `<div class="admin-grid">${state.clients.map((client) => `<article class="card admin-client"><h3>${esc(client.client_id)}</h3><div class="admin-row"><span>Role</span><strong>${esc(client.role)}</strong></div><div class="admin-row"><span>Active</span><strong>${client.is_active ? 'Yes' : 'No'}</strong></div><div class="admin-row"><span>Daily limit</span><strong>${esc(client.daily_run_limit)}</strong></div><div class="admin-row"><span>Runs today</span><strong>${esc(client.runs_today)}</strong></div><div class="admin-row"><span>Active runs</span><strong>${esc(client.active_runs)} / ${esc(client.max_active_runs)}</strong></div></article>`).join('')}</div>` : `<section class="card empty-state"><div><strong>No API clients configured</strong><p>The API returned an empty client list.</p></div></section>`}`;
  }

  function settingsView() {
    const connectionState = state.demo ? 'Demo mode is active. These records are samples and no backend calls are made.' : state.connected ? 'Connected through the same-origin FastAPI proxy. The API key and database configuration stay on the server.' : state.connectionError || 'Checking the server-side API proxy configuration…';
    const form = state.healthChecking ? `<div class="loader" role="status">${loaderMark()} Checking the server-side proxy and API readiness…</div>` : `<div class="note-box" role="status">${esc(connectionState)}</div><div style="display:flex;gap:9px;margin-top:13px"><button class="button primary" data-action="refresh-health">${icon('refresh')} ${state.connected ? 'Refresh connection' : 'Check connection'}</button><button class="button" data-action="demo">Preview demo</button></div>`;
    return `${heading('Connection', 'Settings', 'The UI calls the allowlisted same-origin proxy; it never receives an API key or connects to the database.')}
      <div class="settings-grid"><section class="card form-card"><div class="form-section"><h2>Server-side API connection</h2><p>Configure <code>ABACUS_API_BASE_URL</code> and <code>ABACUS_API_KEY</code> in the FastAPI server environment, then enable <code>ABACUS_UI_PROXY_ENABLED=1</code> for loopback-only local use.</p>${form}</div></section>
      <aside class="card settings-info"><h3>Security and scope</h3><ul><li>API keys never enter browser code, requests, logs, or local storage.</li><li>Database credentials remain on the backend.</li><li>The UI proxy accepts direct loopback requests only; public hosts and tunnels need separate authenticated access.</li><li>Built-in runs use p01_true_sort or p02_false_sort. Custom code is limited to one sort input and stays blocked until Docker isolation verification passes.</li><li>AI questions need explicit server-side opt-in and a Gemini key; no paid-provider fallback is used.</li></ul><h3>Evidence labels</h3><p><code>TESTS_PASSED</code> means no counterexample was found in the executed tests. It does not prove correctness.</p></aside></div>`;
  }

  function loaderMark() { return `<svg class="loader-mark" viewBox="0 0 112 112" fill="none"><path d="M56 7 96 30v52l-40 23L16 82V30L56 7Z" stroke="#191917" stroke-width="6" stroke-linejoin="round"/><circle cx="56" cy="56" r="9" fill="#ef583c"/></svg>`; }

  async function checkApiConnection() {
    if (state.healthChecking || state.demo) return;
    state.healthChecking = true;
    state.connectionError = '';
    if (state.view !== 'run') render();
    try {
      const sessionResponse = await fetch('/ui-api/session', { headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!sessionResponse.ok) {
        const data = await readJson(sessionResponse);
        throw new Error(data?.detail || 'Server-side API proxy is not configured or is unavailable for this host.');
      }
      await connectServerProxy();
    } catch (error) {
      state.apiReady = false;
      state.connected = false;
      state.connectionError = error.message || 'Could not reach the server-side API proxy.';
      state.qaAvailable = false;
      state.qaReason = 'not_connected';
      state.customAvailable = false;
      state.customReason = 'not_connected';
    } finally {
      state.healthChecking = false;
    }
    if (state.view !== 'run') render();
  }

  async function connectServerProxy() {
    state.connectionError = '';
    try {
      const { response: health } = await apiRequest('/ui-api/health/ready');
      state.apiReady = health.ok;
      const { data: problems } = await apiRequest('/ui-api/v1/problems');
      if (!Array.isArray(problems) || problems.length !== 2) throw new Error('The API did not return its two supported built-in problems.');
      state.problems = problems;
      state.connected = true;
      state.adminAllowed = false;
      state.adminForbidden = false;
      state.clients = null;
      try {
        const { data: clients } = await apiRequest('/ui-api/v1/admin/clients');
        state.clients = Array.isArray(clients) ? clients : [];
        state.adminAllowed = true;
      } catch (error) {
        state.adminForbidden = error.status === 403;
      }
      try {
        const { data: capabilities } = await apiRequest('/ui-api/v1/capabilities');
        state.qaAvailable = capabilities?.questions?.available === true;
        state.qaReason = capabilities?.questions?.reason || (state.qaAvailable ? '' : 'qa_disabled');
        state.customAvailable = capabilities?.custom_code?.available === true;
        state.customReason = capabilities?.custom_code?.reason || (state.customAvailable ? '' : 'day37_verification_not_passed');
      } catch {
        state.qaAvailable = false;
        state.qaReason = 'not_connected';
        state.customAvailable = false;
        state.customReason = 'not_connected';
      }
      state.connectionError = '';
      return true;
    } catch (error) {
      state.connected = false;
      state.apiReady = false;
      state.adminAllowed = false;
      state.connectionError = error.message || 'Could not reach the configured Abacus API.';
      return false;
    }
  }

  async function readJson(response) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) return null;
    try { return await response.json(); } catch { return null; }
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');
    const response = await fetch(path, { ...options, headers, cache: 'no-store' });
    const data = await readJson(response);
    if (!response.ok) {
      const error = new Error(errorMessage(response.status, data));
      error.status = response.status;
      error.retryAfter = retryAfterSeconds(response.headers.get('Retry-After'));
      if (response.status === 429 && path.includes('/v1/runs')) error.message = `Run quota reached. Retry after ${error.retryAfter} second${error.retryAfter === 1 ? '' : 's'}.`;
      throw error;
    }
    return { response, data };
  }

  function errorMessage(status, data) {
    if (data?.detail && typeof data.detail === 'object') {
      const detail = data.detail;
      if (detail.code === 'qa_disabled') return 'AI questions are disabled on the backend.';
      if (detail.code === 'gemini_not_configured') return 'A Gemini API key is not configured on the backend.';
      if (detail.code === 'qa_requires_gemini') return 'This pilot does not fall back to a paid AI provider.';
      if (detail.code === 'day37_verification_not_passed') return 'Custom code was not run: Docker sandbox verification has not passed.';
      if (detail.code === 'execution_flag_disabled') return 'Custom code execution is disabled by the backend operator.';
      if (detail.message) return detail.message;
    }
    if (status === 401) return 'The backend rejected its server-side API key. Check the FastAPI host configuration.';
    if (status === 403) return 'This server-side API key does not have permission for that page or action.';
    if (status === 404) return 'The run or problem could not be found for this API key.';
    if (status === 409) return 'This run request conflicts with an earlier idempotency key. Start a fresh evaluation.';
    if (status === 429) return 'Run quota reached. Wait for the Retry-After interval before submitting another run.';
    if (status === 500) return 'The API could not complete this request. Check the service and try again later.';
    if (status === 503) return 'The API or its database is temporarily unavailable. Check readiness, then retry.';
    if (status === 400) return 'The API rejected the request format. Refresh the app and try again.';
    if (data?.detail && typeof data.detail === 'string') return data.detail;
    return `The API returned HTTP ${status}. Try again after checking the service.`;
  }

  async function loadAdmin() {
    if (!state.connected || state.demo) return;
    state.clients = null;
    state.adminForbidden = false;
    render();
    try {
      const { data } = await apiRequest('/ui-api/v1/admin/clients');
      state.clients = Array.isArray(data) ? data : [];
    } catch (error) {
      if (error.status === 403) { state.adminForbidden = true; state.adminAllowed = false; }
      else toast(error.message, 'error');
    }
    render();
  }

  async function openRun(runId) {
    if (state.busy) return;
    state.view = 'run';
    state.currentRun = null;
    state.search = '';
    state.busy = !state.demo;
    state.busyMessage = 'Loading the authoritative run record…';
    render();
    if (state.demo) {
      state.currentRun = demoRuns.find((run) => run.run_id === runId) || null;
      render();
      return;
    }
    if (!state.connected) {
      state.busy = false;
      state.busyMessage = '';
      render();
      toast('The server-side API proxy is not connected. Check its settings before fetching live run data.', 'error');
      return;
    }
    try {
      await fetchRunUntilTerminal(runId);
    } catch (error) {
      state.currentRun = null;
      toast(error.message, 'error');
    } finally {
      state.busy = false;
      state.busyMessage = '';
      render();
    }
  }

  function randomIdempotencyKey() {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
    if (!globalThis.crypto?.getRandomValues) throw new Error('Secure UUID generation is unavailable in this browser. Open Abacus on localhost or HTTPS.');
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  function wait(ms) {
    return new Promise((resolve) => {
      const waitChunk = (remaining) => {
        const chunk = Math.min(remaining, 2147483647);
        window.setTimeout(() => remaining > chunk ? waitChunk(remaining - chunk) : resolve(), chunk);
      };
      waitChunk(Math.max(0, ms));
    });
  }
  function retryAfterSeconds(value) {
    if (value == null || value === '') return 1;
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.max(1, Math.ceil(seconds));
    const date = Date.parse(value);
    return Number.isNaN(date) ? 1 : Math.max(1, Math.ceil((date - Date.now()) / 1000));
  }
  const retryDelay = (seconds) => Math.max(1, Number(seconds) || 1) * 1000;

  async function fetchRunUntilTerminal(runId) {
    while (true) {
      const result = await apiRequest(`/ui-api/v1/runs/${encodeURIComponent(runId)}`);
      const run = result.data;
      state.currentRun = run;
      saveRecentRun(run);
      if (!['queued', 'running'].includes(run.state)) {
        state.nextPollAt = 0;
        render();
        return run;
      }
      const delay = retryDelay(retryAfterSeconds(result.response.headers.get('Retry-After')));
      state.nextPollAt = Date.now() + delay;
      state.busy = true;
      state.busyMessage = run.state === 'queued' ? 'Waiting for the worker…' : 'Checking the evaluation…';
      render();
      await wait(delay);
    }
  }

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
      const { data } = await apiRequest('/ui-api/v1/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomIdempotencyKey() },
        body: JSON.stringify({ problem_id: selected }),
      });
      if (!data?.run_id) throw new Error('The API accepted the request but did not return a run ID.');
      const runId = data.run_id;
      state.view = 'run';
      state.currentRun = data;
      state.busyMessage = 'Fetching the authoritative run record…';
      render();
      await fetchRunUntilTerminal(runId);
      state.busy = false;
      state.busyMessage = '';
      render();
    } catch (error) {
      state.busy = false;
      state.busyMessage = '';
      state.error = error.message;
      state.retryAvailable = error.status === 503 || error.status === 429;
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
    state.busy = true;
    state.busyMessage = 'Refreshing the authoritative run record…';
    try {
      if (state.nextPollAt > Date.now()) {
        state.busyMessage = 'Waiting for the API Retry-After interval…';
        render();
        await wait(state.nextPollAt - Date.now());
      }
      await fetchRunUntilTerminal(state.currentRun.run_id);
    } catch (error) { toast(error.message, 'error'); }
    finally { state.busy = false; state.busyMessage = ''; render(); }
  }

  async function submitQuestion() {
    if (state.qaBusy || !state.connected || !state.qaAvailable || state.demo) return;
    const question = state.questionText.trim();
    if (!question) { state.qaError = 'Enter a question first.'; render(); return; }
    state.qaBusy = true;
    state.qaError = '';
    render();
    try {
      const { data } = await apiRequest('/ui-api/v1/questions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (!data?.answer || data.provider_api_called !== true) throw new Error('The API did not return a live AI answer.');
      state.qaMessages.push({ question, answer: data.answer, provider: data.provider, model: data.model, disclaimer: data.disclaimer });
      state.questionText = '';
    } catch (error) {
      state.qaError = error.message || 'The AI provider did not return an answer.';
    } finally {
      state.qaBusy = false;
      render();
    }
  }

  async function submitCustomCheck() {
    if (state.customBusy || !state.connected || !state.customAvailable || state.demo) return;
    let values;
    try {
      values = JSON.parse(state.customInput);
      if (!Array.isArray(values) || values.length > 100 || !values.every(Number.isSafeInteger)) {
        throw new Error('Input must be a JSON array of up to 100 safe integers.');
      }
    } catch (error) {
      state.customError = error.message || 'Enter a valid JSON integer array.';
      render();
      return;
    }
    state.customBusy = true;
    state.customError = '';
    state.customResult = null;
    render();
    try {
      const { data } = await apiRequest('/ui-api/v1/custom-checks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: state.customSource, input: values }),
      });
      state.customResult = data;
    } catch (error) {
      state.customError = error.message || 'The sandbox did not return a result.';
    } finally {
      state.customBusy = false;
      render();
    }
  }

  function enterDemo() {
    state.connected = false;
    state.demo = true;
    state.apiReady = null;
    state.clients = null;
    state.adminAllowed = false;
    state.qaAvailable = false;
    state.customAvailable = false;
    state.connectionError = '';
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
      } else {
        await checkApiConnection();
        if (state.connected) toast('The server-side API proxy and backend are ready.');
      }
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
    } else if (action === 'demo') {
      enterDemo();
    } else if (action === 'exit-demo') {
      state.demo = false;
      state.view = 'overview';
      state.currentRun = null;
      render();
      checkApiConnection();
    } else if (action === 'copy') {
      await copyText(actionButton.dataset.copy || '');
    }
  });

  document.addEventListener('submit', async (event) => {
    if (event.target.id === 'question-form') {
      event.preventDefault();
      await submitQuestion();
    } else if (event.target.id === 'custom-form') {
      event.preventDefault();
      await submitCustomCheck();
    }
  });

  document.addEventListener('input', (event) => {
    if (event.target.id === 'question-text') state.questionText = event.target.value;
    if (event.target.id === 'custom-source') state.customSource = event.target.value;
    if (event.target.id === 'custom-input') state.customInput = event.target.value;
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
