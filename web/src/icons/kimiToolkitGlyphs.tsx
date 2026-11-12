import type { SVGProps } from 'react';

/**
 * kimi.ai `.toolkit-item` (composer `+` menu) icon family — 24px grid, idle
 * frame extracted from the live page. Geometry is verbatim: strokes are baked
 * with their own `matrix(...)`/`translate(...)` transforms, so do not retarget
 * the paths by hand — re-extract instead.
 */
export type KimiToolkitName = keyof typeof TOOLKIT_GLYPHS;

type Glyph = { props: Record<string, string>; inner: string };

const TOOLKIT_GLYPHS = {
  /* `ArtboardTimeline1Icon` — «Add files & images». */
  addFiles: {
    props: {},
    inner:
      '<path d="M 5.6 -5.15 C 5.6 -5.15 5.6 3.25 5.6 3.25 C 5.6 6.343 3.093 8.85 0 8.85 C -3.093 8.85 -5.6 6.343 -5.6 3.25 C -5.6 3.25 -5.6 -5.15 -5.6 -5.15 C -5.6 -7.193 -3.943 -8.85 -1.9 -8.85 C 0.144 -8.85 1.8 -7.193 1.8 -5.15 C 1.8 -5.15 1.8 3.349 1.8 3.349 C 1.8 4.371 0.972 5.199 -0.05 5.199 C -1.072 5.199 -1.9 4.371 -1.9 3.349 C -1.9 3.349 -1.9 -5.15 -1.9 -5.15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" style="transform-box:view-box;transform-origin:0 0;transform:translate(50%,48.9583%)"></path>',
  },
  /* `PlugIn2Timeline2Icon`. */
  plugins: {
    props: {},
    inner:
      '<path d="M 9.752 -15.268 C 10.103 -15.62 10.674 -15.62 11.025 -15.268 C 11.377 -14.917 11.377 -14.346 11.025 -13.995 C 11.025 -13.995 8.904 -11.874 8.904 -11.874 C 8.88 -11.85 8.855 -11.829 8.829 -11.808 C 8.829 -11.808 11.807 -8.831 11.807 -8.831 C 11.827 -8.856 11.85 -8.881 11.874 -8.905 C 11.874 -8.905 13.995 -11.026 13.995 -11.026 C 14.347 -11.377 14.917 -11.377 15.269 -11.026 C 15.62 -10.674 15.62 -10.104 15.269 -9.752 C 15.269 -9.752 13.147 -7.631 13.147 -7.631 C 13.124 -7.608 13.098 -7.585 13.072 -7.565 C 13.072 -7.565 13.147 -7.49 13.147 -7.49 C 14.28 -6.357 14.28 -4.521 13.147 -3.388 C 13.147 -3.388 11.025 -1.267 11.025 -1.267 C 8.721 1.037 4.986 1.037 2.682 -1.267 C 2.682 -1.267 2.606 -1.342 2.606 -1.342 C 2.586 -1.316 2.564 -1.291 2.54 -1.267 C 2.54 -1.267 -0.995 2.268 -0.995 2.268 C -1.347 2.62 -1.917 2.62 -2.269 2.268 C -2.62 1.917 -2.62 1.346 -2.269 0.995 C -2.269 0.995 1.267 -2.54 1.267 -2.54 C 1.29 -2.564 1.315 -2.586 1.341 -2.607 C 1.341 -2.607 1.267 -2.681 1.267 -2.681 C -1.037 -4.985 -1.037 -8.722 1.267 -11.026 C 1.267 -11.026 3.389 -13.147 3.389 -13.147 C 4.521 -14.279 6.358 -14.279 7.49 -13.147 C 7.49 -13.147 7.564 -13.073 7.564 -13.073 C 7.585 -13.098 7.607 -13.123 7.631 -13.147 C 7.631 -13.147 9.752 -15.268 9.752 -15.268 Z M 6.217 -11.874 C 5.787 -12.303 5.092 -12.303 4.662 -11.874 C 4.662 -11.874 2.54 -9.752 2.54 -9.752 C 0.939 -8.151 0.939 -5.556 2.54 -3.955 C 2.54 -3.955 3.955 -2.54 3.955 -2.54 C 5.556 -0.94 8.151 -0.94 9.752 -2.54 C 9.752 -2.54 11.874 -4.662 11.874 -4.662 C 12.303 -5.091 12.304 -5.788 11.874 -6.217 C 11.874 -6.217 6.217 -11.874 6.217 -11.874 Z" transform="matrix(1 0 0 1 5.5 18.5)" fill="currentColor" fill-rule="evenodd"></path>',
  },
  /* `SkillTimeline1Icon`. */
  skills: {
    props: {},
    inner:
      '<path d="M 5.215 -8.119 C 6.375 -8.119 7.316 -7.179 7.316 -6.02 C 7.316 -6.02 7.316 4.52 7.316 4.52 L 9.116 4.52 C 9.116 4.52 9.116 -6.02 9.116 -6.02 C 9.116 -8.173 7.369 -9.92 5.215 -9.92 C 5.215 -9.92 -5.989 -9.92 -5.989 -9.92 C -7.811 -9.92 -9.116 -8.159 -8.584 -6.415 C -8.584 -6.415 -8.376 -5.729 -8.376 -5.729 C -8.232 -5.254 -7.728 -4.986 -7.252 -5.131 C -6.777 -5.276 -6.509 -5.779 -6.654 -6.254 C -6.654 -6.254 -6.863 -6.939 -6.863 -6.939 C -7.042 -7.526 -6.602 -8.119 -5.989 -8.119 C -5.989 -8.119 -5.783 -8.119 -5.783 -8.119 C -5.783 -8.119 -5.783 6.52 -5.783 6.52 C -5.783 8.397 -4.261 9.92 -2.383 9.92 C -2.383 9.92 5.715 9.92 5.715 9.92 L 5.715 8.12 C 5.715 8.12 -2.383 8.12 -2.383 8.12 C -3.267 8.12 -3.983 7.403 -3.983 6.52 C -3.983 6.52 -3.983 -8.119 -3.983 -8.119 C -3.983 -8.119 5.215 -8.119 5.215 -8.119 Z" fill="currentColor" transform="matrix(1 0 0 1 10.704 11.92)"></path><path d="M 5.8 -2.895 C 6.352 -2.895 6.799 -2.448 6.8 -1.895 C 6.8 -1.895 6.8 -1.006 6.8 -1.006 C 6.8 1.148 5.054 2.895 2.9 2.895 C 2.9 2.895 -6.8 2.895 -6.8 2.895 C -6.8 2.895 -6.8 1.096 -6.8 1.096 C -6.59 1.096 -6.382 1.05 -6.191 0.963 C -6.191 0.963 -6.088 0.916 -6.088 0.916 C -5.381 0.593 -4.927 -0.112 -4.927 -0.89 C -4.927 -0.89 -4.927 -1.95 -4.927 -1.95 C -4.927 -2.472 -4.504 -2.895 -3.982 -2.895 C -3.982 -2.895 5.8 -2.895 5.8 -2.895 Z M -3.127 -0.89 C -3.127 -0.173 -3.331 0.51 -3.692 1.096 C -3.692 1.096 2.9 1.096 2.9 1.096 C 4.06 1.095 5 0.155 5 -1.005 C 5 -1.005 5 -1.095 5 -1.095 L -3.127 -1.095 C -3.127 -1.095 -3.127 -0.89 -3.127 -0.89 Z" fill="currentColor" transform="matrix(1 0 0 1 14.997 18.944)"></path><path d="M -3.925 0.244 C -3.415 0.042 -2.851 -0.94 -2.514 -2.663 C -2.202 -0.476 -1.072 2.648 0.776 -2.663 C 0.234 0.016 3.347 2.041 4.02 -2.663" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" transform="matrix(1 0 0 1 12.42 11.657)"></path>',
  },
  /* `TaskSubagentTaskIcon` — three orbiting dots + rails. */
  swarm: {
    props: {},
    inner:
      '<path d="M 0 -2 C 1.105 -2 2 -1.105 2 0 C 2 1.105 1.105 2 0 2 C -1.105 2 -2 1.105 -2 0 C -2 -1.105 -1.105 -2 0 -2 Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" transform="matrix(-1 0 0 -1 4.955 9.452)"></path><path d="M 0 -2 C 1.105 -2 2 -1.105 2 0 C 2 1.105 1.105 2 0 2 C -1.105 2 -2 1.105 -2 0 C -2 -1.105 -1.105 -2 0 -2 Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(-1 0 0 -1 19.045 9.452)"></path><path d="M 0 -2 C 1.105 -2 2 -1.105 2 0 C 2 1.105 1.105 2 0 2 C -1.105 2 -2 1.105 -2 0 C -2 -1.105 -1.105 -2 0 -2 Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(-1 0 0 -1 12 5.779)"></path><path d="M 0 2.305 L 0 -2.305" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(1 0 0 1 12 10.714)"></path><path d="M -3.535 4.43 C -3.535 4.43 -3.535 -0.012 -3.535 -0.012 C -3.535 -0.123 -3.446 -0.212 -3.335 -0.212 C -3.335 -0.212 1.535 -0.212 1.535 -0.212 C 2.64 -0.212 3.535 -1.108 3.535 -2.212 C 3.535 -2.212 3.535 -4.43 3.535 -4.43" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(1 0 0 1 15.535 16.485)"></path><path d="M 1.72 2.49 C 1.72 2.49 0.28 2.49 0.28 2.49 C -0.825 2.49 -1.72 1.595 -1.72 0.49 C -1.72 0.49 -1.72 -2.109 -1.72 -2.109" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(1 0 0 0.95 6.707 14.058)"></path>',
  },
  /* `Goal2Timeline1Icon` — target arcs + flag. */
  goal: {
    props: {},
    inner:
      '<path d="M 8.648 -3.102 C 8.877 -2.308 9 -1.469 9 -0.602 C 9 4.369 4.971 8.398 0 8.398 C -4.971 8.398 -9 4.369 -9 -0.602 C -9 -3.268 -7.841 -5.662 -6 -7.31 C -5.54 -7.722 -5.038 -8.087 -4.5 -8.398" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(1 0 0 1 11.9 13.002)"></path><path d="M -3.077 -3.677 C -3.774 -2.945 -4.218 -1.965 -4.259 -0.875 C -4.35 1.498 -2.499 3.496 -0.126 3.586 C 2.248 3.677 4.245 1.826 4.336 -0.547 C 4.35 -0.918 4.317 -1.28 4.241 -1.627" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="miter" transform="matrix(1 0 0 1 11.889 13.156)"></path><path d="M -3.313 5.092 L -3.313 -5.092 L 3.313 -1.43 L -2.755 1.639" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="transform-box:view-box;transform-origin:0 0;transform:translate(63.3875%,31.22083%)"></path>',
  },
} satisfies Record<string, Glyph>;

export type KimiToolkitGlyphProps = SVGProps<SVGSVGElement> & {
  name: KimiToolkitName;
  size?: number;
};

export function KimiToolkitGlyph({ name, size = 18, ...rest }: KimiToolkitGlyphProps) {
  const glyph = TOOLKIT_GLYPHS[name];
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      focusable="false"
      {...glyph.props}
      {...rest}
      // eslint-disable-next-line @eslint-react/dom-no-dangerously-set-innerhtml -- static committed geometry extracted from kimi.ai; never user input
      dangerouslySetInnerHTML={{ __html: glyph.inner }}
    />
  );
}
