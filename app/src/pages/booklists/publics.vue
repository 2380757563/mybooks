<template>
    <div>
        <h2 class="mb-4">{{ $t('booklist.publicBooklistsTitle') }}</h2>

        <v-progress-circular v-if="loading && booklists.length === 0" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>
        <p v-else-if="booklists.length === 0" class="grey--text text-center my-6">{{ $t('booklist.noPublicBooklists') }}</p>
        <template v-else>
            <v-row>
                <v-col v-for="b in booklists" :key="b.id" cols="12" md="6">
                    <BookListCard
                        :booklist="b"
                        :show-recommend-badge="true"
                        :is-admin="isAdmin"
                        @toggle-sticky="toggleSticky"
                        @toggle-like="toggleLike"
                    />
                </v-col>
            </v-row>
            <div class="text-center mt-4" v-if="hasMore">
                <v-btn text :loading="loading" @click="loadMore">{{ $t('common.loadMore') }}</v-btn>
            </div>
        </template>
    </div>
</template>

<script>
import BookListCard from '~/components/BookListCard.vue';

export default {
    components: { BookListCard },
    data() {
        return {
            loading: false,
            booklists: [],
            page: 1,
            pageSize: 20,
            total: 0,
        };
    },
    head() {
        return { title: this.$t('booklist.publicBooklistsTitle') };
    },
    computed: {
        isAdmin() {
            return !!this.$store.state.user.is_admin;
        },
        hasMore() {
            return this.booklists.length < this.total;
        },
    },
    mounted() {
        this.fetchBooklists();
    },
    methods: {
        async fetchBooklists() {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/booklists/public?page=${this.page}&page_size=${this.pageSize}`);
                if (rsp.err === 'ok') {
                    this.booklists = this.page === 1 ? rsp.booklists : this.booklists.concat(rsp.booklists);
                    this.total = rsp.total;
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.loading = false;
            }
        },
        loadMore() {
            this.page += 1;
            this.fetchBooklists();
        },
        async toggleSticky(b) {
            try {
                const rsp = await this.$backend(`/booklist/${b.id}/sticky`, {
                    method: 'POST',
                    body: JSON.stringify({ is_sticky: !b.is_sticky }),
                });
                if (rsp.err === 'ok') {
                    b.is_sticky = rsp.booklist.is_sticky;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        async toggleLike(b) {
            try {
                const rsp = await this.$backend(`/booklist/${b.id}/like`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    b.liked_by_me = rsp.liked;
                    b.like_count += rsp.liked ? 1 : -1;
                } else if (rsp.err === 'user.need_login') {
                    this.$router.push('/login');
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
    },
};
</script>
