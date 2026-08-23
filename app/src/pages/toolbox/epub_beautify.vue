<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('epubBeautify.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('epubBeautify.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="eb-card pa-6">
          <!-- Hint -->
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('epubBeautify.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('epubBeautify.selectBook')"
            :loading="searching"
            outlined
            dense
            clearable
            :hide-details="true"
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="search"
            @click:clear="clearSearch"
          />

          <!-- Book list -->
          <div class="eb-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('epubBeautify.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="eb-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['eb-book-item', { 'eb-book-selected': selected && selected.id === book.id }]"
                @click="selectBook(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="eb-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="eb-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      :color="file.format === 'EPUB' ? 'primary' : 'default'"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="selected && selected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <template v-if="selected">
            <v-divider class="mb-4" />

            <!-- Analysis -->
            <v-alert
              v-if="analysisError"
              type="error"
              dense
              text
              rounded="lg"
              class="mb-3"
            >{{ analysisError }}</v-alert>
            <v-card v-else-if="analysis" outlined rounded="lg" class="eb-analysis mb-4">
              <v-card-text class="pa-3 caption">
                <div class="d-flex flex-wrap">
                  <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisChapters', { count: analysis.text_entries }) }}</v-chip>
                  <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisToc', { kind: tocKindText }) }}</v-chip>
                  <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisFonts', { has: analysis.has_fontface ? $t('epubBeautify.yes') : $t('epubBeautify.no') }) }}</v-chip>
                  <v-chip v-if="analysis.calibre_soup" x-small outlined color="warning" class="mr-2 mb-1">
                    {{ $t('epubBeautify.analysisCalibre') }}
                  </v-chip>
                  <v-chip x-small outlined class="mb-1">{{ $t('epubBeautify.analysisHeadings', { count: headingCount }) }}</v-chip>
                  <v-chip v-if="analysis.leading_space_paras" x-small outlined color="secondary" class="mr-2 mb-1">
                    {{ $t('epubBeautify.anaLeading', { count: analysis.leading_space_paras }) }}
                  </v-chip>
                  <v-chip v-if="analysis.empty_para_est" x-small outlined color="secondary" class="mr-2 mb-1">
                    {{ $t('epubBeautify.anaEmpty', { count: analysis.empty_para_est }) }}
                  </v-chip>
                  <v-chip v-if="analysis.p_close_mismatch_files" x-small outlined color="error" class="mr-2 mb-1">
                    {{ $t('epubBeautify.anaMismatch', { count: analysis.p_close_mismatch_files }) }}
                  </v-chip>
                  <v-chip v-if="analysis.css_conflict_risk" x-small outlined color="warning" class="mr-2 mb-1">
                    {{ $t('epubBeautify.anaConflict', { count: analysis.css_important_count }) }}
                  </v-chip>
                  <v-chip v-if="analysis.image_count" x-small outlined class="mb-1">
                    {{ $t('epubBeautify.anaImages', { count: analysis.image_count, big: analysis.image_oversize || 0 }) }}
                  </v-chip>
                </div>
                <!-- 目录预览（应用排除规则后的前 12 条） -->
                <div v-if="tocPreviewText" class="mt-2 caption grey--text eb-toc-preview">
                  <div class="font-weight-medium">{{ $t('epubBeautify.tocPreviewTitle') }}</div>
                  <div style="max-height:96px;overflow-y:auto;white-space:pre-line">{{ tocPreviewText }}</div>
                </div>
              </v-card-text>
            </v-card>

            <!-- Presets -->
            <div class="text-subtitle-2 font-weight-medium mb-2">{{ $t('epubBeautify.presetTitle') }}</div>
            <v-row dense>
              <v-col
                v-for="p in presets"
                :key="p.id"
                cols="6"
                sm="6"
                class="mb-1"
              >
                <v-card
                  outlined
                  rounded="lg"
                  :class="['eb-preset', { 'eb-preset-selected': preset === p.id }]"
                  @click="preset = p.id"
                >
                  <v-card-text class="pa-2">
                    <div class="body-2 font-weight-medium d-flex align-center">
                      <v-icon v-if="preset === p.id" small color="primary" class="mr-1">mdi-check-circle</v-icon>
                      {{ $i18n.locale === 'en' ? p.name_en : p.name }}
                      <v-chip v-if="p.page_progression === 'rtl'" x-small outlined class="ml-1 px-1" style="height:16px">{{ $t('epubBeautify.rtlBadge') }}</v-chip>
                      <span class="ml-auto d-inline-flex">
                        <span class="eb-swatch" :style="{ background: p.accent }" />
                        <span class="eb-swatch eb-swatch-b" :style="{ background: p.quote_bg }" />
                        <span class="eb-swatch eb-swatch-b" :style="{ background: p.accent_light }" />
                        <span class="eb-swatch" :style="{ background: p.border }" />
                      </span>
                    </div>
                    <div class="eb-mini mt-1" :style="miniStyle(p)">
                      <span>{{ $i18n.locale === 'en' ? p.name_en : p.name }}</span>
                    </div>
                    <div class="caption grey--text mt-1">{{ p.description }}</div>
                    <div v-if="p.scene" class="caption mt-1" :style="{ color: p.muted }">{{ p.scene }}<template v-if="p.line_height"> · 行高 {{ p.line_height }}</template></div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <!-- Options -->
            <div class="text-subtitle-2 font-weight-medium mb-1 mt-3">{{ $t('epubBeautify.tocStyleTitle') }}</div>
            <v-row dense>
              <v-col v-for="ts in tocStyles" :key="ts.id" cols="6" sm="3" class="mb-1">
                <v-card
                  outlined
                  rounded="lg"
                  :class="['eb-preset', { 'eb-preset-selected': tocStyle === ts.id }]"
                  @click="tocStyle = ts.id"
                >
                  <v-card-text class="pa-2">
                    <div class="caption font-weight-medium d-flex align-center">
                      <v-icon v-if="tocStyle === ts.id" x-small color="primary" class="mr-1">mdi-check-circle</v-icon>
                      {{ $i18n.locale === 'en' ? ts.name_en : ts.name }}
                    </div>
                    <div class="eb-toc-mini mt-1" :style="tocMiniFrame(ts.id)">
                      <div v-if="ts.id === 'cool'" class="eb-toc-mock" :style="{ backgroundColor: currentPreset.accent, backgroundImage: currentPreset.toc_gradient, color: '#F5E6D0', borderBottom: '1px solid #C9A96A' }">目 录</div>
                      <div v-else-if="ts.id === 'minimal'" class="eb-toc-mock" :style="{ background: 'transparent', color: currentPreset.accent, letterSpacing: '0.3em', fontSize: '0.72rem', fontWeight: 600 }">目 录</div>
                      <div v-else class="eb-toc-mock" :style="{ background: ts.id === 'seal' ? '#FFFFFF' : currentPreset.accent_light, color: currentPreset.accent, borderTop: ts.id === 'elegant' ? ('2px solid ' + currentPreset.accent) : 'none', textAlign: ts.id === 'seal' ? 'left' : 'center' }">目 录<span v-if="ts.id === 'seal'" style="background:#B54942;color:#F5E6D0;font-size:0.6em;padding:0 3px;border-radius:2px;margin-left:4px">隐</span></div>
                      <div class="eb-toc-row" :style="ts.id === 'minimal' ? { borderBottom: 'none' } : {}"><span :style="{ color: ts.id === 'minimal' ? (currentPreset.muted || '#999') : currentPreset.accent, fontWeight: ts.id === 'minimal' ? 400 : 700 }">01</span>第一章 血尸</div>
                      <div class="eb-toc-row" :style="{ borderBottom: 'none' }"><span :style="{ color: ts.id === 'minimal' ? (currentPreset.muted || '#999') : currentPreset.accent, fontWeight: ts.id === 'minimal' ? 400 : 700 }">02</span>第二章 五十年后<template v-if="ts.id === 'seal'"><span style="float:right;color:#A2906A">\ ✦</span></template></div>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <v-switch
              v-model="useSystemFonts"
              :label="$t('epubBeautify.fontSwitch')"
              dense
              hide-details
              class="mt-1 mb-1"
            />
            <v-expand-transition>
              <div v-if="useSystemFonts" class="ml-6 mb-2">
                <v-switch
                  v-model="fontBody"
                  :label="$t('epubBeautify.fontBody')"
                  dense
                  hide-details
                  class="mt-0"
                />
                <v-switch
                  v-model="fontHead"
                  :label="$t('epubBeautify.fontHead')"
                  dense
                  hide-details
                  class="mt-0"
                />
                <v-switch
                  v-model="fontKai"
                  :label="$t('epubBeautify.fontKai')"
                  dense
                  hide-details
                  class="mt-0"
                />
                <v-switch
                  v-model="fontCode"
                  :label="$t('epubBeautify.fontCode')"
                  dense
                  hide-details
                  class="mt-0"
                />
              </div>
            </v-expand-transition>

            <!-- 内容清理 -->
            <div class="text-subtitle-2 font-weight-medium mb-1 mt-3">{{ $t('epubBeautify.cleanTitle') }}</div>
            <v-switch
              v-model="cleanLeading"
              :label="$t('epubBeautify.cleanLeading')"
              dense hide-details class="mt-0"
            />
            <v-switch
              v-model="cleanEmpty"
              :label="$t('epubBeautify.cleanEmpty')"
              dense hide-details class="mt-0"
            />
            <v-switch
              v-model="cleanMeta"
              :label="$t('epubBeautify.cleanMeta')"
              dense hide-details class="mt-0 mb-1"
            />

            <!-- 目录深度 -->
            <div class="d-flex align-center">
              <span class="text-subtitle-2 font-weight-medium mr-3">{{ $t('epubBeautify.tocDepth') }}</span>
              <v-select
                v-model="tocDepth"
                :items="tocDepthItems"
                item-text="label"
                item-value="value"
                dense hide-details
                style="max-width:180px"
                class="mt-0"
              />
            </div>

            <v-text-field
              v-model="suffix"
              :label="$t('epubBeautify.suffix')"
              outlined
              dense
              :hide-details="true"
              class="mb-4"
              prepend-inner-icon="mdi-format-title"
            />

            <!-- Run -->
            <v-btn
              block
              large
              color="primary"
              :loading="processing"
              :disabled="!selected || analysisError !== ''"
              @click="startRun"
            >
              <v-icon left>mdi-play</v-icon>{{ $t('epubBeautify.runBtn') }}
            </v-btn>

            <!-- Progress -->
            <div v-if="processing" class="mt-4">
              <v-progress-linear
                :value="progress"
                color="primary"
                height="10"
                rounded
                class="mb-2"
              />
              <div class="text-center caption grey--text">
                {{ progressMsg }}
              </div>
            </div>

            <!-- Result -->
            <v-alert
              v-if="resultMsg"
              :type="resultType === 'success' ? 'success' : 'error'"
              dense
              text
              rounded="lg"
              class="mt-4"
            >{{ resultMsg }}</v-alert>

            <v-btn
              v-if="resultType === 'success' && newBookId"
              block
              outlined
              color="primary"
              class="mt-2"
              @click="$router.push('/book/' + newBookId)"
            >
              <v-icon left>mdi-book-open-page-variant</v-icon>{{ $t('epubBeautify.viewBook') }}
            </v-btn>
          </template>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    query: '',
    books: [],
    searching: false,
    searched: false,
    selected: null,

    analysis: null,
    analysisError: '',
    presets: [],

    preset: 'classic',
    tocStyle: 'elegant',
    tocStyles: [
      { id: 'elegant', name: '精致', name_en: 'Elegant' },
      { id: 'cool', name: '酷炫', name_en: 'Cool' },
      { id: 'seal', name: '朱印', name_en: 'Seal' },
      { id: 'minimal', name: '极简', name_en: 'Minimal' },
    ],
    useSystemFonts: true,
    fontBody: true,
    fontHead: true,
    fontKai: true,
    fontCode: true,
    // 内容清理（混合默认：段首空格开 / 空段关 / meta 开）
    cleanLeading: true,
    cleanEmpty: false,
    cleanMeta: true,
    // 目录深度（0 = 全部）
    tocDepth: 0,
    tocDepthItems: [
      { value: 0, label: '全部层级' },
      { value: 1, label: '仅一级' },
      { value: 2, label: '前两级' },
      { value: 3, label: '前三级' },
    ],
    suffix: '',

    processing: false,
    progress: 0,
    progressMsg: '',
    resultMsg: '',
    resultType: 'success',
    newBookId: null,
    pollTimer: null,
  }),
  computed: {
    tocKindText() {
      if (!this.analysis) return '';
      if (this.analysis.has_inbook_toc) return this.$t('epubBeautify.tocInbook');
      if (this.analysis.ncx_entries > 0) return this.$t('epubBeautify.tocNcx');
      if (this.analysis.nav_entries > 0) return this.$t('epubBeautify.tocNav');
      return this.$t('epubBeautify.tocNone');
    },
    headingCount() {
      if (!this.analysis) return 0;
      const s = this.analysis.heading_stats || {};
      return (s.h1 || 0) + (s.h2 || 0) + (s.h3 || 0) + this.analysis.text_headings;
    },
    tocPreviewText() {
      const titles = (this.analysis && this.analysis.toc_preview_titles) || [];
      return titles.map((t, i) => (i + 1) + '. ' + t).join('\n');
    },
    currentPreset() {
      return this.presets.find((p) => p.id === this.preset) || this.presets[0] || {};
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  beforeDestroy() {
    this.stopPolling();
  },
  methods: {
    searchDebounce: null,
    miniStyle(p) {
      if (p.id === 'inkstone') {
        return { background: p.accent, color: '#FFFFFF', borderRadius: '2px', padding: '7px 4px', textAlign: 'center', fontWeight: 800, letterSpacing: '0.12em', fontSize: '0.8rem' };
      }
      if (p.id === 'xuanzhi') {
        return { color: p.accent, borderBottom: '2px solid ' + p.accent, padding: '9px 4px 6px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.14em', fontSize: '0.8rem' };
      }
      if (p.id === 'vertclassical') {
        // 竖排预览：真实 writing-mode 竖排 + 左右界栏线
        return { background: p.accent_light || '#F6F1E3', color: p.accent, writingMode: 'vertical-rl', textOrientation: 'mixed', height: '62px', margin: '0 auto', padding: '4px 6px', borderLeft: '1px solid ' + (p.border || '#DDD'), borderRight: '1px solid ' + (p.border || '#DDD'), fontWeight: 700, letterSpacing: '0.16em', fontSize: '0.78rem' };
      }
      return { background: p.accent_light || '#F5F5F5', color: p.accent, borderTop: '3px solid ' + p.accent, borderBottom: '1px solid ' + (p.border || '#DDD'), borderRadius: '3px', padding: '8px 4px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.06em', fontSize: '0.8rem' };
    },
    tocMiniFrame(id) {
      const cp = this.currentPreset || {};
      if (id === 'minimal') {
        return { background: '#FFFFFF', border: '1px dashed ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
      }
      if (id === 'cool') {
        return { background: cp.quote_bg || '#F5F5F5', border: '1px solid ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
      }
      return { background: '#FFFFFF', border: '1px solid ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
    },
    async search() {
      clearTimeout(this.searchDebounce);
      this.searchDebounce = setTimeout(() => {
        this.doSearch();
      }, 300);
    },
    async doSearch() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.selected = null;
      this.analysis = null;
      this.analysisError = '';
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.books = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (_e) {
        this.books = [];
      } finally {
        this.searching = false;
        this.searched = true;
      }
    },
    clearSearch() {
      this.books = [];
      this.selected = null;
      this.analysis = null;
      this.analysisError = '';
      this.searched = false;
    },
    async selectBook(book) {
      if (this.selected && this.selected.id === book.id) {
        this.selected = null;
        this.analysis = null;
        this.analysisError = '';
        return;
      }
      this.selected = book;
      this.analysis = null;
      this.analysisError = '';
      this.resultMsg = '';
      this.newBookId = null;
      const hasEpub = (book.files || []).some((f) => f.format === 'EPUB');
      if (!hasEpub) {
        this.analysisError = this.$t('epubBeautify.noEpub');
        return;
      }
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: book.id }),
        });
        if (rsp.err === 'ok') {
          this.analysis = (rsp.data || {}).analysis || null;
          this.presets = (rsp.data || {}).presets || [];
          if ((rsp.data || {}).toc_styles && (rsp.data || {}).toc_styles.length > 0) {
            const raw = (rsp.data || {}).toc_styles || [];
            this.tocStyles = raw.map((s) => {
              if (Array.isArray(s)) {
                const mapEn = { elegant: 'Elegant', cool: 'Cool', seal: 'Seal' };
                return { id: s[0], name: s[1], name_en: mapEn[s[0]] || s[0] };
              }
              return s;
            });
          }
          if (this.presets.length > 0) this.preset = this.presets[0].id;
        } else {
          this.analysisError = rsp.msg || rsp.err;
        }
      } catch (e) {
        this.analysisError = String(e);
      }
    },
    stageText(stage) {
      const map = {
        analyzing: this.$t('epubBeautify.progressAnalyzing'),
        processing: this.$t('epubBeautify.progressProcessing'),
        saving: this.$t('epubBeautify.progressSaving'),
        completed: this.$t('epubBeautify.progressCompleted'),
      };
      return map[stage] || '';
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(this.pollProgress, 2000);
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    async pollProgress() {
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/progress');
        if (rsp.err === 'task.not_found') {
          return;
        }
        const data = rsp.data || {};
        this.progress = data.progress || 0;
        this.progressMsg = this.stageText(data.stage);

        if (rsp.err === 'task.failed') {
          this.stopPolling();
          this.processing = false;
          this.resultMsg = rsp.msg || this.$t('epubBeautify.runFailed');
          this.resultType = 'error';
          return;
        }
        if (data.status === 'completed') {
          this.stopPolling();
          this.processing = false;
          this.progress = 100;
          this.progressMsg = this.$t('epubBeautify.progressCompleted');
          this.resultMsg = this.$t('epubBeautify.runCompleted');
          this.resultType = 'success';
          this.newBookId = data.new_book_id || null;
        }
      } catch (e) {
        // 网络抖动时忽略，继续轮询
      }
    },
    async startRun() {
      if (!this.selected || this.processing) return;
      this.resultMsg = '';
      this.newBookId = null;
      this.processing = true;
      this.progress = 0;
      this.progressMsg = '';
      const fontOverrides = this.useSystemFonts ? {
        body: this.fontBody,
        head: this.fontHead,
        kai: this.fontKai,
        code: this.fontCode,
      } : { body: false, head: false, kai: false, code: false };
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            preset: this.preset,
            toc_style: this.tocStyle,
            use_system_fonts: this.useSystemFonts,
            font_overrides: fontOverrides,
            toc_depth: this.tocDepth || null,
            cleanup: {
              leading: this.cleanLeading,
              empty: this.cleanEmpty,
              meta: this.cleanMeta,
            },
            suffix: this.suffix,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('epubBeautify.runStarted');
          this.resultType = 'success';
          this.startPolling();
        } else {
          this.processing = false;
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.processing = false;
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
  },
};
</script>

<style scoped>
.eb-preset {
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  height: 100%;
}
.eb-preset:hover {
  border-color: #90caf9;
}
.eb-preset-selected {
  border-color: #1976d2 !important;
  background: #e3f2fd !important;
}
.eb-swatch {
  display: inline-block;
  width: 13px;
  height: 13px;
  border-radius: 3px;
  margin-left: 3px;
  vertical-align: middle;
}
.eb-swatch-b {
  border: 1px solid rgba(0, 0, 0, 0.12);
}
.eb-mini {
  font-size: 0.8rem;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-toc-mini {
  font-size: 0.72rem;
  line-height: 1.6;
}
.eb-toc-mock {
  padding: 4px 6px;
  font-weight: 700;
  letter-spacing: 0.2em;
  font-size: 0.78rem;
  text-align: center;
}
.eb-toc-row {
  padding: 3px 8px;
  color: #444;
  border-bottom: 1px dashed #ddd;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-toc-row span {
  margin-right: 4px;
}
</style>
