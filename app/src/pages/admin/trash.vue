<template>
  <v-card>
    <v-card-title>{{ $t('adminTrash.pageTitle') }}</v-card-title>
    <v-card-text class="pt-0">
      <p class="text-body-2 grey--text">{{ $t('adminTrash.description') }}</p>
    </v-card-text>
    <v-card-actions class="pa-4">
      <v-row no-gutters>
        <v-col cols="12" class="d-flex flex-wrap ga-2 mb-2 align-center">
          <v-btn
            :disabled="loading"
            :outlined="$vuetify.breakpoint.xs"
            color="primary"
            @click="fetchItems"
            class="flex-shrink-0 mr-2 mb-2"
            :icon="$vuetify.breakpoint.xs"
            :small="$vuetify.breakpoint.xs"
          >
            <v-icon>mdi-reload</v-icon>
            <span v-if="!$vuetify.breakpoint.xs">{{ $t('adminTrash.refresh') }}</span>
          </v-btn>
          <v-btn
            v-if="!loading && selected.length > 0"
            color="primary"
            @click="restoreSelected"
            class="flex-shrink-0 mr-2 mb-2"
            :icon="$vuetify.breakpoint.xs"
            :small="$vuetify.breakpoint.xs"
          >
            <v-icon>mdi-restore</v-icon>
            <span v-if="!$vuetify.breakpoint.xs">{{ $t('adminTrash.restoreSelected') }}</span>
          </v-btn>
          <v-btn
            v-if="!loading && selected.length > 0"
            color="#9f353a"
            @click="purgeConfirmDialog = true"
            class="flex-shrink-0 mr-2 mb-2"
            :icon="$vuetify.breakpoint.xs"
            :small="$vuetify.breakpoint.xs"
          >
            <v-icon>mdi-delete</v-icon>
            <span v-if="!$vuetify.breakpoint.xs">{{ $t('adminTrash.purgeSelected') }}</span>
          </v-btn>
          <span v-if="selected.length > 0" class="caption grey--text flex-shrink-0">
            {{ $t('adminTrash.selectedCount', { count: selected.length }) }}
          </span>
        </v-col>
      </v-row>
    </v-card-actions>

    <v-data-table
      dense
      class="elevation-1 text-body-2"
      show-select
      v-model="selected"
      item-key="book_id"
      :headers="headers"
      :items="items"
      :loading="loading"
      :items-per-page="20"
      :footer-props="{ 'items-per-page-options': [20, 50, 100, -1] }"
      :no-data-text="$t('adminTrash.empty')"
    ></v-data-table>

    <AppDialog
      v-model="purgeConfirmDialog"
      type="confirm"
      :title="$t('adminTrash.purgeConfirmTitle')"
      color="deep-orange"
      confirm-dark
      max-width="400"
      :confirm-text="$t('adminTrash.purgeConfirmButton')"
      @confirm="purgeSelected"
    >
      {{ $t('adminTrash.purgeConfirmMessage', { count: selected.length }) }}
    </AppDialog>
  </v-card>
</template>

<script>
export default {
  data() {
    return {
      items: [],
      selected: [],
      loading: false,
      purgeConfirmDialog: false,
    };
  },
  head() {
    return { title: this.$t('adminTrash.pageTitle') };
  },
  computed: {
    headers() {
      return [
        { text: this.$t('adminTrash.colId'), value: 'book_id', width: '120' },
        { text: this.$t('adminTrash.colTitle'), value: 'title' },
        { text: this.$t('adminTrash.colAuthor'), value: 'author' },
      ];
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    fetchItems() {
      this.loading = true;
      this.$backend('/admin/trash/books')
        .then((rsp) => {
          if (rsp.err !== 'ok') {
            this.$alert('error', rsp.msg);
            return;
          }
          this.items = rsp.books || [];
        })
        .finally(() => {
          this.selected = [];
          this.loading = false;
        });
    },
    restoreSelected() {
      const bookIds = this.selected.map((item) => item.book_id);
      if (bookIds.length === 0) return;
      this.$backend('/admin/trash/books/restore', {
        method: 'POST',
        body: JSON.stringify({ book_ids: bookIds }),
      }).then((rsp) => {
        this.$alert(rsp.err === 'ok' ? 'success' : 'error', rsp.msg);
        this.fetchItems();
      });
    },
    purgeSelected() {
      this.purgeConfirmDialog = false;
      const bookIds = this.selected.map((item) => item.book_id);
      if (bookIds.length === 0) return;
      this.$backend('/admin/trash/books/purge', {
        method: 'POST',
        body: JSON.stringify({ book_ids: bookIds }),
      }).then((rsp) => {
        this.$alert(rsp.err === 'ok' ? 'success' : 'error', rsp.msg);
        this.fetchItems();
      });
    },
  },
};
</script>
