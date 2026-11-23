#!/usr/bin/env node
/* 照片命名 / 相册目录 / 水印行 的自动化测试（v1.5，node 直跑）
 *
 * 覆盖 static/photo_tpl.js 的纯逻辑：
 *   · 项目名称留空 → 回落 App 名「抚育调查」
 *   · {{占位符}} 渲染（未知占位符替换为空，参数解析阶段已拒收，这里只兜住不崩）
 *   · 相册子目录：默认 {{项目名称}}/{{小班号}}；非法字符清洗；. / .. 段剔除
 *   · 文件名：默认模板；非法字符清洗；模板为空时按项目名+小班+样地+时间兜底
 *   · 水印行：项目名 → 小班/样地 → 说明 → 时间 → 坐标；开关去掉某项就不出现
 *
 * 为什么值得单独测：这几条字符串直接决定照片落到相册的哪个文件夹、叫什么名字。
 * 写错了不会报错，只会让两万张照片堆在同一个目录里、事后按小班找不回来。
 */
const T = require('../static/photo_tpl.js');

let pass = 0, fail = 0;
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  \u2705 ' + name + (detail ? '  ' + detail : '')); }
  else { fail++; console.log('  \u274c ' + name + (detail ? '  ' + detail : '')); }
}

const WHEN = new Date(2026, 10, 23, 11, 5, 9);   // 2026-11-23 11:05:09
const INFO = { number: 'XP-01', plotNo: '2' };

console.log('=== A. 上下文 ===');
const ctx = T.context({ 项目名称: '2025年度中幼林抚育', 说明: '外业现地调查' }, INFO, WHEN);
ok('A1 项目名称原样带入', ctx.项目名称 === '2025年度中幼林抚育');
ok('A2 时间用紧凑格式 YYYYMMDD_HHMMSS', ctx.时间 === '20261123_110509', ctx.时间);
ok('A3 时间显示用可读格式', ctx.时间显示 === '2026-11-23 11:05:09', ctx.时间显示);
ok('A4 小班/样地取自当前样地', ctx.小班号 === 'XP-01' && ctx.样地号 === '2');

const blank = T.context({}, INFO, WHEN);
ok('A5 没有项目名称 → 回落 App 名', blank.项目名称 === T.APP_NAME, blank.项目名称);
const spaced = T.context({ 项目名称: '   ' }, INFO, WHEN);
ok('A6 项目名称只有空格也算空 → 回落 App 名', spaced.项目名称 === T.APP_NAME);

console.log('\n=== B. 模板渲染 ===');
ok('B1 五个占位符都能替换',
  T.render('{{项目名称}}/{{小班号}}/样地{{样地号}}/{{时间}}/{{说明}}', ctx)
    === '2025年度中幼林抚育/XP-01/样地2/20261123_110509/外业现地调查');
ok('B2 未知占位符替换为空串（不抛异常）', T.render('a{{不存在}}b', ctx) === 'ab');
ok('B3 不是占位符的花括号原样保留', T.render('{{项目名称}}-{x}', ctx) === '2025年度中幼林抚育-{x}');

console.log('\n=== C. 相册目录 ===');
ok('C1 默认目录 = 项目名称/小班号',
  T.albumSubdir({ 目录: '{{项目名称}}/{{小班号}}' }, ctx) === '2025年度中幼林抚育/XP-01',
  T.albumSubdir({ 目录: '{{项目名称}}/{{小班号}}' }, ctx));
ok('C2 目录为空 → 仍按 项目名称/小班号 兜底',
  T.albumSubdir({}, ctx) === '2025年度中幼林抚育/XP-01');
ok('C3 目录带样地层级',
  T.albumSubdir({ 目录: '{{项目名称}}/{{小班号}}/样地{{样地号}}' }, ctx)
    === '2025年度中幼林抚育/XP-01/样地2');
ok('C4 非法字符被清洗成下划线',
  T.albumSubdir({ 目录: '项目:2025/{{小班号}}' }, ctx) === '项目_2025/XP-01',
  T.albumSubdir({ 目录: '项目:2025/{{小班号}}' }, ctx));
