<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('authorClean.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('authorClean.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Tool card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="ac-card pa-6">
          <p class="ac-desc mb-4">{{ $t('authorClean.description') }}</p>

          <!-- Existing author -->
          <v-autocomplete
            v-model="authorName"
            :items="authorNames"
            :label="$t('authorClean.authorLabel')"
            :placeholder="$t('authorClean.authorPlaceholder')"
            :loading="loadingAuthors"
            outlined
            dense
            clearable
            hide-details
            class="mb-5"
          ></v-autocomplete>

          <!-- Action -->
          <p class="ac-options-title mb-2">{{ $t('authorClean.actionLabel') }}</p>
          <v-radio-group v-model="action" hide-details class="mt-0 mb-4">
            <v-radio :label="$t('authorClean.actionClean')" value="clean" dense></v-radio>
            <v-radio :label="$t('authorClean.actionReplace')" value="replace" dense></v-radio>
          </v-radio-group>

          <p v-if="action === 'clean'" class="ac-hint mb-4">{{ $t('authorClean.cleanHint') }}</p>

          <!-- New author name -->
          <template v-if="action === 'replace'">
            <v-text-field
              v-model="newAuthorName"
              :label="$t('authorClean.newAuthorLabel')"
              :placeholder="$t('authorClean.newAuthorPlaceholder')"
              :error-messages="newAuthorNameError"
              outlined
              dense
              class="mb-2"
            ></v-text-field>
            <p class="ac-hint mb-4">{{ $t('authorClean.replaceHint') }}</p>
          </template>

          <!-- Start button -->
          <div class="d-flex justify-center">
            <v-btn
              color="primary"
              class="ac-start-btn"
              :loading="loading"
              :disabled="!canSubmit || loading"
              @click="showConfirmDialog = true"
            >
              {{ $t('authorClean.startBtn') }}
            </v-btn>
          </div>

          <!-- Result message -->
          <transition name="ac-fade">
            <v-alert
              v-if="resultMsg"
              :type="resultType"
              dense
              text
              rounded="lg"
              class="mt-6 mb-0"
            >{{ resultMsg }}</v-alert>
          </transition>
        </v-card>
      </v-col>
    </v-row>

    <!-- Confirm dialog -->
    <v-dialog v-model="showConfirmDialog" max-width="460px">
      <v-card>
        <v-card-title class="headline">{{ $t('authorClean.confirmTitle') }}</v-card-title>
        <v-card-text>
          <p v-if="action === 'clean'">{{ $t('authorClean.confirmClean', { author: authorName }) }}</p>
          <p v-else>{{ $t('authorClean.confirmReplace', { author: authorName, newAuthor: newAuthorName }) }}</p>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey" text @click="showConfirmDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="red" :loading="loading" @click="confirmStart">{{ $t('authorClean.startBtn') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    authorNames: [],
    loadingAuthors: false,
    authorName: '',
    action: 'clean',
    newAuthorName: '',

    loading: false,
    resultMsg: '',
    resultType: 'success',
    showConfirmDialog: false,
  }),
  computed: {
    newAuthorNameError() {
      if (this.action !== 'replace' || !this.newAuthorName) return [];
      return this.isValidNewAuthorName(this.newAuthorName) ? [] : [this.$t('authorClean.newAuthorInvalid')];
    },
    canSubmit() {
      if (!this.authorName) return false;
      if (this.action === 'replace') {
        return !!this.newAuthorName && this.isValidNewAuthorName(this.newAuthorName);
      }
      return true;
    },
  },
  created() {
    this.$store.commit('navbar', true);
    this.loadAuthors();
  },
  methods: {
    isValidNewAuthorName(name) {
      return /^[^\s'"]+$/.test(name) && [...name].every((c) => /[\p{L}\p{N}]/u.test(c) || c === '.' || c === '·');
    },
    async loadAuthors() {
      this.loadingAuthors = true;
      try {
        const rsp = await this.$backend('/author?show=all');
        if (rsp.err === 'ok' && Array.isArray(rsp.items)) {
          this.authorNames = rsp.items.map((i) => i.name).filter(Boolean);
        }
      } catch (e) {
        // Non-fatal: user can still type an author name manually.
      } finally {
        this.loadingAuthors = false;
      }
    },
    confirmStart() {
      this.showConfirmDialog = false;
      this.startClean();
    },
    async startClean() {
      if (!this.canSubmit) return;

      this.resultMsg = '';
      this.loading = true;
      try {
        const rsp = await this.$backend('/toolbox/author_clean', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: this.action,
            author_name: this.authorName,
            new_author_name: this.action === 'replace' ? this.newAuthorName : '',
          }),
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('authorClean.success') : rsp.err);
        this.resultType = rsp.err === 'ok' ? 'success' : 'error';
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.loading = false;
      }
    },
  },
};
</script>

<style scoped>
.ac-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

.ac-desc {
  font-size: 14px;
  line-height: 1.7;
  color: #606880;
  margin: 0;
}

.theme--dark .ac-desc {
  color: #8892a4;
}

.ac-options-title {
  font-size: 14px;
  line-height: 1.7;
  color: #606880;
  margin: 0;
}
.theme--dark .ac-options-title {
  color: #8892a4;
}

.ac-hint {
  font-size: 12px;
  line-height: 1.6;
  color: #8892a4;
  margin: 0;
}

.ac-start-btn {
  width: 33%;
  min-width: 160px;
}

.ac-fade-enter-active,
.ac-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.ac-fade-enter,
.ac-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
