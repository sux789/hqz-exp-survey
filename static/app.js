const $ = (selector) => document.querySelector(selector);
const BASE = (document.querySelector('meta[name="exp-base"]')?.content || '').replace(/\/+$/, '');
const url = (path) => `${BASE}${path.startsWith('/') ? path : `/${path}`}`;
const state = {
  me: null,
  projects: [], project: null, detail: null, plotId: null,
  filters: { section: '', township: '', village: '', number: '' },
  saveTimer: null, saveRevision: 0, saveInFlight: false, toastTimer: null,
  map: null, polyline: null, markers: [], trackPoints: [], watchId: null, recording: false,
  lastTrackAt: 0,
};

// 列表列：header 是 Excel 表头原文（用于匹配「不显示列」），label 是界面显示
const COLUMNS = [
  { header: '小班号', label: '小班号', field: 'number' },
  { header: '样地号', label: '样地号', field: 'plots' },
  { header: '村委会', label: '村委会', field: 'village' },
  { header: '小班面积', label: '面积（亩）', field: 'area' },
  { header: '树种组成', label: '树种组成', field: 'composition' },
  { header: '郁闭度', label: '郁闭度', field: 'canopy' },
  { header: '平均胸径', label: '平均胸径', field: 'avg_dbh' },
  { header: '平均树高', label: '平均树高', field: 'avg_height' },
  { header: '采伐方式', label: '采伐方式', field: 'cut_method' },
  { header: '调查状态', label: '调查状态', field: 'status' },
];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function toast(message, error = false) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.toggle('error', error);
  node.classList.remove('hidden');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => node.classList.add('hidden'), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(url(path), options);
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('application/json') ? await response.json() : null;
  if (response.status === 401) {
    showLogin(payload?.login_url);
    throw new Error(payload?.error || '登录已过期，请重新登录');
  }
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload;
}

function showLogin(loginUrl) {
  // 统一账号：登录在森林门户 /forest/login 做，这里只给入口，不再收密码
  const target = loginUrl || `${BASE}/`;
  const link = $('#loginLink');
  if (link) {
    link.href = target.startsWith('/forest/') ? target : `/forest/login?next=${encodeURIComponent(target)}`;
  }
  $('#loginMask').classList.remove('hidden');
  $('#currentUser').classList.add('hidden');
  $('#adminLink').classList.add('hidden');
  $('#logoutButton').classList.add('hidden');
}

function hideLogin() {
  $('#loginMask').classList.add('hidden');
}

function updateTopbar() {
  const me = state.me;
  if (!me?.user) return showLogin();
  $('#currentUser').textContent = me.user;
  $('#currentUser').classList.remove('hidden');
  $('#logoutButton').classList.remove('hidden');
  const visible = me.role === 'admin';
  $('#adminLink').classList.toggle('hidden', !visible);
  $('#adminTip').classList.toggle('hidden', !visible);
}

function canSee(column) {
  const hidden = state.project?.params?.['不显示列'] || [];
  return !hidden.includes(column.header);
}

function showView(name) {
  ['projects', 'subcompartments', 'detail'].forEach((key) => {
    $(`#${key}View`).classList.toggle('hidden', key !== name);
  });
  $('#backButton').classList.toggle('hidden', name === 'projects');
  $('#saveStatus').classList.toggle('hidden', name !== 'detail');
  window.scrollTo(0, 0);
}

