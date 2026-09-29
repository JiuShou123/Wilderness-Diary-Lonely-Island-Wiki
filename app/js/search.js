/**
 * search.js —— 全文检索模块（纯前端、无需分词库）
 *
 * 实现思路：
 *   - 加载完成后为全部页面建立轻量索引：标题 / 分类 / 小节标题 / 正文纯文本（小写化）；
 *   - 查询按空白切分为若干关键词（多关键词为「与」关系，任一命中即可参与排序）；
 *   - 打分规则：标题完全匹配 > 标题包含 > 小节标题包含 > 正文出现次数（封顶）；
 *   - 结果附带上下文摘要（snippet），并返回命中关键词用于高亮展示。
 *
 * 对外接口（挂载在 window.WikiSearch）：
 *   build(pages)          -> void 建立索引
 *   query(keyword, limit) -> [{ path, title, category, score, snippet, tokens }]
 */
(function (global) {
  'use strict';

  var TOKEN_MAX = 5;        // 单次查询最多参与的关键词数量
  var SNIPPET_PREFIX = 42;  // 摘要中命中词前的字符数
  var SNIPPET_SUFFIX = 78;  // 摘要中命中词后的字符数
  var BODY_HIT_CAP = 12;    // 正文命中计分封顶（防止长页面刷分）

  var WikiSearch = {
    pages: [],   // 索引：{ path, title, category, headings, text, titleLower, textLower }

    /**
     * 建立索引
     * @param {Array} pages WikiData 中的页面对象数组
     */
    build: function (pages) {
      this.pages = pages.map(function (p) {
        return {
          path: p.path,
          title: p.title || '',
          category: p.category || '',
          headings: (p.headings || []).map(function (h) { return h.text; }),
          text: p.text || '',
          titleLower: (p.title || '').toLowerCase(),
          textLower: (p.text || '').toLowerCase()
        };
      });
    },

    /** 统计子串出现次数（限制上限，避免长文本耗时） */
    _countOccurrences: function (haystack, needle, cap) {
      var count = 0;
      var idx = 0;
      while (count < cap) {
        idx = haystack.indexOf(needle, idx);
        if (idx === -1) break;
        count++;
        idx += needle.length;
      }
      return count;
    },

    /** 生成命中摘要 */
    _makeSnippet: function (page, tokens) {
      var source = page.text || '';
      var lower = page.textLower || '';
      var hitIndex = -1;
      var hitToken = '';
      // 优先用最长关键词定位，摘要更贴近意图
      var sorted = tokens.slice().sort(function (a, b) { return b.length - a.length; });
      for (var i = 0; i < sorted.length; i++) {
        var idx = lower.indexOf(sorted[i]);
        if (idx !== -1) { hitIndex = idx; hitToken = sorted[i]; break; }
      }
      if (hitIndex === -1) {
        // 仅标题/小节命中：截取正文开头作为摘要
        return source.slice(0, SNIPPET_PREFIX + SNIPPET_SUFFIX) + (source.length > SNIPPET_PREFIX + SNIPPET_SUFFIX ? '…' : '');
      }
      var start = Math.max(0, hitIndex - SNIPPET_PREFIX);
      var end = Math.min(source.length, hitIndex + hitToken.length + SNIPPET_SUFFIX);
      return (start > 0 ? '…' : '') + source.slice(start, end) + (end < source.length ? '…' : '');
    },

    /**
     * 执行查询
     * @param {string} keyword 查询词（空格分隔多个关键词）
     * @param {number} limit   最多返回条数（默认 40）
     */
    query: function (keyword, limit) {
      var q = String(keyword || '').trim();
      if (!q) return [];
      var max = limit || 40;
      var tokens = q.toLowerCase().split(/\s+/).filter(function (s) { return s.length > 0; }).slice(0, TOKEN_MAX);
      if (!tokens.length) return [];

      var results = [];
      this.pages.forEach(function (page) {
        var score = 0;
        var matchedTokens = [];
        var bodyHits = 0;

        tokens.forEach(function (token) {
          var hit = false;
          if (page.titleLower === token) { score += 200; hit = true; }
          else if (page.titleLower.indexOf(token) !== -1) { score += 100; hit = true; }

          var headingHit = false;
          for (var h = 0; h < page.headings.length; h++) {
            if (page.headings[h].toLowerCase().indexOf(token) !== -1) { headingHit = true; break; }
          }
          if (headingHit) { score += 40; hit = true; }

          var occurrences = WikiSearch._countOccurrences(page.textLower, token, BODY_HIT_CAP);
          if (occurrences > 0) {
            bodyHits += occurrences;
            score += Math.min(occurrences, BODY_HIT_CAP) * 3;
            hit = true;
          }
          if (hit) matchedTokens.push(token);
        });

        if (!matchedTokens.length) return; // 一个关键词都未命中则跳过

        // 命中关键词越多排序越靠前
        score += matchedTokens.length * 15;
        // 标题命中多个关键词额外加成
        if (matchedTokens.length === tokens.length && tokens.length > 1) score += 30;

        results.push({
          path: page.path,
          title: page.title,
          category: page.category,
          score: score,
          bodyHits: bodyHits,
          snippet: WikiSearch._makeSnippet(page, matchedTokens),
          tokens: matchedTokens
        });
      });

      results.sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        return a.title.localeCompare(b.title, 'zh-Hans-CN');
      });
      return results.slice(0, max);
    }
  };

  global.WikiSearch = WikiSearch;
})(window);