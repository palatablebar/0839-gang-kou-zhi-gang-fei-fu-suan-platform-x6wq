(function () {
  var state = { payload: null, kind: 'bars', run: null, approved: false, correction: null };
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function setNotice(text) { $('notice').textContent = text || ''; }
  function renderIssues(data) {
    $('issue-count').textContent = data.issues.length + ' 条';
    $('issue-list').innerHTML = data.issues.length ? data.issues.map(function (item) {
      return '<li><span>' + esc(item.line || '-') + '</span><span>' + esc(item.key || '无主键') + '</span><code>' + esc(item.code) + '</code></li>';
    }).join('') : '<li class="empty">暂无异常</li>';
  }
  function renderBreakdown(items) {
    if (!items || !items.length) return '';
    return '<details><summary>' + items.length + ' 项</summary><ul>' + items.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('') + '</ul></details>';
  }
  function renderRows(data) {
    var labels = Object.assign({label: '记录'}, state.resultColumns);
    var source = data.row_kind === 'source';
    var hasBreakdown = data.rows.some(function (row) { return row.breakdown && row.breakdown.length; });
    var keys = source ? state.inputColumns : Object.keys(labels).filter(function (key) {
      return data.rows.some(function (row) { return Object.hasOwn(row, key); });
    });
    $('row-count').textContent = source ? data.rows.length + ' 行预览' :
      data.summary.PASS + ' 通过 / ' + data.summary.REVIEW + ' 复核 / ' + data.summary.REJECT + ' 阻断';
    var tail = source ? '' : '<th>结论</th>' + (hasBreakdown ? '<th>计算分项</th>' : '');
    $('row-head').innerHTML = '<tr>' + keys.map(function (key) { return '<th>' + esc(labels[key] || key) + '</th>'; }).join('') + tail + '</tr>';
    $('row-body').innerHTML = data.rows.length ? data.rows.map(function (row) {
      var values = keys.map(function (key) { return '<td class="' + (typeof row[key] === 'number' ? 'num' : '') + '">' + esc(row[key]) + '</td>'; }).join('');
      var verdict = source ? '' : '<td><span class="verdict" data-v="' + esc(row.verdict) + '">' + esc(row.verdict || '') + '</span><br><small>' + esc(row.reason || '') + '</small></td>';
      var breakdown = hasBreakdown ? '<td>' + renderBreakdown(row.breakdown) + '</td>' : '';
      return '<tr>' + values + verdict + breakdown + '</tr>';
    }).join('') : '<tr><td class="empty" colspan="' + (keys.length + (source ? 0 : 1)) + '">没有可展示条目</td></tr>';
  }
  function renderLedger(data) {
    if (!data.ledger) { $('ledger-list').innerHTML = '<p class="empty">运行对账后显示</p>'; return; }
    var values = data.ledger;
    $('ledger-list').innerHTML = [
      ['来源行', values.counts.input], ['采信行', values.counts.accepted], ['隔离行', values.counts.isolated],
      ['精确重复', values.counts.duplicates], ['忽略行', values.counts.ignored], ['计算条目', values.counts.computed]
    ].map(function (row) { return '<div class="ledger-row"><span>' + row[0] + '</span><strong>' + row[1] + '</strong></div>'; }).join('') +
      '<div class="ledger-row"><span>' + esc(values.metric_field) + '</span><strong>' + esc(values.metric_total) + '</strong></div>' +
      values.checks.map(function (check) { return '<div class="ledger-row"><span>' + esc(check.label) + '</span><strong class="' + (check.ok ? 'check-ok' : 'check-bad') + '">' + (check.ok ? '通过' : '异常') + '</strong></div>'; }).join('');
  }
  function render(data) {
    state.payload = data;
    $('chart-label').textContent = Object.values(state.resultColumns)[0];
    $('m-input').textContent = data.counts.input;
    $('m-accepted').textContent = data.counts.accepted;
    $('m-isolated').textContent = data.counts.isolated + data.counts.duplicates;
    $('m-rejected').textContent = data.summary.REJECT;
    renderRows(data);
    renderIssues(data);
    renderLedger(data);
    window.renderChart($('chart'), data.chart && data.chart.length ? (state.kind || 'bars') : 'bars', data.chart || []);
  }
  function stageButtons(stages) {
    $('stage-nav').innerHTML = stages.map(function (stage, index) {
      return '<button type="button" data-stage="' + stage.id + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '">' + esc(stage.name) + '</button>';
    }).join('');
    Array.from(document.querySelectorAll('[data-stage]')).forEach(function (button) {
      button.addEventListener('click', function () {
        document.querySelectorAll('[data-stage]').forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
        loadStage(button.getAttribute('data-stage'));
      });
    });
  }
  async function loadStage(stage) {
    try {
      setNotice('');
      document.body.setAttribute('aria-busy', 'true');
      var payload = await request('/api/stages/' + stage, {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      render(payload);
    } catch (error) { setNotice(error.message); }
    finally { document.body.removeAttribute('aria-busy'); }
  }
  async function runBatch() {
    try {
      setNotice('');
      $('run').disabled = true;
      var run = await request('/api/runs', {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      state.run = run;
      state.approved = run.status === 'APPROVED';
      render(run);
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = run.summary.REJECT > 0 || state.approved;
      $('hold').disabled = state.approved;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
      state.correction = null;
      syncCorrectionPanel();
    } catch (error) { setNotice(error.message); }
    finally { $('run').disabled = false; }
  }
  async function review(decision) {
    if (!state.run) return;
    try {
      var run = await request('/api/runs/' + state.run.run_id + '/review', {
        method: 'POST',
        body: JSON.stringify({decision: decision, comment: $('comment').value, expected_revision: state.run.revision})
      });
      state.run = run;
      state.approved = run.status === 'APPROVED';
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = true;
      $('hold').disabled = true;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
      syncCorrectionPanel();
    } catch (error) { setNotice(error.message); }
  }
  function parseClosures() {
    var lines = $('closures').value.split('\n').map(function (line) { return line.trim(); }).filter(Boolean);
    return lines.map(function (line) {
      var parts = line.split(',').map(function (cell) { return cell.trim(); });
      return {date: parts[0], status: (parts[1] || '').toUpperCase(), note: parts.slice(2).join(',')};
    });
  }
  function renderCorrectionPlan(data) {
    state.correction = data;
    var rows = data.plan.entries || [];
    $('corr-body').innerHTML = rows.length ? rows.map(function (row) {
      return '<tr><td>' + esc(row.container_id) + '</td>' +
        '<td><span class="verdict" data-v="' + esc(row.action) + '">' + esc(row.action) + '</span></td>' +
        '<td class="num">' + esc(row.original_fee_cents) + '</td>' +
        '<td class="num">' + esc(row.current_fee_cents) + '</td>' +
        '<td class="num">' + esc(row.booking_delta_cents) + '</td>' +
        '<td class="num">' + esc(row.cumulative_delta_cents) + '</td>' +
        '<td>' + esc(row.current_free_end) + '</td>' +
        '<td>' + (row.held_by_pending ? esc(row.tentative_free_end) + ' / ' + esc(row.tentative_fee_cents) : '—') + '</td></tr>';
    }).join('') : '<tr><td class="empty" colspan="8">没有可展示条目</td></tr>';
    var s = data.plan.summary;
    $('corr-summary').innerHTML = [
      ['入账箱数', s.booked], ['保留原账(待核)', s.held], ['无变化', s.unchanged],
      ['本次差额合计(分)', s.booking_delta_total_cents],
      ['累计守恒', s.balanced ? '通过' : '异常']
    ].map(function (pair) {
      var cls = pair[0] === '累计守恒' ? (s.balanced ? 'check-ok' : 'check-bad') : '';
      return '<div class="ledger-row"><span>' + pair[0] + '</span><strong class="' + cls + '">' + esc(pair[1]) + '</strong></div>';
    }).join('');
    var bookable = state.approved && s.held === 0 && s.balanced;
    $('corr-sign').disabled = !bookable;
    $('corr-hold').disabled = !state.approved;
    $('corr-notice').textContent = s.held ? '存在待核日期会改变免堆截止日或应收金额，已保留原账' :
      (bookable ? '可签发更正，差额将按增量入账' : '复算计划已生成');
  }
  async function previewCorrection() {
    if (!state.run) return;
    try {
      setNotice('');
      var closures = parseClosures();
      var docId = $('doc-id').value.trim();
      var resp = await request('/api/runs/' + state.run.run_id + '/corrections', {
        method: 'POST',
        body: JSON.stringify({doc_id: docId, closures: closures})
      });
      renderCorrectionPlan(resp);
      await refreshEvidence();
    } catch (error) { setNotice(error.message); }
  }
  async function reviewCorrection(decision) {
    if (!state.correction) return;
    try {
      var resp = await request('/api/runs/' + state.run.run_id + '/corrections/' + state.correction.correction_id + '/review', {
        method: 'POST',
        body: JSON.stringify({decision: decision, comment: $('comment').value || '休港补证更正', expected_revision: state.correction.revision})
      });
      state.correction = resp;
      var run = await request('/api/runs/' + state.run.run_id);
      state.run = run;
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      await refreshEvidence();
      setNotice(decision === 'APPROVED' ? '更正已签发，旧凭证版本保留' : '已保留原账，未记账');
      $('corr-sign').disabled = true;
    } catch (error) { setNotice(error.message); }
  }
  async function refreshEvidence() {
    if (!state.run) return;
    var versions = await request('/api/runs/' + state.run.run_id + '/evidence/versions');
    $('evidence-list').innerHTML = versions.length ? versions.map(function (item) {
      var label = item.version === 1 ? '原批次凭证' : ('更正凭证 v' + item.version);
      return '<li><a href="/api/runs/' + state.run.run_id + '/evidence/versions/' + item.version + '" download>' +
        esc(label) + '</a><code>' + esc(item.digest.slice(0, 12)) + '</code></li>';
    }).join('') : '<li class="empty">签发后显示</li>';
  }
  function syncCorrectionPanel() {
    var enabled = state.approved;
    $('doc-id').disabled = !enabled;
    $('closures').disabled = !enabled;
    $('corr-preview').disabled = !enabled;
    $('corr-sign').disabled = true;
    $('corr-hold').disabled = !enabled;
    $('correction-hint').textContent = enabled ? ('批次 rev ' + state.run.revision + '，可登记补证') : '先执行并签发批次';
    if (enabled) refreshEvidence().catch(function (error) { setNotice(error.message); });
  }
  async function boot() {
    try {
      var catalog = await request('/api/catalog');
      state.kind = catalog.chart;
      state.resultColumns = catalog.result_columns;
      state.inputColumns = catalog.columns;
      stageButtons(catalog.stages.slice(0, 5));
      document.querySelector('.rail-note').textContent = catalog.code + ' · ' + catalog.stages[6].name;
      await loadStage('intake');
    } catch (error) { setNotice(error.message); }
    $('run').addEventListener('click', runBatch);
    $('sign').addEventListener('click', function () { review('APPROVED'); });
    $('hold').addEventListener('click', function () { review('HELD'); });
    $('corr-preview').addEventListener('click', previewCorrection);
    $('corr-sign').addEventListener('click', function () { reviewCorrection('APPROVED'); });
    $('corr-hold').addEventListener('click', function () { reviewCorrection('HELD'); });
    $('profile').addEventListener('change', function () {
      state.run = null; state.approved = false; state.correction = null;
      $('sign').disabled = true; $('hold').disabled = true; $('download').hidden = true;
      $('doc-id').disabled = true; $('closures').disabled = true;
      $('corr-preview').disabled = true; $('corr-sign').disabled = true; $('corr-hold').disabled = true;
      $('corr-body').innerHTML = '<tr><td class="empty" colspan="8">暂无更正计划</td></tr>';
      $('corr-summary').innerHTML = ''; $('evidence-list').innerHTML = '<li class="empty">签发后显示</li>';
      $('run-status').textContent = '未执行批次'; $('revision').textContent = 'rev 0';
      loadStage('intake');
    });
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
