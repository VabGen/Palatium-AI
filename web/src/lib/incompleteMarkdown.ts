/**
 * Close incomplete markdown constructs for streaming pending preview (FOIM).
 * Final UI still uses ContentDocument / BlockRenderer — this is preview-only.
 *
 * Canonical implementation: ``closeDanglingMarkdown`` in ``./markdown``.
 */
export { closeDanglingMarkdown as closeIncompleteMarkdown } from './markdown';