function navigate(path) {
  if (location.hash === path) handleRoute();
  else location.hash = path;
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

async function loadProjects() {
  stopTracking(false);
  showView('projects');
  $('#pageSubtitle').textContent = '调查项目';
  try {
    const data = await api('/api/projects');
    state.projects = data.projects;
    renderProjects();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderProjects() {
  $('#projectCount').textContent = `${state.projects.length} 个项目`;
  const list = $('#projectList');
  if (!state.projects.length) {
    list.innerHTML = '<div class="empty-state">尚未上传调查项目，请先选择调查设计总表。</div>';
    return;
  }
  list.innerHTML = state.projects.map((project) => `
    <button class="project-item" type="button" data-project-id="${project.id}">
      <span class="file-icon">XLSX</span>
      <span class="project-info"><strong>${escapeHtml(project.filename)}</strong><span>${project.subcompartment_count} 个小班 · ${formatDate(project.uploaded_at)}</span></span>
      <span class="open-label">进入项目 →</span>
    </button>`).join('');
  list.querySelectorAll('[data-project-id]').forEach((button) => {
    button.addEventListener('click', () => navigate(`#/project/${button.dataset.projectId}`));
  });
}

async function loadProject(projectId) {
  stopTracking(false);
  showView('subcompartments');
  $('#pageSubtitle').textContent = '小班列表';
  try {
    state.project = await api(`/api/projects/${projectId}`);
    state.filters = { section: '', township: '', village: '', number: '' };
    $('#projectTitle').textContent = state.project.filename;
    $('#projectMeta').textContent = `共 ${state.project.subcompartments.length} 个小班`;
    $('#exportAll').href = url(`/api/projects/${projectId}/export.xlsx`);
    $('#filterNumber').value = '';
    populateFilters();
    renderSubcompartments();
  } catch (error) {
    toast(error.message, true);
    navigate('#/');
  }
}

function filteredBefore(field) {
  const rows = state.project?.subcompartments || [];
  return rows.filter((row) => {
    if (field === 'section') return true;
    if (state.filters.section && row.fields.section !== state.filters.section) return false;
    if (field === 'township') return true;
    if (state.filters.township && row.fields.township !== state.filters.township) return false;
    return true;
  });
}

function setOptions(selector, rows, field, selected, allLabel) {
  const values = [...new Set(rows.map((row) => row.fields[field]).filter((value) => value !== null && value !== ''))]
    .sort((a, b) => String(a).localeCompare(String(b), 'zh-CN', { numeric: true }));
  const select = $(selector);
  select.innerHTML = `<option value="">${allLabel}</option>${values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('')}`;
  select.value = values.includes(selected) ? selected : '';
  return select.value;
}

function populateFilters() {
  setOptions('#filterSection', filteredBefore('section'), 'section', state.filters.section, '全部标段');
  state.filters.township = setOptions('#filterTownship', filteredBefore('township'), 'township', state.filters.township, '全部乡镇');
  state.filters.village = setOptions('#filterVillage', filteredBefore('village'), 'village', state.filters.village, '全部村委会');
}

function matchingRows() {
  const query = state.filters.number.trim().toLowerCase();
  return (state.project?.subcompartments || []).filter((row) => {
    if (state.filters.section && row.fields.section !== state.filters.section) return false;
    if (state.filters.township && row.fields.township !== state.filters.township) return false;
    if (state.filters.village && row.fields.village !== state.filters.village) return false;
    if (query && !String(row.fields.number || '').toLowerCase().includes(query)) return false;
    return true;
  });
}

function renderSubcompartments() {
  const rows = matchingRows();
  const columns = COLUMNS.filter(canSee);
  $('#filterCount').textContent = `匹配 ${rows.length} / ${state.project.subcompartments.length} 个小班`;
  $('#emptySubcompartments').classList.toggle('hidden', rows.length > 0);
  $('#subcompartmentHead').innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join('')}</tr>`;
  $('#subcompartmentRows').innerHTML = rows.map((row) => {
    const fields = row.fields;
    const cells = columns.map((column) => {
      if (column.field === 'number') {
        return `<td><button class="sub-link" type="button" data-sub-id="${row.id}">${escapeHtml(fields.number)}</button></td>`;
      }
      if (column.field === 'plots') {
        // 样地号直接可点：点哪块进哪块，＋ 就地新增，不用先进详情页
        const chips = (row.plots || []).map((plot) => `<button class="plot-chip ${plot.has_survey ? 'done' : ''}" type="button" data-sub-id="${row.id}" data-plot-id="${plot.id}">${escapeHtml(plot.plot_no)}</button>`).join('');
        return `<td class="plot-cell">${chips}<button class="plot-chip add" type="button" data-add-sub="${row.id}" title="新增样地">＋</button></td>`;
      }
      if (column.field === 'status') {
        const total = row.plots?.length || 0;
        const done = (row.plots || []).filter((plot) => plot.has_survey).length;
        return `<td><span class="status-pill ${done ? 'done' : ''}">${done ? `${done}/${total} 已调查` : `待调查（${total} 块）`}</span></td>`;
      }
      return `<td>${escapeHtml(fields[column.field] ?? '—')}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  }).join('');
  $('#subcompartmentRows').querySelectorAll('[data-sub-id]').forEach((button) => {
    button.addEventListener('click', () => navigate(
      button.dataset.plotId ? `#/sub/${button.dataset.subId}/${button.dataset.plotId}` : `#/sub/${button.dataset.subId}`));
  });
  $('#subcompartmentRows').querySelectorAll('[data-add-sub]').forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const data = await api(`/api/subcompartments/${button.dataset.addSub}/plots`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        toast(`已新增样地 ${data.plot.plot_no}`);
        navigate(`#/sub/${button.dataset.addSub}/${data.plot.id}`);
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function emptySurvey(detail) {
  const trees = {};
  detail.species.forEach(({ name }) => {
    trees[name] = {};
    detail.schema.diameters.forEach((dbh) => { trees[name][dbh] = { height: null, count: 0 }; });
  });
  const cut = {};
  detail.schema.diameters.forEach((dbh) => { cut[dbh] = 0; });
  return { trees, cut };
}

/** 当前正在填的那块样地（一个小班可以有多块）。 */
function currentPlot() {
  const plots = state.detail?.plots || [];
  return plots.find((plot) => plot.id === state.plotId) || plots[0] || null;
}

/** 后端给的空样地没有 trees 骨架，这里补上，避免渲染时空指针。 */
function plotSurveyReady(detail, plot) {
  if (!plot) return;
  if (!plot.survey?.trees || !Object.keys(plot.survey.trees).length) {
    plot.survey = emptySurvey(detail);
  }
}

async function loadDetail(subId, plotId) {
  stopTracking(false);
  showView('detail');
  $('#pageSubtitle').textContent = '样地调查';
  $('#surveyTable').innerHTML = '';
  try {
    state.detail = await api(`/api/subcompartments/${subId}`);
    const plots = state.detail.plots || [];
    const wanted = Number(plotId);
    state.plotId = (plots.find((plot) => plot.id === wanted) || plots[0])?.id ?? null;
    plots.forEach((plot) => plotSurveyReady(state.detail, plot));
    renderDetail();
    if (state.detail.params?.has_track !== false) initTrackMap();
  } catch (error) {
    toast(error.message, true);
    if (state.project) navigate(`#/project/${state.project.id}`);
    else navigate('#/');
  }
}

/** 样地条：当前样地实心绿，非当前灰色；已填过的加浅底提示。 */
function renderPlotBar() {
  const plots = state.detail?.plots || [];
  $('#plotChips').innerHTML = plots.map((plot) => `
    <button class="plot-chip ${plot.id === state.plotId ? 'active' : ''} ${plot.has_survey ? 'done' : ''}"
      type="button" role="tab" aria-selected="${plot.id === state.plotId}" data-plot="${plot.id}"
      title="样地 ${escapeHtml(plot.plot_no)}${plot.has_survey ? '（已调查）' : '（未调查）'}">${escapeHtml(plot.plot_no)}</button>`).join('');
  $('#plotChips').querySelectorAll('[data-plot]').forEach((button) => {
    button.addEventListener('click', () => switchPlot(Number(button.dataset.plot)));
  });
  $('#deletePlot').classList.toggle('hidden', plots.length <= 1);
}

/** 切样地：先把当前样地的调查/轨迹落盘，再换数据，避免串数据。 */
async function switchPlot(plotId) {
  if (!state.detail || !plotId || plotId === state.plotId) return;
  if (state.saveTimer) {
    clearTimeout(state.saveTimer);
    await saveSurvey();
  }
  stopTracking(true);
  state.plotId = plotId;
  const plot = currentPlot();
  plotSurveyReady(state.detail, plot);
  renderDetail();
  if (state.detail.params?.has_track !== false) initTrackMap();
  history.replaceState(null, '', `#/sub/${state.detail.id}/${plotId}`);
}

async function addPlot() {
  if (!state.detail) return;
  try {
    const data = await api(`/api/subcompartments/${state.detail.id}/plots`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    plotSurveyReady(state.detail, data.plot);
    state.detail.plots.push(data.plot);
    toast(`已新增样地 ${data.plot.plot_no}`);
    await switchPlot(data.plot.id);
  } catch (error) {
    toast(error.message, true);
  }
}

async function renamePlot(value) {
  const plot = currentPlot();
  if (!plot) return;
  const text = String(value || '').trim();
  if (!text || text === plot.plot_no) {
    $('#plotNumber').value = plot.plot_no;
    return;
  }
  try {
    const data = await api(`/api/subcompartments/${state.detail.id}/plots/${plot.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plot_no: text }),
    });
    plot.plot_no = data.plot.plot_no;
    $('#plotNumber').value = plot.plot_no;
    renderPlotBar();
    toast(`样地号已改为 ${plot.plot_no}`);
  } catch (error) {
    $('#plotNumber').value = plot.plot_no;   // 失败回退到旧号，避免界面和库里不一致
    toast(error.message, true);
  }
}

async function deletePlot() {
  const plot = currentPlot();
  const plots = state.detail?.plots || [];
  if (!plot || plots.length <= 1) return;
  const warn = `确认删除样地 ${plot.plot_no}？\n该样地的调查数据、照片、轨迹会一起删除，无法恢复。`;
  if (!window.confirm(warn)) return;
  try {
    await api(`/api/subcompartments/${state.detail.id}/plots/${plot.id}`, { method: 'DELETE' });
    state.detail.plots = plots.filter((item) => item.id !== plot.id);
    state.plotId = state.detail.plots[0]?.id ?? null;
    renderDetail();
    if (state.detail.params?.has_track !== false) initTrackMap();
    toast(`已删除样地 ${plot.plot_no}`);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderDetail() {
  const detail = state.detail;
  const plot = currentPlot();
  const fields = detail.fields;
  $('#subcompartmentTitle').textContent = fields.number;
  $('#subcompartmentMeta').textContent = [fields.section, fields.township, fields.village, `小班面积 ${fields.area ?? '—'} 亩`].filter(Boolean).join(' · ');
  renderPlotBar();
  $('#plotNumber').value = plot?.plot_no || '';
  $('#speciesChips').innerHTML = detail.species.map((item) => `<span class="species-chip">${item.coefficient}${escapeHtml(item.name)}</span>`).join('');
  renderSurveyTable();
  recalculateSurvey();
  renderPhotos();
  state.trackPoints = (plot?.track || []).slice();
  const cached = readTrackCache();
  if (cached.length > state.trackPoints.length) state.trackPoints = cached;
  applyParamsToDetail();
  updateTrackUI(true);
}

/** 「程序参数」sheet 决定详情页显示哪些工具、照片怎么压。 */
function applyParamsToDetail() {
  const plot = currentPlot();
  const params = state.detail?.params || {};
  const hasPhoto = params.has_photo !== false;
  const hasTrack = params.has_track !== false;
  $('#photoCard').classList.toggle('hidden', !hasPhoto);
  $('#trackCard').classList.toggle('hidden', !hasTrack);
  $('#toolsGrid').classList.toggle('single', !hasPhoto || !hasTrack);
  if (hasPhoto) {
    const ctx = PhotoTpl.context(params, {
      number: state.detail?.fields?.number,
      plotNo: plot?.plot_no,
    });
    $('#photoHint').textContent = `拍照后压缩到最长边 ${params.压缩最长边 || 1440}px、质量 `
      + `${params.压缩质量 ?? 0.8}，存手机相册 Pictures/${PhotoTpl.albumSubdir(params, ctx)}/；`
      + '时间与坐标优先取原片 EXIF。';
  } else {
    $('#photoHint').textContent = '';
  }
  $('#trackStatus').textContent = hasTrack
    ? `卫星底图需要网络；每 ${params.轨迹采样间隔 || 5} 秒取一个定位点。`
    : '';
}

function countControl(type, species, dbh, value) {
  const speciesAttr = species === null ? '' : `data-species="${escapeHtml(species)}"`;
  return `<div class="number-control"><button type="button" data-step="-1" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="减少株数">−</button><input class="survey-input" type="number" min="0" step="1" inputmode="numeric" value="${value || 0}" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="${type === 'cut' ? '采伐' : escapeHtml(species)} ${dbh}厘米株数"><button type="button" data-step="1" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="增加株数">+</button></div>`;
}

function renderSurveyTable() {
  const { schema, species } = state.detail;
  const survey = currentPlot().survey;
  let html = '<thead><tr><th class="dbh-cell" rowspan="2">胸径<br>(cm)</th>';
  species.forEach(({ name }) => { html += `<th colspan="2">${escapeHtml(name)}</th>`; });
  html += '<th class="cut-head" colspan="2">采伐</th>';
  species.forEach(({ name }) => { html += `<th colspan="2">${escapeHtml(name)}蓄积</th>`; });
  html += '</tr><tr>';
  species.forEach(() => { html += '<th>树高<br>(m)</th><th>株数</th>'; });
  html += '<th class="cut-head">株数</th><th class="cut-head">蓄积<br>(m³)</th>';
  species.forEach(() => { html += '<th>单株<br>(m³)</th><th>径阶<br>(m³)</th>'; });
  html += '</tr></thead><tbody>';
  schema.diameters.forEach((dbh) => {
    html += `<tr><td class="dbh-cell">${dbh}</td>`;
    species.forEach(({ name }) => {
      const values = survey.trees[name]?.[dbh] || { height: null, count: 0 };
      html += `<td><input class="survey-input" type="number" min="0" step="0.1" inputmode="decimal" value="${values.height ?? ''}" data-type="height" data-species="${escapeHtml(name)}" data-dbh="${dbh}" aria-label="${escapeHtml(name)} ${dbh}厘米树高"></td>`;
      html += `<td>${countControl('count', name, dbh, values.count)}</td>`;
    });
    html += `<td class="cut-cell">${countControl('cut', null, dbh, survey.cut?.[dbh])}</td><td class="calc-cell cut-cell" id="cut-volume-${dbh}">0.000</td>`;
    species.forEach(({ name }) => {
      html += `<td class="calc-cell" id="unit-${escapeHtml(name)}-${dbh}">0.000</td><td class="calc-cell" id="volume-${escapeHtml(name)}-${dbh}">0.000</td>`;
    });
    html += '</tr>';
  });
  html += '<tr><td class="dbh-cell subtotal-cell">小计</td>';
  species.forEach(({ name }) => { html += `<td class="subtotal-cell">—</td><td class="subtotal-cell" id="count-total-${escapeHtml(name)}">0</td>`; });
  html += '<td class="subtotal-cell cut-cell" id="cut-count-total">0</td><td class="subtotal-cell cut-cell" id="cut-volume-total">0.000</td>';
  species.forEach(({ name }) => { html += `<td class="subtotal-cell">—</td><td class="subtotal-cell" id="volume-total-${escapeHtml(name)}">0.000</td>`; });
  html += '</tr></tbody>';
  $('#surveyTable').innerHTML = html;
  $('#formulaNote').textContent = `单株材积 V = ROUND(a × D^b × H^c, 3)，径阶蓄积 = 单株材积 × 株数；每公顷换算系数 ${state.detail.schema.area_factor}。`;
}

function round3(value) {
  return Math.round((value + Number.EPSILON) * 1000) / 1000;
}

function unitVolume(params, dbh, height) {
  if (!height || height <= 0) return 0;
  return round3(params.a * Math.pow(dbh, params.b) * Math.pow(height, params.c));
}

function recalculateSurvey() {
  const detail = state.detail;
  const plot = currentPlot();
  if (!detail || !plot) return;
  const { schema, species } = detail;
  const survey = plot.survey;
  let plotCount = 0;
  let weightedSquares = 0;
  let allVolume = 0;
  let cutCount = 0;
  let cutVolume = 0;
  species.forEach(({ name }) => {
    let speciesCount = 0;
    let speciesVolume = 0;
    schema.diameters.forEach((dbh) => {
      const values = survey.trees[name][dbh];
      const unit = unitVolume(schema.species[name], dbh, values.height);
      const volume = round3(unit * (values.count || 0));
      speciesCount += values.count || 0;
      speciesVolume += volume;
      plotCount += values.count || 0;
      weightedSquares += (values.count || 0) * dbh * dbh;
      $(`#unit-${CSS.escape(name)}-${dbh}`).textContent = unit.toFixed(3);
      $(`#volume-${CSS.escape(name)}-${dbh}`).textContent = volume.toFixed(3);
    });
    speciesVolume = round3(speciesVolume);
    allVolume += speciesVolume;
    $(`#count-total-${CSS.escape(name)}`).textContent = speciesCount;
    $(`#volume-total-${CSS.escape(name)}`).textContent = speciesVolume.toFixed(3);
  });
  schema.diameters.forEach((dbh) => {
    const count = survey.cut[dbh] || 0;
    const volume = count ? schema.cut.a * Math.pow(count, schema.cut.exponent) : 0;
    cutCount += count;
    cutVolume += volume;
    $(`#cut-volume-${dbh}`).textContent = volume.toFixed(3);
  });
  $('#cut-count-total').textContent = cutCount;
  $('#cut-volume-total').textContent = cutVolume.toFixed(3);
  $('#summaryCount').textContent = plotCount;
  $('#summaryDbh').textContent = (plotCount ? Math.sqrt(weightedSquares / plotCount) : 0).toFixed(1);
  $('#summaryPerHaCount').textContent = round3(plotCount * schema.area_factor);
  $('#summaryPerHaVolume').textContent = round3(allVolume * schema.area_factor).toFixed(3);
  $('#summaryCutCount').textContent = cutCount;
  $('#summaryCutVolume').textContent = round3(cutVolume).toFixed(3);
}

function setSaveStatus(text, className = '') {
  const node = $('#saveStatus');
  node.textContent = text;
  node.className = `save-status ${className}`;
}

function scheduleSurveySave() {
  if (!state.detail) return;
  state.saveRevision += 1;
  setSaveStatus('待保存…', 'saving');
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveSurvey, 650);
}

