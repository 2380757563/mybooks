<template>
    <v-dialog v-model="visible" max-width="600px" persistent>
        <v-card>
            <v-card-title>
                {{ title || $t('admin.users.reading_range_dialog_title') }}
                <v-spacer></v-spacer>
                <v-btn icon @click="visible = false">
                    <v-icon>mdi-close</v-icon>
                </v-btn>
            </v-card-title>
            <v-card-text>
                <!-- Mode radio group -->
                <v-radio-group v-model="range.mode" mandatory>
                    <v-radio :label="$t('admin.users.reading_range_all')" :value="0"></v-radio>
                    <v-radio :label="$t('admin.users.reading_range_whitelist')" :value="1"></v-radio>
                    <v-radio :label="$t('admin.users.reading_range_blacklist')" :value="2"></v-radio>
                </v-radio-group>

                <template v-if="range.mode !== 0">
                    <!-- Categories multi-select -->
                    <v-select
                        v-model="range.selectedCategories"
                        :items="allCategories"
                        item-text="name"
                        item-value="name"
                        :label="$t('admin.users.reading_range_categories_label')"
                        multiple
                        chips
                        small-chips
                        deletable-chips
                        :loading="loadingCategories"
                        class="mb-2"
                    ></v-select>

                    <!-- Tag search + chips -->
                     <!-- Selected tags chips -->
                    <div v-if="range.selectedTags.length > 0" class="d-flex flex-wrap gap-1 mt-1">
                        <v-chip
                            v-for="tag in range.selectedTags"
                            :key="tag"
                            close
                            small
                            @click:close="removeTag(tag)"
                        >{{ tag }}
                        </v-chip>
                    </div>
                    <div class="mb-1 subtitle-2">{{ $t('admin.users.reading_range_tags_label') }}</div>
                    <v-text-field
                        v-model="tagSearchInput"
                        :label="$t('admin.users.reading_range_tags_hint')"
                        :loading="loadingTags"
                        clearable
                        dense
                        outlined
                        @input="onTagSearchInput"
                        @click:clear="tagSuggestions = []"
                    ></v-text-field>
                    <!-- Tag suggestions list -->
                    <v-list dense class="mb-2" v-if="tagSuggestions.length > 0" style="max-height:160px;overflow-y:auto;border:1px solid #ddd;border-radius:4px;">
                        <v-list-item
                            v-for="tag in tagSuggestions"
                            :key="tag.name"
                            @click="addTag(tag.name)"
                            :disabled="range.selectedTags.includes(tag.name)"
                        >
                            <v-list-item-title>{{ tag.name }} <span class="grey--text caption">({{ tag.count }})</span></v-list-item-title>
                            <v-list-item-action>
                                <v-icon small color="primary">mdi-plus</v-icon>
                            </v-list-item-action>
                        </v-list-item>
                        <v-list-item v-if="tagSuggestions.length === 0 && tagSearchInput">
                            <v-list-item-title class="grey--text">{{ $t('admin.users.reading_range_tags_no_result') }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </template>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" @click="onSave" :loading="saving">{{ $t('admin.users.reading_range_save') }}</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: "ReadingRangeDialog",
    props: {
        title: { type: String, default: "" },
        saving: { type: Boolean, default: false },
    },
    data() {
        return {
            visible: false,
            range: {
                mode: 0,
                selectedCategories: [],
                selectedTags: [],
            },
            allCategories: [],
            loadingCategories: false,
            tagSearchInput: "",
            tagSuggestions: [],
            loadingTags: false,
            tagSearchTimer: null,
        };
    },
    methods: {
        /**
         * Open the dialog, seeded with an existing range.
         * @param {{mode?: number, categories?: string, tags?: string}} initialRange
         */
        open(initialRange) {
            initialRange = initialRange || {};
            this.range = {
                mode: initialRange.mode || 0,
                selectedCategories: initialRange.categories ? initialRange.categories.split(',').filter(Boolean) : [],
                selectedTags: initialRange.tags ? initialRange.tags.split(',').filter(Boolean) : [],
            };
            this.tagSearchInput = "";
            this.tagSuggestions = [];
            this.visible = true;
            this.fetchCategories();
        },
        close() {
            this.visible = false;
        },
        fetchCategories() {
            if (this.allCategories.length > 0) return;
            this.loadingCategories = true;
            this.$backend("/categories")
                .then(rsp => {
                    if (rsp.err === "ok") {
                        this.allCategories = rsp.categories || [];
                    }
                })
                .finally(() => { this.loadingCategories = false; });
        },
        onTagSearchInput(val) {
            if (this.tagSearchTimer) clearTimeout(this.tagSearchTimer);
            if (!val || val.trim().length === 0) {
                this.tagSuggestions = [];
                return;
            }
            this.tagSearchTimer = setTimeout(() => {
                this.loadingTags = true;
                this.$backend("/tags/search?q=" + encodeURIComponent(val.trim()) + "&limit=20")
                    .then(rsp => {
                        if (rsp.err === "ok") {
                            this.tagSuggestions = rsp.tags || [];
                        }
                    })
                    .finally(() => { this.loadingTags = false; });
            }, 300);
        },
        addTag(name) {
            if (!this.range.selectedTags.includes(name)) {
                this.range.selectedTags.push(name);
            }
        },
        removeTag(name) {
            this.range.selectedTags = this.range.selectedTags.filter(t => t !== name);
        },
        onSave() {
            this.$emit('save', {
                mode: this.range.mode,
                categories: this.range.mode === 0 ? "" : this.range.selectedCategories.join(','),
                tags: this.range.mode === 0 ? "" : this.range.selectedTags.join(','),
            });
        },
    },
};
</script>
