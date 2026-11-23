import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const artifactDir = path.join(root, 'instance', 'ui-smoke');
await mkdir(artifactDir, { recursive: true });
const origin = 'http://127.0.0.1:5000';
const targets = await fetch('http://127.0.0.1:9222/json/list').then((response) => response.json());
const target = targets.find((item) => item.type === 'page');
if (!target) throw new Error('No Chrome page target');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});
let sequence = 0;
const pending = new Map();
const errors = [];
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const item = pending.get(message.id);
    if (!item) return;
    pending.delete(message.id);
    if (message.error) item.reject(new Error(JSON.stringify(message.error)));
    else item.resolve(message.result);
  }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
    errors.push(message.params.args.map((arg) => arg.value || arg.description).join(' '));
  }
});

function send(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}

async function waitFor(expression, timeout = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 120));
  }
  throw new Error(`Timed out: ${expression}`);
}

function assert(value, message) {
  if (!value) throw new Error(message);
  console.log(`PASS ${message}`);
}

async function screenshot(name) {
  const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(path.join(artifactDir, name), Buffer.from(result.data, 'base64'));
}

async function setFiles(selector, files) {
  const documentNode = await send('DOM.getDocument');
  const node = await send('DOM.querySelector', { nodeId: documentNode.root.nodeId, selector });
  if (!node.nodeId) throw new Error(`Input not found: ${selector}`);
  await send('DOM.setFileInputFiles', { nodeId: node.nodeId, files });
}

await send('Page.enable');
await send('Runtime.enable');
await send('DOM.enable');
await send('Page.navigate', { url: origin });
await waitFor('document.readyState === "complete" && !document.querySelector("#projectsView").classList.contains("hidden")');
await screenshot('ui-01-projects.png');

await setFiles('#projectFile', [path.join(root, 'data', '中幼林抚育林木采伐调查设计总表.xlsx')]);
await waitFor('location.hash.startsWith("#/project/") && document.querySelectorAll("#subcompartmentRows tr").length === 684');
assert(await evaluate('document.querySelector("#projectTitle").textContent.includes("中幼林抚育林木采伐调查设计总表.xlsx")'), '项目页显示原始文件名');
assert(await evaluate('document.querySelector("#filterCount").textContent.includes("684 / 684")'), '上传后显示全部 684 个小班');
await screenshot('ui-02-subcompartments.png');

await evaluate('document.querySelector("#filterTownship").value = "平甸乡"; document.querySelector("#filterTownship").dispatchEvent(new Event("change", { bubbles: true }))');
await waitFor('document.querySelector("#filterCount").textContent.includes("63 / 684")');
await evaluate('document.querySelector("#filterVillage").value = "磨皮村"; document.querySelector("#filterVillage").dispatchEvent(new Event("change", { bubbles: true }))');
await evaluate('document.querySelector("#filterNumber").value = "XP-06"; document.querySelector("#filterNumber").dispatchEvent(new Event("input", { bubbles: true }))');
await waitFor('document.querySelectorAll("#subcompartmentRows tr").length === 1');
assert(await evaluate('document.querySelector("#subcompartmentRows").textContent.includes("磨皮村")'), '标段/乡镇/村委会与小班号筛选联动');
await evaluate('document.querySelector(".sub-link").click()');
await waitFor('location.hash.startsWith("#/sub/") && document.querySelectorAll("#surveyTable tbody tr").length === 24');
assert(await evaluate('!document.querySelector("#surveyTable").textContent.includes("油杉")'), '调查表只显示当前小班树种组成');
assert(await evaluate('document.querySelectorAll("#surveyTable tbody tr").length === 24'), '显示 23 个固定胸径项及小计行');

