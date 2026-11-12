import type { MessageKey } from '../i18n/messages';

/**
 * Состояние ожидания ответа: какой режим орба показывать и что озвучить.
 *
 * Паттерн Big Tech (ChatGPT / Claude / Gemini / Copilot): пока ответа нет,
 * в ленте живёт не «облако с подписью», а сама марка ассистента — и она
 * МЕНЯЕТСЯ по ходу работы. Здесь этим управляет единственный реальный сигнал
 * пайплайна: SSE-событие `hop`, которое `intent_graph_runner.py` отдаёт на
 * СТАРТЕ каждого узла графа LangGraph (`stream_mode="tasks"`). Никаких таймеров
 * и «угадывания» фазы: подпись называет шаг, который выполняется сейчас.
 *
 * Визуал — `ThinkingOrb` из `thinking-orbs` (`state` = режим анимации);
 * `label` озвучивается через `role="status"` (084).
 *
 * Таблица — маппинг id узла → фаза, а не эвристика по тексту запроса (055):
 * перечень узлов закрыт реестром `core/types/graph_nodes.py`. Неизвестный
 * узел падает на нейтральную фазу.
 */

/**
 * Режимы `ThinkingOrb.state` (подмножество библиотеки), которые мы реально
 * мапим с узлов графа. Источник имён — thinking-orbs; перечень здесь закрыт
 * под наш пайплайн (не импортируем чужой OrbState как SoT продукта).
 */
export type PendingOrbState =
  'working' | 'weaving' | 'connecting' | 'searching' | 'solving' | 'composing' | 'shaping';

export interface PendingPhase {
  readonly state: PendingOrbState;
  readonly label: MessageKey;
}

/**
 * Нейтральная фаза: до первого `hop` и для узлов, которых виджет ещё не знает.
 */
export const DEFAULT_PENDING_PHASE: PendingPhase = {
  state: 'working',
  label: 'msg.pending.thinking',
};

/**
 * Ключи — `GraphNodeId` бэкенда; намеренно `string`: чужой узел не ошибка.
 *
 * Визуальный режим и подпись независимы, поэтому «похожие» узлы делят один
 * режим, но озвучиваются по-своему: `shaping` (перебор форм) читается как
 * «проверяю/уточняю» — отсюда подбор файлов и критика.
 */
const NODE_PHASES: Readonly<Record<string, PendingPhase>> = {
  context_enricher_continuation: { state: 'weaving', label: 'msg.pending.context' },
  context_enricher_weaving: { state: 'weaving', label: 'msg.pending.context' },
  intent_classifier: { state: 'working', label: 'msg.pending.thinking' },
  attachment_selection: { state: 'shaping', label: 'msg.pending.files' },
  memory_mutation: { state: 'connecting', label: 'msg.pending.memory' },
  supervisor: { state: 'weaving', label: 'msg.pending.planning' },
  researcher: { state: 'searching', label: 'msg.pending.searching' },
  coder: { state: 'solving', label: 'msg.pending.solving' },
  analyst: { state: 'solving', label: 'msg.pending.solving' },
  parallel_workers: { state: 'connecting', label: 'msg.pending.workers' },
  critic: { state: 'shaping', label: 'msg.pending.checking' },
  quality_revision: { state: 'solving', label: 'msg.pending.revision' },
  formatter: { state: 'composing', label: 'msg.pending.composing' },
};

/**
 * Фаза для узла графа; `null` (ещё ни одного `hop`) — нейтральная.
 *
 * `Object.hasOwn`, а не `NODE_PHASES[node] ?? DEFAULT`: индекс по недоверенной
 * строке из SSE проходит и по цепочке прототипов, и `node="constructor"` вернул
 * бы `Object` (truthy) — тогда орб получил бы функцию вместо фазы, а подпись
 * `role="status"` пропала бы молча.
 */
export function pendingPhaseForNode(node: string | null): PendingPhase {
  if (node === null || !Object.hasOwn(NODE_PHASES, node)) return DEFAULT_PENDING_PHASE;
  return NODE_PHASES[node] ?? DEFAULT_PENDING_PHASE;
}
