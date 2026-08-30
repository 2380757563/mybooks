<template>
    <AppDialog
        v-model="internalValue"
        :persistent="false"
        type="action"
        :title="$t('booklist.addBooksTitle')"
        icon="mdi-book-plus-outline"
        max-width="800"
        :dismiss-label="$t('common.close')"
        hide-footer-button
    >
                <div class="d-flex mb-2">
                    <v-text-field
                        v-model="query"
                        :placeholder="$t('booklist.searchPlaceholder')"
                        hide-details
                        dense
                        outlined
                        clearable
                        @keyup.enter="search"
                    ></v-text-field>
                    <v-btn color="primary" class="ml-2" :loading="searching" @click="search">{{ $t('appHeader.search') }}</v-btn>
                </div>

                <v-progress-circular v-if="searching" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>

                <template v-else>
                    <p v-if="!searched" class="grey--text text-center my-6">{{ $t('booklist.searchHint') }}</p>
                    <p v-else-if="results.length === 0" class="grey--text text-center my-6">{{ $t('booklist.searchNotFound') }}</p>
                    <div v-else class="addbook-list">
                        <div v-for="b in results" :key="b.id" class="addbook-item d-flex py-2">
                            <v-img :src="b.thumb || b.img" width="60" class="flex-grow-0 mr-3" :aspect-ratio="11 / 15"></v-img>
                            <div class="flex-grow-1" style="min-width: 0">
                                <a :href="`/book/${b.id}`" target="_blank" class="font-weight-bold text-truncate d-block">{{ b.title }}</a>
                                <div class="grey--text text-caption text-truncate">{{ b.author }}</div>
                                <div class="grey--text text-caption">
                                    <span v-if="b.pubdate">{{ b.pubdate }}</span>
                                    <span v-if="b.languages"> · {{ b.languages }}</span>
                                    <template v-for="(f, idx) in (b.files || []).slice(0, 3)">
                                        <v-chip :key="idx" x-small class="ml-1" color="cyan" text-color="white">{{ f.format }}</v-chip>
                                    </template>
                                </div>
                            </div>
                            <div class="flex-grow-0 align-self-center">
                                <v-btn
                                    v-if="!isAdded(b.id)"
                                    small
                                    color="primary"
                                    :loading="pending === b.id"
                                    @click="addBook(b)"
                                >{{ $t('booklist.addToBooklist') }}</v-btn>
                                <v-btn
                                    v-else
                                    small
                                    outlined
                                    color="green"
                                    :loading="pending === b.id"
                                    @click="removeBook(b)"
                                >
                                    <v-icon small left>mdi-check</v-icon>{{ $t('booklist.added') }}
                                </v-btn>
                            </div>
                        </div>
                    </div>
                </template>
    </AppDialog>
</template>

<script>
export default {
    name: 'BookListAddBooksDialog',
    props: {
        value: { type: Boolean, default: false },
        booklistId: { type: [Number, String], required: true },
        existingBookIds: { type: Array, default: () => [] },
    },
    data() {
        return {
            query: '',
            searching: false,
            searched: false,
            results: [],
            pending: null,
            addedIds: new Set(),
        };
    },
    computed: {
        internalValue: {
            get() { return this.value; },
            set(v) { this.$emit('input', v); },
        },
    },
    watch: {
        value(v) {
            if (v) {
                this.addedIds = new Set(this.existingBookIds || []);
            }
        },
    },
    methods: {
        isAdded(bookId) {
            return this.addedIds.has(bookId);
        },
        close() {
            this.internalValue = false;
        },
        async search() {
            const name = (this.query || '').trim();
            if (!name) return;
            this.searching = true;
            this.searched = true;
            try {
                const rsp = await this.$backend(`/search?name=${encodeURIComponent(name)}`);
                this.results = (rsp && rsp.books) || [];
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
                this.results = [];
            } finally {
                this.searching = false;
            }
        },
        async addBook(book) {
            this.pending = book.id;
            try {
                const rsp = await this.$backend(`/booklist/${this.booklistId}/books/add`, {
                    method: 'POST',
                    body: JSON.stringify({ book_id: book.id }),
                });
                if (rsp.err === 'ok') {
                    this.addedIds.add(book.id);
                    this.addedIds = new Set(this.addedIds);
                    this.$emit('book-added', book);
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.pending = null;
            }
        },
        async removeBook(book) {
            this.pending = book.id;
            try {
                const rsp = await this.$backend(`/booklist/${this.booklistId}/books/remove`, {
                    method: 'POST',
                    body: JSON.stringify({ book_id: book.id }),
                });
                if (rsp.err === 'ok') {
                    this.addedIds.delete(book.id);
                    this.addedIds = new Set(this.addedIds);
                    this.$emit('book-removed', book);
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.pending = null;
            }
        },
    },
};
</script>

<style scoped>
.addbook-item + .addbook-item {
    border-top: 1px solid rgba(128, 128, 128, 0.15);
}
</style>
