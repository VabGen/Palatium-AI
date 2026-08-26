import { TokenIcon } from "../icons/TokenIcon";
import type { WidgetBlock } from "../types/contentDocument";

type WidgetEmbedProps = {
  block: WidgetBlock;
};

/**
 * Generic embed card. Product-specific renderers (EDMS, calendar, …) belong in
 * optional UI plugins / MCP adapters — not hardcoded in the core chat shell.
 */
function safeHttpHref(href: string): string | null {
  try {
    const parsed = new URL(href);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return href;
    }
  } catch {
    return null;
  }
  return null;
}

export function WidgetEmbed({ block }: WidgetEmbedProps) {
  const label = block.title ?? block.ref_id;
  const ctaHref = block.href?.trim() ? safeHttpHref(block.href.trim()) : null;

  return (
    <div className="widget-embed kind-generic">
      <div className="widget-icon">
        <TokenIcon token="link" size={22} />
      </div>
      <div className="widget-body">
        <p className="widget-kind">{block.kind}</p>
        <strong>{label}</strong>
        <p className="widget-ref">{block.ref_id}</p>
      </div>
      {ctaHref ? (
        <a className="widget-cta" href={ctaHref} target="_blank" rel="noopener noreferrer">
          Open
        </a>
      ) : null}
    </div>
  );
}
