import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DialogHost } from './components/DialogHost';

import { I18nProvider } from './i18n';

try {
  const fs = Number(localStorage.getItem('fssc_font_px')) || 14;
  document.documentElement.style.fontSize = `${Math.min(18, Math.max(12, fs))}px`;
} catch { /* localStorage yoksa varsayılan */ }

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <I18nProvider>
      <ErrorBoundary label="Pano"><App /></ErrorBoundary>
      <DialogHost />
    </I18nProvider>
  </React.StrictMode>
);
