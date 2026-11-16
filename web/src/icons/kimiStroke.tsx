import type { SVGProps } from 'react';

/** Shared props for Kimi chrome icons — stroke 1.5px, no fill (K5). */
export type KimiIconProps = SVGProps<SVGSVGElement> & { size?: number };

function base(size: number): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
  };
}

/** kimi.ai menu iconify glyphs — filled paths on 1024 grid (Edit / PinToTop / Delete). */
function filledBase(size: number): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 1024 1024',
    fill: 'currentColor',
    'aria-hidden': true,
  };
}

export function IconPlus({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconPanelLeft({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </svg>
  );
}

export function IconMessage({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7A2.5 2.5 0 0 1 17.5 16H10l-4 3v-3H6.5A2.5 2.5 0 0 1 4 13.5v-7Z" />
    </svg>
  );
}

export function IconAddConversation({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7A2.5 2.5 0 0 1 17.5 16H10l-4 3v-3H6.5A2.5 2.5 0 0 1 4 13.5v-7Z" />
      <path d="M12 7.5v4M10 9.5h4" />
    </svg>
  );
}

export function IconChevronDown({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function IconGlobe({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

export function IconBrain({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M9.5 4.5a3 3 0 0 0-3 3v1a3 3 0 0 0-1.5 2.6V14a3 3 0 0 0 3 3h.5M14.5 4.5a3 3 0 0 1 3 3v1a3 3 0 0 1 1.5 2.6V14a3 3 0 0 1-3 3H15" />
      <path d="M9.5 8.5h5M10 12h4M10.5 17.5v2M13.5 17.5v2" />
    </svg>
  );
}

export function IconSpark({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  );
}

export function IconUser({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="9" r="3.5" />
      <path d="M5 19.5a7 7 0 0 1 14 0" />
    </svg>
  );
}

/** kimi.ai iconify ``Setting`` — gear for «Настройки» (1024 filled). */
export function IconSettings({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M677.4784 524.288a165.4784 165.4784 0 1 0-330.9568 0 165.4784 165.4784 0 0 0 330.9568 0z m-74.46528 0a91.01312 91.01312 0 1 1-182.0672 0 91.01312 91.01312 0 0 1 182.0672 0z" />
      <path d="M426.43456 925.696a80.6912 80.6912 0 0 1-57.5488-45.38368l-17.69472-38.33856c-7.61856-16.46592-26.13248-26.66496-45.8752-24.61696l-43.33568 4.5056a82.24768 82.24768 0 0 1-68.52608-24.73984 402.80064 402.80064 0 0 1-51.32288-67.29728 393.46176 393.46176 0 0 1-35.47136-76.22656 77.53728 77.53728 0 0 1 12.4928-72.37632l25.76384-33.5872a37.84704 37.84704 0 0 0 0-46.6944l-25.96864-33.87392a77.49632 77.49632 0 0 1-12.36992-72.704A405.54496 405.54496 0 0 1 193.3312 251.61728a82.24768 82.24768 0 0 1 68.68992-24.90368l43.29472 4.5056c19.74272 2.048 38.25664-8.192 45.8752-24.576l17.57184-38.0928a80.73216 80.73216 0 0 1 57.38496-45.34272 444.98944 444.98944 0 0 1 171.37664-0.36864 80.6912 80.6912 0 0 1 57.58976 45.42464l17.69472 38.33856c7.61856 16.46592 26.13248 26.66496 45.8752 24.61696l43.33568-4.5056a82.24768 82.24768 0 0 1 68.52608 24.73984c19.6608 20.8896 36.78208 43.29472 51.32288 67.29728 14.49984 24.00256 26.29632 49.43872 35.47136 76.22656a77.53728 77.53728 0 0 1-12.4928 72.37632l-25.76384 33.5872a37.84704 37.84704 0 0 0 0 46.6944l25.96864 33.83296c15.9744 20.80768 21.01248 48.00512 12.36992 72.74496a405.504 405.504 0 0 1-86.75328 142.7456 82.24768 82.24768 0 0 1-68.68992 24.90368l-43.29472-4.5056c-19.74272-2.048-38.25664 8.192-45.8752 24.576l-17.57184 38.0928a80.73216 80.73216 0 0 1-57.38496 45.34272c-56.85248 11.264-115.0976 11.34592-171.4176 0.36864z m156.95872-73.35936a6.3488 6.3488 0 0 0 4.25984-3.56352l17.57184-38.05184c21.0944-45.71136 70.16448-72.74496 121.15968-67.46112l43.29472 4.5056c3.03104 0.32768 5.57056-0.57344 6.5536-1.6384a331.03872 331.03872 0 0 0 70.8608-116.49024c0.12288-0.32768-0.04096-1.4336-1.14688-2.8672l-25.92768-33.792a112.31232 112.31232 0 0 1 0-137.37984l25.72288-33.5872c1.10592-1.39264 1.31072-2.4576 1.14688-2.8672a319.0784 319.0784 0 0 0-28.75392-61.8496 328.4992 328.4992 0 0 0-41.86112-54.8864c-1.024-1.06496-3.52256-1.92512-6.5536-1.6384l-43.33568 4.5056c-50.9952 5.3248-100.06528-21.7088-121.15968-67.42016l-17.73568-38.37952a6.22592 6.22592 0 0 0-4.17792-3.52256 370.52416 370.52416 0 0 0-142.70464 0.28672 6.30784 6.30784 0 0 0-4.25984 3.56352l-17.57184 38.05184C397.7216 283.56608 348.65152 310.59968 297.61536 305.31584l-43.29472-4.5056c-3.03104-0.32768-5.57056 0.57344-6.5536 1.6384a331.07968 331.07968 0 0 0-70.8608 116.49024c-0.12288 0.32768 0.08192 1.4336 1.14688 2.8672l25.92768 33.792a112.31232 112.31232 0 0 1 0 137.37984l-25.72288 33.5872c-1.06496 1.39264-1.26976 2.4576-1.14688 2.8672 7.49568 21.83168 17.03936 42.47552 28.75392 61.8496 11.75552 19.41504 25.72288 37.6832 41.86112 54.8864 1.024 1.06496 3.56352 1.92512 6.5536 1.6384l43.33568-4.5056c51.03616-5.3248 100.06528 21.7088 121.15968 67.42016l17.73568 38.37952a6.22592 6.22592 0 0 0 4.17792 3.52256 370.64704 370.64704 0 0 0 142.70464-0.28672z" />
    </svg>
  );
}

/** kimi.ai iconify ``Switch`` — dual sliders for «Настроить боковую панель». */
export function IconSidebarCustomize({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M624.469333 520.32c78.933333 0 145.066667 55.04 162.133334 128.810667l-0.170667-0.810667h70.656a38.442667 38.442667 0 0 1 0 76.842667h-70.656l0.341333-1.706667a166.442667 166.442667 0 0 1-324.266666 1.706667H166.997333l-3.925333-0.213334a38.4 38.4 0 0 1 0-76.373333l3.925333-0.256h295.594667c17.322667-73.386667 83.2-128 161.92-128z m0 76.842667a89.6 89.6 0 1 0 0 179.2 89.6 89.6 0 0 0 0-179.2zM402.048 170.837333a166.442667 166.442667 0 0 1 162.304 129.578667l-0.341333-1.578667h293.077333l3.925333 0.213334a38.4 38.4 0 0 1 0 76.373333l-3.925333 0.256h-293.12a166.442667 166.442667 0 0 1-323.84 0H166.954667a38.485333 38.485333 0 0 1-38.442667-38.4c0-21.248 17.237333-38.4 38.442667-38.442667h73.173333c17.322667-73.386667 83.2-128 161.92-128z m0 76.8a89.6 89.6 0 1 0 0 179.2 89.6 89.6 0 0 0 0-179.2z" />
    </svg>
  );
}

export function IconCheck({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m5 12 4.5 4.5L19 7" />
    </svg>
  );
}

export function IconArrowUp({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" />
    </svg>
  );
}

export function IconX({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

/** kimi.ai header iconify `Clip` (1024 filled). */
export function IconPaperclip({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M239.08352 319.0784a188.17024 188.17024 0 0 1 376.29952 0v0.16384l4.62848 347.62752v0.08192a112.64 112.64 0 0 1-156.0576 105.63584 112.55808 112.55808 0 0 1-68.97664-105.39008V315.14624a36.864 36.864 0 1 1 73.728 0v352.99328a38.83008 38.83008 0 1 0 77.57824 0v-0.16384l-4.58752-347.58656V320.3072a114.4832 114.4832 0 0 0-228.88448-0.4096l4.5056 347.58656a190.13632 190.13632 0 1 0 380.3136 0l0.4096-334.39744a36.864 36.864 0 1 1 73.728 0.08192l-0.4096 334.31552a263.90528 263.90528 0 0 1-450.43712 186.61376 263.86432 263.86432 0 0 1-77.29152-186.368l-4.54656-347.50464v-1.10592z" />
    </svg>
  );
}

export function IconFolder({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M3.75 7.25A1.75 1.75 0 0 1 5.5 5.5h3.9l1.7 1.85H18.5A1.75 1.75 0 0 1 20.25 9.1v7.65A1.75 1.75 0 0 1 18.5 18.5H5.5A1.75 1.75 0 0 1 3.75 16.75V7.25Z" />
      <path d="M3.75 10.25h16.5" />
    </svg>
  );
}

export function IconPin({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      {/* kimi.ai menu — thin pushpin (round head + tapered body + needle). */}
      <path d="M12 17v5" />
      <path d="M8 2h8l-1 7 3 2v2H6v-2l3-2L8 2Z" />
    </svg>
  );
}

/** kimi.ai chat menu «Закрепить сверху» — iconify `PinToTop` (1024). */
export function IconPinTop({ size = 18, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M576 554.666667h160.341333a4.266667 4.266667 0 0 0 3.029334-7.253334l-2.986667-3.072-48.341333-48.298666-18.176-18.176-151.850667-151.850667a8.533333 8.533333 0 0 0-12.032 0L354.133333 477.866667l-18.176 18.176L287.573333 544.426667l-2.986666 2.986666a4.266667 4.266667 0 0 0 2.986666 7.253334H448v290.133333c0 4.736 3.84 8.533333 8.533333 8.533333h110.933334a8.533333 8.533333 0 0 0 8.533333-8.533333V554.666667z m160.384 76.8H652.8v213.333333a85.333333 85.333333 0 0 1-85.333333 85.333333h-110.933334a85.333333 85.333333 0 0 1-85.333333-85.333333v-213.333333H287.616c-72.192 0-108.373333-87.338667-57.301333-138.410667l221.354666-221.312a85.333333 85.333333 0 0 1 120.661334 0l221.354666 221.312c51.072 51.072 14.933333 138.410667-57.301333 138.410667zM256 89.6a38.4 38.4 0 0 0 0 76.8h512a38.4 38.4 0 1 0 0-76.8H256z" />
    </svg>
  );
}

export function IconCircle({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="12" r="7.5" />
    </svg>
  );
}

export function IconFileText({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M14 3H7.5A1.5 1.5 0 0 0 6 4.5v15A1.5 1.5 0 0 0 7.5 21h9a1.5 1.5 0 0 0 1.5-1.5V8.5L14 3Z" />
      <path d="M14 3v5.5H21M9 13h6M9 17h4" />
    </svg>
  );
}

export function IconDownload({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 4v10M8 10l4 4 4-4M5 19h14" />
    </svg>
  );
}

/** kimi.ai Expand — enter fullscreen preview. */
export function IconExpand({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M9 4H4v5M15 4h5v5M9 20H4v-5M20 15v5h-5" />
    </svg>
  );
}

/** Exit fullscreen — corners point inward. */
export function IconCompress({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M9 9H4M9 9V4M15 9h5M15 9V4M9 15H4M9 15v5M15 15h5M15 15v5" />
    </svg>
  );
}

/** kimi.ai Magnify / Minify — preview zoom. */
export function IconZoomIn({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M16 16l4 4M10.5 8v5M8 10.5h5" />
    </svg>
  );
}

export function IconZoomOut({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M16 16l4 4M8 10.5h5" />
    </svg>
  );
}

/** kimi.ai Pages — toggle file list inside the preview rail. */
export function IconPages({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="8" y="4" width="12" height="16" rx="2" />
      <path d="M5 7v12a2 2 0 0 0 2 2h9" />
    </svg>
  );
}

export function IconCopy({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="8" y="8" width="11" height="11" rx="1.5" />
      <path d="M5 15V5.5A1.5 1.5 0 0 1 6.5 4H15" />
    </svg>
  );
}

export function IconThumbsUp({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M7 11v9H4.5A1.5 1.5 0 0 1 3 18.5v-6A1.5 1.5 0 0 1 4.5 11H7Zm0 0 3.2-6.5A2 2 0 0 1 12 3.5h.3a1.7 1.7 0 0 1 1.6 2.2L13.2 11H19a2 2 0 0 1 2 2.3l-.8 5A2 2 0 0 1 18.2 20H7" />
    </svg>
  );
}

export function IconThumbsDown({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M7 13V4H4.5A1.5 1.5 0 0 0 3 5.5v6A1.5 1.5 0 0 0 4.5 13H7Zm0 0 3.2 6.5A2 2 0 0 0 12 20.5h.3a1.7 1.7 0 0 0 1.6-2.2L13.2 13H19a2 2 0 0 0 2-2.3l-.8-5A2 2 0 0 0 18.2 4H7" />
    </svg>
  );
}

/** kimi.ai iconify `Refresh` (1024 filled) — regenerate answer. */
export function IconRotateCw({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M303.104 315.392c114.688-114.688 303.104-114.688 417.792 0l-32.768 32.768c-20.48 20.48-4.096 57.344 24.576 57.344h118.784c16.384 0 32.768-16.384 32.768-32.768V253.952c0-28.672-36.864-45.056-57.344-24.576l-32.768 32.768c-143.36-143.36-376.832-143.36-520.192 0s-143.36 376.832 0 520.192 376.832 143.36 520.192 0c49.152-49.152 77.824-106.496 94.208-163.84 4.096-20.48-8.192-40.96-24.576-45.056-20.48-4.096-40.96 8.192-45.056 24.576-12.288 49.152-36.864 94.208-77.824 131.072-114.688 114.688-303.104 114.688-417.792 0-114.688-110.592-114.688-299.008 0-413.696z" />
    </svg>
  );
}

export function IconLoader({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 3.5a8.5 8.5 0 1 1-7.4 4.3" />
    </svg>
  );
}

export function IconListChecks({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M10 7h10M10 12h10M10 17h10M4.5 7.5 6 9l3-3M4.5 12.5 6 14l3-3M4.5 17.5 6 19l3-3" />
    </svg>
  );
}

export function IconShieldAlert({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 3 5 6v5c0 4.5 2.9 7.4 7 9 4.1-1.6 7-4.5 7-9V6l-7-3Z" />
      <path d="M12 9v4M12 16h.01" />
    </svg>
  );
}

/** kimi.ai menu iconify `Edit` (1024) — pencil + baseline. */
export function IconPencil({ size = 18, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M736.085333 222.592a46.165333 46.165333 0 0 1 65.322667 65.28L336.426667 752.938667a132.266667 132.266667 0 0 1-61.44 34.773333l-51.541334 12.885333 12.885334-51.541333a132.266667 132.266667 0 0 1 34.773333-61.44L736.085333 222.592z m32.682667-90.325333c-32.64 0-63.914667 12.970667-86.997333 36.010666L216.832 633.258667a209.066667 209.066667 0 0 0-55.04 97.152l-28.373333 113.621333a38.4 38.4 0 0 0 46.549333 46.549333l113.621333-28.416a209.066667 209.066667 0 0 0 97.152-54.997333l361.813334-361.813333 103.168-103.125334A122.965333 122.965333 0 0 0 768.768 132.266667zM512 814.933333a38.4 38.4 0 1 0 0 76.8h298.666667a38.4 38.4 0 1 0 0-76.8h-298.666667z" />
    </svg>
  );
}

/** kimi.ai menu iconify `Delete` (1024) — lid + can + inner bars. */
export function IconTrash({ size = 18, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M352.256 155.648c0-20.48 16.384-36.864 36.864-36.864h245.76c20.48 0 36.864 16.384 36.864 36.864s-16.384 36.864-36.864 36.864H389.12c-20.48 0-36.864-16.384-36.864-36.864zM430.08 684.032c-20.48 0-36.864-16.384-36.864-36.864v-204.8c0-20.48 16.384-36.864 36.864-36.864s36.864 16.384 36.864 36.864v204.8c0 20.48-16.384 36.864-36.864 36.864zM557.056 647.168c0 20.48 16.384 36.864 36.864 36.864s36.864-16.384 36.864-36.864v-204.8c0-20.48-16.384-36.864-36.864-36.864s-36.864 16.384-36.864 36.864v204.8z" />
      <path d="M880.64 241.664H143.36c-20.48 0-36.864 16.384-36.864 36.864s16.384 36.864 36.864 36.864h49.152l40.96 483.328c4.096 49.152 45.056 90.112 98.304 90.112h364.544c49.152 0 94.208-40.96 98.304-90.112l40.96-483.328H880.64c20.48 0 36.864-16.384 36.864-36.864s-16.384-36.864-36.864-36.864z m-159.744 548.864c0 12.288-12.288 24.576-24.576 24.576h-368.64c-12.288 0-24.576-8.192-24.576-24.576L266.24 315.392h491.52l-36.864 475.136z" />
    </svg>
  );
}

export function IconMic({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6" />
    </svg>
  );
}

export function IconMonitor({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="2.75" y="3.75" width="18.5" height="12.5" rx="2.25" />
      <path d="M8.5 20.25h7M12 16.25v4" />
      <path d="M6.5 14.25h11" opacity="0.35" />
    </svg>
  );
}

export function IconLightbulb({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.8c.6.5 1 1.2 1.1 2h4.8c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3Z" />
    </svg>
  );
}

export function IconSearch({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

export function IconCompass({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="12" r="9" />
      <path d="m15.5 8.5-2 6-6 2 2-6 6-2Z" />
    </svg>
  );
}

export function IconBriefcase({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 12h18" />
    </svg>
  );
}

export function IconGrid({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1" />
    </svg>
  );
}

export function IconWand({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m15 4 1.5 3L20 8.5 16.5 10 15 13l-1.5-3L10 8.5 13.5 7 15 4ZM5 14l7-7 2.5 2.5-7 7L5 14Z" />
    </svg>
  );
}

export function IconCube({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 3 4.5 7.5v9L12 21l7.5-4.5v-9L12 3Z" />
      <path d="M12 12 4.5 7.5M12 12l7.5-4.5M12 12v9" />
    </svg>
  );
}

export function IconSlides({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3" y="5" width="18" height="12" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  );
}

export function IconHammer({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m15 5 4 4-3 3-4-4 3-3ZM5.5 18.5 12 12M9 19l2 2" />
    </svg>
  );
}

export function IconClaw({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M8.2 10.4c-1.7-1-3.5-2.9-2.6-4.6.8-1.5 3.1-.6 4.3.7M15.8 10.4c1.7-1 3.5-2.9 2.6-4.6-.8-1.5-3.1-.6-4.3.7" />
      <path d="M12 8.5c2.9 0 5.2 2.3 5.2 5.2 0 2.9-2.3 5.3-5.2 5.3s-5.2-2.4-5.2-5.3c0-2.9 2.3-5.2 5.2-5.2Z" />
      <path d="M10 13v.6M14 13v.6M11 16c.6.4 1.4.4 2 0" />
    </svg>
  );
}

export function IconLink({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 1 0-5.7-5.7l-1.1 1.1" />
      <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 1 0 5.7 5.7l1.1-1.1" />
    </svg>
  );
}

export function IconCalendar({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M8 3v4M16 3v4M3.5 10h17" />
    </svg>
  );
}

export function IconHeart({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M12 20s-7-4.4-7-9.2A3.8 3.8 0 0 1 12 8a3.8 3.8 0 0 1 7 2.8C19 15.6 12 20 12 20Z" />
    </svg>
  );
}

export function IconMoreHorizontal({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="6" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconSpeaker({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M4 10v4h3.5L12 18V6L7.5 10H4Z" />
      <path d="M15.5 9.5a3.5 3.5 0 0 1 0 5M17.5 7a6 6 0 0 1 0 10" />
    </svg>
  );
}

/** kimi.ai header iconify `Share_a` (1024 filled). */
export function IconShare({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...filledBase(size)} {...rest}>
      <path d="M386.218667 247.850667c0-102.4 120.405333-157.397333 197.76-90.282667l304.426666 264.32a119.466667 119.466667 0 0 1 1.365334 179.285333l-304.469334 272.170667c-76.970667 68.778667-199.082667 14.122667-199.082666-89.088v-89.173333c-33.024 2.261333-59.306667 6.826667-83.2 15.36-30.592 10.88-61.866667 29.952-98.602667 67.712a76.8 76.8 0 0 1-131.84-53.504c0-98.645333 24.106667-190.976 83.712-261.888 55.253333-65.792 133.973333-104.789333 229.930667-117.845334V247.850667z m147.413333-32.256c-27.648-23.978667-70.613333-4.352-70.613333 32.256v126.208l-0.256 4.309333c-2.218667 21.504-20.437333 38.186667-42.410667 40.021333l-17.194667 1.706667c-173.994667 20.949333-253.824 136.405333-253.824 304.554667 86.997333-89.557333 163.925333-105.386667 270.933334-107.861334a42.026667 42.026667 0 0 1 42.752 42.24v125.226667c0 34.56 38.272 53.845333 65.706666 35.925333l5.376-4.096 304.426667-272.213333a42.666667 42.666667 0 0 0 2.986667-60.714667l-3.413334-3.285333-304.469333-264.277333z" />
    </svg>
  );
}

export function IconStop({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconChevronLeft({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m15 6-6 6 6 6" />
    </svg>
  );
}

export function IconChevronRight({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function IconCluster({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="8" cy="8" r="2.5" />
      <circle cx="16" cy="8" r="2.5" />
      <circle cx="12" cy="16" r="2.5" />
      <path d="M9.8 9.5 11 14M14.2 9.5 13 14M10.5 8h3" />
    </svg>
  );
}

/** kimi.ai profile menu glyphs — same 24 grid, 1.5 stroke as the chrome set. */
export function IconCrown({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M4 8.6 7.2 12 12 6.2 16.8 12 20 8.6V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8.6Z" />
    </svg>
  );
}

export function IconGift({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <rect x="3.5" y="9" width="17" height="3.5" rx="1" />
      <path d="M5 12.5V18a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5.5M12 9v11" />
      <path d="M12 9S10.7 5 8.7 5a2 2 0 0 0 0 4H12Zm0 0s1.3-4 3.3-4a2 2 0 0 1 0 4H12Z" />
    </svg>
  );
}

export function IconInfo({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11.2v5.3M12 8h.01" />
    </svg>
  );
}

export function IconInbox({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <path d="M4 13.6 6.3 5.9A2 2 0 0 1 8.2 4.5h7.6a2 2 0 0 1 1.9 1.4L20 13.6V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4.4Z" />
      <path d="M4 13.6h4l1.1 2h5.8l1.1-2h4" />
    </svg>
  );
}

export function IconHelp({ size = 16, ...rest }: KimiIconProps) {
  return (
    <svg {...base(size)} {...rest}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.7 9.5a2.4 2.4 0 1 1 3.3 2.2c-.7.3-1 .8-1 1.5v.4M12 16.6h.01" />
    </svg>
  );
}

/** Product mark — rounded square with P (Palatium). */
export function IconBrandMark({ size = 20, ...rest }: KimiIconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <rect width="24" height="24" rx="6" fill="var(--kimi-ink)" />
      <path
        d="M8.2 17V7h4.1c2.2 0 3.6 1.2 3.6 3.1 0 1.9-1.4 3.1-3.6 3.1H10.5V17H8.2Zm2.3-5.4h1.7c1.1 0 1.7-.5 1.7-1.4s-.6-1.4-1.7-1.4h-1.7v2.8Z"
        fill="var(--kimi-white)"
      />
    </svg>
  );
}

/** Assistant face avatar — brand blue circle with two dots. */
export function IconAssistantFace({ size = 28, ...rest }: KimiIconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden {...rest}>
      <circle cx="14" cy="14" r="14" fill="var(--kimi-brand-blue)" />
      <circle cx="10.5" cy="14" r="2" fill="var(--kimi-white)" />
      <circle cx="17.5" cy="14" r="2" fill="var(--kimi-white)" />
    </svg>
  );
}
