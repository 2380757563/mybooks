<template>
    <div>
        <div class="d-flex align-center mb-4">
            <h2 class="mb-0">{{ $t('booklist.myBooklistsTitle') }}</h2>
            <v-spacer></v-spacer>
            <v-btn color="primary" @click="openCreate">
                <v-icon left>mdi-plus</v-icon>
                {{ $t('booklist.createNew') }}
            </v-btn>
        </div>

        <v-progress-circular v-if="loading" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>
        <p v-else-if="booklists.length === 0" class="grey--text text-center my-6">{{ $t('booklist.noBooklistsYet') }}</p>
        <v-row v-else>
            <v-col v-for="b in booklists" :key="b.id" cols="12" md="6">
                <BookListCard
                    :booklist="b"
                    :show-manage="true"
                    :is-admin="isAdmin"
                    @edit="openEdit"
                    @delete="confirmDelete"
                    @toggle-visibility="toggleVisibility"
                    @change-color="changeColor"
                    @toggle-sticky="toggleSticky"
                    @toggle-like="toggleLike"
                />
            </v-col>
        </v-row>

        <BookListEditDialog v-model="editDialog" :mode="editMode" :booklist="editing" @saved="onSaved" />

        <v-dialog v-model="deleteDialog" max-width="400">
            <v-card>
                <v-card-title class="headline">{{ $t('booklist.deleteConfirmTitle') }}</v-card-title>
                <v-card-text>{{ $t('booklist.deleteConfirmText', { name: deleting && deleting.name }) }}</v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="deleteDialog = false">{{ $t('common.cancel') }}</v-btn>
                    <v-btn color="red" text :loading="deleting_loading" @click="doDelete">{{ $t('common.delete') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
import BookListCard from '~/components/BookListCard.vue';
import BookListEditDialog from '~/components/BookListEditDialog.vue';

export default {
    components: { BookListCard, BookListEditDialog },
    data() {
        return {
            loading: false,
            booklists: [],
            editDialog: false,
            editMode: 'create',
            editing: null,
            deleteDialog: false,
            deleting: null,
            deleting_loading: false,
        };
    },
    head() {
        return { title: this.$t('booklist.myBooklistsTitle') };
    },
    computed: {
        isAdmin() {
            return !!this.$store.state.user.is_admin;
        },
    },
    mounted() {
        this.fetchBooklists();
    },
    methods: {
        async fetchBooklists() {
            this.loading = true;
            try {
                const rsp = await this.$backend('/booklists/mine');
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
        openCreate() {
            this.editMode = 'create';
            this.editing = null;
            this.editDialog = true;
        },
        openEdit(b) {
            this.editMode = 'edit';
            this.editing = b;
            this.editDialog = true;
        },
        onSaved() {
            this.fetchBooklists();
        },
        confirmDelete(b) {
            this.deleting = b;
            this.deleteDialog = true;
        },
        async doDelete() {
            if (!this.deleting) return;
            this.deleting_loading = true;
            try {
                const rsp = await this.$backend(`/booklist/${this.deleting.id}/delete`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                    this.deleteDialog = false;
                    this.fetchBooklists();
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.deleting_loading = false;
            }
        },
        async toggleVisibility(b) {
            try {
                const rsp = await this.$backend(`/booklist/${b.id}/update`, {
                    method: 'POST',
                    body: JSON.stringify({ is_public: !b.is_public }),
                });
                if (rsp.err === 'ok') {
                    b.is_public = !b.is_public;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        async changeColor({ booklist, color }) {
            try {
                const rsp = await this.$backend(`/booklist/${booklist.id}/update`, {
                    method: 'POST',
                    body: JSON.stringify({ color }),
                });
                if (rsp.err === 'ok') {
                    booklist.color = color;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
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