ok('C5 . 与 .. 段被剔除（防路径穿越）',
  T.albumSubdir({ 目录: '../{{项目名称}}/./{{小班号}}' }, ctx) === '2025年度中幼林抚育/XP-01');
ok('C6 全空目录 → 回落到项目名（不产生空路径）',
  T.albumSubdir({ 目录: '/' }, T.context({}, { number: '' }, WHEN)) === T.APP_NAME);

console.log('\n=== D. 文件名 ===');
ok('D1 默认模板：项目名_小班号_样地N_时间',
  T.photoName({ 相片文件名: '{{项目名称}}_{{小班号}}_样地{{样地号}}_{{时间}}' }, ctx)
    === '2025年度中幼林抚育_XP-01_样地2_20261123_110509',
  T.photoName({ 相片文件名: '{{项目名称}}_{{小班号}}_样地{{样地号}}_{{时间}}' }, ctx));
ok('D2 文件名里的冒号/斜杠等非法字符被清洗（括号是合法字符，保留）',
  T.photoName({ 相片文件名: '{{小班号}}:a*b' }, ctx) === 'XP-01_a_b',
  T.photoName({ 相片文件名: '{{小班号}}:a*b' }, ctx));
ok('D3 模板为空 → 按兜底命名（不出现空文件名）',
  T.photoName({ 相片文件名: '' }, ctx) === '2025年度中幼林抚育_XP-01_样地2_20261123_110509');
ok('D4 项目名与小班号都空 → 至少给出可辨识名字',
  T.photoName({ 相片文件名: '{{项目名称}}{{小班号}}' }, T.context({ 项目名称: '' }, { number: '', plotNo: '1' }, WHEN))
    === T.APP_NAME);

console.log('\n=== E. 水印行 ===');
const marks = { 水印内容: ['项目名称', '小班', '时间', '坐标'] };
const plainCtx = T.context({ 项目名称: '2025年度中幼林抚育' }, INFO, WHEN);   // 不带说明
const lines = T.watermarkLines(marks, plainCtx, '24.12345, 102.67890');
ok('E1 四行齐全且顺序固定（项目名 → 小班/样地 → 时间 → 坐标）',
  JSON.stringify(lines) === JSON.stringify([
    '2025年度中幼林抚育',
    '小班：XP-01  样地：2',
    '时间：2026-11-23 11:05:09',
    '坐标：24.12345, 102.67890',
  ]), JSON.stringify(lines));
ok('E2 说明填了就插在小班之后',
  T.watermarkLines(marks, ctx, '1,2')[2] === '说明：外业现地调查');
ok('E3 说明留空不占行',
  T.watermarkLines(marks, T.context({ 项目名称: 'X' }, INFO, WHEN), '1,2').length === 4);
ok('E4 去掉「坐标」不写定位',
  T.watermarkLines({ 水印内容: ['项目名称', '小班', '时间'] }, ctx, null)
    .every((line) => !line.startsWith('坐标')), JSON.stringify(lines));
ok('E5 去掉「项目名称」「小班」只剩时间坐标',
  JSON.stringify(T.watermarkLines({ 水印内容: ['时间', '坐标'] }, plainCtx, '1,2'))
    === JSON.stringify(['时间：2026-11-23 11:05:09', '坐标：1,2']));
ok('E6 没有定位时写「定位未获取」而不是留空',
  T.watermarkLines({ 水印内容: ['坐标'] }, plainCtx, null)[0] === '坐标：定位未获取');
ok('E7 样地号缺失时不出现空的「样地：」',
  JSON.stringify(T.watermarkLines({ 水印内容: ['小班'] }, T.context({ 项目名称: 'X' }, { number: 'XP-9' }, WHEN), null))
    === JSON.stringify(['小班：XP-9']));

console.log('\n' + '='.repeat(62));
console.log('通过 ' + pass + ' / 失败 ' + fail);
process.exit(fail ? 1 : 0);
