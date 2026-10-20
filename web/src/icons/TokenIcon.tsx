import { LottieLight } from 'lottie-react';
import type { LucideIcon } from 'lucide-react';
import {
  AlertTriangle,
  Calendar,
  Check,
  Clock,
  FileText,
  Info,
  Link2,
  Mail,
  Pencil,
  Search,
  Settings,
  Shield,
  CircleAlert,
  CircleCheck,
  User,
  Users,
  BarChart3,
  X,
} from 'lucide-react';
import type { IconToken } from '../types/contentDocument';
import dangerAnim from '../lottie/danger.json';
import infoAnim from '../lottie/info.json';
import successAnim from '../lottie/success.json';
import warningAnim from '../lottie/warning.json';

const TOKEN_MAP: Record<IconToken, LucideIcon> = {
  calendar: Calendar,
  mail: Mail,
  search: Search,
  document: FileText,
  warning: AlertTriangle,
  success: CircleCheck,
  danger: CircleAlert,
  info: Info,
  user: User,
  users: Users,
  clock: Clock,
  chart: BarChart3,
  shield: Shield,
  check: Check,
  x: X,
  link: Link2,
  edit: Pencil,
  settings: Settings,
};

const LOTTIE_BY_TOKEN: Partial<Record<IconToken, object>> = {
  success: successAnim,
  warning: warningAnim,
  danger: dangerAnim,
  info: infoAnim,
  check: successAnim,
};

/** Default when LLM invents a name outside the allow-list — never render raw tags. */
const FALLBACK_ICON: LucideIcon = Info;
const FALLBACK_TOKEN: IconToken = 'info';

type TokenIconProps = {
  /** Known IconToken, or raw string from stream (unknown → fallback + warn). */
  token?: IconToken | string | null;
  className?: string;
  size?: number;
  animated?: boolean;
  /** Optional turn correlation for warn logs (Path C). */
  turnId?: string | null;
};

function resolveToken(token: IconToken | string | null | undefined): {
  known: IconToken | null;
  raw: string | null;
} {
  if (token == null || token === '') return { known: null, raw: null };
  const raw = String(token).trim().toLowerCase();
  if (!raw) return { known: null, raw: null };
  if (raw in TOKEN_MAP) return { known: raw as IconToken, raw };
  return { known: null, raw };
}

export function TokenIcon({
  token,
  className,
  size = 18,
  animated = false,
  turnId = null,
}: TokenIconProps) {
  const { known, raw } = resolveToken(token);
  if (raw == null && known == null) return null;

  const resolved: IconToken = known ?? FALLBACK_TOKEN;
  if (!known && raw) {
    console.warn('[TokenIcon] unknown icon name; using fallback', {
      name: raw,
      turnId,
      fallback: FALLBACK_TOKEN,
    });
  }

  const lottieData = animated ? LOTTIE_BY_TOKEN[resolved] : undefined;
  if (lottieData) {
    return (
      <span
        className={['token-lottie', className].filter(Boolean).join(' ')}
        style={{ width: size, height: size, display: 'inline-flex' }}
        aria-hidden
      >
        {/*
          LottieLight, а не полный/LottieSvg: анимации статусов (info/success/
          warning/danger) не используют expression-движок (проверено: 0 маркеров
          `x` в JSON), а light-сборка меньше на ~30% и не тянет `eval` — важно для
          бюджета виджета и CSP страницы-хоста.
        */}
        <LottieLight src={lottieData} loop style={{ width: size, height: size }} />
      </span>
    );
  }

  const Icon = TOKEN_MAP[resolved] ?? FALLBACK_ICON;
  return (
    <Icon
      size={size}
      className={[className, animated ? 'icon-animated' : ''].filter(Boolean).join(' ')}
      aria-hidden
    />
  );
}
