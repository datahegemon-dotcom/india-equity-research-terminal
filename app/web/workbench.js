/* Workbench client.
 *
 * Deliberately dependency free. The interaction surface is small: adjust seven
 * sliders, fill some text, tick ten boxes, publish. That does not justify a
 * build step in a local, zero-cost tool.
 */

const state = {
  meta: null,
  reports: [],
  record: null,
  decision: null,
  saveTimer: null,
  saving: false,
};

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ helpers

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

function toast(message, bad = false) {
  const el = $('toast');
  el.textContent = message;
  el.classList.toggle('bad', bad);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4200);
}

const fmt = {
  rupees: (v, d = 2) => (v === null || v === undefined || v === '' ? '—' : `₹${Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`),
  crore: (v) => (v === null || v === undefined ? '—' : (Number(v) / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 0 })),
  pct: (v, d = 1) => (v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(d)}%`),
  signed: (v, d = 1) => (v === null || v === undefined ? '—' : `${(Number(v) * 100) >= 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`),
  x: (v, d = 2) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(d)}x`),
  num: (v, d = 1) => (v === null || v === undefined ? '—' : Number(v).toFixed(d)),
  date: (v) => (v ? new Date(v).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' }) : '—'),
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

const lines = (list) => (list || []).join('\n');
const parseLines = (text) => text.split('\n').map((s) => s.trim()).filter(Boolean);

// -------------------------------------------------------------------- state

function payload() { return state.record.payload; }

function queueSave() {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(save, 450);
}

async function save() {
  if (!state.record) return;
  state.saving = true;
  try {
    const p = payload();
    const body = {
      scores: p.scores,
      score_notes: p.score_notes,
      context: p.context,
      narrative: p.narrative,
      scenarios: p.scenarios,
    };
    const result = await api(`/reports/${state.record.id}`, { method: 'PUT', body: JSON.stringify(body) });
    state.record = result.record;
    state.decision = result.decision;
    renderHead();
  } catch (error) {
    toast(`Could not save: ${error.message}`, true);
  } finally {
    state.saving = false;
  }
}

// ------------------------------------------------------------------ loading

async function loadReports() {
  state.reports = await api('/reports');
  renderReportList();
}

async function openReport(id) {
  const result = await api(`/reports/${id}`);
  state.record = result.record;
  state.decision = result.decision;
  $('empty').hidden = true;
  $('report').hidden = false;
  renderAll();
  renderReportList();
  window.scrollTo({ top: 0 });
}

function renderAll() {
  renderHead();
  renderScoring();
  renderRules();
  renderValuation();
  renderNarrative();
  renderAudit();
  renderData();
}

// -------------------------------------------------------------------- views

function renderReportList() {
  const el = $('report-list');
  if (!state.reports.length) {
    el.innerHTML = '<p class="small dim">No reports yet.</p>';
    return;
  }
  const groups = { draft: [], published: [] };
  state.reports.forEach((r) => groups[r.status === 'published' ? 'published' : 'draft'].push(r));

  const section = (title, items) => (items.length
    ? `<div class="reportlist__group">${title}</div>` + items.map((r) => `
        <button class="reportitem" data-id="${r.id}" aria-current="${state.record && state.record.id === r.id}">
          <strong>${escapeHtml(r.company_name || r.ticker)}</strong>
          <span>${escapeHtml(r.ticker)} · ${escapeHtml((r.updated_at || '').slice(0, 10))}</span>
        </button>`).join('')
    : '');

  el.innerHTML = section('Drafts', groups.draft) + section('Published', groups.published);
  el.querySelectorAll('.reportitem').forEach((b) => {
    b.addEventListener('click', () => openReport(Number(b.dataset.id)));
  });
}

function toneClass(tone) { return `tone-${tone}`; }

function renderHead() {
  const r = state.record;
  const d = state.decision;
  const company = payload().analysis.company || {};

  const columns = d.columns.map((c) => `
    <div class="column" style="flex:${c.weight} 1 0; height:100%;" title="${escapeHtml(c.label)} ${c.score}/10">
      <div class="column__fill${c.tone === 'strong' ? ' column__fill--strong' : c.tone === 'weak' ? ' column__fill--weak' : ''}" style="height:${c.fill}%"></div>
    </div>`).join('');

  $('workhead').innerHTML = `
    <div class="workhead__top">
      <div>
        <h1>${escapeHtml(company.name || r.ticker)}</h1>
        <div class="factline">
          <span>NSE <b>${escapeHtml(r.ticker)}</b></span>
          <span>Price <b>${fmt.rupees(company.price)}</b></span>
          ${company.sector ? `<span>Sector <b>${escapeHtml(company.sector)}</b></span>` : ''}
          <span>Framework <b>${escapeHtml((payload().analysis.profile || {}).label || 'Generic')}</b></span>
          <span>Status <b>${escapeHtml(r.status)}</b></span>
        </div>
      </div>
      <div class="actions">
        <button class="quiet" id="btn-refresh">Refresh data</button>
        <button class="quiet" id="btn-preview">Preview page</button>
        ${r.status === 'published'
          ? '<button class="quiet" id="btn-unpublish">Unpublish</button>'
          : `<button class="primary" id="btn-publish" ${d.publishable ? '' : 'disabled'}>Publish</button>`}
      </div>
    </div>

    <div class="headline">
      <div>
        <div class="headline__score">${fmt.num(d.total, 1)}<small> / 100</small></div>
        <div class="headline__meta">${escapeHtml(d.band)}</div>
      </div>
      <div>
        <div class="headline__verdict ${toneClass(d.tone)}">${escapeHtml(d.action)}</div>
        <div class="headline__meta">Margin of safety ${escapeHtml(d.margin_of_safety)}</div>
      </div>
      <div class="minibar">${columns}</div>
    </div>

    ${d.labels.length ? `<div class="blockers"><h4>Rules applied</h4><ul>${d.labels.map((l) => `<li>${escapeHtml(l)}</li>`).join('')}</ul></div>` : ''}
    ${d.publish_blockers.length ? `<div class="blockers"><h4>Not publishable yet</h4><ul>${d.publish_blockers.map((b) => `<li>${escapeHtml(b)}</li>`).join('')}</ul></div>` : ''}
  `;

  const bind = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', fn); };
  bind('btn-refresh', refreshData);
  bind('btn-preview', () => window.open(`/api/reports/${r.id}/preview`, '_blank'));
  bind('btn-publish', publishReport);
  bind('btn-unpublish', unpublishReport);
}

function renderScoring() {
  const p = payload();
  const drafts = p.analysis.drafts || {};
  const weights = state.meta.weights;
  const labels = state.meta.labels;

  $('scoring').innerHTML = Object.keys(weights).map((key) => {
    const draft = drafts[key] || {};
    const score = p.scores[key];
    const proposed = p.draft_scores ? p.draft_scores[key] : draft.score;
    const moved = Number(score) !== Number(proposed);
    const contribution = (Number(score) / 10) * weights[key];

    const evidence = (draft.adjustments || []).map((a) => `
      <li><span class="pts ${a.points > 0 ? 'up' : 'down'}">${a.points > 0 ? '+' : ''}${a.points}</span>
          <span>${escapeHtml(a.reason)}. <span class="dim">${escapeHtml(a.evidence)}</span></span></li>`).join('');

    return `
      <div class="scorerow">
        <div class="scorerow__id">
          <strong>${escapeHtml(labels[key])}</strong>
          <span>Weight ${weights[key]}${key === 'risk' ? ' · ten is low risk' : ''}</span>
          ${draft.requires_analyst ? '<div class="needs-analyst">Needs your judgement</div>' : ''}
        </div>

        <div class="scorerow__control">
          <div class="slide">
            <input type="range" min="1" max="10" step="0.5" value="${score}" data-score="${key}" aria-label="${escapeHtml(labels[key])} score">
            <output class="slide__value" id="out-${key}">${score}</output>
          </div>
          <div class="proposal ${moved ? 'moved' : ''}">Proposed <b>${proposed}</b>${moved ? ` · you set ${score}` : ''} · confidence ${escapeHtml(draft.confidence || 'n/a')}</div>
          ${evidence ? `<ul class="evidence">${evidence}</ul>` : ''}
          ${draft.note ? `<p class="small dim" style="margin:.35rem 0 0;max-width:60ch">${escapeHtml(draft.note)}</p>` : ''}
          <div class="field" style="margin:.5rem 0 0">
            <label for="note-${key}">Basis shown in the published report</label>
            <textarea id="note-${key}" data-note="${key}" rows="2" style="min-height:3.4rem">${escapeHtml(p.score_notes[key] || '')}</textarea>
          </div>
        </div>

        <div class="scorerow__contribution">
          <b id="contrib-${key}">${contribution.toFixed(1)}</b>
          <span>of ${weights[key]}</span>
        </div>
      </div>`;
  }).join('');

  $('scoring').querySelectorAll('[data-score]').forEach((input) => {
    input.addEventListener('input', () => {
      const key = input.dataset.score;
      const value = Number(input.value);
      payload().scores[key] = value;
      $(`out-${key}`).textContent = value;
      $(`contrib-${key}`).textContent = ((value / 10) * weights[key]).toFixed(1);
      queueSave();
    });
  });
  $('scoring').querySelectorAll('[data-note]').forEach((area) => {
    area.addEventListener('input', () => {
      payload().score_notes[area.dataset.note] = area.value;
      queueSave();
    });
  });
}

function renderRules() {
  const ctx = payload().context;
  const options = (values, chosen) => values.map((v) => `<option value="${escapeHtml(v)}" ${v === chosen ? 'selected' : ''}>${escapeHtml(v)}</option>`).join('');

  $('rules').innerHTML = `
    <div class="cols2">
      <div>
        <div class="field">
          <label for="ctx-mos">Margin of safety</label>
          <select id="ctx-mos" data-ctx="margin_of_safety">${options(state.meta.margin_of_safety, ctx.margin_of_safety)}</select>
        </div>
        <div class="field">
          <label for="ctx-gap">Expectations against what the company is delivering</label>
          <select id="ctx-gap" data-ctx="expectation_gap">${options(state.meta.expectation_gaps, ctx.expectation_gap)}</select>
        </div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-extreme" data-ctx-bool="valuation_extreme" ${ctx.valuation_extreme ? 'checked' : ''}>
          <label for="ctx-extreme">Valuation is demonstrably extreme against history, peers and cash flow</label>
        </div>
        <div class="field">
          <label for="ctx-compress">Multiple-compression note, required when the box above is ticked</label>
          <textarea id="ctx-compress" data-ctx="multiple_compression_note" rows="3">${escapeHtml(ctx.multiple_compression_note || '')}</textarea>
        </div>
      </div>

      <div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-risk" data-ctx-bool="severe_unresolved_risk" ${ctx.severe_unresolved_risk ? 'checked' : ''}>
          <label for="ctx-risk">A severe risk remains unresolved</label>
        </div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-turn" data-ctx-bool="credible_turnaround_catalyst" ${ctx.credible_turnaround_catalyst ? 'checked' : ''}>
          <label for="ctx-turn">A credible turnaround catalyst exists</label>
        </div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-conc" data-ctx-bool="portfolio_concentration_breach" ${ctx.portfolio_concentration_breach ? 'checked' : ''}>
          <label for="ctx-conc">Owning this breaches portfolio concentration limits</label>
        </div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-break" data-ctx-bool="thesis_break" ${ctx.thesis_break ? 'checked' : ''}>
          <label for="ctx-break">The thesis has broken</label>
        </div>
        <div class="field--inline">
          <input type="checkbox" id="ctx-severe" data-ctx-bool="thesis_break_severe" ${ctx.thesis_break_severe ? 'checked' : ''}>
          <label for="ctx-severe">The break is severe enough to exit rather than reduce</label>
        </div>
        <div class="field">
          <label for="ctx-reasons">Evidence for the break, one per line</label>
          <textarea id="ctx-reasons" data-ctx-lines="thesis_break_reasons" rows="3">${escapeHtml(lines(ctx.thesis_break_reasons))}</textarea>
        </div>
        <div class="field">
          <label for="ctx-asym">Asymmetry argument, needed to buy below a score of 85</label>
          <textarea id="ctx-asym" data-ctx="asymmetry_justification" rows="3">${escapeHtml(ctx.asymmetry_justification || '')}</textarea>
        </div>
      </div>
    </div>`;

  bindContext($('rules'));
}

function bindContext(root) {
  root.querySelectorAll('[data-ctx]').forEach((el) => {
    el.addEventListener('input', () => { payload().context[el.dataset.ctx] = el.value; queueSave(); });
    el.addEventListener('change', () => { payload().context[el.dataset.ctx] = el.value; queueSave(); });
  });
  root.querySelectorAll('[data-ctx-bool]').forEach((el) => {
    el.addEventListener('change', () => { payload().context[el.dataset.ctxBool] = el.checked; queueSave(); });
  });
  root.querySelectorAll('[data-ctx-lines]').forEach((el) => {
    el.addEventListener('input', () => { payload().context[el.dataset.ctxLines] = parseLines(el.value); queueSave(); });
  });
}

function renderValuation() {
  const p = payload();
  const price = (p.analysis.company || {}).price;
  const rows = (p.scenarios || []).map((s, i) => `
    <tr>
      <td style="text-align:left"><input value="${escapeHtml(s.name)}" data-scn="${i}" data-field="name"></td>
      <td><input type="number" step="0.01" value="${s.value_per_share ?? ''}" data-scn="${i}" data-field="value_per_share"></td>
      <td>${s.value_per_share && price ? fmt.signed(s.value_per_share / price - 1) : '—'}</td>
      <td><input type="number" step="0.01" min="0" max="1" placeholder="leave blank" value="${s.probability ?? ''}" data-scn="${i}" data-field="probability"></td>
      <td style="text-align:left"><input value="${escapeHtml(s.description || '')}" data-scn="${i}" data-field="description"></td>
    </tr>`).join('');

  const rel = p.analysis.relative || {};
  const wacc = p.analysis.wacc || {};
  const dcf = p.analysis.dcf;

  $('valuation').innerHTML = `
    <div class="table-scroll">
      <table class="scenario-editor">
        <thead><tr><th style="text-align:left">Scenario</th><th>Value per share</th><th>Against price</th><th>Probability</th><th style="text-align:left">Assumption</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="dim">No scenarios could be built from the available data.</td></tr>'}</tbody>
      </table>
    </div>
    ${state.decision.expected_value ? `<p class="small" style="margin-top:.75rem">Expected value ${fmt.rupees(state.decision.expected_value, 0)} against a price of ${fmt.rupees(price)}.</p>` : '<p class="small dim" style="margin-top:.75rem">Expected value is omitted until every scenario carries a defensible probability.</p>'}

    <div class="cols2" style="margin-top:1.5rem">
      <dl class="kv">
        <dt>Price to earnings now</dt><dd>${fmt.num(rel.current_pe, 1)}</dd>
        <dt>Five-year median</dt><dd>${fmt.num(rel.median_pe, 1)}</dd>
        <dt>Premium to median</dt><dd>${fmt.signed(rel.pe_premium)}</dd>
        <dt>Price to book now</dt><dd>${fmt.num(rel.current_pb, 2)}</dd>
        <dt>Free cash flow yield</dt><dd>${fmt.pct((p.analysis.company || {}).fcf_yield)}</dd>
      </dl>
      <dl class="kv">
        <dt>Cost of equity</dt><dd>${fmt.pct(wacc.cost_of_equity)}</dd>
        <dt>Cost of capital</dt><dd>${fmt.pct(wacc.wacc)}</dd>
        <dt>Beta used</dt><dd>${fmt.num(wacc.beta, 2)}</dd>
        ${dcf ? `<dt>Discounted cash flow value</dt><dd>${fmt.rupees(dcf.value_per_share, 0)}</dd>
        <dt>Terminal share of value</dt><dd>${fmt.pct(dcf.terminal_share, 0)}</dd>` : ''}
      </dl>
    </div>

    ${(p.analysis.valuation_flags || []).length ? `<div class="blockers" style="border-left-color:var(--marigold)"><h4>Valuation checks</h4><ul>${p.analysis.valuation_flags.map((f) => `<li>${escapeHtml(f)}</li>`).join('')}</ul></div>` : ''}
  `;

  $('valuation').querySelectorAll('[data-scn]').forEach((input) => {
    input.addEventListener('input', () => {
      const scenario = payload().scenarios[Number(input.dataset.scn)];
      const field = input.dataset.field;
      if (field === 'value_per_share' || field === 'probability') {
        scenario[field] = input.value === '' ? null : Number(input.value);
      } else {
        scenario[field] = input.value;
      }
      queueSave();
    });
  });
}

function renderNarrative() {
  const n = payload().narrative;
  const block = (key, label, hint, rows = 4) => `
    <div class="field">
      <label for="nar-${key}">${label}</label>
      <textarea id="nar-${key}" data-nar-lines="${key}" rows="${rows}" placeholder="${escapeHtml(hint)}">${escapeHtml(lines(n[key]))}</textarea>
    </div>`;

  $('narrative').innerHTML = `
    <div class="cols2">
      <div>
        ${block('why', 'Why this conclusion, at most five points', 'One point per line')}
        ${block('market_missing', 'What the market may be missing, at most three points', 'One point per line', 3)}
        <div class="field">
          <label for="nar-against">The strongest argument against this view</label>
          <textarea id="nar-against" data-nar="against" rows="3" placeholder="Framework 22 requires at least one.">${escapeHtml(n.against || '')}</textarea>
        </div>
      </div>
      <div>
        ${block('catalysts', 'Catalysts, with timing and what would confirm each', 'One per line', 4)}
        ${block('risks', 'Top risks', 'One per line', 4)}
        ${block('invalidation', 'What would break this thesis, with measurable thresholds', 'One per line', 4)}
        ${block('monitor', 'What to monitor, five to ten items', 'One per line', 4)}
      </div>
    </div>`;

  $('narrative').querySelectorAll('[data-nar-lines]').forEach((el) => {
    el.addEventListener('input', () => { payload().narrative[el.dataset.narLines] = parseLines(el.value); queueSave(); });
  });
  $('narrative').querySelectorAll('[data-nar]').forEach((el) => {
    el.addEventListener('input', () => { payload().narrative[el.dataset.nar] = el.value; queueSave(); });
  });
}

function renderAudit() {
  const audit = payload().context.audit || {};
  const questions = state.meta.audit_questions;
  $('audit').innerHTML = Object.keys(questions).map((key) => `
    <div class="field--inline">
      <input type="checkbox" id="audit-${key}" data-audit="${key}" ${audit[key] ? 'checked' : ''}>
      <label for="audit-${key}">${escapeHtml(questions[key])}</label>
    </div>`).join('');

  $('audit').querySelectorAll('[data-audit]').forEach((el) => {
    el.addEventListener('change', () => {
      payload().context.audit = payload().context.audit || {};
      payload().context.audit[el.dataset.audit] = el.checked;
      queueSave();
    });
  });
}

function renderData() {
  const a = payload().analysis;
  const core = a.core_table || { rows: [] };
  const tech = a.technical || {};

  const coreRows = core.rows.map((r) => `
    <tr>
      <td>${escapeHtml(r.label)}</td>
      <td>${fmt.crore(r.revenue)}</td>
      <td>${fmt.pct(r.ebitda_margin)}</td>
      <td>${fmt.crore(r.pat)}</td>
      <td>${fmt.num(r.eps, 2)}</td>
      <td>${fmt.crore(r.cfo)}</td>
      <td>${fmt.x(r.cfo_to_pat)}</td>
      <td>${fmt.pct(r.roce)}</td>
      <td>${fmt.crore(r.net_debt)}</td>
    </tr>`).join('');

  const quarterRows = (a.quarterly || []).map((q) => `
    <tr>
      <td>${escapeHtml(q.label)}</td>
      <td>${fmt.crore(q.revenue)}</td>
      <td class="${q.revenue_yoy > 0 ? 'pos' : q.revenue_yoy < 0 ? 'neg' : ''}">${fmt.signed(q.revenue_yoy)}</td>
      <td>${fmt.pct(q.ebitda_margin)}</td>
      <td>${fmt.crore(q.pat)}</td>
      <td class="${q.pat_yoy > 0 ? 'pos' : q.pat_yoy < 0 ? 'neg' : ''}">${fmt.signed(q.pat_yoy)}</td>
    </tr>`).join('');

  const flags = ((a.forensics || {}).flags || []).map((f) => `
    <li><strong>${escapeHtml(f.title)}.</strong> ${escapeHtml(f.observation)}</li>`).join('');

  $('data').innerHTML = `
    ${(a.warnings || []).length ? `<div class="blockers" style="border-left-color:var(--marigold)"><h4>Data gaps</h4><ul>${a.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul></div>` : ''}

    <div class="table-scroll" style="margin-top:1.25rem">
      <table>
        <caption>Annual record, figures in crore</caption>
        <thead><tr><th>Year to</th><th>Revenue</th><th>Margin</th><th>Profit</th><th>Earnings per share</th><th>Operating cash</th><th>Cash to profit</th><th>Return on capital</th><th>Net debt</th></tr></thead>
        <tbody>${coreRows || '<tr><td colspan="9" class="dim">No annual data.</td></tr>'}</tbody>
      </table>
    </div>

    <div class="table-scroll" style="margin-top:1.5rem">
      <table>
        <caption>Recent quarters</caption>
        <thead><tr><th>Quarter to</th><th>Revenue</th><th>Year on year</th><th>Margin</th><th>Profit</th><th>Profit year on year</th></tr></thead>
        <tbody>${quarterRows || '<tr><td colspan="6" class="dim">No quarterly data available from the free source.</td></tr>'}</tbody>
      </table>
    </div>

    <div class="cols2" style="margin-top:1.5rem">
      <div>
        <dl class="kv">
          <dt>Red-flag score</dt><dd>${(a.forensics || {}).score ?? '—'} (${escapeHtml((a.forensics || {}).concern || '')})</dd>
          <dt>Cumulative cash conversion</dt><dd>${fmt.x((a.forensics || {}).cash_conversion)}</dd>
          <dt>Balance-sheet strength</dt><dd>${fmt.num((a.forensics || {}).financial_strength, 1)} / 10</dd>
        </dl>
        ${flags ? `<ul class="list-clean small" style="margin-top:.75rem">${flags}</ul>` : '<p class="small dim">No red flags raised.</p>'}
      </div>
      <div>
        <dl class="kv">
          <dt>Technical score</dt><dd>${tech.score ?? '—'} / 10</dd>
          <dt>Trend</dt><dd>${escapeHtml(tech.trend || '—')}</dd>
          <dt>Relative strength index</dt><dd>${fmt.num(tech.rsi14, 1)}</dd>
          <dt>200 day average</dt><dd>${fmt.rupees(tech.sma200, 0)}</dd>
          <dt>Support</dt><dd>${(tech.support || []).map((v) => fmt.rupees(v, 0)).join('  ') || '—'}</dd>
          <dt>Resistance</dt><dd>${(tech.resistance || []).map((v) => fmt.rupees(v, 0)).join('  ') || '—'}</dd>
        </dl>
      </div>
    </div>`;
}

// ------------------------------------------------------------------ actions

async function refreshData() {
  const button = $('btn-refresh');
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span> Refreshing';
  try {
    const result = await api(`/reports/${state.record.id}/refresh`, { method: 'POST' });
    state.record = result.record;
    state.decision = result.decision;
    renderAll();
    toast('Market data refreshed. Your scores and notes are unchanged.');
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = 'Refresh data';
  }
}

async function publishReport() {
  await save();
  try {
    const result = await api(`/reports/${state.record.id}/publish`, { method: 'POST' });
    state.record = result.record;
    state.decision = result.decision;
    renderHead();
    await loadReports();
    await loadSiteStatus();
    toast(`Published to site/${state.record.slug}/. Commit and push to put it online.`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function unpublishReport() {
  try {
    const result = await api(`/reports/${state.record.id}/unpublish`, { method: 'POST' });
    state.record = result.record;
    state.decision = result.decision;
    renderHead();
    await loadReports();
    await loadSiteStatus();
    toast('Removed from the site. Commit and push to take it offline.');
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadSiteStatus() {
  try {
    const status = await api('/site');
    $('site-status').textContent = status.published_count
      ? `${status.published_count} page${status.published_count === 1 ? '' : 's'} staged in site/`
      : 'Nothing staged for publication.';
  } catch {
    $('site-status').textContent = '';
  }
}

$('new-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const ticker = $('ticker').value.trim().toUpperCase();
  if (!ticker) return;
  const button = $('analyse-btn');
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>';
  $('new-status').textContent = `Fetching ${ticker}. This takes a few seconds.`;
  try {
    const result = await api('/reports', { method: 'POST', body: JSON.stringify({ ticker }) });
    $('ticker').value = '';
    $('new-status').textContent = 'Enter an NSE symbol. Data is fetched from free sources.';
    await loadReports();
    await openReport(result.record.id);
    toast(`${result.record.company_name || ticker} loaded with proposed scores.`);
  } catch (error) {
    $('new-status').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Analyse';
  }
});

(async function boot() {
  state.meta = await api('/meta');
  await loadReports();
  await loadSiteStatus();
  if (state.reports.length) openReport(state.reports[0].id);
})();
