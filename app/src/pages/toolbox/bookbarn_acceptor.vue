<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('bookbarnAcceptor.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('bookbarnAcceptor.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Tool card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="rcb-card pa-6">
          <!-- Description -->
          <p class="rcb-desc mb-4">{{ $t('bookbarnAcceptor.description') }}</p>

          <!-- BookBarn service status -->
          <div class="d-flex align-center mb-4">
            <span class="rcb-status-label">{{ $t('bookbarnAcceptor.serviceStatus') }}</span>
            <v-chip small :color="status.enable_bookbarn ? 'success' : 'default'" text-color="white">
              {{ status.enable_bookbarn ? $t('bookbarnAcceptor.enabled') : $t('bookbarnAcceptor.disabled') }}
            </v-chip>
          </div>

          <!-- Receiving books toggle -->
          <v-checkbox
            small
            hide-details
            v-model="status.enable_receiving_books"
            :disabled="!status.enable_bookbarn || toggling"
            :label="$t('bookbarnAcceptor.enableReceiving')"
            class="mb-4"
            @change="toggleReceiving"
          ></v-checkbox>

          <!-- Collection hour -->
          <v-select
            small
            prepend-icon="mdi-clock-outline"
            v-model="status.collection_hour"
            :disabled="!status.enable_bookbarn || !status.enable_receiving_books || savingHour"
            :items="hours"
            :label="$t('bookbarnAcceptor.collectionHour')"
            class="mb-4"
            @change="setCollectionHour"
          ></v-select>

          <!-- Token -->
          <v-text-field
            flat
            small
            v-model="status.token"
            :label="$t('bookbarnAcceptor.token')"
            type="text"
            :disabled="true"
          ></v-text-field>
          <div class="d-flex justify-center">
            <button
              class="rcb-btn-start"
              :class="{ 'rcb-btn-loading': applying }"
              :disabled="!status.enable_bookbarn || applying || !!status.token"
              @click="applyToken"
            >
              <span v-if="applying" class="rcb-spinner" />
              <span v-else><v-icon small left color="#fff">mdi-key</v-icon>{{ $t('bookbarnAcceptor.applyToken') }}</span>
            </button>
          </div>

          <!-- Result message -->
          <transition name="rcb-fade">
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
  </v-container>
</template>

<script>
export default {
  data: () => ({
    status: {
      enable_bookbarn: false,
      enable_receiving_books: false,
      token: '',
      collection_hour: 3,
    },
    hours: Array.from({ length: 24 }, (_, i) => ({ text: i.toString(), value: i })),
    toggling: false,
    applying: false,
    savingHour: false,
    resultMsg: '',
    resultType: 'success',
  }),
  created() {
    this.$store.commit('navbar', true);
    this.loadStatus();
  },
  methods: {
    async loadStatus() {
      try {
        const rsp = await this.$backend('/toolbox/bookbarn_acceptor/status');
        if (rsp.err === 'ok') {
          this.status = rsp.data;
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
    async toggleReceiving(enabled) {
      this.resultMsg = '';
      this.toggling = true;
      try {
        const rsp = await this.$backend('/toolbox/bookbarn_acceptor/toggle', {
          method: 'POST',
          body: JSON.stringify({ enabled }),
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('bookbarnAcceptor.success') : rsp.err);
        this.resultType = rsp.err === 'ok' ? 'success' : 'error';
        if (rsp.err === 'ok' && rsp.data) {
          this.status = rsp.data;
        } else {
          this.status.enable_receiving_books = !enabled;
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
        this.status.enable_receiving_books = !enabled;
      } finally {
        this.toggling = false;
      }
    },
    async setCollectionHour(hour) {
      this.resultMsg = '';
      this.savingHour = true;
      const prevHour = this.status.collection_hour;
      try {
        const rsp = await this.$backend('/toolbox/bookbarn_acceptor/set_collection_hour', {
          method: 'POST',
          body: JSON.stringify({ hour }),
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('bookbarnAcceptor.success') : rsp.err);
        this.resultType = rsp.err === 'ok' ? 'success' : 'error';
        if (rsp.err === 'ok' && rsp.data) {
          this.status = rsp.data;
        } else {
          this.status.collection_hour = prevHour;
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
        this.status.collection_hour = prevHour;
      } finally {
        this.savingHour = false;
      }
    },
    async applyToken() {
      this.resultMsg = '';
      this.applying = true;
      try {
        const rsp = await this.$backend('/toolbox/bookbarn_acceptor/apply_token', {
          method: 'POST',
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('bookbarnAcceptor.success') : rsp.err);
        this.resultType = rsp.err === 'ok' ? 'success' : 'error';
        if (rsp.err === 'ok' && rsp.token) {
          this.status.token = rsp.token;
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.applying = false;
      }
    },
  },
};
</script>

<style scoped>
.rcb-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

/* Description text — 14px normal */
.rcb-desc {
  font-size: 14px;
  line-height: 1.7;
  color: #606880;
  margin: 0;
}

.theme--dark .rcb-desc {
  color: #8892a4;
}

.rcb-status-label {
  font-size: 14px;
  color: #606880;
  margin-right: 12px;
}

.theme--dark .rcb-status-label {
  color: #8892a4;
}

/* Start button */
.rcb-btn-start {
  background: #003153;
  color: #fff;
  border: none;
  padding: 10px 40px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  letter-spacing: 0.04em;
  transition: background 0.2s, opacity 0.2s;
  min-width: 140px;
  justify-content: center;
}

.rcb-btn-start:hover:not(:disabled) {
  background: #004a7c;
}

.rcb-btn-start:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

/* Spinner */
.rcb-spinner {
  display: inline-block;
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: rcb-spin 0.7s linear infinite;
}

@keyframes rcb-spin {
  to { transform: rotate(360deg); }
}

/* Transition */
.rcb-fade-enter-active,
.rcb-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.rcb-fade-enter,
.rcb-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
