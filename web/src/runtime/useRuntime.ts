import { useSyncExternalStore } from 'react';
import { getRuntimeSnapshot, subscribeRuntime, type AssistantRuntime } from './store';

/** Подписка React-компонентов на runtime-состояние виджета. */
export function useAssistantRuntime(): AssistantRuntime {
  return useSyncExternalStore(subscribeRuntime, getRuntimeSnapshot, getRuntimeSnapshot);
}
