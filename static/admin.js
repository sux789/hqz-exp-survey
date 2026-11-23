const $ = (selector) => document.querySelector(selector);
const BASE = (document.querySelector('meta[name="exp-base"]')?.content || '').replace(/\/+$/, '');
const url = (path) => `${BASE}${path.startsWith('/') ? path : `/${path}`}`;

const state = { me: null, projects: [], target: null, file: null, toastTimer: null };

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
  state.toastTimer = setTimeout(() => node.classList.add('hidden'), 3800);
}

async function api(path, options = {}) {
  const response = await fetch(url(path), options);
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('application/json') ? await response.json() : null;
  if (response.status === 401) {
    location.href = payload?.login_url || '/forest/login';
    throw new Error('请先登录');
  }
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload;
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

function paramSummary(params) {
  if (!params) return '—';
  const features = (params.功能 || []).join(' · ') || '无功能';
  const hide = params.不显示列?.length ? ` · 隐藏 ${params.不显示列.length} 列` : '';
  return `<strong>${escapeHtml(features)}</strong><small>${params.压缩最长边}px / 质量 ${params.压缩质量}${escapeHtml(hide)}</small>`;
}

// ── 项目列表 ──────────────────────────────────────────────
async function loadProjects() {
  const data = await api('/admin/api/projects');
  state.projects = data.projects;
  const rows = state.projects.map((project) => {
    const disabled = project.can_overwrite ? '' : 'disabled title="只有上传人本人或管理员可以覆盖"';
    return `<tr>
      <td><strong>${escapeHtml(project.filename)}</strong><small>${escapeHtml(project.id.slice(0, 8))}</small></td>
      <td>${project.subcompartment_count}</td>
      <td>${paramSummary(project.params)}</td>
      <td>${escapeHtml(project.uploader || '—')}</td>
      <td>${formatTime(project.uploaded_at)}</td>
      <td class="row-actions">
        <button class="button secondary small" type="button" data-update="${project.id}" ${disabled}>覆盖更新</button>
        <a class="button secondary small" href="${url(`/admin/api/projects/${project.id}/source`)}">下载源文件</a>
      </td>
    </tr>`;
  }).join('');
  $('#projectRows').innerHTML = rows;
  $('#projectCount').textContent = `${state.projects.length} 个`;
  $('#emptyProjects').classList.toggle('hidden', state.projects.length > 0);
  document.querySelectorAll('[data-update]').forEach((button) => {
    button.addEventListener('click', () => openUpdate(button.dataset.update));
  });
}

// ── 上传新项目 ────────────────────────────────────────────
function bindNewFile() {
  $('#newFile').addEventListener('change', (event) => {
    state.file = event.target.files[0] || null;
    $('#newFileName').textContent = state.file ? state.file.name : '点击选择或拖入 .xlsx 文件';
    $('#uploadBtn').disabled = !state.file;
  });
  ['dragenter', 'dragover'].forEach((name) => $('#dropBox').addEventListener(name, (event) => {
    event.preventDefault();
    $('#dropBox').classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((name) => $('#dropBox').addEventListener(name, (event) => {
    event.preventDefault();
    $('#dropBox').classList.remove('dragging');
  }));
  $('#dropBox').addEventListener('drop', (event) => {
    const file = event.dataTransfer.files[0];
    if (!file) return;
    state.file = file;
    $('#newFileName').textContent = file.name;
    $('#uploadBtn').disabled = false;
  });
  $('#uploadBtn').addEventListener('click', async () => {
    if (!state.file) return;
    const message = $('#uploadMsg');
    message.textContent = `正在上传并解析 ${state.file.name}…`;
    $('#uploadBtn').disabled = true;
    const form = new FormData();
    form.append('file', state.file);
    try {
      const data = await api('/admin/api/projects', { method: 'POST', body: form });
      message.textContent = `已导入 ${data.project.subcompartment_count} 个小班`;
      toast('上传成功');
      state.file = null;
      $('#newFile').value = '';
      $('#newFileName').textContent = '点击选择或拖入 .xlsx 文件';
      await loadProjects();
    } catch (error) {
      message.textContent = error.message;
      toast(error.message, true);
    } finally {
      $('#uploadBtn').disabled = !state.file;
    }
  });
}

// ── 覆盖更新 ──────────────────────────────────────────────
function resetUpdate() {
  state.target = null;
  state.file = null;
  $('#updateFile').value = '';
  $('#updateFileName').textContent = '选择新的 Excel 文件';
  $('#previewBtn').disabled = true;
  $('#previewBox').classList.add('hidden');
  $('#previewBox').innerHTML = '';
  $('#confirmBox').classList.add('hidden');
  $('#confirmName').value = '';
  $('#updateMsg').textContent = '';
  $('#updateError').textContent = '';
}

function openUpdate(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  resetUpdate();
  state.target = project;
  $('#updateTarget').innerHTML = `目标项目：<strong>${escapeHtml(project.filename)}</strong> · ${project.subcompartment_count} 个小班`;
  $('#updateModal').classList.remove('hidden');
}

function previewHtml(preview) {
  const items = [
    ['按小班号匹配', preview.matched, '保留调查数据、照片与轨迹'],
    ['新增小班', preview.added, '追加到列表末尾'],
    ['仅旧表有', preview.kept_old, '不会被删除，仍可在 App 中查看'],
  ];
  return `<div class="preview-grid">${items.map(([label, count, note]) => `
    <div><span>${label}</span><strong>${count}</strong><small>${note}</small></div>`).join('')}</div>
    <p class="preview-total">旧 ${preview.old_total} → 新 ${preview.new_total} 条</p>
    ${preview.added_numbers?.length ? `<p class="preview-note">新增示例：${preview.added_numbers.map(escapeHtml).join('、')}</p>` : ''}
    ${preview.kept_numbers?.length ? `<p class="preview-note">仅旧表示例：${preview.kept_numbers.map(escapeHtml).join('、')}</p>` : ''}`;
}

function bindUpdate() {
  $('#updateClose').addEventListener('click', () => $('#updateModal').classList.add('hidden'));
  $('#updateFile').addEventListener('change', (event) => {
    state.file = event.target.files[0] || null;
    $('#updateFileName').textContent = state.file ? state.file.name : '选择新的 Excel 文件';
    $('#previewBtn').disabled = !state.file;
    $('#confirmBox').classList.add('hidden');
    $('#previewBox').classList.add('hidden');
  });

  $('#previewBtn').addEventListener('click', async () => {
    if (!state.file || !state.target) return;
    const form = new FormData();
    form.append('file', state.file);
    $('#updateMsg').textContent = '正在预检…';
    $('#previewBtn').disabled = true;
    $('#updateError').textContent = '';
    try {
      const data = await api(`/admin/api/projects/${state.target.id}/update?dry=1`, { method: 'POST', body: form });
      $('#previewBox').innerHTML = previewHtml(data.preview);
      $('#previewBox').classList.remove('hidden');
      $('#confirmBox').classList.remove('hidden');
      $('#updateMsg').textContent = '预检完成，请确认覆盖';
    } catch (error) {
      $('#updateError').textContent = error.message;
      toast(error.message, true);
    } finally {
      $('#previewBtn').disabled = !state.file;
    }
  });

  $('#submitBtn').addEventListener('click', async () => {
    if (!state.file || !state.target) return;
    const confirmName = $('#confirmName').value.trim();
    if (confirmName !== state.target.filename) {
      $('#updateError').textContent = '确认名称不一致：请照原样输入当前项目文件名';
      return;
    }
    const form = new FormData();
    form.append('file', state.file);
    form.append('confirm', confirmName);
    $('#updateError').textContent = '';
    $('#submitBtn').disabled = true;
    $('#updateMsg').textContent = '正在写入…';
    try {
      const data = await api(`/admin/api/projects/${state.target.id}/update`, { method: 'POST', body: form });
      toast(`已更新：匹配 ${data.preview.matched}、新增 ${data.preview.added}`);
      $('#updateModal').classList.add('hidden');
      await loadProjects();
    } catch (error) {
      $('#updateError').textContent = error.message;
      toast(error.message, true);
    } finally {
      $('#submitBtn').disabled = false;
    }
  });
}

// ── 启动 ──────────────────────────────────────────────────
$('#logoutButton').addEventListener('click', async () => {
  let target = '/forest/logout';
  try {
    const payload = await api('/api/logout', { method: 'POST' });
    target = payload?.logout_url || target;
  } catch (_) {}
  location.href = target;
});

async function init() {
  try {
    const me = await api('/api/me');
    if (!me.user || me.role !== 'admin') {
      location.href = `${BASE}/`;
      return;
    }
    state.me = me;
    const nameNode = $('#currentUser');
    if (nameNode) nameNode.textContent = me.display_name || me.user;
    bindNewFile();
    bindUpdate();
    await loadProjects();
  } catch (error) {
    toast(error.message, true);
  }
}

init();
