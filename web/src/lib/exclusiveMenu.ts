/** Client-side exclusive-menu heuristic (mirrors domain menu_shaped, not phrase lists). */

import type { ContentDocument, KeyValueItem } from '../types/contentDocument';

const MIN_OPTIONS = 2;
const MAX_OPTIONS = 12;
const MAX_FRAMING = 3;

function kvLooksLikeChoiceMenu(items: readonly KeyValueItem[]): boolean {
  if (items.length < MIN_OPTIONS || items.length > MAX_OPTIONS) return false;
  let expansions = 0;
  for (const item of items) {
    if (item.value.trim().length > 160) return false;
    const label = item.label.trim().toLocaleLowerCase();
    const value = item.value.trim().toLocaleLowerCase();
    if (value === label || value.startsWith(label)) expansions += 1;
  }
  return expansions >= Math.max(MIN_OPTIONS, Math.ceil(items.length / 2));
}

/**
 * True when the document looks like an exclusive option menu that should have
 * become HITL cards. Used only for a DEV gap banner — server remains source of truth.
 */
export function looksLikeExclusiveMenu(document: ContentDocument | null | undefined): boolean {
  if (!document) return false;
  if (document.meta?.interaction === 'choice' || document.meta?.interaction === 'confirm') {
    return true;
  }

  const lists = document.blocks.filter(block => block.type === 'list');
  const steps = document.blocks.filter(block => block.type === 'steps');
  const callouts = document.blocks.filter(block => block.type === 'callout');
  const kvs = document.blocks.filter(block => block.type === 'kv');

  let optionCount = 0;
  let optionKind: 'list' | 'steps' | 'callout' | 'kv' | null = null;
  if (lists.length === 1 && steps.length === 0 && kvs.length === 0) {
    optionCount = lists[0].items.filter(item => item.text.trim()).length;
    optionKind = 'list';
  } else if (steps.length === 1 && lists.length === 0) {
    // Domain: steps = howto timeline, not exclusive picker (W10).
    return false;
  } else if (
    kvs.length === 1 &&
    lists.length === 0 &&
    steps.length === 0 &&
    kvLooksLikeChoiceMenu(kvs[0].items)
  ) {
    optionCount = kvs[0].items.length;
    optionKind = 'kv';
  } else if (
    lists.length === 0 &&
    steps.length === 0 &&
    kvs.length === 0 &&
    callouts.length >= MIN_OPTIONS
  ) {
    const other = document.blocks.filter(
      block =>
        block.type !== 'callout' &&
        block.type !== 'heading' &&
        block.type !== 'paragraph' &&
        block.type !== 'divider'
    );
    if (other.length === 0) {
      optionCount = callouts.filter(block => (block.title || block.body).trim()).length;
      optionKind = 'callout';
    }
  } else {
    return false;
  }

  if (optionCount < MIN_OPTIONS || optionCount > MAX_OPTIONS) {
    return false;
  }

  let framing = 0;
  for (const block of document.blocks) {
    if (block.type === 'list' || block.type === 'steps' || block.type === 'callout') {
      continue;
    }
    if (optionKind === 'kv' && block.type === 'kv') {
      continue;
    }
    if (block.type === 'heading' || block.type === 'paragraph' || block.type === 'divider') {
      framing += 1;
      continue;
    }
    return false;
  }
  return framing <= MAX_FRAMING;
}