async function saveSurvey() {
  if (!state.detail || state.saveInFlight) return;
  const plot = currentPlot();
  if (!plot) return;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  const detailId = state.detail.id;
  const plotId = plot.id;
  const revision = state.saveRevision;
  const payload = JSON.stringify(plot.survey);
  state.saveInFlight = true;
  setSaveStatus('保存中…', 'saving');
  try {
    const data = await api(`/api/subcompartments/${detailId}/plots/${plotId}/survey`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: payload,
    });
    if (revision === state.saveRevision && plot.id === plotId) {
      plot.survey = data.survey;
      plot.summary = data.summary;
      plot.has_survey = data.has_survey;
      setSaveStatus('已自动保存');
    }
  } catch (error) {
    setSaveStatus('保存失败', 'error');
    toast(`调查数据保存失败：${error.message}`, true);
  } finally {
    state.saveInFlight = false;
    if (state.detail && revision !== state.saveRevision) saveSurvey();
  }
}

function updateSurveyInput(input) {
  const plot = currentPlot();
  if (!plot) return;
  const survey = plot.survey;
  const { type, species, dbh } = input.dataset;
  if (type === 'cut') {
    const value = Math.max(0, Math.round(Number(input.value) || 0));
    input.value = value;
    survey.cut[dbh] = value;
  } else if (type === 'count') {
    const value = Math.max(0, Math.round(Number(input.value) || 0));
    input.value = value;
    survey.trees[species][dbh].count = value;
  } else {
    const value = input.value === '' ? null : Math.max(0, Number(input.value) || 0);
    input.value = value ?? '';
    survey.trees[species][dbh].height = value;
  }
  recalculateSurvey();
  scheduleSurveySave();
}

