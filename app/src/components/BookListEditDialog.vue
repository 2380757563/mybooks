<template>
    <v-dialog v-model="internalValue" persistent max-width="600">
        <v-card>
            <v-card-title class="headline">
                <v-icon class="mr-2">mdi-format-list-bulleted-square</v-icon>
                {{ mode === 'create' ? $t('booklist.createTitle') : $t('booklist.editTitle') }}
            </v-card-title>
            <v-card-text>
                <v-text-field
                    v-model="form.name"
                    :label="$t('booklist.fieldName')"
                    counter="100"
                    maxlength="100"
                    :rules="[v => !!(v && v.trim()) || $t('booklist.nameRequired')]"
                ></v-text-field>
                <v-textarea
                    v-model="form.description"
                    :label="$t('booklist.fieldDescription')"
                    counter="500"
                    maxlength="500"
                    rows="3"
                ></v-textarea>

                <div class="mb-2 grey--text text-caption">{{ $t('booklist.fieldColor') }}</div>
                <div class="d-flex flex-wrap mb-4">
                    <v-btn
                        v-for="c in colors"
                        :key="c.key"
                        icon
                        class="ma-1 booklist-color-swatch"
                        :style="{ backgroundColor: dark ? c.dark : c.light }"
                        @click="form.color = c.key"
                    >
                        <v-icon v-if="form.color === c.key" color="white">mdi-check</v-icon>
                    </v-btn>
                </div>

                <v-switch
                    v-model="form.is_public"
                    :label="form.is_public ? $t('booklist.publicHint') : $t('booklist.privateHint')"
                    color="primary"
                ></v-switch>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="close">{{ $t('common.cancel') }}</v-btn>
                <v-btn color="primary" :loading="submitting" :disabled="!form.name || !form.name.trim()" @click="submit">{{ $t('common.save') }}</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { BOOKLIST_COLORS, DEFAULT_BOOKLIST_COLOR } from '~/utils/booklistColors';

export default {
    name: 'BookListEditDialog',
    props: {
        value: { type: Boolean, default: false },
        mode: { type: String, default: 'create' }, // 'create' | 'edit'
        booklist: { type: Object, default: null }, // 编辑态下的原始书单对象
    },
    data() {
        return {
            colors: BOOKLIST_COLORS,
            submitting: false,
            form: {
                name: '',
                description: '',
                color: DEFAULT_BOOKLIST_COLOR,
                is_public: false,
            },
        };
    },
    computed: {
        internalValue: {
            get() { return this.value; },
            set(v) { this.$emit('input', v); },
        },
        dark() {
            return this.$vuetify.theme.dark;
        },
    },
    watch: {
        value(v) {
            if (v) this.resetForm();
        },
    },
    methods: {
        resetForm() {
            if (this.mode === 'edit' && this.booklist) {
                this.form = {
                    name: this.booklist.name,
                    description: this.booklist.description || '',
                    color: this.booklist.color || DEFAULT_BOOKLIST_COLOR,
                    is_public: !!this.booklist.is_public,
                };
            } else {
                this.form = { name: '', description: '', color: DEFAULT_BOOKLIST_COLOR, is_public: false };
            }
        },
        close() {
            this.internalValue = false;
        },
        async submit() {
            if (this.submitting || !this.form.name || !this.form.name.trim()) return;
            this.submitting = true;
            try {
                const payload = {
                    name: this.form.name.trim(),
                    description: (this.form.description || '').trim(),
                    color: this.form.color,
                    is_public: this.form.is_public,
                };
                const url = this.mode === 'edit' ? `/booklist/${this.booklist.id}/update` : '/booklist/create';
                const rsp = await this.$backend(url, { method: 'POST', body: JSON.stringify(payload) });
                if (rsp.err === 'ok') {
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                    this.$emit('saved', rsp.booklist);
                    this.close();
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.submitting = false;
            }
        },
    },
};
</script>

<style scoped>
.booklist-color-swatch {
    border: 2px solid transparent;
}
</style>
