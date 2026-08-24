/**
 * MyBooks Toolbox Bridge
 *
 * 由核心 App 随构建发布，工具前端在自己的 `index.html` 里通过
 * `<script src="/static/toolbox-bridge.js"></script>` 引用，运行时得到
 * `window.MyBooksToolBridge`。
 *
 * 设计见 document/Toolbox_Dynamic_Design.md 4.3 节。这是"运行时实现"，跑在真实的
 * MyBooks 页面里；tool_builder（独立仓库）会内置一份 API 形状一致的本地开发 mock 实现，
 * 两者需要保持同步。
 *
 * 纯 ES5+ 原生 JS，不依赖任何构建工具或框架，因为工具作者可以用任意技术栈。
 */
(function (window) {
  'use strict';

  function getQueryParam(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  // 工具的 index.html 是从 /get/tool/{tool_id}/index.html 加载的，从当前路径里解析出
  // tool_id，这样同一份 bridge.js 可以被任意工具复用，不需要针对每个工具单独生成。
  function getToolId() {
    var match = window.location.pathname.match(/^\/get\/tool\/([^/]+)\/index\.html$/);
    return match ? match[1] : null;
  }

  var toolId = getToolId();
  // 宿主渲染 <iframe> 时把当前主题/语言拼进 src 的 query string（见 4.3 节），首次渲染就能
  // 拿到，不需要等待 postMessage 握手；宿主切换主题/语言时会重设 iframe.src，页面会重新加载
  // 一次，届时这两个值也会随之更新。
  var theme = getQueryParam('theme') || 'light';
  var locale = getQueryParam('locale') || 'zh';

  /**
   * 对 /api/toolbox/plugin/{tool_id}/... 的 fetch 简单封装。
   * iframe 与宿主同源，Cookie 天然带上，不需要额外处理鉴权。
   *
   * @param {string} path 相对路径（不需要带前导 /），例如 "ping"
   * @param {RequestInit} [options] 透传给 fetch 的选项
   * @returns {Promise<any>} 解析后的 JSON 响应
   */
  function bridgeFetch(path, options) {
    if (!toolId) {
      return Promise.reject(new Error('MyBooksToolBridge: 无法从当前页面 URL 解析出 tool_id'));
    }
    var cleanPath = String(path || '').replace(/^\//, '');
    var url = '/api/toolbox/plugin/' + toolId + '/' + cleanPath;
    var opts = Object.assign({ credentials: 'include' }, options || {});
    return fetch(url, opts).then(function (resp) {
      var contentType = resp.headers.get('content-type') || '';
      if (contentType.indexOf('application/json') !== -1) {
        return resp.json();
      }
      return resp.text();
    });
  }

  /**
   * 请求宿主用它自己的 Vuetify v-snackbar 展示一条提示。可选能力——工具也可以完全自己在
   * iframe 内部画提示条，不依赖这个接口。
   *
   * @param {string} message 提示文案
   * @param {"success"|"error"|"info"|"warning"} [level="info"]
   */
  function bridgeNotify(message, level) {
    window.parent.postMessage(
      {
        source: 'mybooks-toolbox-bridge',
        type: 'notify',
        toolId: toolId,
        message: message,
        level: level || 'info',
      },
      window.location.origin
    );
  }

  window.MyBooksToolBridge = {
    toolId: toolId,
    theme: theme,
    locale: locale,
    fetch: bridgeFetch,
    notify: bridgeNotify,
  };
})(window);
