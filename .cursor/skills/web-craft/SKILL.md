---
name: web-craft
description: >
  Индекс внешних скиллов по UI-полировке и анимации (Emil Kowalski,
  emilkowalski/skills) для фронтенда AI-ассистента. Используй, когда нужно
  решить, какой из установленных animation/design-скиллов вызвать.
  Сами скиллы (emil-design-eng, animate, animate-expo, improve-animations,
  find-animation-opportunities, apple-design, pick-ui-library) НЕ входят
  в этот файл — они устанавливаются официальным CLI в соседние папки
  `.cursor/skills/<name>/`.
---

# Web Craft — внешние скиллы UI/анимации

## Стек фронтенда

Проект использует React 18 + Vite (SPA) + Tailwind CSS, пакет `web/`. Это накладывает следующие ограничения/особенности:

- **`animate-expo` НЕ используется** — в проекте нет Expo/React Native.
- Vite — чистый клиентский рендеринг, без RSC/App Router гидратации → оговорки `emil-design-eng` про `useEffect`+`mounted` вместо `@starting-style` можно применять без поправок на серверный рендеринг.
- В `pick-ui-library` пункт про `cva` (typed-варианты для Tailwind) — прямое попадание в наш стек.

## Состояние скиллов

✅ Все перечисленные ниже скиллы уже установлены в `.cursor/skills/` и готовы к использованию.
🔧 Установка выполнена через официальный CLI; повторная установка не требуется.

## Что делает каждый скилл (краткое описание)

| Скилл | Роль | Когда вызывать |
|-------|------|----------------|
| `emil-design-eng` | Общая философия полировки интерфейса: когда деталь того стоит, как оценивать «на глаз» тональность/отклик компонентов. Верхнеуровневый, не даёт готовых значений | Общие вопросы по вкусу/полировке UI, не привязанные к конкретной анимации |
| `animate` | Конструирующий скилл: пошагово решает, стоит ли вообще анимировать, каким инструментом (CSS transition/`@starting-style`/CSS animation/WAAPI/Motion), какими свойствами, кривой, длительностью — и пишет реализацию | Явный запрос «добавь анимацию/переход/motion для X» |
| `animate-expo` | То же самое для React Native/Expo: работа с двумя потоками (JS/UI runtime), Reanimated, Gesture Handler, haptics | **Только если в проекте есть Expo/React Native** — в текущем проекте не используется |
| `improve-animations` | Только читает код, не пишет: обходит существующие анимации по чек-листу (частота, easing, физичность, прерываемость, производительность, доступность, консистентность токенов), выдаёт приоритизированный план правок для другого прогона | «Проаудируй анимации в проекте», «почему интерфейс ощущается дёрганым» |
| `find-animation-opportunities` | Тоже только читает: ищет места, которым анимация реально бы помогла, и явно отклоняет остальное — скилл-фильтр, а не генератор идей | «Что здесь можно оживить анимацией» — не путать с `improve-animations` (тот чинит уже существующее) |
| `apple-design` | Принципы Apple по жестам и «физичной» анимации (spring, прерываемость, momentum, sheet/drawer-паттерны), адаптированные под веб | Свайпы/шторки/drag-жесты, когда нужен spring-физика вместо duration-based CSS |
| `pick-ui-library` | Справочник готовых библиотек под конкретную задачу (тосты, command menu, виртуализация, drag&drop, стейт-менеджмент, стилизация) — вызывается только явно, не триггерится сам | Перед тем как писать компонент с нуля — сначала спросить, нет ли уже готового выбора |

## Как стыкуется с правилами проекта

- Это чисто клиентский слой (`web/`) — правила HITL/RBAC/audit (020, 070) сюда не применяются.
- Новая зависимость (например, Motion, Sonner, base-ui, zustand из `pick-ui-library`) — обычное добавление в `package.json`. Отдельного процесса ревью фронтенд-зависимостей в проекте пока нет; если такой процесс появится — его следует оформить как дополнение к `code-revision`, а не к этому файлу.
- **Порядок вызова при комплексной задаче:**
  1. Если надо выбрать библиотеку → `@pick-ui-library`
  2. Затем общий подход → `@emil-design-eng` (если нужен)
  3. Реализация анимации → `@animate` (или `@animate-expo` для RN)
- **Read-only скиллы** (только анализ):
  - `improve-animations`
  - `find-animation-opportunities`
- **Не путать** `improve-animations` (план правок по анимациям) с `max-pro-review` (проектный скилл про архитектуру/безопасность backend).

---

## Для новых разработчиков

Если по какой-то причине скиллы не установлены, установите их командой из корня проекта:

```bash
npx skills add emilkowalski/skills --skill emil-design-eng --agent cursor
npx skills add emilkowalski/skills --skill animate --agent cursor
npx skills add emilkowalski/skills --skill improve-animations --agent cursor
npx skills add emilkowalski/skills --skill find-animation-opportunities --agent cursor
npx skills add emilkowalski/skills --skill apple-design --agent cursor
npx skills add emilkowalski/skills --skill pick-ui-library --agent cursor