/* ── 本机拍摄记录（v1.5）───────────────────────────────────────────
   照片只写手机相册、不上传服务器，所以界面上能给的只有「存到哪」这条线索：
   文件名 + 相册相对路径 + 时间。记录存在本机 localStorage（按样地分键），
   换设备/清缓存就没了 —— 权威副本永远是相册里的那张图。 */
function shotsKey(plotId) {
  return `forest_shots_plot_${plotId}`;
}

function readShots(plotId) {
  try { return JSON.parse(localStorage.getItem(shotsKey(plotId)) || '[]'); } catch (_) { return []; }
}

function recordShot(shot) {
  const plot = currentPlot();
  if (!plot) return;
  try {
    const list = readShots(plot.id);
    list.unshift(shot);
    localStorage.setItem(shotsKey(plot.id), JSON.stringify(list.slice(0, 100)));
  } catch (_) { /* 配额满不影响照片已存相册 */ }
}

function renderPhotos() {
  const plot = currentPlot();
  const shots = plot ? readShots(plot.id) : [];
  const box = $('#photoList');
  box.className = 'shot-list';
  box.innerHTML = shots.length
    ? shots.map((shot) => `<div class="shot-item" title="${escapeHtml(shot.path || '')}">
        <strong>${escapeHtml(shot.name || 'photo.jpg')}</strong>
        <span>${escapeHtml(shot.dir || '')} · ${escapeHtml(shot.at || '')}</span></div>`).join('')
    : '<span class="inline-status">本次调查还没有拍照；照片存手机相册，不上传服务器。</span>';
}

