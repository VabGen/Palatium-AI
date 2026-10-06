import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { installCanvasStub } from './canvas';
import { server } from './msw';

// jsdom не умеет canvas, а `lottie-web` требует его уже на импорте — без заглушки
// не рендерится ни один компонент с иконкой (см. `tests/canvas.ts`).
installCanvasStub();

// Один сервер на файл: `setupFiles` выполняется для каждого тестового файла, а
// `setupServer` — глобальный перехватчик процесса, поэтому поднимать его глобально
// (`globalSetup`) значило бы держать перехват и между файлами тоже.
beforeAll(() => {
  // Незамоканный запрос = падение теста, а не тихий выход в сеть (см. `msw.ts`).
  // MSW 3 переименовал опцию: `onUnhandledFrame`, не `onUnhandledRequest`.
  server.listen({ onUnhandledFrame: 'error' });
});

afterEach(() => {
  // Хэндлеры сбрасываются между тестами: иначе `server.use()` в одном тесте
  // меняет поведение следующего, и порядок прогона начинает влиять на результат.
  server.resetHandlers();
  cleanup();
});

afterAll(() => {
  server.close();
});
