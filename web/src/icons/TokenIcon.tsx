import { LottieSvg } from 'lottie-react';
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

type TokenIconProps = {
  token?: IconToken | null;
  className?: string;
  size?: number;
  animated?: boolean;
};

export function TokenIcon({ token, className, size = 18, animated = false }: TokenIconProps) {
  if (!token) return null;

  const lottieData = animated ? LOTTIE_BY_TOKEN[token] : undefined;
  if (lottieData) {
    return (
      <span
        className={['token-lottie', className].filter(Boolean).join(' ')}
        style={{ width: size, height: size, display: 'inline-flex' }}
        aria-hidden
      >
        <LottieSvg src={lottieData} loop style={{ width: size, height: size }} />
      </span>
    );
  }

  const Icon = TOKEN_MAP[token];
  if (!Icon) return null;
  return (
    <Icon
      size={size}
      className={[className, animated ? 'icon-animated' : ''].filter(Boolean).join(' ')}
      aria-hidden
    />
  );
}