function currentCoordinates() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (position) => resolve(`${position.coords.latitude.toFixed(6)}, ${position.coords.longitude.toFixed(6)}`),
      () => resolve(null), { enableHighAccuracy: true, timeout: 3500, maximumAge: 60000 },
    );
  });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/* ── EXIF（对齐 hqz-supervision doc/017）─────────────────────────
   Canvas 重绘必然丢 EXIF，这是管线行为不是 bug。这里做两件事：
   ① 水印的时间/经纬度优先取原片 EXIF（相机定位比浏览器 geolocation 权威，且不依赖权限）
   ② 压缩后把原片 EXIF 回写进上传的那份，服务器拿到的是机器可读的时间与坐标
   纯逻辑在 static/photo_exif.js（依赖 vendor/piexif.js），任何失败都静默退回原行为。 */
async function photoExif(file) {
  try {
    if (!(window.piexif && window.PhotoExif && file)) return null;
    if (!/jpe?g/i.test(file.type || file.name || '')) return null;
    return PhotoExif.exifOfDataUrl(await blobToDataUrl(file), window.piexif);
  } catch (_) { return null; }
}

async function keepExif(original, blob) {
  try {
    if (!(window.piexif && window.PhotoExif && original)) return blob;
    if (!/jpe?g/i.test(original.type || original.name || '')) return blob;
    const url = PhotoExif.preserveExifDataUrl(
      await blobToDataUrl(original), await blobToDataUrl(blob), window.piexif);
    return await (await fetch(url)).blob();
  } catch (_) { return blob; }
}

