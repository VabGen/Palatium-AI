/**
 * Конфигурация Custom Elements Manifest (`npm run cem`).
 *
 * Анализируется только точка входа виджета: CEM описывает публичный контракт
 * кастомного элемента (тег, атрибуты, методы), а не внутренние компоненты React.
 */
export default {
  globs: ['src/widget.tsx'],
  exclude: [],
  outdir: '.',
  /**
   * `litelement: false` — элемент не на Lit, поэтому не тянем Lit-плагины.
   * Дефолтный `custom-elements` плагин читает `observedAttributes` и JSDoc.
   */
  litelement: false,
  plugins: [],
};
