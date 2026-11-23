const $ = (selector) => document.querySelector(selector);
const BASE = (document.querySelector('meta[name="exp-base"]')?.content || '').replace(/\/+$/, '');
const url = (path) => `${BASE}${path.startsWith('/') ? path : `/${path}`}`;
const state = {
  me: null,
  projects: [], project: null, detail: null, filters: { section: '', township: '', village: '', number: '' },
  saveTimer: null, saveRevision: 0, saveInFlight: false, toastTimer: null,
  map: null, polyline: null, markers: [], trackPoints: [], watchId: null, recording: false,
  lastTrackAt: 0,
};

// 列表列：header 是 Excel 表头原文（用于匹配「不显示列」），label 是界面显示
const COLUMNS = [
  { header: '小班号', label: '小班号', field: 'number' },
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
      if (column.field === 'status') {
        return `<td><span class="status-pill ${row.has_survey ? 'done' : ''}">${row.has_survey ? '已调查' : '待调查'}</span></td>`;
      }
      return `<td>${escapeHtml(fields[column.field] ?? '—')}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  }).join('');
  $('#subcompartmentRows').querySelectorAll('[data-sub-id]').forEach((button) => {
    button.addEventListener('click', () => navigate(`#/sub/${button.dataset.subId}`));
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
  return { plot_no: '', trees, cut };
}

async function loadDetail(subId) {
  stopTracking(false);
  showView('detail');
  $('#pageSubtitle').textContent = '样地调查';
  $('#surveyTable').innerHTML = '';
  try {
    state.detail = await api(`/api/subcompartments/${subId}`);
    if (!state.detail.survey?.trees || !Object.keys(state.detail.survey.trees).length) {
      state.detail.survey = emptySurvey(state.detail);
    }
    renderDetail();
    if (state.detail.params?.has_track !== false) initTrackMap();
  } catch (error) {
    toast(error.message, true);
    if (state.project) navigate(`#/project/${state.project.id}`);
    else navigate('#/');
  }
}

function renderDetail() {
  const detail = state.detail;
  const fields = detail.fields;
  $('#subcompartmentTitle').textContent = fields.number;
  $('#subcompartmentMeta').textContent = [fields.section, fields.township, fields.village, `小班面积 ${fields.area ?? '—'} 亩`].filter(Boolean).join(' · ');
  $('#plotNumber').value = detail.survey.plot_no || '';
  $('#speciesChips').innerHTML = detail.species.map((item) => `<span class="species-chip">${item.coefficient}${escapeHtml(item.name)}</span>`).join('');
  renderSurveyTable();
  recalculateSurvey();
  renderPhotos();
  state.trackPoints = detail.track || [];
  const cached = readTrackCache();
  if (cached.length > state.trackPoints.length) state.trackPoints = cached;
  applyParamsToDetail();
  updateTrackUI(true);
}

/** 「程序参数」sheet 决定详情页显示哪些工具、照片怎么压。 */
function applyParamsToDetail() {
  const params = state.detail?.params || {};
  const hasPhoto = params.has_photo !== false;
  const hasTrack = params.has_track !== false;
  $('#photoCard').classList.toggle('hidden', !hasPhoto);
  $('#trackCard').classList.toggle('hidden', !hasTrack);
  $('#toolsGrid').classList.toggle('single', !hasPhoto || !hasTrack);
  $('#photoHint').textContent = hasPhoto
    ? `自动等比压缩至最长边 ${params.压缩最长边 || 1440}px、质量 ${params.压缩质量 ?? 0.8}，并添加水印。`
    : '';
  $('#trackStatus').textContent = hasTrack
    ? `卫星底图需要网络；每 ${params.轨迹采样间隔 || 5} 秒取一个定位点。`
    : '';
}

function countControl(type, species, dbh, value) {
  const speciesAttr = species === null ? '' : `data-species="${escapeHtml(species)}"`;
  return `<div class="number-control"><button type="button" data-step="-1" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="减少株数">−</button><input class="survey-input" type="number" min="0" step="1" inputmode="numeric" value="${value || 0}" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="${type === 'cut' ? '采伐' : escapeHtml(species)} ${dbh}厘米株数"><button type="button" data-step="1" data-type="${type}" ${speciesAttr} data-dbh="${dbh}" aria-label="增加株数">+</button></div>`;
}

function renderSurveyTable() {
  const { schema, species, survey } = state.detail;
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
  if (!detail) return;
  const { schema, species, survey } = detail;
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
  clearTimeout(state.saveTimer);
  const detailId = state.detail.id;
  const revision = state.saveRevision;
  const payload = JSON.stringify(state.detail.survey);
  state.saveInFlight = true;
  setSaveStatus('保存中…', 'saving');
  try {
    const data = await api(`/api/subcompartments/${detailId}/survey`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: payload,
    });
    if (state.detail?.id === detailId && revision === state.saveRevision) {
      state.detail.survey = data.survey;
      setSaveStatus('已自动保存');
    }
  } catch (error) {
    setSaveStatus('保存失败', 'error');
    toast(`调查数据保存失败：${error.message}`, true);
  } finally {
    state.saveInFlight = false;
    if (state.detail && (state.detail.id !== detailId || revision !== state.saveRevision)) saveSurvey();
  }
}