async function imageSource(file) {
  if ('createImageBitmap' in window) {
    try { return await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch (_) {}
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return image;
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
}

/* 水印版式对齐 supervision：半透明白底块 + 实心黑字（省比特，同质量下体积更小、字更清楚）。
   水印内容由参数「水印内容」逐行开关、由 photo_tpl.js 统一生成（项目名 → 小班/样地 → 说明 → 时间 → 坐标）。
   时间优先用原片 EXIF 的拍摄时刻，坐标同理；都没有才退回浏览器定位与当前时间。 */
async function compressPhoto(file, ctx, coordinates) {
  const params = state.detail?.params || {};
  const maxEdge = Number(params.压缩最长边) || 1440;
  const quality = Math.min(1, Math.max(0.3, Number(params.压缩质量) || 0.8));
  const source = await imageSource(file);
  const width = source.width || source.naturalWidth;
  const height = source.height || source.naturalHeight;
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext('2d');
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  if (source.close) source.close();

  const lines = PhotoTpl.watermarkLines(params, ctx, coordinates);
  if (lines.length) {
    let fontSize = Math.max(18, Math.round(canvas.width / 34));
    let lineHeight = Math.round(fontSize * 1.45);
    let padX = Math.round(fontSize * 0.7);
    let padY = Math.round(fontSize * 0.5);
    let margin = Math.round(fontSize * 0.55);
    const maxHeight = canvas.height * 0.55;
    let boxHeight = lines.length * lineHeight + padY * 2;
    if (boxHeight > maxHeight) {
      const ratio = maxHeight / boxHeight;
      fontSize = Math.max(14, Math.round(fontSize * ratio));
      lineHeight = Math.round(fontSize * 1.45);
      padX = Math.round(fontSize * 0.7);
      padY = Math.round(fontSize * 0.5);
      margin = Math.round(fontSize * 0.55);
      boxHeight = lines.length * lineHeight + padY * 2;
    }
    context.font = `${fontSize}px system-ui,'PingFang SC','Microsoft YaHei',sans-serif`;
    context.textAlign = 'left';
    context.textBaseline = 'bottom';
    let textWidth = 0;
    for (const line of lines) textWidth = Math.max(textWidth, context.measureText(line).width);
    const boxWidth = Math.max(Math.round(canvas.width * 0.3),
      Math.min(canvas.width - margin * 2, Math.ceil(textWidth) + padX * 2));
    const boxX = margin;
    const boxY = Math.max(margin, canvas.height - boxHeight - margin);
    const radius = Math.round(fontSize * 0.35);
    context.fillStyle = 'rgba(255,255,255,.62)';
    context.beginPath();
    context.moveTo(boxX + radius, boxY);
    context.lineTo(boxX + boxWidth - radius, boxY);
    context.quadraticCurveTo(boxX + boxWidth, boxY, boxX + boxWidth, boxY + radius);
    context.lineTo(boxX + boxWidth, boxY + boxHeight - radius);
    context.quadraticCurveTo(boxX + boxWidth, boxY + boxHeight, boxX + boxWidth - radius, boxY + boxHeight);
    context.lineTo(boxX + radius, boxY + boxHeight);
    context.quadraticCurveTo(boxX, boxY + boxHeight, boxX, boxY + boxHeight - radius);
    context.lineTo(boxX, boxY + radius);
    context.quadraticCurveTo(boxX, boxY, boxX + radius, boxY);
    context.closePath();
    context.fill();
    context.fillStyle = '#111';
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      const y = boxY + boxHeight - padY - (lines.length - 1 - index) * lineHeight;
      context.fillText(lines[index], boxX + padX, y);
    }
  }
  return new Promise((resolve, reject) => canvas.toBlob(
    (blob) => (blob ? resolve(blob) : reject(new Error('图片编码失败'))), 'image/jpeg', quality));
}

/* ── 拍照（v1.5）：只存手机相册，不上传服务器 ──────────────────────
   链路：原生相机 takePhoto → 取回原片 → 读 EXIF（时间/坐标）→ Canvas 压缩+水印
        → 回写 EXIF → 原生 savePhoto 写入 Pictures/{参数「目录」}/{参数「文件名」}.jpg
   任何跨端失败都不静默：宁可报错让调查员重拍，也不要照片存丢。
   旧 APK（没有 AppPermissions 插件）明确提示升级，不再退回"上传服务器"这条已下线路径。 */
function isNativeApp() {
  return !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === 'function'
    && window.Capacitor.isNativePlatform());
}

function nativePlugin() {
  const plugins = window.Capacitor && window.Capacitor.Plugins;
  return (plugins && plugins.AppPermissions) || null;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/** 原生相机拍一张，返回 File；没有插件时返回 null，由调用方回退到 capture 输入框。 */
async function nativeCapture() {
  const plugin = nativePlugin();
  if (!isNativeApp() || !plugin || typeof plugin.takePhoto !== 'function') return null;
  const shot = await plugin.takePhoto({});
  if (!shot || !shot.path) throw new Error('相机没有返回照片');
  let blob;
  try {
    const src = window.Capacitor.convertFileSrc ? window.Capacitor.convertFileSrc(shot.path) : shot.path;
    blob = await (await fetch(src)).blob();
  } catch (_) {
    if (typeof plugin.readPhoto !== 'function') throw new Error('读取相机照片失败');
    const raw = await plugin.readPhoto({ path: shot.path });   // 回退：原生读文件给 base64
    blob = await (await fetch(`data:image/jpeg;base64,${raw.base64}`)).blob();
  }
  if (typeof plugin.removeCacheFile === 'function') {
    try { await plugin.removeCacheFile({ path: shot.path }); } catch (_) { /* 缓存清理失败不影响出图 */ }
  }
  const name = String(shot.path).split('/').pop() || 'capture.jpg';
  return new File([blob], name, { type: blob.type || 'image/jpeg' });
}

async function handlePhoto(file) {
  if (!file || !state.detail) return;
  if (!file.type.startsWith('image/')) {
    toast('请用相机拍照（不再支持从相册选择）', true);
    return;
  }
  const plot = currentPlot();
  if (!plot) {
    toast('当前小班还没有样地', true);
    return;
  }
  const params = state.detail.params || {};
  $('#photoStatus').textContent = '正在读取定位与水印…';
  $('#takePhoto').disabled = true;
  try {
    const meta = await photoExif(file);
    const coordinates = (meta && meta.lat != null)
      ? `${meta.lat.toFixed(5)}, ${meta.lng.toFixed(5)}`
      : await currentCoordinates();
    const ctx = PhotoTpl.context(params, {
      number: state.detail.fields.number,
      plotNo: plot.plot_no,
    }, meta && meta.takenAt ? meta.takenAt : new Date());
    const blob = await keepExif(file, await compressPhoto(file, ctx, coordinates));
    const name = `${PhotoTpl.photoName(params, ctx)}.jpg`;
    const subdir = PhotoTpl.albumSubdir(params, ctx);

    let savedWhere = '';
    let savedPath = '';
    const plugin = nativePlugin();
    if (isNativeApp()) {
      // App 内只认相册这一条路：失败必须让调查员看见，不能悄悄"看起来存了"
      if (!plugin || typeof plugin.savePhoto !== 'function') {
        throw new Error('当前 App 版本不支持存相册，请更新到 v1.1 后再拍照');
      }
      try {
        const saved = await plugin.savePhoto({ base64: await blobToBase64(blob), name, subdir });
        savedPath = (saved && saved.path) || '';
      } catch (err) {
        throw new Error(`存入相册失败：${err.message || err}`);
      }
      savedWhere = savedPath ? `已存入相册：${savedPath}` : `已存入相册 Pictures/${subdir}/${name}`;
    } else {
      // 浏览器调试：直接下载到本机（页面没有相册写入权限）
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 5000);
      savedPath = name;
      savedWhere = `已下载到本机：${name}`;
    }

    const dir = savedPath.includes('/')
      ? savedPath.slice(0, savedPath.lastIndexOf('/'))
      : `Pictures/${subdir}`;
    recordShot({
      name,
      dir,
      path: savedPath || `Pictures/${subdir}/${name}`,
      at: ctx.时间显示,
      size: Math.round(blob.size / 1024),
    });
    renderPhotos();
    $('#photoStatus').textContent = `${savedWhere}（${Math.round(blob.size / 1024)} KB，压缩 `
      + `${Math.max(0, Math.round((1 - blob.size / file.size) * 100))}%${meta ? '，EXIF 已回写' : ''}）`;
    toast('照片已存入手机相册');
  } catch (error) {
    $('#photoStatus').textContent = error.message;
    toast(`拍照失败：${error.message}`, true);
  } finally {
    $('#takePhoto').disabled = false;
    $('#photoInput').value = '';
  }
}

