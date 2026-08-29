// 书单颜色色板（8 色，Z-Library 命名风格），见 document/BookList_Design.md §2.3。
// 存库/传输用 key，这里映射到亮/暗模式下的具体 hex，供 BookListCard / BookListEditDialog 使用。

export const BOOKLIST_COLORS = [
    { key: 'marine', labelKey: 'booklist.color.marine', light: '#1B6E8C', dark: '#4FA8C7' },
    { key: 'velvet', labelKey: 'booklist.color.velvet', light: '#7D3C5E', dark: '#B0577F' },
    { key: 'night_blue', labelKey: 'booklist.color.night_blue', light: '#1A2456', dark: '#4A5A9E' },
    { key: 'green', labelKey: 'booklist.color.green', light: '#2E7D32', dark: '#66BB6A' },
    { key: 'yellow', labelKey: 'booklist.color.yellow', light: '#F9A825', dark: '#FDD835' },
    { key: 'red', labelKey: 'booklist.color.red', light: '#C62828', dark: '#EF5350' },
    { key: 'purple', labelKey: 'booklist.color.purple', light: '#6A1B9A', dark: '#AB47BC' },
    { key: 'orange', labelKey: 'booklist.color.orange', light: '#EF6C00', dark: '#FFA726' },
];

export const DEFAULT_BOOKLIST_COLOR = 'marine';

export function booklistColorHex(key, dark) {
    const found = BOOKLIST_COLORS.find(c => c.key === key) || BOOKLIST_COLORS[0];
    return dark ? found.dark : found.light;
}
