<template>
  <v-card>
    <v-card-title>
      {{ $t('adminBookReviews.pageTitle') }}
      <v-spacer></v-spacer>
      <v-select
        v-model="status"
        :items="statusOptions"
        dense
        hide-details
        style="max-width: 200px"
        @change="onStatusChange"
      ></v-select>
    </v-card-title>

    <v-data-table
      :headers="headers"
      :items="items"
      :loading="loading"
      :server-items-length="total"
      :options.sync="tableOptions"
      :footer-props="{ 'items-per-page-options': [20, 50, 100] }"
      class="elevation-1"
    >
      <template v-slot:item.status="{ item }">
        <v-chip small :color="statusColor(item.status)" text-color="white">
          {{ statusText(item.status) }}
        </v-chip>
      </template>

      <template v-slot:item.rating="{ item }">
        <v-rating :value="toStars(item.rating)" length="5" readonly dense small color="yellow accent-4"></v-rating>
      </template>

      <template v-slot:item.comment="{ item }">
        <span class="review-comment">{{ item.comment }}</span>
      </template>

      <template v-slot:item.actions="{ item }">
        <template v-if="item.status === 'pending'">
          <v-btn small color="success" class="white--text mr-2 mb-1" @click="moderate(item, 'approve')">
            {{ $t('adminBookReviews.actionApprove') }}
          </v-btn>
          <v-btn small color="error" class="white--text mb-1" @click="moderate(item, 'hide')">
            {{ $t('adminBookReviews.actionHide') }}
          </v-btn>
        </template>
        <v-btn v-else-if="item.status === 'approved'" small color="error" class="white--text mb-1" @click="moderate(item, 'hide')">
          {{ $t('adminBookReviews.actionHide') }}
        </v-btn>
        <v-btn v-else small color="primary" class="white--text mb-1" @click="moderate(item, 'restore')">
          {{ $t('adminBookReviews.actionRestore') }}
        </v-btn>
      </template>
    </v-data-table>
  </v-card>
</template>

<script>
import { toStars } from "~/utils/rating";

export default {
  data() {
    return {
      items: [],
      total: 0,
      loading: false,
      status: '',
      tableOptions: { page: 1, itemsPerPage: 20 },
    };
  },
  head() {
    return { title: this.$t('adminBookReviews.pageTitle') };
  },
  computed: {
    headers() {
      return [
        { text: this.$t('adminBookReviews.colBook'), value: 'book_title', sortable: false, width: '20%' },
        { text: this.$t('adminBookReviews.colUser'), value: 'username', sortable: false, width: '12%' },
        { text: this.$t('adminBookReviews.colRating'), value: 'rating', sortable: false, width: '14%' },
        { text: this.$t('adminBookReviews.colComment'), value: 'comment', sortable: false, width: '25%' },
        { text: this.$t('adminBookReviews.colStatus'), value: 'status', sortable: false, width: '10%' },
        { text: this.$t('adminBookReviews.colActions'), value: 'actions', sortable: false },
      ];
    },
    statusOptions() {
      return [
        { text: this.$t('adminBookReviews.statusAll'), value: '' },
        { text: this.$t('adminBookReviews.statusPending'), value: 'pending' },
        { text: this.$t('adminBookReviews.statusApproved'), value: 'approved' },
        { text: this.$t('adminBookReviews.statusHidden'), value: 'hidden' },
      ];
    },
  },
  watch: {
    tableOptions: {
      handler() {
        this.fetchItems();
      },
      deep: true,
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    toStars,
    statusText(status) {
      if (status === 'pending') return this.$t('adminBookReviews.statusPending');
      if (status === 'approved') return this.$t('adminBookReviews.statusApproved');
      if (status === 'hidden') return this.$t('adminBookReviews.statusHidden');
      return status;
    },
    statusColor(status) {
      if (status === 'pending') return 'orange';
      if (status === 'approved') return 'success';
      if (status === 'hidden') return 'grey';
      return 'grey';
    },
    onStatusChange() {
      this.tableOptions.page = 1;
      this.fetchItems();
    },
    fetchItems() {
      this.loading = true;
      const page = this.tableOptions.page || 1;
      const pageSize = this.tableOptions.itemsPerPage || 20;
      const query = `page=${page}&page_size=${pageSize}` + (this.status ? `&status=${this.status}` : '');
      this.$backend(`/admin/book-reviews?${query}`)
        .then((rsp) => {
          if (rsp.err !== 'ok') {
            this.$alert('error', rsp.msg);
            return;
          }
          this.items = rsp.reviews || [];
          this.total = rsp.total || 0;
        })
        .finally(() => {
          this.loading = false;
        });
    },
    moderate(item, action) {
      this.$backend('/admin/book-reviews', {
        method: 'POST',
        body: JSON.stringify({ id: item.id, action }),
      }).then((rsp) => {
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg);
          return;
        }
        this.$alert('success', rsp.msg);
        this.fetchItems();
      });
    },
  },
};
</script>

<style scoped>
.review-comment {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
