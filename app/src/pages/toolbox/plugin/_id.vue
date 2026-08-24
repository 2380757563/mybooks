<template>
  <v-container fluid class="pa-4 toolbox-plugin-container">
    <v-row class="mb-3 flex-grow-0" align="center" no-gutters>
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ (tool && tool.name) || $t('toolboxPlugin.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="goBack">
          <v-icon small left>mdi-close</v-icon>{{ $t('common.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-alert v-if="!tool" type="warning" dense class="mt-2">
      {{ $t('toolboxPlugin.notFound') }}
    </v-alert>

    <iframe
      v-else
      :key="iframeSrc"
      :src="iframeSrc"
      :title="tool.name"
      class="toolbox-plugin-frame"
      frameborder="0"
    ></iframe>
  </v-container>
</template>

<script>
// 通用的外部插件承载页：核心 App 只维护这一个构建期就存在的动态路由页面，新增/删除任意
// 数量的外部插件（或被"更新"覆盖过的内置工具）都不需要再改前端代码，见
// document/Toolbox_Dynamic_Design.md 4.1/4.3 节。工具自身的 UI 是一个自包含的静态站点，
// 由 <iframe> 加载 /get/tool/{id}/index.html，与宿主完全隔离（CSS/JS 互不影响）。
export default {
  data: () => ({
    tool: null,
  }),
  head() {
    return {
      title: (this.tool && this.tool.name) || this.$t('toolboxPlugin.title'),
    };
  },
  async asyncData({ params, app, res }) {
    if (res !== undefined) {
      res.setHeader('Cache-Control', 'no-cache');
    }
    try {
      const data = await app.$backend('/toolbox/list');
      const tools = (data && data.tools) || [];
      const tool = tools.find((t) => t.id === params.id) || null;
      // status 由后端根据 InstalledTool.enabled 计算，禁用的外部插件在这里也拿不到
      // （见 3.3.1 节），和"根本不存在"是同一种展示——都提示"不存在或已禁用"
      return { tool: tool && tool.status === 'enabled' ? tool : null };
    } catch (e) {
      return { tool: null };
    }
  },
  computed: {
    // 主题/语言变化时这个计算属性的值会变，:key + :src 绑定让浏览器重新加载 iframe 内容，
    // 工具页面首次渲染就能从 URL query 里拿到当前主题/语言，不需要等 postMessage 握手；
    // 见 4.3 节"决策"与 4.5 节"仍需原型验证的风险"。
    iframeSrc() {
      if (!this.tool) return '';
      const theme = this.$vuetify.theme.dark ? 'dark' : 'light';
      const locale = this.$i18n.locale || 'zh';
      return `/get/tool/${this.tool.id}/index.html?theme=${theme}&locale=${encodeURIComponent(locale)}`;
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  mounted() {
    window.addEventListener('message', this.onBridgeMessage);
  },
  beforeDestroy() {
    window.removeEventListener('message', this.onBridgeMessage);
  },
  methods: {
    goBack() {
      this.$router.push('/toolbox');
    },
    // 响应 toolbox-bridge.js 里 bridge.notify() 发出的 postMessage，复用宿主的全局提示组件
    // （见 app/src/plugins/mybooks.js 里的 $alert），4.3 节里描述的可选能力。
    onBridgeMessage(event) {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== 'mybooks-toolbox-bridge' || data.type !== 'notify') return;
      if (this.tool && data.toolId && data.toolId !== this.tool.id) return;
      this.$alert(data.level || 'info', data.message || '');
    },
  },
};
</script>

<style scoped>
.toolbox-plugin-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px);
}
.toolbox-plugin-frame {
  flex: 1 1 auto;
  width: 100%;
  border: none;
}
</style>
