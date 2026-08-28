<template>
    <v-dialog v-model="show" persistent transition="dialog-bottom-transition" max-width="600">
        <v-card class="upload-dialog-card">
            <v-toolbar flat dense dark color="#003153" class="upload-dialog-toolbar">
                {{ $t('upload.batchTitle') }}
                <v-spacer></v-spacer>
                <v-btn color="" text :disabled="importing" @click="close">{{ $t('upload.batchClose') }}</v-btn>
            </v-toolbar>
            <v-card-text class="pt-4">
                <div class="mb-2">{{ $t('upload.batchFileCount', { count: items.length || fileCount }) }}</div>
                <v-progress-linear
                    v-if="importing"
                    :value="progressPercent"
                    height="20"
                    color="green"
                    class="mb-3"
                >
                    <strong class="white--text" style="font-size: 12px;">
                        {{ $t('upload.batchImporting', { processed: processedCount, total: totalCount }) }}
                    </strong>
                </v-progress-linear>
                <div v-else class="mb-3 font-weight-medium">
                    {{ cancelled ? $t('upload.batchCancelled') : $t('upload.batchCompleted') }}
                </div>

                <v-simple-table dense fixed-header height="320px">
                    <template v-slot:default>
                        <thead>
                            <tr>
                                <th style="width: 90px;"></th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="item in items" :key="item.id">
                                <td>
                                    <v-chip small v-if="item.status == 'imported'" class="primary">{{ $t('imports.status.imported') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'exist'" class="lighten-4">{{ $t('imports.status.exist') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'ready'" class="success">{{ $t('imports.status.ready') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'drop'" class="warning" style="color:black;">{{ $t('imports.status.drop') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'invalid'" class="error" style="color:black;">{{ $t('imports.status.invalid') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'missed'" class="error" style="color:black;">{{ $t('imports.status.missed') }}</v-chip>
                                    <v-chip small v-else-if="item.status == 'permission'" class="error" style="color:black;">{{ $t('imports.status.permission') }}</v-chip>
                                    <v-chip small v-else class="grey">{{ $t('imports.status.new') }}</v-chip>
                                </td>
                                <td class="text-truncate" style="max-width: 380px;">
                                    <a v-if="item.book_id" target="_blank" :href="`/book/${item.book_id}`">{{ item.title || item.name }}</a>
                                    <span v-else>{{ item.title || item.name }}</span>
                                </td>
                            </tr>
                        </tbody>
                    </template>
                </v-simple-table>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn v-if="importing" :loading="cancelling" color="error" text @click="cancelImport">
                    {{ $t('upload.batchCancel') }}
                </v-btn>
                <v-btn v-else color="primary" @click="close">{{ $t('upload.batchClose') }}</v-btn>
                <v-spacer></v-spacer>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    props: {
        value: {
            type: Boolean,
            default: false,
        },
        importId: {
            type: [Number, String],
            default: null,
        },
        fileCount: {
            type: Number,
            default: 0,
        },
    },
    data: () => ({
        items: [],
        importing: true,
        cancelling: false,
        cancelled: false,
        processedCount: 0,
        totalCount: 0,
        _pollTimer: null,
    }),
    computed: {
        show: {
            get() {
                return this.value;
            },
            set(val) {
                this.$emit('input', val);
            },
        },
        progressPercent() {
            if (!this.totalCount) return 0;
            const pct = Math.round((this.processedCount / this.totalCount) * 100);
            return Math.min(100, Math.max(0, pct));
        },
    },
    watch: {
        value(val) {
            if (val && this.importId) {
                this.startPolling();
            } else {
                this.stopPolling();
            }
        },
        importId(val) {
            if (val && this.show) {
                this.items = [];
                this.importing = true;
                this.cancelled = false;
                this.startPolling();
            }
        },
    },
    beforeDestroy() {
        this.stopPolling();
    },
    methods: {
        startPolling() {
            this.stopPolling();
            this.poll();
        },
        stopPolling() {
            if (this._pollTimer) {
                clearTimeout(this._pollTimer);
                this._pollTimer = null;
            }
        },
        poll() {
            this.$backend(`/book/upload/batch/status?import_id=${this.importId}`)
                .then((rsp) => {
                    if (rsp.err !== 'ok') {
                        this.$alert('error', rsp.msg);
                        this.importing = false;
                        return;
                    }
                    this.items = rsp.items || [];
                    this.totalCount = this.items.length;
                    this.processedCount = this.items.filter((i) => i.status !== 'ready' && i.status !== 'new').length;
                    this.importing = !!rsp.importing;
                    if (this.importing) {
                        this._pollTimer = setTimeout(() => this.poll(), 1500);
                    }
                })
                .catch(() => {
                    // 网络错误时继续重试，避免误判为已完成
                    this._pollTimer = setTimeout(() => this.poll(), 2000);
                });
        },
        cancelImport() {
            this.cancelling = true;
            this.$backend('/book/upload/batch/cancel', {
                method: 'POST',
                body: JSON.stringify({ import_id: this.importId }),
            })
                .then((rsp) => {
                    if (rsp.err !== 'ok') {
                        this.$alert('error', rsp.msg);
                        return;
                    }
                    this.cancelled = true;
                })
                .finally(() => {
                    this.cancelling = false;
                });
        },
        close() {
            this.show = false;
            this.stopPolling();
        },
    },
};
</script>

<style scoped>
.upload-dialog-card {
    border-radius: 16px 16px 4px 4px !important;
}
.upload-dialog-toolbar {
    border-radius: 16px 16px 0 0 !important;
    overflow: hidden;
}
</style>
