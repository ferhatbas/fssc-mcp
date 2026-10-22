import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, HelpCircle, Lock, ShieldAlert, X } from 'lucide-react';
import { QueueQuestion } from '../types/telemetry';
import { useI18n } from '../i18n';

interface QuestionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  questions: QueueQuestion[];
  /** Seçenek anahtarıyla ya da serbest metinle (customText) cevaplar; hata iletisini fırlatır. */
  onAnswer: (questionId: string, answer: string, customText?: string) => Promise<any>;
}

/** Arayüzdeki 'Diğer (serbest metin)' seçeneğinin yerel anahtarı (sunucuya gönderilmez). */
const OTHER_KEY = '__other__';
const CUSTOM_MAX = 500;

// yedek metinler; çeviri sprint.q.cat.<KOD>
const CATEGORY_LABEL: Record<string, string> = {
  TECHNOLOGY: 'Teknoloji',
  EXTERNAL_ACTION: 'Dış işlem',
  SCOPE: 'Kapsam',
  DESIGN: 'Tasarım',
};

// yedek metinler; çeviri sprint.q.status.<KOD>
const STATUS_LABEL: Record<string, string> = {
  OPEN: 'Açık',
  ANSWERED: 'Cevaplandı',
  DEFAULTED: 'Varsayılana döndü',
  OVERRIDDEN: 'Değiştirildi',
};

const isOpen_ = (q: QueueQuestion) => q.status === 'OPEN';

