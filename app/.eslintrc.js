module.exports = {
    root: true,
    env: {
        browser: true,
        node: true,
        es2021: true,
    },
    extends: [
        'eslint:recommended',
        'plugin:vue/essential', // Vue 2 正确性规则集，不含格式化类规则（存量代码格式不统一，先不引入）
    ],
    parserOptions: {
        ecmaVersion: 2021,
        sourceType: 'module',
    },
    rules: {
        'vue/no-v-for-template-key': 'off', // Disable the rule

        // 命名规范：JS 标识符（变量/函数/data/methods/computed 等）用小驼峰。
        // properties: 'never' 不检查对象属性名/字符串 key（如 localStorage key、
        // 后端返回字段名 book_id 等本就是 snake_case 的场景不受影响）。
        camelcase: ['warn', { properties: 'never', ignoreDestructuring: true }],
        'vue/prop-name-casing': ['warn', 'camelCase'],
        // Vuetify 全局组件按惯例用 kebab-case 标签（<v-btn> 等），不强制模板里用 PascalCase
        'vue/component-name-in-template-casing': 'off',

        // 现有代码量大，先降级为 warn 观察存量问题，不阻断构建；新代码应尽量避免。
        'no-unused-vars': 'warn',
        'vue/multi-word-component-names': 'off', // 页面级组件（如 book/_bookid.vue）天然单词，不强制
        'vue/no-v-html': 'off', // 项目大量使用 v-html 渲染富文本简介等，已知取舍
        // Vuetify v-data-table 官方推荐写法 <template v-slot:item.columnName="{ item }">，
        // 插件把 ".columnName" 误判成 v-slot 不支持的修饰符，属已知误报，关闭该规则
        'vue/valid-v-slot': 'off',
    },
};
