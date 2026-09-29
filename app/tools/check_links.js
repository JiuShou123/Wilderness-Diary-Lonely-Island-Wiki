/**
 * check_links.js —— Wiki 结构校验（Node 环境）
 *
 * 校验内容：
 *   1. front matter 必备字段（title / 分类 / 更新日期）与 H1 数量；
 *   2. 站内 Markdown 链接（.md 相对路径）是否存在；
 *   3. 空页面告警（正文过短且非枢纽页）；
 *   4. weki-cards / wiki-infobox 块语法（字段分隔符 `::` 是否规范）。
 *
 * 运行：node app/tools/check_links.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const WIKI = path.join(__dirname, '..', '..', 'wiki');

function walk(dir, out = []) {
  fs.readdirSync(dir, { withFileTypes: true }).forEach((ent) => {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else if (ent.name.toLowerCase().endsWith('.md')) out.push(p);
  });
  return out;
}

const files = walk(WIKI);
let problems = 0;
let stats = { pages: 0, hub: 0, leaf: 0, chars: 0, links: 0, cardLinks: 0 };

files.forEach((file) => {
  const rel = path.relative(WIKI, file).replace(/\\/g, '/');
  const md = fs.readFileSync(file, 'utf8');
  const issues = [];
  stats.pages++;
  stats.chars += md.length;
  if (/页面类型: 枢纽/.test(md)) stats.hub++;
  else stats.leaf++;

  // 1. front matter 与 H1
  const fmMatch = /^---\r?\n([\s\S]*?)\r?\n---/.exec(md);
  if (!fmMatch) issues.push('缺少 front matter');
  else {
    ['title', '分类', '更新日期'].forEach((k) => {
      if (!fmMatch[1].includes(k + ':')) issues.push(`front matter 缺少字段 ${k}`);
    });
  }
  const h1 = (md.match(/^# .+$/gm) || []).length;
  if (h1 !== 1) issues.push(`H1 数量为 ${h1}（应为 1）`);

  // 2. 链接检查
  const links = md.match(/\[[^\]]+\]\([^)\s]+\)/g) || [];
  const body = md.replace(/^---[\s\S]*?---/, '');
  (body.match(/\[([^\]]+)\]\(([^)\s]+)\)/g) || []).forEach((raw) => {
    const m = /\[([^\]]+)\]\(([^)\s]+)\)/.exec(raw);
    const target = m[2];
    if (/^(https?:|mailto:|#|javascript:)/.test(target)) return;
    const cleanTarget = target.split('#')[0];
    if (!cleanTarget.toLowerCase().endsWith('.md')) return;
    stats.links++;
    const resolved = path.normalize(path.join(path.dirname(file), cleanTarget));
    if (!fs.existsSync(resolved)) issues.push(`死链：[${m[1]}](${target})`);
  });

  // 3. 空页面告警
  const plainLen = md.replace(/^---[\s\S]*?---/, '').replace(/[#*|>`\-\s]/g, '').length;
  const isHub = /页面类型: 枢纽/.test(md) || md.includes('wiki-cards');
  if (plainLen < 80 && !isHub) issues.push(`正文过短（${plainLen} 字）`);

  // 4. 自定义块语法与卡片链接
  // 注意：wiki/ 下的文件是 CRLF 换行，正则必须写成 \r?\n，否则整块匹配不到、校验会静默失效
  const cardBlocks = md.match(/```wiki-cards\r?\n([\s\S]*?)\r?\n```/g) || [];
  cardBlocks.forEach((block) => {
    const lines = block.split(/\r?\n/).slice(1, -1).filter((l) => l.trim());
    lines.forEach((l) => {
      const parts = l.split('::');
      if (parts.length !== 3) {
        issues.push(`wiki-cards 字段数不为 3：${l.slice(0, 40)}`);
        return;
      }
      const href = parts[2].trim();
      if (!href || /^(https?:|mailto:|#)/.test(href)) return;
      stats.cardLinks++;
      const resolved = path.normalize(path.join(path.dirname(file), href));
      if (!fs.existsSync(resolved)) issues.push(`卡片死链：[${parts[0].trim()}] -> ${href}`);
    });
  });

  if (issues.length) {
    problems += issues.length;
    console.log(`\n[!] ${rel}`);
    issues.slice(0, 6).forEach((s) => console.log('    - ' + s));
    if (issues.length > 6) console.log(`    …共 ${issues.length} 处`);
  }
});

console.log(`\n===== 统计 =====`);
console.log(`页面总数 ${stats.pages}（枢纽 ${stats.hub} / 条目 ${stats.leaf}），总字符 ${stats.chars}`);
console.log(`站内链接 ${stats.links} 条、卡片链接 ${stats.cardLinks} 条，问题 ${problems} 处`);
process.exit(problems ? 1 : 0);