/**
 * markdown.js —— 轻量 Markdown 渲染器（为本项目 Wiki 语法定制）
 *
 * 设计说明：
 *   - 零依赖、纯浏览器端实现，不引入外部 CDN 资源，保证完全离线可用；
 *   - 支持本项目 Wiki 实际使用的语法子集：
 *       YAML front matter、ATX 标题（#~######）、段落、无序/有序列表（含嵌套）、
 *       引用块（可嵌套）、GFM 表格（单元格支持 <br>）、围栏代码块、分隔线、
 *       行内代码、粗体、斜体、链接（站内 .md 链接转为 SPA 路由链接）、裸 <br> 标签；
 *   - 安全策略：渲染前对文本做 HTML 转义，仅放行受控的 <br> 标签；
 *   - 标题 id 规则：h2~h6 按出现顺序分配 sec-1、sec-2……（与 extractHeadings 保持一致，
 *     供右侧「本页目录」与锚点跳转使用；引用块与代码块内的 # 不参与编号）。
 *
 * 对外接口（挂载在 window.WikiMarkdown）：
 *   parseFrontMatter(md)             -> { meta, body }
 *   render(md, options)              -> HTML 字符串
 *   extractHeadings(md)              -> [{ id, level, text }]（不含 h1）
 *   toPlainText(md)                  -> 去除 Markdown 标记的纯文本（用于全文检索）
 */
