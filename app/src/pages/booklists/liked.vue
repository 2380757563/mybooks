<template>
    <div>
        <h2 class="mb-4">{{ $t('booklist.likedBooklistsTitle') }}</h2>

        <v-progress-circular v-if="loading" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>
        <p v-else-if="booklists.length === 0" class="grey--text text-center my-6">{{ $t('booklist.noLikedBooklists') }}</p>
        <v-row v-else>
            <v-col v-for="b in booklists" :key="b.id" cols="12" md="6">
                <BookListCard :booklist="b" @toggle-like="toggleLike" />
            </v-col>
        </v-row>
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
        };
    },
    head() {
        return { title: this.$t('booklist.likedBooklistsTitle') };
    },
    mounted() {
        this.fetchBooklists();
    },
    methods: {
        async fetchBooklists() {
            this.loading = true;
            try {
                const rsp = await this.$backend('/booklists/liked');
                if (rsp.err === 'ok') {
                    this.booklists = rsp.booklists;
                } else if (rsp.err === 'user.need_login') {
                    this.$router.push('/login');
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.loading = false;
            }
        },
        async toggleLike(b) {
            try {
                const rsp = await this.$backend(`/booklist/${b.id}/like`, { method: 'POST' });
                if (rsp.err === 'ok' && !rsp.liked) {
                    // 取消点赞后从"收藏书单"列表移除
                    this.booklists = this.booklists.filter(item => item.id !== b.id);
                } else if (rsp.err !== 'ok') {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
    },
};
</script>