/** 拍照入口：原生相机优先，浏览器/旧包回退到 capture 输入框（只调相机，无相册入口）。 */
async function startPhoto() {
  if (!state.detail || !currentPlot()) return;
  if (isNativeApp() && !nativePlugin()) {
    toast('当前 App 版本过旧，请更新后再拍照（旧版没有相册保存能力）', true);
    return;
  }
  const plugin = nativePlugin();
  if (isNativeApp() && plugin && typeof plugin.takePhoto === 'function') {
    $('#takePhoto').disabled = true;
    $('#photoStatus').textContent = '正在打开相机…';
    try {
      const file = await nativeCapture();
      if (file) await handlePhoto(file);
    } catch (error) {
      $('#photoStatus').textContent = error.message;
      toast(`相机启动失败：${error.message}`, true);
    } finally {
      $('#takePhoto').disabled = false;
    }
    return;
  }
  $('#photoInput').click();
}

function trackCacheKey() {
  return state.detail && state.plotId ? `forest_track_plot_${state.plotId}` : '';
}

function readTrackCache() {
  try { return JSON.parse(localStorage.getItem(trackCacheKey()) || '[]'); } catch (_) { return []; }
}

function initTrackMap() {
  if (state.map) {
    state.map.remove();
    state.map = null;
  }
  state.map = L.map('trackMap', { zoomControl: true, attributionControl: true }).setView([24.4, 102.5], 10);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: 'Esri World Imagery',
  }).addTo(state.map);
  state.polyline = L.polyline([], { color: '#36e27d', weight: 4, opacity: .95 }).addTo(state.map);
  setTimeout(() => state.map?.invalidateSize(), 100);
}

function trackDistance() {
  let total = 0;
  for (let index = 1; index < state.trackPoints.length; index += 1) {
    const a = state.trackPoints[index - 1];
    const b = state.trackPoints[index];
    const rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad;
    const dLng = (b.lng - a.lng) * rad;
    const value = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    total += 6371000 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }
  return total;
}

function updateTrackUI(fit = false) {
  if (!state.detail) return;
  const points = state.trackPoints;
  $('#trackPoints').textContent = points.length;
  $('#trackDistance').textContent = (trackDistance() / 1000).toFixed(2);
  $('#trackBadge').textContent = state.recording ? '记录中' : points.length ? '已保存' : '未记录';
  $('#trackBadge').classList.toggle('active', state.recording);
  $('#toggleTrack').textContent = state.recording ? '停止并保存' : points.length ? '继续记录' : '开始记录';
  $('#toggleTrack').classList.toggle('recording', state.recording);
  const exportLink = $('#exportTrack');
  exportLink.classList.toggle('disabled', !points.length);
  exportLink.setAttribute('aria-disabled', points.length ? 'false' : 'true');
  exportLink.href = points.length && currentPlot()
    ? url(`/api/subcompartments/${state.detail.id}/plots/${currentPlot().id}/track.gpx`) : '#';
  if (state.polyline) {
    const latLngs = points.map((point) => [point.lat, point.lng]);
    state.polyline.setLatLngs(latLngs);
    state.markers.forEach((marker) => marker.remove());
    state.markers = [];
    if (points.length) {
      const first = L.marker(latLngs[0], { icon: L.divIcon({ className: '', html: '<span class="track-marker">起</span>', iconSize: [22, 22] }) }).addTo(state.map);
      state.markers.push(first);
      if (points.length > 1) {
        const last = L.marker(latLngs.at(-1), { icon: L.divIcon({ className: '', html: '<span class="track-marker end">终</span>', iconSize: [22, 22] }) }).addTo(state.map);
        state.markers.push(last);
      }
      if (fit) state.map.fitBounds(state.polyline.getBounds(), { padding: [28, 28], maxZoom: 18 });
    }
  }
}

function addTrackPoint(position) {
  // 采样间隔由「程序参数」控制：watchPosition 本身按系统频率回调，这里按时间窗节流
  const gap = (Number(state.detail?.params?.轨迹采样间隔) || 5) * 1000;
  const now = Date.now();
  if (state.lastTrackAt && now - state.lastTrackAt < gap) return;
  state.lastTrackAt = now;
  const point = {
    lat: position.coords.latitude, lng: position.coords.longitude, timestamp: position.timestamp || Date.now(),
    accuracy: position.coords.accuracy ?? null,
  };
  const previous = state.trackPoints.at(-1);
  if (previous?.timestamp === point.timestamp) return;
  state.trackPoints.push(point);
  try { localStorage.setItem(trackCacheKey(), JSON.stringify(state.trackPoints)); } catch (_) {}
  $('#trackAccuracy').textContent = point.accuracy ? `定位精度 ±${Math.round(point.accuracy)} m` : '定位已更新';
  updateTrackUI(state.trackPoints.length === 1);
  if (state.map && state.trackPoints.length > 1) state.map.panTo([point.lat, point.lng], { animate: true });
  if (state.trackPoints.length % 5 === 0) saveTrack(false);
}