(function (global) {
  'use strict';

  /* ============================== 基础工具 ============================== */

  /** HTML 转义，防止内容中的标签被注入页面 */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** 解析 YAML front matter（仅支持本项目用到的「key: value」与「tags 数组」格式） */
  function parseFrontMatter(md) {
    var meta = {};
    var body = md;
    var m = /^---\s*\n([\s\S]*?)\n---\s*\n?/.exec(md);
    if (m) {
      var block = m[1];
      body = md.slice(m[0].length);
      block.split('\n').forEach(function (line) {
        var kv = /^([^:#]+):\s*(.*)$/.exec(line.trim());
        if (!kv) return;
        var key = kv[1].trim();
        var value = kv[2].trim().replace(/^["']|["']$/g, '');
        if (value.charAt(0) === '[' && value.charAt(value.length - 1) === ']') {
          // 数组形式，如：标签: [a, b, c]
          meta[key] = value.slice(1, -1).split(',').map(function (s) { return s.trim(); })
            .filter(function (s) { return s.length > 0; });
        } else {
          meta[key] = value;
        }
      });
    }
    return { meta: meta, body: body };
  }

  /** 判断一行是否为表格分隔行（如 |---|---| 或 | :--- | ---: |） */
  function isTableSeparator(line) {
    if (!line || line.indexOf('-') === -1) return false;
    if (!/^[\s|:\-]+$/.test(line)) return false;
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
  }

  /** 拆分表格行 -> 单元格数组 */
  function splitTableRow(line) {
    var s = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    return s.split('|').map(function (c) { return c.trim(); });
  }

  /** 匹配无序列表项；返回 { indent, text } 或 null */
  function matchUl(line) {
    var m = /^(\s*)[-*+]\s+(.*)$/.exec(line);
    if (!m) return null;
    return { indent: m[1].replace(/\t/g, '  ').length, text: m[2] };
  }

  /** 匹配有序列表项；返回 { indent, text } 或 null */
  function matchOl(line) {
    var m = /^(\s*)(\d+)[.)、]\s+(.*)$/.exec(line);
    if (!m) return null;
    return { indent: m[1].replace(/\t/g, '  ').length, text: m[3] };
  }

  /* ============================== 行内解析 ============================== */

  /** 将 Markdown 链接目标解析为站内页面 / 站外地址 */
  function resolveHref(href, ctx) {
    if (/^(https?:)?\/\//i.test(href) || /^mailto:/i.test(href)) {
      return { kind: 'external', href: href };
    }
    var anchor = '';
    var target = href;
    var hashIndex = href.indexOf('#');
    if (hashIndex >= 0) {
      anchor = href.slice(hashIndex + 1);
      target = href.slice(0, hashIndex);
    }
    if (!target) {
      return { kind: 'internal', path: ctx.fromPath, anchor: anchor };
    }
    if (!/\.md$/i.test(target)) {
      // 非 .md 的站内链接（如附件），按外链兜底处理
      return { kind: 'external', href: href };
    }
    var resolved = ctx.resolveLink ? ctx.resolveLink(ctx.fromPath, target) : target;
    return { kind: 'internal', path: resolved, anchor: anchor };
  }

  /**
   * 行内元素渲染
   * @param {string} text 原始行内文本
   * @param {object} ctx  渲染上下文：{ fromPath, resolveLink }
   */
  function renderInline(text, ctx) {
    var placeholders = [];
    function stash(html) {
      placeholders.push(html);
      return '\u0000' + (placeholders.length - 1) + '\u0000';
    }

    // 1. 行内代码：`code`（先保护，避免内部内容被当作标记处理）
    text = text.replace(/`([^`]+)`/g, function (_, code) {
      return stash('<code>' + escapeHtml(code) + '</code>');
    });

    // 2. 保护受控的 <br> 标签（表格单元格换行等场景使用）
    text = text.replace(/<br\s*\/?>/gi, function () { return stash('<br>'); });

    // 3. HTML 转义，此后文本均按纯文本处理
    text = escapeHtml(text);

    // 4. 链接：[文本](目标)
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (whole, label, href) {
      var info = resolveHref(href, ctx);
      if (info.kind === 'external') {
        return '<a class="ext-link" href="' + escapeHtml(info.href) + '" target="_blank" rel="noopener noreferrer">' +
          label + '</a>';
      }
      var attrs = ' class="int-link" data-link="' + escapeHtml(info.path) + '"';
      if (info.anchor) attrs += ' data-anchor="' + escapeHtml(info.anchor) + '"';
      return '<a' + attrs + ' href="#/' + encodeURI(info.path) + '">' + label + '</a>';
    });

    // 5. 粗体：**text**
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // 6. 斜体：*text*（要求两侧紧邻非空白字符，避免误伤普通星号）
    text = text.replace(/(^|[^*])\*([^\s*][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');

    // 7. 还原占位符
    text = text.replace(/\u0000(\d+)\u0000/g, function (_, i) { return placeholders[+i]; });
    return text;
  }

  /* ============================== 自定义块 ============================== */

/**
 * 渲染本 Wiki 的自定义块（由内容生成器产出）：
 *   wiki-hero     英雄区（首页大标题 + 副标题 + 统计）
 *   wiki-cards    卡片网格（分类枢纽页的条目跳转卡）
 *   wiki-infobox  信息框（条目页右侧资料卡）
 * 内容行采用「字段 :: 字段 :: 字段」格式。
 */
function renderCustomBlock(kind, contentLines, ctx) {
  var rows = contentLines.filter(function (l) { return l.trim(); })
    .map(function (l) { return l.split('::').map(function (s) { return s.trim(); }); });

  if (kind === 'wiki-hero') {
    var hero = { title: '', sub: '', stats: '' };
    rows.forEach(function (r) {
      if (r[0] === '标题') hero.title = r[1] || '';
      else if (r[0] === '副标题') hero.sub = r[1] || '';
      else if (r[0] === '统计') hero.stats = r[1] || '';
    });
    return '<div class="hero">' +
      '<div class="hero-inner">' +
      (hero.title ? '<h2 class="hero-title">' + renderInline(hero.title, ctx) + '</h2>' : '') +
      (hero.sub ? '<p class="hero-sub">' + renderInline(hero.sub, ctx) + '</p>' : '') +
      (hero.stats ? '<p class="hero-stats">' + renderInline(hero.stats, ctx) + '</p>' : '') +
      '</div></div>';
  }

  if (kind === 'wiki-cards') {
    var cards = rows.map(function (r) {
      var title = r[0] || '';
      var desc = r[1] || '';
      var href = r[2] || '';
      if (!href) return '';
      var info = resolveHref(href, ctx);
      var attrs = '';
      if (info.kind === 'external') {
        attrs = ' href="' + escapeHtml(info.href) + '" target="_blank" rel="noopener noreferrer"';
      } else {
        attrs = ' href="#/' + encodeURI(info.path) + '" data-link="' + escapeHtml(info.path) + '"' +
          (info.anchor ? ' data-anchor="' + escapeHtml(info.anchor) + '"' : '');
      }
      var icon = escapeHtml(title.charAt(0) || '·');
      return '<a class="entry-card"' + attrs + '>' +
        '<span class="entry-icon" aria-hidden="true">' + icon + '</span>' +
        '<span class="entry-body">' +
        '<span class="entry-title">' + renderInline(title, ctx) + '</span>' +
        (desc ? '<span class="entry-desc">' + renderInline(desc, ctx) + '</span>' : '') +
        '</span></a>';
    }).join('');
    return '<div class="card-grid">' + cards + '</div>';
  }

  if (kind === 'wiki-infobox') {
    var html = '<div class="infobox"><div class="infobox-head">资料卡</div>';
    rows.forEach(function (r) {
      if (r.length < 2) return;
      html += '<div class="infobox-row"><span class="ib-key">' + renderInline(r[0], ctx) +
        '</span><span class="ib-val">' + renderInline(r.slice(1).join(' :: '), ctx) + '</span></div>';
    });
    return html + '</div>';
  }

  return '';
}

/* ============================== 块级解析 ============================== */

  /**
   * 渲染 Markdown 为 HTML
   * @param {string} md      Markdown 原文
   * @param {object} options { fromPath: 当前页面路径, resolveLink(from, target), skipFirstH1: 是否跳过正文首个 h1（默认 true） }
   */
  function render(md, options) {
    var opts = options || {};
    var ctx = { fromPath: opts.fromPath || '', resolveLink: opts.resolveLink || null };
    var parsed = parseFrontMatter(md);
    var lines = parsed.body.replace(/\r\n?/g, '\n').split('\n');
    var state = { headingCounter: 0, h1Seen: false, skipFirstH1: opts.skipFirstH1 !== false, inQuote: false };
    return renderBlocks(lines, ctx, state);
  }

  /**
   * 块级渲染主循环（供正文与引用块递归使用）
   * state: { headingCounter, h1Seen, skipFirstH1, inQuote }（原地修改，保证标题 id 连续）
   */
  function renderBlocks(lines, ctx, state) {
    var out = [];
    var i = 0;

    while (i < lines.length) {
      var line = lines[i];

      // ---- 空行 ----
      if (!line.trim()) { i++; continue; }

      // ---- 自定义块（hero / cards / infobox） ----
      var custom = /^\s*```+\s*(wiki-hero|wiki-cards|wiki-infobox)\s*$/.exec(line);
      if (custom) {
        var kind = custom[1];
        var cbuf = [];
        i++;
        while (i < lines.length && !/^\s*```+\s*$/.test(lines[i])) {
          cbuf.push(lines[i]); i++;
        }
        i++; // 跳过收尾围栏
        out.push(renderCustomBlock(kind, cbuf, ctx));
        continue;
      }

      // ---- 围栏代码块 ----
      var fence = /^\s*(```+|~~~+)\s*([^\s`]*)\s*$/.exec(line);
      if (fence) {
        var marker = fence[1].charAt(0);
        var lang = fence[2] || '';
        var buf = [];
        i++;
        while (i < lines.length && !(new RegExp('^\\s*' + marker + '{3,}\\s*$')).test(lines[i])) {
          buf.push(lines[i]); i++;
        }
        i++; // 跳过收尾围栏（若缺失则 i 越界，循环自然结束）
        out.push('<pre class="code-block"' + (lang ? ' data-lang="' + escapeHtml(lang) + '"' : '') + '>' +
          '<code>' + escapeHtml(buf.join('\n')) + '</code></pre>');
        continue;
      }

      // ---- 分隔线 ----
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        out.push('<hr>');
        i++; continue;
      }

      // ---- 标题（引用块内不识别标题） ----
      var heading = state.inQuote ? null : /^(#{1,6})\s+(.*?)\s*$/.exec(line);
      if (heading) {
        var level = heading[1].length;
        var text = renderInline(heading[2], ctx);
        if (level === 1 && state.skipFirstH1 && !state.h1Seen) {
          state.h1Seen = true; // 正文首个 h1 由页面头部统一展示，正文中跳过
          i++; continue;
        }
        if (level === 1) state.h1Seen = true;
        var idAttr = '';
        if (level >= 2) {
          state.headingCounter += 1;
          idAttr = ' id="sec-' + state.headingCounter + '"';
        }
        out.push('<h' + level + idAttr + ' class="md-heading">' + text +
          '<button type="button" class="heading-anchor" data-anchor-copy="' + (idAttr ? 'sec-' + state.headingCounter : '') +
          '" title="复制本段链接" aria-label="复制本段链接">#</button></h' + level + '>');
        i++; continue;
      }

      // ---- 引用块（收集连续的 > 行后递归渲染） ----
      if (/^\s{0,3}>/.test(line)) {
        var quoteLines = [];
        while (i < lines.length) {
          if (/^\s{0,3}>/.test(lines[i])) {
            quoteLines.push(lines[i].replace(/^\s{0,3}>\s?/, ''));
            i++;
          } else if (lines[i].trim() === '') {
            // 前瞻：仅当下一行仍是引用时才把空行视为引用块内部空行
            if (i + 1 < lines.length && /^\s{0,3}>/.test(lines[i + 1])) {
              quoteLines.push('');
              i++;
            } else {
              break;
            }
          } else {
            break;
          }
        }
        var childState = {
          headingCounter: state.headingCounter,
          h1Seen: true,
          skipFirstH1: false,
          inQuote: true
        };
        var inner = renderBlocks(quoteLines, ctx, childState);
        state.headingCounter = childState.headingCounter; // 同步计数（引用内通常无标题）
        out.push('<blockquote>' + inner + '</blockquote>');
        continue;
      }

      // ---- 表格 ----
      if (line.indexOf('|') !== -1 && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        var headerCells = splitTableRow(line);
        var rows = [];
        i += 2;
        while (i < lines.length && lines[i].indexOf('|') !== -1 && lines[i].trim() !== '') {
          rows.push(splitTableRow(lines[i]));
          i++;
        }
        out.push(renderTable(headerCells, rows, ctx));
        continue;
      }

      // ---- 列表（无序 / 有序，支持缩进嵌套） ----
      var ul = matchUl(line);
      var ol = matchOl(line);
      if (ul || ol) {
        var listResult = renderList(lines, i, ctx);
        out.push(listResult.html);
        i = listResult.next;
        continue;
      }

      // ---- 段落（连续的非空、非特殊行，行间以 <br> 分隔） ----
      var para = [];
      while (i < lines.length && lines[i].trim() !== '' &&
        !/^(#{1,6})\s+/.test(lines[i]) &&
        !/^\s{0,3}>/.test(lines[i]) &&
        !/^\s*(```+|~~~+)/.test(lines[i]) &&
        !matchUl(lines[i]) && !matchOl(lines[i]) &&
        !/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])) {
        // 段落中出现「表头 + 分隔行」则中断，交给表格分支处理
        if (lines[i].indexOf('|') !== -1 && i + 1 < lines.length && isTableSeparator(lines[i + 1])) break;
        para.push(lines[i].trim());
        i++;
      }
      if (para.length) {
        out.push('<p>' + para.map(function (l) { return renderInline(l, ctx); }).join('<br>') + '</p>');
      }
    }

    return out.join('\n');
  }

  /** 渲染 GFM 表格 */
  function renderTable(header, rows, ctx) {
    var html = '<div class="table-wrap"><table>';
    html += '<thead><tr>';
    header.forEach(function (cell) { html += '<th>' + renderInline(cell, ctx) + '</th>'; });
    html += '</tr></thead><tbody>';
    rows.forEach(function (row) {
      html += '<tr>';
      // 以表头列数为准补齐 / 截断，容忍个别行单元格数量的轻微偏差
      for (var c = 0; c < header.length; c++) {
        html += '<td>' + renderInline(row[c] === undefined ? '' : row[c], ctx) + '</td>';
      }
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  /**
   * 渲染列表（先收集列表行并解析为缩进树，再序列化为 HTML）
   * 返回 { html, next }：next 为列表中最后一行之后的索引
   */
  function renderList(lines, start, ctx) {
    var i = start;
    var items = []; // [{ indent, type, parts:[行文本] }]

    // 1. 收集整个列表块（含缩进续行）
    while (i < lines.length) {
      var line = lines[i];
      var ul = matchUl(line);
      var ol = matchOl(line);
      if (ul || ol) {
        items.push({ indent: (ul || ol).indent, type: ul ? 'ul' : 'ol', parts: [(ul || ol).text] });
        i++;
      } else if (line.trim() !== '' && /^\s+\S/.test(line) && items.length) {
        items[items.length - 1].parts.push(line.trim()); // 列表项续行
        i++;
      } else {
        break;
      }
    }

    // 2. 依据缩进构建嵌套结构：root 与 items[].children 均为「容器数组」
    var root = [];
    var stack = []; // [{ indent, type, items, arr }]

    function lastItemChildren(entry) {
      var last = entry.items[entry.items.length - 1];
      if (!last.children) last.children = [];
      return last.children;
    }

    items.forEach(function (it) {
      while (stack.length && stack[stack.length - 1].indent > it.indent) stack.pop();
      var top = stack.length ? stack[stack.length - 1] : null;
      if (!top || top.indent < it.indent) {
        // 开启更深层（或首个）列表容器
        var arr = top ? lastItemChildren(top) : root;
        var cont = { type: it.type, items: [] };
        arr.push(cont);
        stack.push({ indent: it.indent, type: it.type, items: cont.items, arr: arr });
      } else if (top.type !== it.type) {
        // 同缩进但类型切换：在同一父容器内另起一个列表
        var cont2 = { type: it.type, items: [] };
        top.arr.push(cont2);
        stack[stack.length - 1] = { indent: it.indent, type: it.type, items: cont2.items, arr: top.arr };
      }
      var cur = stack[stack.length - 1];
      cur.items.push({ text: it.parts.join('<br>'), children: null });
    });

    // 3. 序列化为 HTML
    function serializeList(cont) {
      var tag = cont.type === 'ul' ? 'ul' : 'ol';
      var inner = cont.items.map(function (item) {
        var childrenHtml = item.children
          ? item.children.map(serializeList).join('')
          : '';
        return '<li>' + renderInline(item.text, ctx) + childrenHtml + '</li>';
      }).join('');
      return '<' + tag + '>' + inner + '</' + tag + '>';
    }

    return { html: root.map(serializeList).join(''), next: i };
  }

  /* ====================== 标题提取 / 纯文本提取 ====================== */

  /** 去除行内 Markdown 标记（用于标题 / 纯文本） */
  function stripInline(text) {
    return String(text)
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/<br\s*\/?>/gi, ' ')
      .trim();
  }

  /** 提取全部 h2~h6 标题（id 与 render 输出的 sec-N 一致；跳过代码块与引用块内文本） */
  function extractHeadings(md) {
    var parsed = parseFrontMatter(md);
    var lines = parsed.body.replace(/\r\n?/g, '\n').split('\n');
    var result = [];
    var counter = 0;
    var inFence = false;

    lines.forEach(function (line) {
      if (/^\s*(```+|~~~+)/.test(line)) { inFence = !inFence; return; }
      if (inFence) return;
      if (/^\s{0,3}>/.test(line)) return; // 引用块内不参与标题编号
      var m = /^(#{1,6})\s+(.*?)\s*$/.exec(line);
      if (!m) return;
      var level = m[1].length;
      if (level === 1) return; // h1 不入目录
      counter += 1;
      result.push({ id: 'sec-' + counter, level: level, text: stripInline(m[2]) });
    });
    return result;
  }

  /** 提取用于全文检索的纯文本（含 wiki-cards / wiki-infobox 块内可见文本） */
  function toPlainText(md) {
    var parsed = parseFrontMatter(md);
    var lines = parsed.body.replace(/\r\n?/g, '\n').split('\n');
    var buf = [];
    var fence = null; // 记录当前围栏类型：null / 'skip' / 'keep'

    lines.forEach(function (line) {
      var fm = /^\s*(```+|~~~+)\s*([^\s`]*)/.exec(line);
      if (fm) {
        if (fence === null) {
          // 进入围栏：wiki-cards / wiki-infobox 的内容可见，其余代码块跳过
          fence = (fm[2] === 'wiki-cards' || fm[2] === 'wiki-infobox' || fm[2] === 'wiki-hero') ? 'keep' : 'skip';
        } else {
          fence = null;
        }
        return;
      }
      if (fence === 'skip') return;
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) return;
      var t = line
        .replace(/^\s{0,3}>\s?/, '')          // 引用标记
        .replace(/^#{1,6}\s+/, '')            // 标题标记
        .replace(/^\s*[-*+]\s+/, '')          // 无序列表标记
        .replace(/^\s*\d+[.)、]\s+/, '')      // 有序列表标记
        .replace(/\s*::\s*/g, ' ')            // 卡片/信息框字段分隔
        .replace(/\|/g, ' ');                 // 表格分隔符
      t = stripInline(t);
      if (t.trim()) buf.push(t.trim());
    });
    return buf.join(' ');
  }

  /* ============================== 导出 ============================== */
  global.WikiMarkdown = {
    parseFrontMatter: parseFrontMatter,
    render: render,
    extractHeadings: extractHeadings,
    toPlainText: toPlainText,
    escapeHtml: escapeHtml
  };
})(window);