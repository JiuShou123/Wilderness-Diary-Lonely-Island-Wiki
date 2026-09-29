/**
 * app.js —— 应用控制器：界面渲染、路由导航、侧边栏、页内目录、导入与交互
 *
 * 模块划分：
 *   - 工具函数：DOM 选择器、转义、持久化偏好、Toast 提示；
 *   - 路由：基于 location.hash 的 SPA 路由（#/路径@锚点），支持前进/后退与刷新还原；
 *   - 视图：侧边导航树（多级可折叠）、正文渲染、右侧「本页目录」、面包屑与元信息；
 *   - 搜索：搜索框 + 结果下拉（键盘可操作）；
 *   - 数据源管理：HTTP 服务器 / 文件系统 API / 兼容模式导入 / 缓存清理；
 *   - 响应式：移动端抽屉式侧边栏。
 */
(function (global) {
  'use strict';

  var MD = global.WikiMarkdown;
  var WikiData = global.WikiData;
  var WikiSearch = global.WikiSearch;

  var PREF_KEY = 'gudao.wiki.prefs.v1'; // 界面偏好键（主题等）

  /* ============================== 工具函数 ============================== */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /** 创建元素：el('div', {class:'x'}, [子元素或字符串]) */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'text') node.textContent = attrs[k];
        else if (k.indexOf('on') === 0 && typeof attrs[k] === 'function') node.addEventListener(k.slice(2), attrs[k]);
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  /** 读取界面偏好（目前只有主题需要持久化） */
  function loadPrefs() {
    try {
      var saved = JSON.parse(localStorage.getItem(PREF_KEY)) || {};
      if (!saved.theme) saved.theme = 'auto';
      // 侧边栏展开状态不再持久化：每次只展开当前页面所在路径，避免目录过长
      delete saved.collapsed;
      return saved;
    } catch (err) {
      return { theme: 'auto' };
    }
  }

  /** 保存界面偏好 */
  function savePrefs(prefs) {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch (err) { /* 忽略 */ }
  }

  /** 轻提示 */
  var toastTimer = null;
  function toast(message) {
    var box = $('#toast');
    box.textContent = message;
    box.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.classList.remove('show'); }, 2600);
  }

  /** 目录名格式化：'01-游戏概览' -> '01 游戏概览' */
  function formatGroupName(name) {
    return name.replace(/^(\d+)[-_]/, '$1 ');
  }

  /** 时间戳格式化 */
  function formatTime(ts) {
    if (!ts) return '未知';
    var d = new Date(ts);
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /* ============================== 应用主体 ============================== */

  var App = {
    prefs: loadPrefs(),
    currentPath: '',      // 当前页面路径
    tocTimer: null,       // 页内目录滚动监听节流

    /* ------------------------------ 启动 ------------------------------ */

    init: function () {
      this.applyTheme(this.prefs.theme || 'auto');
      this.bindGlobalEvents();
      this.renderShellStats();

      var self = this;
      // 加载进度反馈（HTTP 模式下逐文件显示进度）
      WikiData.onProgress = function (done, total) {
        var box = $('#page-content .loading');
        if (box) box.textContent = '正在加载 Wiki 内容（' + done + ' / ' + total + '）…';
      };
      WikiData.init().then(function (hasContent) {
        self.afterContent(hasContent);
      });
    },

    /** 内容就绪（或缺失）后的统一处理 */
    afterContent: function (hasContent) {
      WikiSearch.build(WikiData.files);
      this.renderSidebar();
      this.renderShellStats();
      if (hasContent) {
        this.route();
      } else {
        this.showOnboarding();
      }
    },

    /** 重新加载内容后的刷新流程 */
    reloadContent: function () {
      WikiSearch.build(WikiData.files);
      this.renderSidebar();
      this.renderShellStats();
      this.route();
    },

    /* ------------------------------ 路由 ------------------------------ */

    /** 解析 hash：#/路径@锚点 */
    parseHash: function () {
      var hash = location.hash || '';
      if (hash.indexOf('#/') !== 0) return null;
      var body = hash.slice(2);
      var anchorIndex = body.indexOf('@');
      var path = anchorIndex >= 0 ? body.slice(0, anchorIndex) : body;
      var anchor = anchorIndex >= 0 ? body.slice(anchorIndex + 1) : '';
      try { path = decodeURI(path); } catch (err) { /* 保持原样 */ }
      return { path: path, anchor: anchor };
    },

    /** 跳转到指定页面 */
    navigate: function (path, anchor) {
      var target = '#/' + encodeURI(path) + (anchor ? '@' + anchor : '');
      if (location.hash === target) {
        this.renderPage(path, anchor); // 相同地址时手动触发一次渲染
      } else {
        location.hash = target;
      }
    },

    /** 按当前 hash 渲染 */
    route: function () {
      var parsed = this.parseHash();
      if (!parsed || !parsed.path) {
        // 默认进入首页（README）
        var home = WikiData.getPage('README.md') || WikiData.listPages()[0];
        if (home) this.navigate(home.path);
        else this.showOnboarding();
        return;
      }
      this.renderPage(parsed.path, parsed.anchor);
    },

    /* ------------------------------ 页面渲染 ------------------------------ */

    renderPage: function (path, anchor) {
      var page = WikiData.getPage(path);
      if (!page) {
        this.renderNotFound(path);
        return;
      }
      this.currentPath = path;
      var self = this;

      // 1. 元信息区（全路径面包屑：支持多级目录）
      var metaBar = $('#page-meta');
      metaBar.innerHTML = '';
      var crumbNodes = [
        el('a', { href: 'javascript:void(0)', class: 'crumb-home', text: '首页',
                  onclick: function () { self.navigate('README.md'); } })
      ];
      var segs = path.split('/');
      segs.forEach(function (seg, idx) {
        crumbNodes.push(el('span', { class: 'crumb-sep', text: '›' }));
        if (idx < segs.length - 1) {
          var dirPath = segs.slice(0, idx + 1).join('/');
          var hub = self.hubForDir(dirPath);
          if (hub) {
            var link = el('a', { class: 'crumb-dir', href: '#/' + encodeURI(hub), text: formatGroupName(seg),
                                 'data-link': hub });
            crumbNodes.push(link);
          } else {
            crumbNodes.push(el('span', { class: 'crumb-dir', text: formatGroupName(seg) }));
          }
        } else {
          crumbNodes.push(el('span', { class: 'crumb-current', text: page.title }));
        }
      });
      metaBar.appendChild(el('div', { class: 'breadcrumb' }, crumbNodes));

      var chips = el('div', { class: 'meta-chips' });
      if (page.meta && page.meta['分类']) {
        chips.appendChild(el('span', { class: 'chip chip-cat', text: '分类：' + page.meta['分类'] }));
      }
      if (page.meta && Array.isArray(page.meta['标签'])) {
        page.meta['标签'].slice(0, 8).forEach(function (tag) {
          chips.appendChild(el('span', { class: 'chip', text: tag }));
        });
      }
      if (page.meta && page.meta['更新日期']) {
        chips.appendChild(el('span', { class: 'chip chip-date', text: '更新：' + page.meta['更新日期'] }));
      }
      metaBar.appendChild(chips);

      // 2. 标题
      var titleEl = $('#page-title');
      titleEl.textContent = page.title;

      // 3. 正文：Markdown -> HTML
      var html = MD.render(page.md, {
        fromPath: path,
        resolveLink: function (from, target) { return WikiData.resolveLink(from, target); }
      });
      var content = $('#page-content');
      content.innerHTML = html;
      this.decorateCodeBlocks(content);

      // 首页模式：门户式布局（隐藏页面标题与右侧目录，交由 hero 区承担）
      var isHome = path === 'README.md' || (page.meta && page.meta['页面类型'] === '首页');
      document.body.classList.toggle('home-mode', !!isHome);

      // 4. 目录：桌面用右侧目录，窄屏用正文顶部「置顶目录」
      this.renderToc(page, isHome);
      this.renderInlineToc(page, isHome);

      // 5. 侧边栏：只展开当前页面所在路径（其余收起），高亮当前项，移动端收起抽屉
      this.syncSidebarExpansion();
      this.setActiveNav(path);
      $('#sidebar').classList.remove('open');
      $('#overlay').classList.remove('show');

      // 6. 文档标题与滚动位置
      document.title = page.title + ' · 荒野日记：孤岛 Wiki';
      if (anchor) {
        var target = document.getElementById(anchor);
        if (target) {
          setTimeout(function () { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 30);
        }
      } else {
        window.scrollTo({ top: 0, behavior: 'auto' });
      }
    },

    /** 404 页面 */
    renderNotFound: function (path) {
      $('#page-meta').innerHTML = '';
      $('#page-title').textContent = '页面不存在';
      document.title = '页面不存在 · 荒野日记：孤岛 Wiki';
      $('#page-content').innerHTML = '';
      var box = el('div', { class: 'empty-panel' });
      box.appendChild(el('p', { text: '未找到页面：' + path }));
      box.appendChild(el('p', { text: '可能是链接指向了尚未收录的页面，或内容缓存已过期。' }));
      var btn = el('button', { class: 'btn primary', text: '返回首页' });
      btn.addEventListener('click', function () { App.navigate('README.md'); });
      box.appendChild(btn);
      $('#page-content').appendChild(box);
      $('#toc').innerHTML = '';
      this.setActiveNav('');
      window.scrollTo({ top: 0, behavior: 'auto' });
    },

    /** 为代码块添加「复制」按钮 */
    decorateCodeBlocks: function (root) {
      $all('pre.code-block', root).forEach(function (pre) {
        if (pre.querySelector('.code-copy')) return;
        var btn = el('button', { class: 'code-copy', type: 'button', text: '复制' });
        btn.addEventListener('click', function () {
          var code = pre.querySelector('code');
          var text = code ? code.textContent : '';
          var finish = function () {
            btn.textContent = '已复制';
            setTimeout(function () { btn.textContent = '复制'; }, 1500);
          };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(finish, function () { toast('复制失败'); });
          } else {
            // 兼容回退：临时 textarea + execCommand
            var ta = el('textarea', { class: 'clip-fallback' });
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); finish(); } catch (err) { toast('复制失败'); }
            document.body.removeChild(ta);
          }
        });
        pre.appendChild(btn);
      });
    },

    /* ------------------------------ 侧边导航树 ------------------------------ */

    /**
     * 依据页面路径生成导航树：
     *   - 站点根目录下的页面（如 README.md）直接展示为「首页」；
     *   - 一级目录作为分组（可折叠），分组内按路径排序展示页面；
     *   - 支持任意层级目录（递归构建）。
     */
    renderSidebar: function () {
      var tree = $('#nav-tree');
      tree.innerHTML = '';
      var self = this;

      // 组装多级目录树：{ dirs: {name: node}, pages: [page] }
      var root = { dirs: {}, pages: [] };
      WikiData.listPages().forEach(function (p) {
        var segs = p.path.split('/');
        if (segs.length === 1) { root.pages.push(p); return; }
        var node = root;
        for (var i = 0; i < segs.length - 1; i++) {
          if (!node.dirs[segs[i]]) node.dirs[segs[i]] = { dirs: {}, pages: [] };
          node = node.dirs[segs[i]];
        }
        node.pages.push(p);
      });

      // 统计目录下的条目总数（用于角标）
      function countPages(node) {
        var n = node.pages.length;
        Object.keys(node.dirs).forEach(function (k) { n += countPages(node.dirs[k]); });
        return n;
      }

      // 递归渲染
      // 展开策略：只展开「当前页面所在路径」上的目录，其余一律收起，
      // 避免 03-物品 / 04-生物 这类大分类把侧边栏撑得过长。
      function renderNode(node, container, prefix, depth) {
        Object.keys(node.dirs).sort().forEach(function (name) {
          var dirPath = prefix ? prefix + '/' + name : name;
          var collapsed = !self.isInCurrentPath(dirPath);
          var group = el('div', { class: 'nav-node depth-' + depth, 'data-dir': dirPath });
          var toggle = el('button', {
            class: 'nav-group-toggle' + (collapsed ? ' collapsed' : ''),
            type: 'button', 'aria-expanded': String(!collapsed)
          });
          toggle.appendChild(el('span', { class: 'chev', text: '▾' }));
          toggle.appendChild(el('span', { class: 'nav-group-name', text: formatGroupName(name) }));
          toggle.appendChild(el('span', { class: 'nav-count', text: String(countPages(node.dirs[name])) }));
          var body = el('div', { class: 'nav-group-body' + (collapsed ? ' collapsed' : '') });
          toggle.addEventListener('click', function () {
            // 手动展开/收起只在当前页面内生效；切换页面时会重新按「只展开当前路径」同步
            self.setGroupCollapsed(group, !toggle.classList.contains('collapsed'));
          });
          group.appendChild(toggle);
          group.appendChild(body);
          container.appendChild(group);
          renderNode(node.dirs[name], body, dirPath, depth + 1);
        });
        node.pages.sort(function (a, b) { return a.path < b.path ? -1 : 1; });
        node.pages.forEach(function (p) {
          var link = el('a', { class: 'nav-item', 'data-link': p.path,
                               href: '#/' + encodeURI(p.path), title: p.title });
          link.appendChild(el('span', { class: 'nav-text', text: p.title }));
          container.appendChild(link);
        });
      }

      // 根级页面（首页）
      if (root.pages.length) {
        var homeBox = el('div', { class: 'nav-group nav-group-root' });
        root.pages.forEach(function (p) {
          var link = el('a', { class: 'nav-item nav-home', 'data-link': p.path, href: '#/' + encodeURI(p.path) });
          link.appendChild(el('span', { class: 'nav-icon', text: '◆' }));
          link.appendChild(el('span', { class: 'nav-text', text: p.path === 'README.md' ? '首页' : p.title }));
          homeBox.appendChild(link);
        });
        tree.appendChild(homeBox);
      }
      renderNode(root, tree, '', 0);
      this.setActiveNav(this.currentPath);
    },

    /** 判断某个目录是否位于当前页面所在路径上（含其自身） */
    isInCurrentPath: function (dirPath) {
      return this.currentPath.indexOf(dirPath + '/') === 0;
    },

    /** 设置某个目录分组的展开 / 收起状态 */
    setGroupCollapsed: function (group, collapsed) {
      var toggle = group.querySelector('.nav-group-toggle');
      var body = group.querySelector('.nav-group-body');
      if (!toggle || !body) return;
      toggle.classList.toggle('collapsed', collapsed);
      toggle.setAttribute('aria-expanded', String(!collapsed));
      body.classList.toggle('collapsed', collapsed);
    },

    /**
     * 同步侧边栏展开状态：只展开当前页面所在路径，其余自动收起。
     * 每次切换页面时调用，避免浏览过的分类把目录越撑越长。
     */
    syncSidebarExpansion: function () {
      var self = this;
      $all('#nav-tree .nav-node[data-dir]').forEach(function (group) {
        self.setGroupCollapsed(group, !self.isInCurrentPath(group.getAttribute('data-dir')));
      });
    },

    /** 查找某目录（支持任意层级）对应的枢纽页（*一览 / *总览） */
    hubForDir: function (dirPath) {
      var depth = dirPath.split('/').length;
      var best = null;
      WikiData.listPages().forEach(function (p) {
        var segs = p.path.split('/');
        if (segs.length === depth + 1 &&
            segs.slice(0, depth).join('/') === dirPath &&
            /(一览|总览)\.md$/.test(segs[depth])) {
          best = p.path;
        }
      });
      return best;
    },

    /** 渲染正文顶部的「置顶目录」（窄屏显示，桌面隐藏） */
    renderInlineToc: function (page, isHome) {
      var old = $('#inline-toc');
      if (old) old.remove();
      if (isHome) return;
      var headings = page.headings.filter(function (h) { return h.level === 2 || h.level === 3; });
      if (headings.length < 3) return; // 章节太少时不必展示
      var details = el('details', { class: 'toc-inline', id: 'inline-toc' });
      details.appendChild(el('summary', { text: '本页目录（点击快速定位）' }));
      var list = el('ul', { class: 'toc-inline-list' });
      headings.forEach(function (h) {
        var item = el('li', { class: 'level-' + h.level });
        var link = el('a', { href: 'javascript:void(0)', text: h.text });
        link.addEventListener('click', function (ev) {
          ev.preventDefault();
          App.scrollToHeading(h.id);
        });
        item.appendChild(link);
        list.appendChild(item);
      });
      details.appendChild(list);
      var article = $('.article');
      article.insertBefore(details, $('#page-content'));
    },

    /** 高亮当前页面所在的导航项（必要时滚动使其可见） */
    setActiveNav: function (path) {
      $all('#nav-tree .nav-item').forEach(function (item) {
        item.classList.toggle('active', item.getAttribute('data-link') === path);
      });
      this.revealActiveNav();
    },

    /** 当前项不在侧边栏可视区域内时，滚动到中间位置（已可见则不动） */
    revealActiveNav: function () {
      var tree = $('#nav-tree');
      if (!tree) return;
      var active = tree.querySelector('.nav-item.active');
      if (!active) return;
      var box = tree.getBoundingClientRect();
      var item = active.getBoundingClientRect();
      if (item.top >= box.top && item.bottom <= box.bottom) return;
      var top = tree.scrollTop + (item.top - box.top) - (box.height - item.height) / 2;
      tree.scrollTop = Math.max(0, top);
    },

    /* ------------------------------ 页内目录 ------------------------------ */

    /** 渲染右侧「本页目录」并绑定滚动高亮 */
    renderToc: function (page, isHome) {
      var toc = $('#toc');
      toc.innerHTML = '';
      if (this.tocTimer) { window.removeEventListener('scroll', this.tocTimer); this.tocTimer = null; }
      if (isHome) return;

      // 只展示 h2 / h3 级标题，避免目录过长
      var headings = page.headings.filter(function (h) { return h.level === 2 || h.level === 3; });
      if (!headings.length) return;

      toc.appendChild(el('div', { class: 'toc-title', text: '本页目录' }));
      var list = el('ul', { class: 'toc-list' });
      headings.forEach(function (h) {
        var item = el('li', { class: 'toc-item level-' + h.level });
        var link = el('a', { href: '#/' + encodeURI(page.path) + '@' + h.id, text: h.text, 'data-anchor': h.id });
        link.addEventListener('click', function (ev) {
          ev.preventDefault();
          App.scrollToHeading(h.id);
          history.replaceState(null, '', '#/' + encodeURI(page.path) + '@' + h.id);
        });
        item.appendChild(link);
        list.appendChild(item);
      });
      toc.appendChild(list);

      // 滚动高亮：取「已滚过视口顶部」的最后一个标题
      var self = this;
      var ticking = false;
      this.tocTimer = function () {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () {
          ticking = false;
          self.updateTocActive(page, headings);
        });
      };
      window.addEventListener('scroll', this.tocTimer, { passive: true });
      this.updateTocActive(page, headings);
    },

    /** 滚动到指定标题 */
    scrollToHeading: function (id) {
      var target = document.getElementById(id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },

    /** 更新页内目录的高亮项 */
    updateTocActive: function (page, headings) {
      var threshold = 96; // 顶部固定栏高度的偏移
      var currentId = '';
      headings.forEach(function (h) {
        var node = document.getElementById(h.id);
        if (node && node.getBoundingClientRect().top <= threshold) currentId = h.id;
      });
      $all('#toc .toc-item a').forEach(function (a) {
        a.classList.toggle('active', a.getAttribute('data-anchor') === currentId);
      });
    },

    /* ------------------------------ 搜索 ------------------------------ */

    /** 绑定搜索框交互（输入、键盘、点击结果） */
    bindSearch: function () {
      var input = $('#search-input');
      var panel = $('#search-results');
      var self = this;
      var results = [];
      var activeIndex = -1;
      var debounceTimer = null;

      function closePanel() {
        panel.classList.remove('show');
        panel.innerHTML = '';
        activeIndex = -1;
        results = [];
      }

      /** 高亮关键词（先转义再包裹 <mark>） */
      function highlight(text, tokens) {
        var escaped = MD.escapeHtml(text);
        tokens.forEach(function (token) {
          if (!token) return;
          var pattern = new RegExp('(' + token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
          escaped = escaped.replace(pattern, '<mark>$1</mark>');
        });
        return escaped;
      }

      function renderResults(list, keyword) {
        panel.innerHTML = '';
        if (!keyword.trim()) { closePanel(); return; }
        if (!list.length) {
          panel.appendChild(el('div', { class: 'search-empty', text: '未找到相关内容' }));
          panel.classList.add('show');
          return;
        }
        var head = el('div', { class: 'search-head', text: '共 ' + list.length + ' 条结果（↑↓ 选择，Enter 打开）' });
        panel.appendChild(head);
        list.forEach(function (r, idx) {
          var item = el('div', { class: 'search-item', 'data-index': idx });
          var top = el('div', { class: 'search-item-top' });
          top.innerHTML = '<span class="search-item-title">' + highlight(r.title, r.tokens) + '</span>' +
            '<span class="search-item-cat">' + MD.escapeHtml(formatGroupName(r.category)) + '</span>';
          item.appendChild(top);
          var snippet = el('div', { class: 'search-item-snippet' });
          snippet.innerHTML = highlight(r.snippet, r.tokens);
          item.appendChild(snippet);
          item.addEventListener('click', function () { self.navigate(r.path); closePanel(); input.blur(); });
          panel.appendChild(item);
        });
        panel.classList.add('show');
      }

      function setActive(idx) {
        var items = $all('.search-item', panel);
        items.forEach(function (it, i) { it.classList.toggle('active', i === idx); });
        if (items[idx]) items[idx].scrollIntoView({ block: 'nearest' });
        activeIndex = idx;
      }

      input.addEventListener('input', function () {
        clearTimeout(debounceTimer);
        var keyword = input.value;
        debounceTimer = setTimeout(function () {
          results = WikiSearch.query(keyword, 30);
          activeIndex = -1;
          renderResults(results, keyword);
        }, 140);
      });

      input.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowDown' && panel.classList.contains('show')) {
          ev.preventDefault();
          setActive(Math.min(activeIndex + 1, results.length - 1));
        } else if (ev.key === 'ArrowUp' && panel.classList.contains('show')) {
          ev.preventDefault();
          setActive(Math.max(activeIndex - 1, 0));
        } else if (ev.key === 'Enter') {
          if (activeIndex >= 0 && results[activeIndex]) {
            self.navigate(results[activeIndex].path);
            closePanel();
            input.blur();
          } else if (results.length) {
            self.navigate(results[0].path);
            closePanel();
            input.blur();
          }
        } else if (ev.key === 'Escape') {
          closePanel();
          input.blur();
        }
      });

      // 点击页面其他区域时关闭结果面板
      document.addEventListener('click', function (ev) {
        if (!panel.contains(ev.target) && ev.target !== input) closePanel();
      });
    },

    /* ------------------------------ 数据源与帮助 ------------------------------ */

    /** 显示「未加载内容」的引导面板 */
    showOnboarding: function () {
      $('#page-meta').innerHTML = '';
      $('#page-title').textContent = '欢迎使用 荒野日记：孤岛 Wiki';
      $('#toc').innerHTML = '';
      var box = $('#page-content');
      box.innerHTML = '';

      var wrap = el('div', { class: 'onboarding' });
      wrap.appendChild(el('p', { class: 'lead', text: '尚未加载 Wiki 内容。请选择以下任一方式加载本地 wiki 资料：' }));

      var cards = el('div', { class: 'onboarding-cards' });

      // 卡片 1：本地 HTTP 服务器（推荐）
      var card1 = el('div', { class: 'card' });
      card1.appendChild(el('h3', { text: '① 本地服务器（推荐）' }));
      card1.appendChild(el('p', { text: '在项目根目录执行命令后，通过 http 地址打开本页面，将自动读取 wiki/ 目录：' }));
      var code1 = el('pre', { class: 'code-block' });
      code1.innerHTML = '<code>python -m http.server 8000</code>';
      card1.appendChild(code1);
      card1.appendChild(el('p', { class: 'muted', text: '然后访问：http://localhost:8000/app/' }));
      cards.appendChild(card1);

      // 卡片 2：文件系统 API 导入
      var card2 = el('div', { class: 'card' });
      card2.appendChild(el('h3', { text: '② 选择文件夹导入' }));
      if (typeof global.showDirectoryPicker === 'function') {
        card2.appendChild(el('p', { text: '点击下方按钮选择 wiki 文件夹；内容会缓存到本地，之后可直接离线打开（Chrome / Edge 推荐）。' }));
        var btn2 = el('button', { class: 'btn primary', text: '选择 wiki 文件夹' });
        btn2.addEventListener('click', function () { App.pickDirectoryFlow(); });
        card2.appendChild(btn2);
      } else {
        card2.appendChild(el('p', { text: '当前浏览器不支持文件系统 API，请使用方式 ① 或 ③。' }));
      }
      cards.appendChild(card2);

      // 卡片 3：兼容模式导入
      var card3 = el('div', { class: 'card' });
      card3.appendChild(el('h3', { text: '③ 文件夹导入（兼容模式）' }));
      card3.appendChild(el('p', { text: '适用于所有现代浏览器的回退方案：选择 wiki 文件夹即可（同样会写入本地缓存）。' }));
      var picker = el('input', { type: 'file', webkitdirectory: '', multiple: '', class: 'hidden-input' });
      picker.addEventListener('change', function () {
        if (!picker.files || !picker.files.length) return;
        WikiData.loadFromFileList(picker.files).then(function () {
          toast('内容加载完成（' + WikiData.stats().pages + ' 页）');
          App.reloadContent();
        }).catch(function (err) {
          toast('导入失败：' + err.message);
        });
      });
      var btn3 = el('button', { class: 'btn', text: '选择文件夹（兼容模式）' });
      btn3.addEventListener('click', function () { picker.click(); });
      card3.appendChild(btn3);
      card3.appendChild(picker);
      cards.appendChild(card3);

      wrap.appendChild(cards);
      box.appendChild(wrap);
    },

    /** FS API 选择目录的统一流程 */
    pickDirectoryFlow: function () {
      WikiData.pickDirectory().then(function () {
        toast('内容加载完成（' + WikiData.stats().pages + ' 页）');
        App.reloadContent();
      }).catch(function (err) {
        if (err && err.name === 'AbortError') return; // 用户取消选择
        toast('导入失败：' + err.message);
      });
    },

    /** 刷新/同步内容 */
    syncContent: function () {
      var self = this;
      if (WikiData.hasDirectoryHandle()) {
        WikiData.refreshDirectory().then(function () {
          toast('已从文件夹同步最新内容');
          self.reloadContent();
        }).catch(function (err) { toast('同步失败：' + err.message); });
      } else if (location.protocol === 'http:' || location.protocol === 'https:') {
        WikiData.loadFromHttp().then(function () {
          toast('已重新从服务器加载内容');
          self.reloadContent();
        }).catch(function (err) { toast('加载失败：' + err.message); });
      } else {
        this.pickDirectoryFlow();
      }
    },

    /** 更新底部/帮助中的统计信息 */
    renderShellStats: function () {
      var stats = WikiData.stats();
      var text = stats.pages
        ? stats.pages + ' 个页面 · 内容来源：' + stats.source + ' · 缓存时间：' + formatTime(stats.savedAt)
        : '尚未加载内容';
      $('#footer-stats').textContent = text;
      var helpStats = $('#help-stats');
      if (helpStats) helpStats.textContent = text;
    },

    /** 打开帮助弹层 */
    openHelp: function () {
      this.renderShellStats();
      $('#help-modal').classList.add('show');
    },

    /* ------------------------------ 主题 ------------------------------ */

    /** 应用主题：auto / light / dark */
    applyTheme: function (theme) {
      this.prefs.theme = theme;
      savePrefs(this.prefs);
      if (theme === 'auto') {
        document.documentElement.removeAttribute('data-theme');
      } else {
        document.documentElement.setAttribute('data-theme', theme);
      }
      var btn = $('#theme-toggle');
      if (btn) {
        btn.textContent = theme === 'auto' ? '跟随系统' : (theme === 'light' ? '浅色' : '深色');
      }
    },

    /** 循环切换主题 */
    cycleTheme: function () {
      var order = ['auto', 'light', 'dark'];
      var next = order[(order.indexOf(this.prefs.theme || 'auto') + 1) % order.length];
      this.applyTheme(next);
      toast('主题：' + (next === 'auto' ? '跟随系统' : next === 'light' ? '浅色' : '深色'));
    },

    /* ------------------------------ 全局事件 ------------------------------ */

    bindGlobalEvents: function () {
      var self = this;

      // 路由：hash 变化
      window.addEventListener('hashchange', function () { self.route(); });

      // 站内链接点击（正文中的 .md 链接）
      document.addEventListener('click', function (ev) {
        var link = ev.target.closest ? ev.target.closest('a.int-link') : null;
        if (link) {
          ev.preventDefault();
          var path = link.getAttribute('data-link');
          var anchor = link.getAttribute('data-anchor') || '';
          self.navigate(path, anchor);
          return;
        }
        // 标题锚点「复制本段链接」
        var copyBtn = ev.target.closest ? ev.target.closest('[data-anchor-copy]') : null;
        if (copyBtn) {
          ev.preventDefault();
          var anchorId = copyBtn.getAttribute('data-anchor-copy');
          var url = location.href.split('#')[0] + '#/' + encodeURI(self.currentPath) + (anchorId ? '@' + anchorId : '');
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function () {
              toast('已复制本段链接');
            }).catch(function () {
              // 剪贴板不可用（无焦点 / 无权限）时给出降级提示
              console.info('[WikiApp] 剪贴板不可用，段落链接：', url);
              toast('复制失败，链接已输出到控制台');
            });
          } else {
            toast('链接：' + url);
          }
        }
      });

      // 顶栏按钮
      $('#theme-toggle').addEventListener('click', function () { self.cycleTheme(); });
      $('#help-btn').addEventListener('click', function () { self.openHelp(); });
      $('#sync-btn').addEventListener('click', function () { self.syncContent(); });
      $('#menu-btn').addEventListener('click', function () {
        $('#sidebar').classList.toggle('open');
        $('#overlay').classList.toggle('show');
      });
      $('#overlay').addEventListener('click', function () {
        $('#sidebar').classList.remove('open');
        $('#overlay').classList.remove('show');
      });
      $all('[data-close-modal]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          btn.closest('.modal').classList.remove('show');
        });
      });
      $('#clear-cache-btn').addEventListener('click', function () {
        WikiData.clearCache();
        toast('已清除本地内容缓存（刷新页面后生效）');
      });

      // 键盘快捷键：Ctrl/Cmd + K 聚焦搜索；Esc 关闭弹层
      document.addEventListener('keydown', function (ev) {
        if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
          ev.preventDefault();
          $('#search-input').focus();
          $('#search-input').select();
        } else if (ev.key === 'Escape') {
          $all('.modal.show').forEach(function (m) { m.classList.remove('show'); });
        }
      });

      this.bindSearch();
    }
  };

  /* ============================== 引导启动 ============================== */

  document.addEventListener('DOMContentLoaded', function () {
    App.init();
  });

  global.WikiApp = App;
})(window);