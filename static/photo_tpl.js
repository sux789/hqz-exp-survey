/* 照片命名与相册目录（v1.5）
 *
 * 纯逻辑，不碰 DOM：浏览器里挂在 window.PhotoTpl，node 里 module.exports，
 * 因此 tests/test_photo_tpl.js 可以直接跑断言（同 photo_exif.js 的做法）。
 *
 * 背景（doc/010）：照片不再上传服务器，改为写入手机系统相册
 *   Pictures/{目录}/{文件名}.jpg
 * 目录与文件名都由「程序参数」sheet 的模板决定，占位符只有五个（param_parser 已校验）：
 *   {{项目名称}} {{说明}} {{小班号}} {{样地号}} {{时间}}
 * 项目名称留空时用 App 名兜底 —— 兜底值只在这里出现一处，别在调用方再写一遍。
 */
(function (global) {
  'use strict';

  const APP_NAME = '抚育调查';
  const ILLEGAL = /[\\/:*?"<>|]+/g;          // 文件系统非法字符
  const CONTROL = /[\u0000-\u001f\u007f]+/g; // 控制字符（含换行）

  function text(value) {
    return value == null ? '' : String(value).replace(CONTROL, ' ').trim();
  }

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  /** 文件名用的紧凑时间：YYYYMMDD_HHMMSS */
  function fileStamp(date) {
    return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
      + `_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  }

  /** 水印用的可读时间：YYYY-MM-DD HH:MM:SS */
  function showStamp(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
      + ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  /** 把一段路径/文件名清洗成单段安全字符：非法字符与空白折成下划线，去首尾下划线。 */
  function sanitizeSeg(value, fallback) {
    const cleaned = text(value)
      .replace(ILLEGAL, '_')
      .replace(/\s+/g, '_')
      .replace(/_+/g, '_')
      .replace(/^_+|_+$/g, '');
    return cleaned || (fallback == null ? '' : String(fallback));
  }

  /** 模板上下文：项目名缺失时回落到 App 名（用户要求：没有项目名称就用 app 名称）。 */
  function context(params, info, date) {
    const p = params || {};
    const moment = (date instanceof Date && !isNaN(date)) ? date : new Date();
    return {
      项目名称: text(p.项目名称) || APP_NAME,
      说明: text(p.说明),
      小班号: text(info && info.number),
      样地号: text(info && info.plotNo),
      时间: fileStamp(moment),
      时间显示: showStamp(moment),
    };
  }

  /** {{占位符}} 替换；未知占位符替换为空串（参数解析阶段已经拒收，这里只是兜底）。 */
  function render(template, ctx) {
    return text(template).replace(/\{\{([^{}]*)\}\}/g, (whole, key) => {
      const name = String(key).trim();
      return Object.prototype.hasOwnProperty.call(ctx || {}, name) ? String(ctx[name]) : '';
    });
  }

  /** 相册子目录（Pictures/ 之下）：默认 {{项目名称}}/{{小班号}} → 抚育调查/XP-01 */
  function albumSubdir(params, ctx) {
    const raw = render(params && params.目录, ctx);
    const segs = raw.split('/')
      .map((seg) => sanitizeSeg(seg))
      .filter((seg) => seg && seg !== '.' && seg !== '..');
    if (segs.length) return segs.join('/');
    const project = sanitizeSeg(ctx && ctx.项目名称, APP_NAME);
    const plot = sanitizeSeg(ctx && ctx.小班号);
    return plot ? `${project}/${plot}` : project;
  }

  /** 照片文件名（不含扩展名） */
  function photoName(params, ctx) {
    const raw = render(params && params.相片文件名, ctx);
    const fallback = `${ctx.项目名称}_${ctx.小班号}_样地${ctx.样地号 || '1'}_${ctx.时间}`;
    return sanitizeSeg(raw, sanitizeSeg(fallback, 'photo'));
  }

  /** 水印逐行内容。顺序固定：项目名 → 小班/样地 → 说明 → 时间 → 坐标。
   *  「小班」一项同时带出样地号 —— 一个 小班常有多块样地，只写小班没法区分照片属于哪块。 */
  function watermarkLines(params, ctx, coordinates) {
    const marks = (params && Array.isArray(params.水印内容) ? params.水印内容 : []) || [];
    const lines = [];
    if (marks.includes('项目名称')) lines.push(ctx.项目名称);
    if (marks.includes('小班')) {
      const parts = [];
      if (ctx.小班号) parts.push(`小班：${ctx.小班号}`);
      if (ctx.样地号) parts.push(`样地：${ctx.样地号}`);
      if (parts.length) lines.push(parts.join('  '));
    }
    if (ctx.说明) lines.push(`说明：${ctx.说明}`);
    if (marks.includes('时间')) lines.push(`时间：${ctx.时间显示}`);
    if (marks.includes('坐标')) lines.push(`坐标：${coordinates || '定位未获取'}`);
    return lines;
  }

  const api = {
    APP_NAME: APP_NAME,
    fileStamp: fileStamp,
    showStamp: showStamp,
    sanitizeSeg: sanitizeSeg,
    context: context,
    render: render,
    albumSubdir: albumSubdir,
    photoName: photoName,
    watermarkLines: watermarkLines,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.PhotoTpl = api;

})(typeof window !== 'undefined' ? window : globalThis);
