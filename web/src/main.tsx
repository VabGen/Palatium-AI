import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { ensureDefaultTheme } from './lib/theme';
import { applyTheme, languageLocale, readSettingsPrefs } from './lib/settingsPrefs';
import { setLangOverride } from './runtime/store';
import './fonts.css';
import './tokens.css';
import './styles.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root not found');
}

ensureDefaultTheme(document.documentElement);

// Сохранённые предпочтения применяются ДО первого рендера: иначе тема и язык
// мигают дефолтными, а `t()` вне React (client.ts) стартует с чужой локалью.
const savedPrefs = readSettingsPrefs();
applyTheme(savedPrefs.theme);
const savedLocale = languageLocale(savedPrefs.language);
if (savedLocale) setLangOverride(savedLocale);

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);