await evaluate('document.querySelector("#plotNumber").value = "1"; document.querySelector("#plotNumber").dispatchEvent(new Event("input", { bubbles: true }))');
for (const species of ['云南松', '其他阔叶']) {
  await evaluate(`document.querySelector('input[data-species="${species}"][data-dbh="6"][data-type="height"]').value = "8"; document.querySelector('input[data-species="${species}"][data-dbh="6"][data-type="height"]').dispatchEvent(new Event("input", { bubbles: true }))`);
  await evaluate(`document.querySelector('input[data-species="${species}"][data-dbh="6"][data-type="count"]').value = "2"; document.querySelector('input[data-species="${species}"][data-dbh="6"][data-type="count"]').dispatchEvent(new Event("input", { bubbles: true }))`);
}
await evaluate('document.querySelector(\'input[data-type="cut"][data-dbh="6"]\').value = "2"; document.querySelector(\'input[data-type="cut"][data-dbh="6"]\').dispatchEvent(new Event("input", { bubbles: true }))');
await waitFor('document.querySelector("#saveStatus").textContent === "已自动保存"');
assert(await evaluate('document.querySelector("#unit-云南松-6").textContent === "0.013"'), '单株材积按样地表公式实时计算');
assert(await evaluate('document.querySelector("#summaryCount").textContent === "4"'), '样地株数联动汇总');
assert(await evaluate('document.querySelector("#summaryPerHaVolume").textContent === "0.750"'), '每公顷蓄积按系数 15 联动计算');
await screenshot('ui-03-survey.png');

await send('Page.reload', { ignoreCache: true });
await waitFor('location.hash.startsWith("#/sub/") && document.querySelector(\'input[data-species="云南松"][data-dbh="6"][data-type="count"]\')?.value === "2"');
assert(await evaluate('document.querySelector("#plotNumber").value === "1"'), '刷新后调查数据仍然保留');

await send('Browser.grantPermissions', { permissions: ['geolocation'], origin });
await send('Emulation.setGeolocationOverride', { latitude: 24.1, longitude: 102.1, accuracy: 5 });
await setFiles('#photoInput', [path.join(root, 'tests', 'fixtures', 'photo-source.jpg')]);
await waitFor('document.querySelector("#photoStatus").textContent.startsWith("已保存")');
await waitFor('document.querySelector("#photoList img")?.complete && document.querySelector("#photoList img")?.naturalWidth > 0');
assert(await evaluate('document.querySelector("#photoList img").naturalWidth === 1440 && document.querySelector("#photoList img").naturalHeight === 864'), '2000×1200 照片压缩为 1440×864');
await evaluate('document.querySelector(".tools-grid").scrollIntoView({ block: "start" })');
await screenshot('ui-04-photo.png');

await evaluate('document.querySelector("#toggleTrack").click()');
await waitFor('Number(document.querySelector("#trackPoints").textContent) >= 1');
await send('Emulation.setGeolocationOverride', { latitude: 24.1001, longitude: 102.1001, accuracy: 4 });
await waitFor('Number(document.querySelector("#trackPoints").textContent) >= 2');
await evaluate('document.querySelector("#toggleTrack").click()');
await waitFor('document.querySelector("#trackStatus").textContent.includes("轨迹已保存")');
assert(await evaluate('!document.querySelector("#exportTrack").classList.contains("disabled")'), '轨迹保存后可导出 GPX');
assert(await evaluate('Number(document.querySelector("#trackDistance").textContent) > 0'), '卫星定位点生成轨迹距离');
await waitFor('[...document.querySelectorAll("#trackMap img.leaflet-tile")].filter((image) => image.complete && image.naturalWidth > 0).length >= 4', 30000);
assert(await evaluate('[...document.querySelectorAll("#trackMap img.leaflet-tile")].some((image) => image.complete && image.naturalWidth > 0)'), 'Esri 卫星底图瓦片实际加载');
await evaluate('document.querySelector(".track-card").scrollIntoView({ block: "start" })');
await screenshot('ui-05-track.png');

await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await send('Page.reload', { ignoreCache: true });
await waitFor('document.querySelectorAll("#surveyTable tbody tr").length === 24');
assert(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), '390px 移动视口无页面级横向溢出');
await screenshot('ui-06-mobile.png');
assert(errors.length === 0, `浏览器无 JavaScript 异常${errors.length ? `：${errors.join('; ')}` : ''}`);
console.log('UI smoke test completed');
socket.close();
