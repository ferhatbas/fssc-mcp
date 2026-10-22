import React, { useEffect, useMemo, useState } from 'react';
import { X, Settings2, CheckCircle2, Sparkles, RotateCcw } from 'lucide-react';
import { TechDecisions, TechQuestion } from '../types/telemetry';
import { api } from '../config';
import { useI18n } from '../i18n';

interface DepQuestion { id: string; dependency: string; file?: string; question: string; options: { value: string; pros?: string; cons?: string }[]; recommended?: string; status: string }

interface TechDecisionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  questions: TechQuestion[];
  decisions: TechDecisions | null;
  /** Bir koşu bu kararları bekliyor (karar kapısı açık) */
  pending: boolean;
  onSave: (answers: Record<string, string>, notes: string) => Promise<any>;
  onReset?: () => Promise<any>;
}

const OTHER = '__other__';

/**
 * Teknoloji ve mimari kararları: pipeline tasarım adımına (2) geçmeden kullanıcıya sorulur.
 * Önerilen seçenek ön-seçilidir; "Diğer" ile serbest metin girilebilir; notlar tüm adımlara aktarılır.
 */
export const TechDecisionsModal: React.FC<TechDecisionsModalProps> = ({ isOpen, onClose, questions, decisions, pending, onSave, onReset }) => {
  const { t } = useI18n();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [other, setOther] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Ek bağımlılık izni soruları (ajan onaylı yığında olmayan bir kütüphane ekledi): kapı bunlar cevaplanana kadar açık kalır
  const [deps, setDeps] = useState<DepQuestion[]>([]);
  const [depBusy, setDepBusy] = useState<string | null>(null);
  const loadDeps = () => fetch(api('/api/tech-requirements')).then(r => r.json())
    .then(j => setDeps(((j?.tech_requirements?.questions || []) as DepQuestion[] & { kind?: string }[]).filter((q: any) => q.kind === 'dependency' && q.status === 'AÇIK')))
    .catch(() => setDeps([]));
  useEffect(() => { if (isOpen) loadDeps(); }, [isOpen, pending]);
  const answerDep = async (q: DepQuestion, answer: string) => {
    setDepBusy(q.id);
    try {
      const r = await fetch(api(`/api/tech-requirements/questions/${encodeURIComponent(q.id)}/answer`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer }) });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error || t('sprint.tech.errorStatus', { n: r.status }, 'Hata {n}'));
      await loadDeps();
    } catch (e) { setError(e instanceof Error ? e.message : t('sprint.tech.answerFailed', undefined, 'Cevaplanamadı')); } finally { setDepBusy(null); }
  };

  // Açılışta: kayıtlı cevaplar, yoksa önerilenler
  useEffect(() => {
    if (!isOpen) return;
    const init: Record<string, string> = {};
    const initOther: Record<string, string> = {};
    for (const q of questions) {
      const saved = decisions?.answers?.[q.id];
      if (saved && q.options.includes(saved)) init[q.id] = saved;
      else if (saved) { init[q.id] = OTHER; initOther[q.id] = saved; }
      else init[q.id] = q.recommended || q.options[0] || '';
    }
    setAnswers(init);
    setOther(initOther);
    setNotes(decisions?.notes || '');
    setError(null);
  }, [isOpen, questions, decisions]);

  const missing = useMemo(() => questions.filter(q => !answers[q.id] || (answers[q.id] === OTHER && !(other[q.id] || '').trim())).map(q => q.id), [questions, answers, other]);

  if (!isOpen) return null;

  const submit = async () => {
    if (missing.length) { setError(t('sprint.tech.selectAll', undefined, 'Tüm sorular için bir seçim yapın (veya "Diğer" alanını doldurun).')); return; }
    setSaving(true);
    setError(null);
    try {
      const final: Record<string, string> = {};
      for (const q of questions) final[q.id] = answers[q.id] === OTHER ? (other[q.id] || '').trim() : answers[q.id];
      await onSave(final, notes);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('sprint.tech.saveFailed', undefined, 'Kaydedilemedi'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-bg/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="w-full max-w-3xl max-h-[92vh] flex flex-col bg-panel border border-line rounded-panel shadow-panel" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-line">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-card bg-acd border border-ac/20 text-ac"><Settings2 className="w-5 h-5" /></div>
            <div>
              <h2 className="text-sm font-bold text-ink font-sans">{t('sprint.tech.title', undefined, 'Teknoloji ve Mimari Kararları')}</h2>
              <p className="text-[11px] text-ink3 mt-0.5">
                {pending
                  ? t('sprint.tech.pendingHint', undefined, 'Pipeline tasarım adımına geçmeden önce bu kararları bekliyor. Cevaplar projede saklanır ve Mimar, geliştiriciler, QA ve DevOps adımlarına aktarılır.')
                  : t('sprint.tech.editHint', undefined, 'İstediğiniz zaman düzenleyin; bir sonraki koşudan itibaren tüm adımlara aktarılır.')}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md text-ink3 hover:text-ink hover:bg-sunk" aria-label={t('sprint.tech.close', undefined, 'Kapat')}><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
          {deps.length > 0 && (
            <div className="rounded-xl border border-warn/60 bg-warnd/40 p-4 space-y-3">
              <div className="text-xs font-bold uppercase tracking-wider text-warn">{t('sprint.tech.depWaiting', { n: deps.length }, 'Pipeline bu soruyu bekliyor: ek bağımlılık izni ({n})')}</div>
              {deps.map(q => (
                <div key={q.id} className="rounded-lg border border-line bg-panel p-3 space-y-2">
                  <div className="text-sm text-ink"><span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-acd text-ac border border-ac/40 mr-2">{q.id}</span>{q.question}</div>
                  <div className="flex flex-wrap gap-2">
                    {q.options.map(o => (
                      <button key={o.value} disabled={depBusy === q.id} onClick={() => answerDep(q, o.value)}
                        className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition disabled:opacity-50 ${/^onay/i.test(o.value) ? 'bg-ink text-bg border-ink hover:opacity-90' : 'bg-panel2 text-ink2 border-line hover:text-ink'}`}
                        title={[o.pros && `+ ${o.pros}`, o.cons && `− ${o.cons}`].filter(Boolean).join(' · ')}>
                        {o.value}{o.value === q.recommended ? t('sprint.tech.recommendedParen', undefined, ' (önerilen)') : ''}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {decisions && (
            <div className="text-[11px] font-mono px-2.5 py-1.5 rounded-md bg-sunk border border-line text-ink2 flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-ok" />
              {t('sprint.tech.savedDecisions', { src: decisions.source === 'user' ? t('sprint.tech.srcUser', undefined, 'sizin seçiminiz') : t('sprint.tech.srcAuto', undefined, 'önerilenler otomatik uygulandı'), at: new Date(decisions.answered_at).toLocaleString('tr-TR') }, 'Kayıtlı kararlar var ({src}, {at}). Değiştirip kaydedebilirsiniz.')}
            </div>
          )}
          {questions.map((q, i) => (
            <fieldset key={q.id} className="border border-line rounded-card p-3 bg-panel2/40">
              <legend className="px-1.5 text-xs font-bold text-ink font-sans flex items-center gap-2">
                <span className="text-[10px] font-mono text-ink3">{i + 1}.</span> {q.question}
                {q.source === 'spec' && <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-warnd text-warn border border-warn/40">{t('sprint.tech.fromSpec', undefined, 'şartnameden')}</span>}
              </legend>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mt-1">
                {q.options.map(opt => (
                  <label key={opt} className={`flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[11.5px] cursor-pointer transition ${answers[q.id] === opt ? 'bg-acd border-ac/50 text-ink' : 'bg-panel border-line text-ink2 hover:border-line2'}`}>
                    <input type="radio" name={q.id} value={opt} checked={answers[q.id] === opt} onChange={() => setAnswers(a => ({ ...a, [q.id]: opt }))} className="accent-ac" />
                    <span className="flex-1">{opt}</span>
                    {opt === q.recommended && <span className="inline-flex items-center gap-0.5 text-[9px] font-mono text-ac"><Sparkles className="w-3 h-3" /> {t('sprint.tech.recommended', undefined, 'önerilen')}</span>}
                  </label>
                ))}
                <label className={`flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[11.5px] cursor-pointer transition ${answers[q.id] === OTHER ? 'bg-acd border-ac/50' : 'bg-panel border-line text-ink2 hover:border-line2'}`}>
                  <input type="radio" name={q.id} value={OTHER} checked={answers[q.id] === OTHER} onChange={() => setAnswers(a => ({ ...a, [q.id]: OTHER }))} className="accent-ac" />
                  <input
                    type="text"
                    placeholder={t('sprint.tech.other', undefined, 'Diğer…')}
                    value={other[q.id] || ''}
                    onFocus={() => setAnswers(a => ({ ...a, [q.id]: OTHER }))}
                    onChange={e => setOther(o => ({ ...o, [q.id]: e.target.value }))}
                    className="flex-1 bg-transparent outline-none text-ink placeholder:text-ink3"
                  />
                </label>
              </div>
              {q.why && <p className="text-[10.5px] text-ink3 mt-1.5">{q.why}</p>}
            </fieldset>
          ))}
          <div>
            <label className="text-xs font-bold text-ink font-sans">{t('sprint.tech.notesLabel', undefined, 'Ek notlar / kısıtlar (isteğe bağlı)')}</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
              placeholder={t('sprint.tech.notesPh', undefined, 'Örn. Redis kullanılmasın; tüm zaman damgaları UTC; kod yorumları Türkçe; mevcut ekip PHP biliyor…')}
              className="mt-1 w-full text-[11.5px] bg-sunk border border-line rounded-md px-2.5 py-2 text-ink placeholder:text-ink3 outline-none focus:border-ac/60"
            />
          </div>
          {error && <div className="text-[11px] text-err font-mono">{error}</div>}
        </div>

        <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-line">
          <div className="flex items-center gap-2">
            {onReset && decisions && (
              <button onClick={() => onReset()} className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-md border border-line text-ink3 hover:text-ink hover:border-line2" title={t('sprint.tech.resetTip', undefined, 'Kararları sil; bir sonraki koşu yeniden sorar')}>
                <RotateCcw className="w-3.5 h-3.5" /> {t('sprint.tech.reset', undefined, 'Sıfırla')}
              </button>
            )}
            <span className="text-[10.5px] text-ink3 font-mono">{t('sprint.tech.questionCount', { n: questions.length }, '{n} soru')} · {missing.length ? t('sprint.tech.missing', { n: missing.length }, '{n} eksik') : t('sprint.tech.allAnswered', undefined, 'hepsi cevaplı')}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="text-[11px] px-3 py-1.5 rounded-md border border-line text-ink2 hover:text-ink">{t('sprint.tech.close', undefined, 'Kapat')}</button>
            <button onClick={submit} disabled={saving} className="inline-flex items-center gap-1.5 text-[11px] font-bold px-3.5 py-1.5 rounded-md bg-ink text-bg hover:opacity-90 disabled:opacity-50">
              <CheckCircle2 className="w-3.5 h-3.5" /> {saving ? t('sprint.tech.saving', undefined, 'Kaydediliyor…') : pending ? t('sprint.tech.saveResume', undefined, 'Kaydet ve pipeline’ı sürdür') : t('sprint.tech.save', undefined, 'Kaydet')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
