/**
 * data.js —— 数据层：负责 Wiki 内容的获取、解析缓存与索引数据准备
 *
 * 内容来源（按可用性依次尝试）：
 *   1. HTTP 本地服务器（推荐）：读取 wiki/manifest.json + 各 .md 文件；
 *   2. 文件系统 API（File System Access API）：用户选择 wiki 文件夹后直接读取，
 *      目录句柄保存在 IndexedDB 中，下次访问可一键恢复授权；
 *   3. 文件夹选择回退方案（<input webkitdirectory>）：兼容不支持 FS API 的浏览器；
 *   4. localStorage 缓存：以上任一方式加载成功后都会缓存内容，之后可完全离线秒开。
 *
 * 对外接口（挂载在 window.WikiData）：
 *   init()                        -> Promise<boolean> 是否已有可用内容
 *   loadFromHttp()                -> Promise<void>
 *   pickDirectory()               -> Promise<void>  （FS API 选择目录）
 *   restoreDirectory()            -> Promise<boolean>（恢复上次目录授权）
 *   loadFromFileList(fileList)    -> Promise<void>  （webkitdirectory 回退）
 *   resolveLink(fromPath, target) -> string 解析站内相对链接
 *   getPage(path) / listPages() / stats()
 */
(function (global) {
  'use strict';

  /* ============================== 常量与工具 ============================== */

  var CACHE_KEY = 'gudao.wiki.cache.v1';   // 内容缓存键（localStorage）
  var IDB_NAME = 'gudao-wiki';             // IndexedDB 数据库名（保存目录句柄）
  var IDB_STORE = 'handles';
  var HANDLE_KEY = 'wiki-dir-handle';
  var MD = global.WikiMarkdown;

  /** 是否支持 File System Access API */
  function supportsFSApi() {
    return typeof global.showDirectoryPicker === 'function';
  }

  /* ------------------------- IndexedDB 极简封装 ------------------------- */

  function openIDB() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(IDB_NAME, 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains(IDB_STORE)) {
          req.result.createObjectStore(IDB_STORE);
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function idbPut(key, value) {
    return openIDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(IDB_STORE, 'readwrite');
        tx.objectStore(IDB_STORE).put(value, key);
        tx.oncomplete = resolve;
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function idbGet(key) {
    return openIDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(IDB_STORE, 'readonly');
        var req = tx.objectStore(IDB_STORE).get(key);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    }).catch(function () { return undefined; });
  }

  /* ============================== 数据模块 ============================== */

  /** 并发池：以 limit 为上限并行执行 worker(items[i])，返回结果数组 */
  function pool(items, limit, worker) {
    return new Promise(function (resolve, reject) {
      var results = new Array(items.length);
      var next = 0;
      var active = 0;
      var finished = 0;
      var failed = false;

      function launch() {
        if (failed) return;
        if (finished === items.length) { resolve(results); return; }
        while (active < limit && next < items.length) {
          (function (idx) {
            active++;
            worker(items[idx], idx).then(function (r) {
              results[idx] = r;
              active--; finished++;
              if (finished === items.length) resolve(results);
              else launch();
            }).catch(function (err) {
              failed = true;
              reject(err);
            });
          })(next++);
        }
      }
      if (!items.length) resolve(results);
      else launch();
    });
  }

  var WikiData = {
    files: [],        // 页面对象数组：{ path, title, category, md, headings, text }
    source: '',       // 'http' | 'fs' | 'dir-input' | 'cache'
    sourceLabel: '',  // 展示用来源描述
    savedAt: 0,       // 缓存写入时间（时间戳）
    cacheFailed: false, // 缓存写入失败标记（配额不足等）
    dirHandle: null,  // 当前目录句柄（会话内）
    onProgress: null, // 加载进度回调：(done, total) => void

    /* ---------------------------- 初始化 ---------------------------- */

    /**
     * 初始化：
     *   ① 先读 localStorage 缓存实现「秒开」；
     *   ② 若经由 http(s) 访问，再静默尝试在线加载最新内容；
     * 返回是否已有可用内容（缓存或在线）。
     */
    init: function () {
      var self = this;
      var cache = this._readCache();
      if (cache && cache.files && cache.files.length) {
        this._applyFiles(cache.files, 'cache', cache.savedAt);
      }

      var httpReady = location.protocol === 'http:' || location.protocol === 'https:';
      if (!httpReady) {
        return Promise.resolve(!!this.files.length);
      }
      return this.loadFromHttp()
        .then(function () { return true; })
        .catch(function (err) {
          console.warn('[WikiData] HTTP 加载失败（将使用缓存或等待手动导入）：', err);
          return !!self.files.length;
        });
    },

    /* ------------------------- 方式一：HTTP 加载 ------------------------- */

    /** 通过本地 HTTP 服务器加载：读取 manifest.json 后并发（限流）请求全部 .md 文件 */
    loadFromHttp: function () {
      var self = this;
      var candidates = ['../wiki/manifest.json', 'wiki/manifest.json', 'manifest.json'];
      return this._tryFetchManifest(candidates, 0).then(function (found) {
        var manifest = found.manifest;
        var baseUrl = found.baseUrl; // wiki/ 目录的 URL 前缀
        var total = manifest.files.length;
        var done = 0;
        return pool(manifest.files, 12, function (f) {
          var url = baseUrl + f.path.split('/').map(encodeURIComponent).join('/');
          return fetch(url).then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status + '：' + url);
            return res.text();
          }).then(function (md) {
            done++;
            if (self.onProgress) self.onProgress(done, total);
            return { path: f.path, md: md };
          });
        });
      }).then(function (rawFiles) {
        self._applyFiles(rawFiles, 'http', Date.now());
        self._saveCache(rawFiles);
      });
    },

    /** 依次尝试候选清单地址 */
    _tryFetchManifest: function (candidates, index) {
      var url = candidates[index];
      if (!url) {
        return Promise.reject(new Error('未找到 manifest.json，请先运行 app/tools/build_manifest.py 或改用导入文件夹方式'));
      }
      return fetch(url, { cache: 'no-store' }).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      }).then(function (manifest) {
        if (!manifest || !Array.isArray(manifest.files)) throw new Error('manifest 格式不正确');
        return { manifest: manifest, baseUrl: new URL('.', new URL(url, location.href)).href };
      }).catch(function () {
        return this._tryFetchManifest(candidates, index + 1);
      }.bind(this));
    },

    /* --------------------- 方式二：文件系统 API 读取 --------------------- */

    /** 弹出目录选择器并读取其中的全部 Markdown 文件 */
    pickDirectory: function () {
      var self = this;
      if (!supportsFSApi()) {
        return Promise.reject(new Error('当前浏览器不支持文件系统 API，请使用「选择文件夹（兼容模式）」或本地服务器方式'));
      }
      return global.showDirectoryPicker({ id: 'gudao-wiki', mode: 'read' })
        .then(function (handle) {
          self.dirHandle = handle;
          // 目录句柄持久化（下次可一键恢复）
          return idbPut(HANDLE_KEY, handle).catch(function () { /* 忽略持久化失败 */ })
            .then(function () { return self._readDirectoryHandle(handle); });
        })
        .then(function (rawFiles) {
          self._applyFiles(rawFiles, 'fs', Date.now());
          self._saveCache(rawFiles);
        });
    },

    /** 恢复上次选择的目录（若权限仍在，直接重读；否则由界面引导用户重新授权） */
    restoreDirectory: function () {
      var self = this;
      return idbGet(HANDLE_KEY).then(function (handle) {
        if (!handle) return false;
        return handle.queryPermission({ mode: 'read' }).then(function (state) {
          var need = state !== 'granted'
            ? handle.requestPermission({ mode: 'read' })
            : Promise.resolve('granted');
          return need.then(function (result) {
            if (result !== 'granted') return false;
            self.dirHandle = handle;
            return self._readDirectoryHandle(handle).then(function (rawFiles) {
              self._applyFiles(rawFiles, 'fs', Date.now());
              self._saveCache(rawFiles);
              return true;
            });
          });
        });
      }).catch(function (err) {
        console.warn('[WikiData] 恢复目录失败：', err);
        return false;
      });
    },

    /** 重新扫描当前目录（用于内容更新后的「同步」操作） */
    refreshDirectory: function () {
      var self = this;
      if (!this.dirHandle) return Promise.reject(new Error('尚未选择目录'));
      return this._readDirectoryHandle(this.dirHandle).then(function (rawFiles) {
        self._applyFiles(rawFiles, 'fs', Date.now());
        self._saveCache(rawFiles);
      });
    },

    /** 是否会话内存在可刷新的目录句柄 */
    hasDirectoryHandle: function () { return !!this.dirHandle; },

    /** 递归读取目录句柄中的 .md 文件 */
    _readDirectoryHandle: function (dirHandle) {
      var rawFiles = [];
      function scan(handle, prefix) {
        var iterator = handle.entries();
        var chain = Promise.resolve();
        var step = function (next) {
          if (next.done) return Promise.resolve();
          var name = next.value[0];
          var entry = next.value[1];
          var path = prefix ? prefix + '/' + name : name;
          var p;
          if (entry.kind === 'directory') {
            p = scan(entry, path);
          } else if (name.toLowerCase().endsWith('.md')) {
            p = entry.getFile().then(function (file) {
              return file.text().then(function (md) { rawFiles.push({ path: path, md: md }); });
            });
          } else {
            p = Promise.resolve();
          }
          return p.then(function () { return iterator.next().then(step); });
        };
        return iterator.next().then(step);
      }
      return scan(dirHandle, '').then(function () {
        return WikiData._normalizePaths(rawFiles);
      });
    },

    /* ------------------ 方式三：文件夹选择回退（兼容模式） ------------------ */

    /**
     * 处理 <input type="file" webkitdirectory> 选择结果
     * @param {FileList} fileList 用户选择的文件列表
     */
    loadFromFileList: function (fileList) {
      var self = this;
      var tasks = [];
      Array.prototype.forEach.call(fileList, function (file) {
        if (!file.name.toLowerCase().endsWith('.md')) return;
        // webkitRelativePath 形如 "wiki/02-核心机制/地图与关卡.md"
        var rel = (file.webkitRelativePath || file.name).replace(/\\/g, '/');
        tasks.push(file.text().then(function (md) { return { path: rel, md: md }; }));
      });
      if (!tasks.length) {
        return Promise.reject(new Error('所选文件夹中没有 Markdown 文件'));
      }
      return Promise.all(tasks).then(function (rawFiles) {
        rawFiles = self._normalizePaths(rawFiles);
        self._applyFiles(rawFiles, 'dir-input', Date.now());
        self._saveCache(rawFiles);
      });
    },

    /* ---------------------------- 路径处理 ---------------------------- */

    /**
     * 规范化路径：当用户选择的是 wiki 的「上级目录」或「同名文件夹」时，
     * 剥离多余的顶层目录，保证页面路径相对 wiki 根。
     */
    _normalizePaths: function (rawFiles) {
      if (!rawFiles.length) return rawFiles;
      var firstSegs = {};
      rawFiles.forEach(function (f) {
        var seg = f.path.split('/')[0];
        firstSegs[seg] = true;
      });
      var segs = Object.keys(firstSegs);
      // 仅当所有文件都在同一个顶层目录之内时，剥离该目录
      if (segs.length === 1 && rawFiles.every(function (f) { return f.path.indexOf('/') !== -1; })) {
        rawFiles = rawFiles.map(function (f) {
          return { path: f.path.split('/').slice(1).join('/'), md: f.md };
        });
      }
      return rawFiles.sort(function (a, b) { return a.path < b.path ? -1 : 1; });
    },

    /**
     * 解析站内相对链接
     * @param {string} fromPath 当前页面路径（如 "04-攻略指南/逃离方式.md"）
     * @param {string} target   链接目标（如 "../02-核心机制/进阶技巧.md"）
     * @returns {string} 规范化后的页面路径
     */
    resolveLink: function (fromPath, target) {
      var baseDir = fromPath.split('/').slice(0, -1); // 当前页面所在目录
      var parts = target.replace(/\\/g, '/').split('/');
      var stack = baseDir.slice();
      parts.forEach(function (seg) {
        if (!seg || seg === '.') return;
        if (seg === '..') stack.pop();
        else stack.push(seg);
      });
      return stack.join('/');
    },

    /* ---------------------------- 数据装配 ---------------------------- */

    /**
     * 将原始文件数组装配为页面对象数组（计算标题、目录、检索文本等派生数据）
     * @param {Array} rawFiles [{ path, md }]
     * @param {string} source  来源标记
     * @param {number} savedAt 时间戳
     */
    _applyFiles: function (rawFiles, source, savedAt) {
      this.files = rawFiles.map(function (f) {
        var parsed = MD.parseFrontMatter(f.md);
        var meta = parsed.meta || {};
        var title = meta.title || '';
        if (!title) {
          var h1 = /^#\s+(.+)$/m.exec(parsed.body);
          title = h1 ? h1[1].trim() : f.path.replace(/\.md$/i, '').split('/').pop();
        }
        var segs = f.path.split('/');
        var category = segs.length > 1 ? segs[0] : '首页';
        return {
          path: f.path,
          title: title,
          category: category,
          md: f.md,
          meta: meta,
          headings: MD.extractHeadings(f.md),
          text: MD.toPlainText(f.md)
        };
      });
      this.files.sort(function (a, b) {
        if (a.path === 'README.md') return -1;
        if (b.path === 'README.md') return 1;
        return a.path < b.path ? -1 : 1;
      });
      this.source = source;
      this.savedAt = savedAt || 0;
      this.sourceLabel = {
        http: '本地服务器（wiki 目录）',
        fs: '文件系统（已选择文件夹）',
        'dir-input': '文件夹导入（兼容模式）',
        cache: '本地缓存（localStorage）'
      }[source] || source;
    },

    /* ---------------------------- 缓存读写 ---------------------------- */

    _saveCache: function (rawFiles) {
      try {
        var payload = JSON.stringify({
          version: 1,
          savedAt: Date.now(),
          files: rawFiles
        });
        localStorage.setItem(CACHE_KEY, payload);
        this.cacheFailed = false;
      } catch (err) {
        // 常见于隐私模式或配额不足：降级为仅当前会话可用
        this.cacheFailed = true;
        console.warn('[WikiData] 内容缓存失败（不影响本次使用）：', err);
      }
    },

    _readCache: function () {
      try {
        var raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return null;
        var data = JSON.parse(raw);
        if (!data || !Array.isArray(data.files) || !data.files.length) return null;
        return data;
      } catch (err) {
        console.warn('[WikiData] 读取缓存失败：', err);
        return null;
      }
    },

    /** 清除本地缓存（供「帮助 / 设置」中使用） */
    clearCache: function () {
      try { localStorage.removeItem(CACHE_KEY); } catch (err) { /* 忽略 */ }
    },

    /* ---------------------------- 查询接口 ---------------------------- */

    getPage: function (path) {
      for (var i = 0; i < this.files.length; i++) {
        if (this.files[i].path === path) return this.files[i];
      }
      return null;
    },

    listPages: function () { return this.files; },

    /** 站点统计信息 */
    stats: function () {
      var chars = 0;
      this.files.forEach(function (f) { chars += f.md.length; });
      return {
        pages: this.files.length,
        chars: chars,
        source: this.sourceLabel,
        savedAt: this.savedAt
      };
    }
  };

  global.WikiData = WikiData;
})(window);