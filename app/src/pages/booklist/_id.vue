<template>
    <div>
        <v-progress-circular v-if="loading && !booklist" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>

        <template v-else-if="booklist">
            <v-card class="booklist-header-card mb-4" :style="{ borderLeftColor: borderColor }">
                <v-card-text>
                    <div class="d-flex align-start flex-wrap">
                        <div class="flex-grow-1" style="min-width: 0">
                            <div class="d-flex align-center flex-wrap">
                                <span class="booklist-header-name">{{ booklist.name }}</span>
                                <v-icon v-if="!booklist.is_public" small class="ml-2" color="grey">mdi-lock-outline</v-icon>
                            </div>
                            <p class="mt-2 mb-2">{{ booklist.description }}</p>
                            <div class="d-flex align-center flex-wrap" style="gap: 16px">
                                <div class="d-flex align-center">
                                    <v-avatar size="28" class="mr-1">
                                        <v-img v-if="booklist.owner && booklist.owner.avatar" :src="booklist.owner.avatar"></v-img>
                                        <v-icon v-else>mdi-account-circle</v-icon>
                                    </v-avatar>
                                    <span class="grey--text text-caption">{{ booklist.owner && booklist.owner.username }}</span>
                                </div>
                                <span><v-icon x-small class="mr-1">mdi-bookmark-outline</v-icon>{{ booklist.book_count }}</span>
                                <span><v-icon x-small class="mr-1">mdi-eye-outline</v-icon>{{ booklist.view_count }}</span>
                                <span class="booklist-like" @click="toggleLike">
                                    <v-icon x-small class="mr-1" :color="booklist.liked_by_me ? 'red' : undefined">{{ booklist.liked_by_me ? 'mdi-heart' : 'mdi-heart-outline' }}</v-icon>{{ booklist.like_count }}
                                </span>
                            </div>
                        </div>
                    </div>
                </v-card-text>
            </v-card>

            <div class="d-flex align-center mb-3 flex-wrap" style="gap: 8px">
                <v-select
                    v-model="order"
                    :items="orderOptions"
                    item-text="text"
                    item-value="value"
                    dense
                    outlined
                    hide-details
                    style="max-width: 200px"
                    @change="reload"
                ></v-select>
                <v-spacer></v-spacer>
                <v-btn v-if="booklist.is_owner" color="primary" @click="addDialog = true">
                    <v-icon left>mdi-book-plus-outline</v-icon>
                    {{ $t('booklist.addBooksTitle') }}
                </v-btn>
            </div>

            <v-row v-if="books.length || booklist.is_owner">
                <v-col v-if="booklist.is_owner" cols="6" sm="4" md="3" lg="2">
                    <v-card class="booklist-add-tile d-flex align-center justify-center" height="100%" @click="addDialog = true">
                        <div class="text-center grey--text">
                            <v-icon large>mdi-plus</v-icon>
                            <div class="text-caption mt-1">{{ $t('booklist.addBooksTitle') }}</div>
                        </div>
                    </v-card>
                </v-col>
                <v-col v-for="b in books" :key="b.book_id" cols="6" sm="4" md="3" lg="2">
                    <v-card class="position-relative">
                        <a :href="b.href" target="_blank">
                            <v-img :src="b.thumb || b.img" :aspect-ratio="11 / 15"></v-img>
                        </a>
                        <div class="text-caption text-truncate pa-1">{{ b.title }}</div>
                        <v-btn
                            v-if="booklist.is_owner"
                            icon
                            class="booklist-remove-btn"
                            @click="confirmRemove(b)"
                        >
                            <v-icon color="white">mdi-close-circle</v-icon>
                        </v-btn>
                    </v-card>
                </v-col>
            </v-row>
            <p v-else class="grey--text text-center my-6">{{ $t('booklist.noBooks') }}</p>

            <div class="text-center mt-4" v-if="hasMore">
                <v-btn text :loading="loading" @click="loadMore">{{ $t('common.loadMore') }}</v-btn>
            </div>

            <BookListAddBooksDialog
                v-model="addDialog"
                :booklist-id="booklist.id"
                :existing-book-ids="books.map(b => b.book_id)"
                @book-added="onBookAdded"
                @book-removed="onBookRemoved"
            />
        </template>

        <p v-else class="grey--text text-center my-6">{{ $t('booklist.notFound') }}</p>
    </div>