export const QuestionsModal: React.FC<QuestionsModalProps> = ({ isOpen, onClose, questions, onAnswer }) => {
  const { t } = useI18n();
  const [tab, setTab] = useState<'open' | 'all'>('open');
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [customText, setCustomText] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  const open = useMemo(() => questions.filter(isOpen_), [questions]);
  const blockingOpen = open.filter((q) => q.blocking).length;
  const shown = tab === 'open' ? open : questions.slice().sort((a, b) => Number(isOpen_(b)) - Number(isOpen_(a)));

  if (!isOpen) return null;

  const submit = async (q: QueueQuestion) => {
    const key = picked[q.id] ?? q.recommended ?? '';
    if (!key) {
      setErrors((e) => ({ ...e, [q.id]: t('sprint.q.pickOne', undefined, 'Bir seçenek seçin.') }));
      return;
    }
    const text = (customText[q.id] || '').trim();
    if (key === OTHER_KEY && !text) {
      setErrors((e) => ({ ...e, [q.id]: t('sprint.q.writeFree', undefined, 'Serbest metin cevabınızı yazın.') }));
      return;
    }
    setBusyId(q.id);
    setErrors((e) => ({ ...e, [q.id]: '' }));
    try {
      await (key === OTHER_KEY ? onAnswer(q.id, '', text) : onAnswer(q.id, key));
    } catch (err) {
      setErrors((e) => ({ ...e, [q.id]: err instanceof Error ? err.message : t('sprint.q.saveFailed', undefined, 'Cevap kaydedilemedi.') }));
    } finally {
      setBusyId(null);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sm:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('sprint.q.title', undefined, 'Sorular')}
    >
      <div
        className="w-full max-w-3xl max-h-[88vh] bg-panel border border-line2/80 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 bg-sunk/70 border-b border-line flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <HelpCircle className="w-5 h-5 text-ac" />
            <div>
              <div className="text-sm font-bold text-ink">{t('sprint.q.title', undefined, 'Sorular')}</div>
              <div className="text-[11px] text-ink3">
                {t('sprint.q.openCount', { n: open.length }, '{n} açık')}{blockingOpen ? t('sprint.q.blockingCount', { n: blockingOpen }, ' · {n} engelleyici (sprint bunlar cevaplanana kadar bekler)') : ''}
              </div>
            </div>
          </div>
          <button onClick={onClose} aria-label={t('sprint.q.close', undefined, 'Kapat')} className="p-1.5 rounded-lg text-ink2 hover:text-ink hover:bg-panel2 transition">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 pt-3 flex items-center gap-2 shrink-0">
          {(['open', 'all'] as const).map((tb) => (
            <button
              key={tb}
              onClick={() => setTab(tb)}
              className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${tab === tb ? 'bg-acd border-ac/40 text-ac' : 'bg-panel2 border-line text-ink2 hover:text-ink'}`}
            >
              {tb === 'open' ? t('sprint.q.tabOpen', { n: open.length }, 'Açık ({n})') : t('sprint.q.tabAll', { n: questions.length }, 'Tümü ({n})')}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {shown.length === 0 ? (
            <div className="text-center text-ink3 text-sm py-10 italic">
              {tab === 'open' ? t('sprint.q.noneOpen', undefined, 'Cevap bekleyen soru yok.') : t('sprint.q.noneYet', undefined, 'Henüz soru oluşmadı.')}
            </div>
          ) : (
            shown.map((q) => {
              const isOpenQ = isOpen_(q);
              const current = picked[q.id] ?? q.recommended ?? '';
              return (
                <div key={q.id} className={`rounded-xl border p-4 space-y-2 ${isOpenQ ? (q.blocking ? 'border-warn/50 bg-warnd/30' : 'border-line bg-sunk/40') : 'border-line bg-sunk/20 opacity-90'}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[11px] font-bold text-ink">{q.id}</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-ac/40 bg-acd text-ac">{CATEGORY_LABEL[q.category] ? t(`sprint.q.cat.${q.category}`, undefined, CATEGORY_LABEL[q.category]) : q.category}</span>
                    {q.blocking && isOpenQ && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border border-warn/50 bg-warnd text-warn" title={t('sprint.q.blockingTip', undefined, 'Cevaplanana kadar sprint ilerlemez; süreyle geçilmez')}>
                        <Lock className="w-3 h-3" /> {t('sprint.q.blocking', undefined, 'engelleyici')}
                      </span>
                    )}
                    {q.raised_by && <span className="text-[10px] text-ink3">{t('sprint.q.raisedBy', { by: q.raised_by }, 'soran: {by}')}</span>}
                    <span className={`ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded border ${isOpenQ ? 'border-warn/40 text-warn bg-warnd' : 'border-ok/40 text-ok bg-okd'}`}>
                      {STATUS_LABEL[q.status] ? t(`sprint.q.status.${q.status}`, undefined, STATUS_LABEL[q.status]) : q.status}
                    </span>
                  </div>

                  <div className="text-sm text-ink font-medium">{q.text}</div>

                  {isOpenQ ? (
                    <>
                      <div className="space-y-1.5" role="radiogroup" aria-label={t('sprint.q.optionsAria', { id: q.id }, '{id} seçenekleri')}>
                        {q.options.map((o) => (
                          <label key={o.key} className={`flex items-start gap-2 text-xs rounded-lg border px-3 py-2 cursor-pointer transition ${current === o.key ? 'border-ac bg-acd/60 text-ink' : 'border-line bg-panel hover:bg-panel2 text-ink2'}`}>
                            <input
                              type="radio"
                              name={`q-${q.id}`}
                              checked={current === o.key}
                              onChange={() => setPicked((p) => ({ ...p, [q.id]: o.key }))}
                              className="mt-0.5"
                            />
                            <span className="min-w-0">
                              <span className="font-mono font-bold mr-1">{o.key}.</span>{o.label}
                              {q.recommended === o.key && <span className="ml-2 text-[10px] font-mono px-1 rounded bg-ok text-onac">{t('sprint.q.recommended', undefined, 'önerilen')}</span>}
                            </span>
                          </label>
                        ))}

                        {/* Diğer: serbest metin cevap (seçeneklerin dışında bir karar) */}
                        <label className={`flex items-start gap-2 text-xs rounded-lg border px-3 py-2 cursor-pointer transition ${current === OTHER_KEY ? 'border-ac bg-acd/60 text-ink' : 'border-line bg-panel hover:bg-panel2 text-ink2'}`}>
                          <input
                            type="radio"
                            name={`q-${q.id}`}
                            checked={current === OTHER_KEY}
                            onChange={() => setPicked((p) => ({ ...p, [q.id]: OTHER_KEY }))}
                            className="mt-0.5"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="font-mono font-bold mr-1">{t('sprint.q.other', undefined, 'Diğer…')}</span>{t('sprint.q.otherDesc', undefined, 'kendi cevabımı yazacağım')}
                            {current === OTHER_KEY && (
                              <textarea
                                autoFocus
                                value={customText[q.id] || ''}
                                onChange={(e) => { setCustomText((c) => ({ ...c, [q.id]: e.target.value })); if (errors[q.id]) setErrors((er) => ({ ...er, [q.id]: '' })); }}
                                rows={3}
                                maxLength={CUSTOM_MAX}
                                placeholder={t('sprint.q.freePh', undefined, 'Örn. Docker yerine Podman kullanılsın; compose dosyası yine hazırlansın.')}
                                aria-label={t('sprint.q.freeAria', { id: q.id }, '{id} serbest metin cevap')}
                                className="mt-2 w-full text-xs rounded-lg border border-line2 bg-sunk text-ink p-2 focus:outline-none focus:border-ac"
                              />
                            )}
                            {current === OTHER_KEY && (
                              <span className="block text-[10px] text-ink3 mt-0.5 text-right">{(customText[q.id] || '').length}/{CUSTOM_MAX}</span>
                            )}
                          </span>
                        </label>
                      </div>
                      {q.rationale && (
                        <div className="text-[11px] text-ink3 flex items-start gap-1.5"><ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5 text-ink3" /><span>{q.rationale}</span></div>
                      )}
                      {errors[q.id] && <div role="alert" className="text-[11px] text-err">{errors[q.id]}</div>}
                      <div className="flex justify-end">
                        <button
                          onClick={() => submit(q)}
                          disabled={busyId === q.id || !current}
                          className="px-4 py-1.5 rounded-lg bg-ok text-onac font-bold text-xs flex items-center gap-1.5 disabled:opacity-50"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          {busyId === q.id ? t('sprint.q.saving', undefined, 'Kaydediliyor…') : t('sprint.q.answer', undefined, 'Cevapla')}
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="text-[11px] text-ink2">
                      {t('sprint.q.answerLabel', undefined, 'Cevap:')} <span className="font-semibold text-ink">{(q.options.find((o) => o.key === q.answer)?.label) || q.answer || '—'}</span>
                      {q.answered_by ? ` · ${q.answered_by}` : ''}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
};
