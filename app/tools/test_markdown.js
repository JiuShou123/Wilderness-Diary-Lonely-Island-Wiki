/**
 * test_markdown.js —— Markdown 渲染器冒烟测试（Node 环境）
 *
 * 用途：用 wiki/ 目录下的真实页面验证渲染器输出质量，检查：
 *   1. 表格数量是否与源文件一致；
 *   2. 标题数量是否一致、id 是否连续；
 *   3. 输出中是否残留未转换的 Markdown 标记（**、"](、"等）；
 *   4. 标签配对是否平衡（div/table/ul/ol/li/blockquote/pre/strong）；
 *   5. 是否产生 undefined / NaN 等异常文本。
 *
 * 运行：node app/tools/test_markdown.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

// ---- 浏览器环境垫片 ----
global.window = global;
require(path.join(__dirname, '..', 'js', 'markdown.js'));
const MD = global.WikiMarkdown;

const WIKI = path.join(__dirname, '..', '..', 'wiki');

/** 递归收集全部 .md 文件 */
function walk(dir, out) {
  fs.readdirSync(dir, { withFileTypes: true }).forEach((ent) => {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else if (ent.name.toLowerCase().endsWith('.md')) out.push(p);
  });
  return out;
}

function count(str, needle) {
  let n = 0, idx = 0;
  while ((idx = str.indexOf(needle, idx)) !== -1) { n++; idx += needle.length; }
  return n;
}

let totalIssues = 0;
const files = walk(WIKI, []).sort();

files.forEach((file) => {
  const rel = path.relative(WIKI, file).replace(/\\/g, '/');
  const md = fs.readFileSync(file, 'utf8');
  const issues = [];

  // 参考统计（源文件）
  const srcBody = md.replace(/^---[\s\S]*?---\n/, '');
  const srcLines = srcBody.split(/\r?\n/);
  let srcTables = 0, srcHeadings = 0, inFence = false;
  for (let i = 0; i < srcLines.length; i++) {
    const l = srcLines[i];
    if (/^\s*(```+|~~~+)/.test(l)) { inFence = !inFence; continue; }
    if (inFence) continue;
    if (/^#{2,6}\s+/.test(l)) srcHeadings++;
    if (/^\s*\|/.test(l) && i + 1 < srcLines.length && /^\s*\|?[\s:|-]*-/.test(srcLines[i + 1]) && srcLines[i + 1].includes('|')) srcTables++;
  }

  const html = MD.render(md, { fromPath: rel, resolveLink: (f, t) => t });
  const toc = MD.extractHeadings(md);
  const plain = MD.toPlainText(md);

  // 1. 表格数量
  const outTables = count(html, '<table>');
  if (outTables !== srcTables) issues.push(`表格数量不一致：源 ${srcTables} / 输出 ${outTables}`);

  // 2. 标题数量与 id
  if (toc.length !== srcHeadings) issues.push(`标题数量不一致：源 ${srcHeadings} / 目录 ${toc.length}`);
  toc.forEach((h, idx) => {
    if (h.id !== 'sec-' + (idx + 1)) issues.push(`标题 id 不连续：${h.id}`);
    if (!html.includes('id="' + h.id + '"')) issues.push(`输出缺少标题锚点：${h.id}`);
  });

  // 3. 残留标记（排除代码块内部）
  const htmlNoCode = html.replace(/<pre[\s\S]*?<\/pre>/g, '');
  if (/\*\*[^*]+\*\*/.test(htmlNoCode)) issues.push('存在未转换的粗体标记 **');
  if (/\]\([^)]*\)/.test(htmlNoCode)) issues.push('存在未转换的链接标记 ](');
  if (/\bundefined\b|\bNaN\b/.test(htmlNoCode)) issues.push('输出包含 undefined/NaN');
  if (/\u0000/.test(html)) issues.push('存在未还原的占位符');

  // 4. 标签配对
  [['div', /<div\b/g, /<\/div>/g], ['table', /<table\b/g, /<\/table>/g],
   ['ul', /<ul\b/g, /<\/ul>/g], ['ol', /<ol\b/g, /<\/ol>/g],
   ['li', /<li\b/g, /<\/li>/g], ['blockquote', /<blockquote\b/g, /<\/blockquote>/g],
   ['pre', /<pre\b/g, /<\/pre>/g], ['strong', /<strong\b/g, /<\/strong>/g],
   ['p', /<p\b/g, /<\/p>/g]].forEach(([name, openRe, closeRe]) => {
    const open = (html.match(openRe) || []).length;
    const close = (html.match(closeRe) || []).length;
    if (open !== close) issues.push(`标签不配对：<${name}> 开 ${open} / 闭 ${close}`);
  });

  // 5. 纯文本抽样（分类枢纽页允许仅含卡片块，单独放行）
  const isHub = /页面类型: 枢纽/.test(md) || html.includes('class="card-grid"') || md.includes('wiki-cards');
  if (plain.length < 50 && !isHub) issues.push('纯文本长度异常');

  if (issues.length) {
    totalIssues += issues.length;
    console.log(`\n[!] ${rel}`);
    issues.forEach((s) => console.log('    - ' + s));
  } else {
    console.log(`[OK] ${rel}  (tables=${outTables}, headings=${toc.length}, plain=${plain.length})`);
  }
});

console.log(`\n共检查 ${files.length} 个文件，问题 ${totalIssues} 处。`);
process.exit(totalIssues ? 1 : 0);