function updateSurveyInput(input) {
  const { type, species, dbh } = input.dataset;
  if (type === 'cut') {
    const value = Math.max(0, Math.round(Number(input.value) || 0));
    input.value = value;
    state.detail.survey.cut[dbh] = value;
  } else if (type === 'count') {
    const value = Math.max(0, Math.round(Number(input.value) || 0));
    input.value = value;
    state.detail.survey.trees[species][dbh].count = value;
  } else {
    const value = input.value === '' ? null : Math.max(0, Number(input.value) || 0);
    input.value = value ?? '';
    state.detail.survey.trees[species][dbh].height = value;
  }
  recalculateSurvey();
  scheduleSurveySave();
}

function renderPhotos() {
  const photos = state.detail?.photos || [];
  $('#photoList').innerHTML = photos.length ? photos.map((photo) => `
    <a class="photo-item" href="${photo.url}" target="_blank" rel="noopener"><img src="${photo.url}" alt="样地照片" loading="lazy"><span>${(photo.compressed_size / 1024).toFixed(0)} KB · ${formatDate(photo.created_at)}</span></a>`).join('') : '<span class="inline-status">暂无照片</span>';
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

async function compressPhoto(file, coordinates) {
  const params = state.detail?.params || {};
  const maxEdge = Number(params.压缩最长边) || 1440;
  const quality = Math.min(1, Math.max(0.3, Number(params.压缩质量) || 0.8));
  const marks = params.水印内容 || ['时间', '坐标', '小班'];
  const source = await imageSource(file);
  const width = source.width || source.naturalWidth;
  const height = source.height || source.naturalHeight;
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext('2d');
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  const lines = [];
  if (marks.includes('时间')) lines.push(new Date().toLocaleString('zh-CN', { hour12: false }));
  if (marks.includes('坐标')) lines.push(coordinates ? `WGS-84  ${coordinates}` : '定位未获取');
  if (marks.includes('小班')) lines.push(`小班 ${state.detail.fields.number}`);
  if (lines.length) {
    const fontSize = Math.max(15, Math.round(canvas.width / 48));
    const lineHeight = Math.round(fontSize * 1.45);
    const boxHeight = lineHeight * lines.length + 18;
    const gradient = context.createLinearGradient(0, canvas.height - boxHeight, 0, canvas.height);
    gradient.addColorStop(0, 'rgba(0,0,0,0)');
    gradient.addColorStop(.3, 'rgba(0,0,0,.65)');
    gradient.addColorStop(1, 'rgba(0,0,0,.82)');
    context.fillStyle = gradient;
    context.fillRect(0, canvas.height - boxHeight, canvas.width, boxHeight);
    context.fillStyle = '#fff';
    context.font = `${fontSize}px -apple-system, PingFang SC, sans-serif`;
    context.textBaseline = 'bottom';
    lines.forEach((line, index) => context.fillText(line, 14, canvas.height - 10 - (lines.length - 1 - index) * lineHeight));
  }
  if (source.close) source.close();
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('图片编码失败')), 'image/jpeg', quality));
}

async function handlePhoto(file) {
  if (!file || !state.detail) return;
  if (!file.type.startsWith('image/')) {
    toast('请选择图片文件', true);
    return;
  }
  $('#photoStatus').textContent = '正在压缩并添加水印…';
  $('#takePhoto').disabled = true;
  try {
    const [source, coordinates] = await Promise.all([Promise.resolve(file), currentCoordinates()]);
    const blob = await compressPhoto(source, coordinates);
    $('#photoStatus').textContent = `已压缩 ${(file.size / 1024).toFixed(0)} KB → ${(blob.size / 1024).toFixed(0)} KB，正在上传…`;
    const form = new FormData();
    form.append('file', blob, `${state.detail.fields.number}_${Date.now()}.jpg`);
    form.append('original_size', file.size);
    const data = await api(`/api/subcompartments/${state.detail.id}/photos`, { method: 'POST', body: form });
    state.detail.photos.unshift(data.photo);
    renderPhotos();
    $('#photoStatus').textContent = `已保存，压缩 ${Math.max(0, Math.round((1 - blob.size / file.size) * 100))}%`;
    toast('照片压缩并保存成功');
  } catch (error) {
    $('#photoStatus').textContent = error.message;
    toast(`照片处理失败：${error.message}`, true);
  } finally {
    $('#takePhoto').disabled = false;
    $('#photoInput').value = '';
  }
}

function trackCacheKey() {
  return state.detail ? `forest_track_${state.detail.id}` : '';
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
  exportLink.href = points.length ? url(`/api/subcompartments/${state.detail.id}/track.gpx`) : '#';
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
  if (!state.detail) return;
  const subId = state.detail.id;
  $('#trackStatus').textContent = '正在保存轨迹…';
  try {
    const data = await api(`/api/subcompartments/${subId}/track`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ points: state.trackPoints }),
    });
    if (state.detail?.id === subId) {
      state.detail.track = data.points;
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
  const subMatch = hash.match(/^#\/sub\/(\d+)$/);
  if (subMatch) await loadDetail(subMatch[1]);
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
$('#plotNumber').addEventListener('input', (event) => {
  if (!state.detail) return;
  state.detail.survey.plot_no = event.target.value;
  scheduleSurveySave();
});
$('#takePhoto').addEventListener('click', () => $('#photoInput').click());
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