function startTracking() {
  if (!navigator.geolocation) {
    toast('当前浏览器不支持定位', true);
    return;
  }
  state.recording = true;
  $('#trackStatus').textContent = '正在获取卫星定位，请保持页面开启并允许定位权限。';
  state.watchId = navigator.geolocation.watchPosition(addTrackPoint, (error) => {
    $('#trackStatus').textContent = `定位失败：${error.message}`;
    toast(`定位失败：${error.message}`, true);
  }, { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 });
  updateTrackUI();
}

function stopTracking(save = true) {
  if (state.watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(state.watchId);
  state.watchId = null;
  state.lastTrackAt = 0;
  const wasRecording = state.recording;
  state.recording = false;
  if (state.detail) {
    updateTrackUI();
    if (save && (wasRecording || state.trackPoints.length)) saveTrack(true);
  }
}

async function saveTrack(notify = true) {
  const plot = currentPlot();
  if (!state.detail || !plot) return;
  const subId = state.detail.id;
  const plotId = plot.id;
  $('#trackStatus').textContent = '正在保存轨迹…';
  try {
    const data = await api(`/api/subcompartments/${subId}/plots/${plotId}/track`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ points: state.trackPoints }),
    });
    if (plot.id === plotId) {
      plot.track = data.points;
      $('#trackStatus').textContent = `轨迹已保存，共 ${data.points.length} 个定位点。`;
    }
    if (notify) toast('卫星轨迹已保存');
  } catch (error) {
    $('#trackStatus').textContent = '云端保存失败，轨迹已保留在本机，可稍后重试。';
    if (notify) toast(`轨迹保存失败：${error.message}`, true);
  }
}

async function handleRoute() {
  clearTimeout(state.saveTimer);
  const hash = location.hash || '#/';
  const projectMatch = hash.match(/^#\/project\/([a-f0-9]+)$/);
  const subMatch = hash.match(/^#\/sub\/(\d+)(?:\/(\d+))?$/);
  if (subMatch) await loadDetail(subMatch[1], subMatch[2]);
  else if (projectMatch) await loadProject(projectMatch[1]);
  else await loadProjects();
}

$('#backButton').addEventListener('click', () => {
  if (state.detail && !$('#detailView').classList.contains('hidden')) {
    if (state.saveRevision) saveSurvey();
    navigate(`#/project/${state.detail.project_id}`);
  } else navigate('#/');
});
[['#filterSection', 'section'], ['#filterTownship', 'township'], ['#filterVillage', 'village']].forEach(([selector, field]) => {
  $(selector).addEventListener('change', (event) => {
    state.filters[field] = event.target.value;
    if (field === 'section') { state.filters.township = ''; state.filters.village = ''; }
    if (field === 'township') state.filters.village = '';
    populateFilters();
    renderSubcompartments();
  });
});
let filterTimer;
$('#filterNumber').addEventListener('input', (event) => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    state.filters.number = event.target.value;
    renderSubcompartments();
  }, 200);
});
$('#resetFilters').addEventListener('click', () => {
  state.filters = { section: '', township: '', village: '', number: '' };
  $('#filterNumber').value = '';
  populateFilters();
  renderSubcompartments();
});
$('#surveyTable').addEventListener('input', (event) => {
  if (event.target.classList.contains('survey-input')) updateSurveyInput(event.target);
});
$('#surveyTable').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-step]');
  if (!button) return;
  const selector = `input[data-type="${button.dataset.type}"][data-dbh="${button.dataset.dbh}"]${button.dataset.species ? `[data-species="${CSS.escape(button.dataset.species)}"]` : ''}`;
  const input = $('#surveyTable').querySelector(selector);
  input.value = Math.max(0, (Number(input.value) || 0) + Number(button.dataset.step));
  updateSurveyInput(input);
});
$('#plotNumber').addEventListener('change', (event) => renamePlot(event.target.value));
$('#plotNumber').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') { event.preventDefault(); event.target.blur(); }
});
$('#addPlot').addEventListener('click', addPlot);
$('#deletePlot').addEventListener('click', deletePlot);
$('#takePhoto').addEventListener('click', startPhoto);
$('#photoInput').addEventListener('change', (event) => handlePhoto(event.target.files[0]));
$('#toggleTrack').addEventListener('click', () => state.recording ? stopTracking(true) : startTracking());
$('#saveTrack').addEventListener('click', () => saveTrack(true));
$('#exportTrack').addEventListener('click', (event) => {
  if (!state.trackPoints.length) event.preventDefault();
});
window.addEventListener('hashchange', handleRoute);
document.addEventListener('visibilitychange', () => {
  if (document.hidden && state.detail && !$('#detailView').classList.contains('hidden')) {
    if (state.saveTimer) saveSurvey();
    if (state.trackPoints.length) saveTrack(false);
  }
});

$('#logoutButton').addEventListener('click', async () => {
  let target = '/forest/logout';
  try {
    const payload = await fetch(url('/api/logout'), { method: 'POST' }).then((r) => r.json());
    target = payload?.logout_url || target;
  } catch (_) {}
  state.me = null;
  state.detail = null;
  state.project = null;
  location.href = target;
});

async function bootstrap() {
  try {
    const me = await fetch(url('/api/me')).then((response) => response.json());
    if (!me.user) {
      showLogin(me.login_url);
      return;
    }
    state.me = me;
    hideLogin();
    updateTopbar();
    await handleRoute();
  } catch (error) {
    toast(error.message, true);
    showLogin();
  }
}

bootstrap();