</template>

<script>
import BookListAddBooksDialog from '~/components/BookListAddBooksDialog.vue';
import { BOOKLIST_COLORS } from '~/utils/booklistColors';

export default {
    components: { BookListAddBooksDialog },
    data() {
        return {
            loading: false,
            booklist: null,
            books: [],
            page: 1,
            pageSize: 24,
            booksTotal: 0,
            order: 'desc',
            addDialog: false,
        };
    },
    head() {
        return { title: this.booklist ? this.booklist.name : this.$t('booklist.myBooklistsTitle') };
    },
    computed: {
        orderOptions() {
            return [
                { text: this.$t('booklist.orderDesc'), value: 'desc' },
                { text: this.$t('booklist.orderAsc'), value: 'asc' },
            ];
        },
        borderColor() {
            const c = BOOKLIST_COLORS.find(item => item.key === (this.booklist && this.booklist.color)) || BOOKLIST_COLORS[0];
            return this.$vuetify.theme.dark ? c.dark : c.light;
        },
        hasMore() {
            return this.books.length < this.booksTotal;
        },
    },
    mounted() {
        this.fetchDetail();
        this.bumpView();
    },
    methods: {
        async fetchDetail() {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/booklist/${this.$route.params.id}?order=${this.order}&page=${this.page}&page_size=${this.pageSize}`);
                if (rsp.err === 'ok') {
                    this.booklist = rsp.booklist;
                    this.books = this.page === 1 ? rsp.booklist.books : this.books.concat(rsp.booklist.books);
                    this.booksTotal = rsp.booklist.books_total;
                } else {
                    this.booklist = null;
                    this.$alert('error', rsp.msg || this.$t('booklist.notFound'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.loading = false;
            }
        },
        bumpView() {
            this.$backend(`/booklist/${this.$route.params.id}/view`, { method: 'POST' }).catch(() => {});
        },
        reload() {
            this.page = 1;
            this.fetchDetail();
        },
        loadMore() {
            this.page += 1;
            this.fetchDetail();
        },
        async toggleLike() {
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/like`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    this.booklist.liked_by_me = rsp.liked;
                    this.booklist.like_count += rsp.liked ? 1 : -1;
                } else if (rsp.err === 'user.need_login') {
                    this.$router.push('/login');
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        confirmRemove(book) {
            if (!confirm(this.$t('booklist.removeConfirmText', { title: book.title }))) return;
            this.removeBook(book);
        },
        async removeBook(book) {
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/books/remove`, {
                    method: 'POST',
                    body: JSON.stringify({ book_id: book.book_id }),
                });
                if (rsp.err === 'ok') {
                    this.books = this.books.filter(b => b.book_id !== book.book_id);
                    this.booklist.book_count = rsp.book_count;
                    this.booksTotal -= 1;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        onBookAdded() {
            this.page = 1;
            this.fetchDetail();
        },
        onBookRemoved() {
            this.page = 1;
            this.fetchDetail();
        },
    },
};
</script>

<style scoped>
.booklist-header-card {
    border-left-width: 4px;
    border-left-style: solid;
}
.booklist-header-name {
    font-size: 28px;
    font-weight: 700;
}
.booklist-like {
    cursor: pointer;
}
.booklist-add-tile {
    cursor: pointer;
    border: 2px dashed rgba(128, 128, 128, 0.4);
    min-height: 140px;
}
.position-relative {
    position: relative;
}
.booklist-remove-btn {
    position: absolute;
    top: 1px;
    right: 1px;
    background: rgba(0, 0, 0, 0.5);
}
</style>
