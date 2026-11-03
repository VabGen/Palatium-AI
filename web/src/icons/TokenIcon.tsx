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
import { useReducedMotion } from '../lib/motion';
import dangerAnim from '../lottie/danger.json';
import infoAnim from '../lottie/info.json';
import successAnim from '../lottie/success.json';
import warningAnim from '../lottie/warning.json';
// Отдельных lottie-файлов для check/x/clock/shield пока нет — используются
// приближения (см. LOTTIE_BY_TOKEN ниже). Когда файлы появятся, раскомментировать
// и заменить значения в таблице:
// import checkAnim  from '../lottie/check.json';
// import xAnim      from '../lottie/x.json';
// import clockAnim  from '../lottie/clock.json';
// import shieldAnim from '../lottie/shield.json';

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

/**
 * Lottie-анимации только для сценарных/статусных токенов.
 * Контентные токены (calendar, mail, document, user, chart, ...)
 * намеренно остаются статичными — анимация контента ухудшает UX.
 *
 * Политика (контракт, не «на будущее»):
 * | Категория | Токены | Анимировать |
 * | Статус / сценарий | info, success, warning, danger, check, x, clock, shield | да |
 * | Контент | calendar, mail, search, document, user, users, chart, link, edit, settings | нет |
 *
 * Отдельных .json для check/x/clock/shield пока нет — используются приближения
 * из существующих статусных файлов. Когда появятся — заменить значения здесь
 * (импорты ниже) и убрать приближения; сигнатуру таблицы менять не нужно.
 */
const LOTTIE_BY_TOKEN: Partial<Record<IconToken, object>> = {
  // Прямые соответствия
  info: infoAnim,
  success: successAnim,
  warning: warningAnim,
  danger: dangerAnim,

  // Приближения через существующие файлы — заменить,
  // когда появятся отдельные .json (check/x/clock/shield)
  check: successAnim, // approve / confirm
  x: dangerAnim, // reject / dismiss / blocked step
  clock: infoAnim, // pending / active step
  shield: infoAnim, // семантический акцент
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
  // `in` walks the prototype chain: 'constructor' / '__proto__' / 'toString' are
  // "in" any object literal too, and `TOKEN_MAP['constructor']` is `Object`, not a
  // Lucide component — rendering it crashes the tree. Own-property check only.
  if (Object.hasOwn(TOKEN_MAP, raw)) return { known: raw as IconToken, raw };
  return { known: null, raw };
}

export function TokenIcon({
  token,
  className,
  size = 18,
  animated = false,
  turnId = null,
}: TokenIconProps) {
  // Хук — до любого раннего `return`: порядок хуков не должен зависеть от того,
  // оказался ли токен пустым или анимируемым (правила react-hooks).
  const reduceMotion = useReducedMotion();
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

  // `prefers-reduced-motion` (084): при выключенном движении берём статичный
  // Lucide-глиф, а НЕ приостановленный Lottie. Приостановленный Lottie рисует
  // пустой кадр (`autoplay={false}` не отрисовывает ни одного кадра) — статус
  // пропадал бы целиком. Так пользователь получает тот же смысл без движения,
  // а rAF-цикл библиотеки вообще не запускается.
  const lottieData =
    animated && !reduceMotion && Object.hasOwn(LOTTIE_BY_TOKEN, resolved)
      ? LOTTIE_BY_TOKEN[resolved]
      : undefined;
  if (lottieData) {
    return (
      <span
        className={['token-lottie', className].filter(Boolean).join(' ')}
        style={{ width: size, height: size, display: 'inline-flex' }}
        aria-hidden
      >
        {/*
          `autoplay` обязателен: в `lottie-react` он по умолчанию `false`, и без
          него библиотека честно рисует первый кадр и останавливается — иконка
          «анимированная» только по имени. При `prefers-reduced-motion` до этой
          ветки дело не доходит: Lottie не монтируется вовсе (см. выше), поэтому
          rAF-цикл не запускается даже на один кадр.

          `loop={false}` — WCAG 2.2.2: иконка стартует сама, поэтому она не имеет
          права двигаться бесконечно. Статус сообщается первым проходом; вечная
          пульсация — декоративный шум рядом с читаемым текстом.
        */}
        <LottieLight
          src={lottieData}
          loop={false}
          autoplay={!reduceMotion}
          style={{ width: size, height: size }}
        />
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
