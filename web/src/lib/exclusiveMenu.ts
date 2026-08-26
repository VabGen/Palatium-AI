/** Client-side exclusive-menu heuristic (mirrors domain menu_shaped, not phrase lists). */

import type { ContentDocument } from "../types/contentDocument";

const MIN_OPTIONS = 2;
const MAX_OPTIONS = 12;
const MAX_FRAMING = 3;

/**
 * True when the document looks like an exclusive option menu that should have
 * become HITL cards. Used only for a DEV gap banner — server remains source of truth.
 */
export function looksLikeExclusiveMenu(document: ContentDocument | null | undefined): boolean {
  if (!document) return false;
  if (document.meta?.interaction === "choice" || document.meta?.interaction === "confirm") {
    return true;
  }

  const lists = document.blocks.filter((block) => block.type === "list");
  const steps = document.blocks.filter((block) => block.type === "steps");
  const callouts = document.blocks.filter((block) => block.type === "callout");

  let optionCount = 0;
  if (lists.length === 1 && steps.length === 0) {
    optionCount = lists[0].items.filter((item) => item.text.trim()).length;
  } else if (steps.length === 1 && lists.length === 0) {
    optionCount = steps[0].items.filter((item) => item.title.trim()).length;
  } else if (lists.length === 0 && steps.length === 0 && callouts.length >= MIN_OPTIONS) {
    const other = document.blocks.filter(
      (block) =>
        block.type !== "callout" &&
        block.type !== "heading" &&
        block.type !== "paragraph" &&
        block.type !== "divider",
    );
    if (other.length === 0) {
      optionCount = callouts.filter((block) => (block.title || block.body).trim()).length;
    }
  } else {
    return false;
  }

  if (optionCount < MIN_OPTIONS || optionCount > MAX_OPTIONS) {
    return false;
  }

  let framing = 0;
  for (const block of document.blocks) {
    if (block.type === "list" || block.type === "steps" || block.type === "callout") {
      continue;
    }
    if (block.type === "heading" || block.type === "paragraph" || block.type === "divider") {
      framing += 1;
      continue;
    }
    return false;
  }
  return framing <= MAX_FRAMING;
}
