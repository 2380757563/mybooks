<template>
    <div v-if="hasAny" class="book-social-info d-flex flex-wrap align-center mt-1">
        <v-chip v-if="stats.reading_count > 0" small outlined class="mr-2 mb-1">
            <v-icon small left>mdi-book-open-page-variant-outline</v-icon>
            {{ $t('book.readingCount', { count: stats.reading_count }) }}
        </v-chip>
        <v-chip v-if="stats.favorite_count > 0" small outlined class="mr-2 mb-1">
            <v-icon small left>mdi-heart</v-icon>
            {{ $t('book.favoriteCount', { count: stats.favorite_count }) }}
        </v-chip>
        <v-chip v-if="stats.recommend_count > 0" small outlined class="mb-1">
            <v-icon small left>mdi-thumb-up</v-icon>
            {{ $t('book.recommendCount', { count: stats.recommend_count }) }}
        </v-chip>
    </div>
</template>

<script>
export default {
    props: {
        bookId: {
            type: [Number, String],
            required: true,
        },
    },
    data() {
        return {
            stats: { reading_count: 0, favorite_count: 0, recommend_count: 0 },
        };
    },
    computed: {
        hasAny() {
            return this.stats.reading_count > 0 || this.stats.favorite_count > 0 || this.stats.recommend_count > 0;
        },
    },
    watch: {
        bookId: {
            immediate: true,
            handler() {
                this.load();
            },
        },
    },
    methods: {
        async load() {
            if (!this.bookId) return;
            try {
                const rsp = await this.$backend(`/book/${this.bookId}/social-stats`);
                if (rsp.err === "ok") {
                    this.stats = {
                        reading_count: rsp.reading_count || 0,
                        favorite_count: rsp.favorite_count || 0,
                        recommend_count: rsp.recommend_count || 0,
                    };
                }
            } catch (e) {
                // 非关键信息，静默失败即可，不影响页面其它部分
            }
        },
        refresh() {
            this.load();
        },
    },
};
</script>
