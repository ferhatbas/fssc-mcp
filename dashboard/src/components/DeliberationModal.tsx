import React, { useEffect, useState } from 'react';
import { api } from '../config';
import { DeliberationSession } from '../types/telemetry';
import { useI18n } from '../i18n';
import { 
  X, 
  Users, 
  MessageSquare, 
  CheckCircle2, 
  Lightbulb, 
  AlertTriangle, 
  Layers, 
  RotateCcw,
  Sparkles,
  ShieldCheck,
  Send,
  History,
  ThumbsUp,
  MessageSquareWarning
} from 'lucide-react';

interface DeliberationModalProps {
  isOpen: boolean;
  onClose: () => void;
  session: DeliberationSession | null;
  onStartDeliberation: (title?: string, prompt?: string) => Promise<any>;
  /** C6: alternatif mimari planlardan birini seç */
  onChoosePlan?: (sessionId: string, planId: string) => Promise<any>;
}

const RISK_CLS: Record<string, string> = {
  LOW: 'bg-okd text-ok border-ok/40',
  MEDIUM: 'bg-warnd text-warn border-warn/40',
  HIGH: 'bg-errd text-err border-err/40',
};

const ROLE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  PM: { bg: 'bg-infod', text: 'text-info', border: 'border-info/30' },
  ARCHITECT: { bg: 'bg-acd', text: 'text-ac', border: 'border-ac/30' },
  BACKEND_DEV: { bg: 'bg-okd', text: 'text-ok', border: 'border-ok/30' },
  FRONTEND_DEV: { bg: 'bg-infod', text: 'text-info', border: 'border-info/30' },
  DESIGNER: { bg: 'bg-acd', text: 'text-ac', border: 'border-ac/30' },
  QA: { bg: 'bg-warnd', text: 'text-warn', border: 'border-warn/30' },
  PO: { bg: 'bg-acd', text: 'text-ac', border: 'border-ac/30' },
  SCM: { bg: 'bg-infod', text: 'text-info', border: 'border-info/30' },
  DEVOPS: { bg: 'bg-acd', text: 'text-ac', border: 'border-ac/30' },
  DOCUMENTOR: { bg: 'bg-warnd', text: 'text-warn', border: 'border-warn/30' },
  REPORTER: { bg: 'bg-okd', text: 'text-ok', border: 'border-ok/30' },
};

export const DeliberationModal: React.FC<DeliberationModalProps> = ({
  isOpen,
  onClose,
  session,
  onStartDeliberation,
  onChoosePlan
}) => {
  const { t } = useI18n();
  const [customTopic, setCustomTopic] = useState<string>('');
  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [choosing, setChoosing] = useState<string | null>(null);
  const [tab, setTab] = useState<'current' | 'history'>('current');
  const [history, setHistory] = useState<Array<{ session_id: string; title: string; status: string; round: number; messages: number; chosen_plan?: string; decision?: string; decision_ref?: string; updated_at?: string }>>([]);
  const [viewed, setViewed] = useState<DeliberationSession | null>(null);   // geçmişten açılan oturum (salt okunur)
  const [pickedPlan, setPickedPlan] = useState<string>('');
  const [applyMode, setApplyMode] = useState<'next' | 'now' | 'none'>('now');
  const [reviseOpen, setReviseOpen] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadHistory = () => fetch(api('/api/deliberation/history')).then(r => r.json()).then(j => setHistory(j.sessions || [])).catch(() => undefined);
  useEffect(() => { if (isOpen) loadHistory(); }, [isOpen, session?.status, session?.session_id, session?.round]);
  useEffect(() => { setPickedPlan(''); setReviseOpen(false); setFeedback(''); setErr(''); }, [session?.session_id, session?.status]);

  if (!isOpen) return null;

  const shown = tab === 'history' && viewed ? viewed : session;
  const readOnly = tab === 'history' && !!viewed && viewed.session_id !== session?.session_id;

  const post = async (url: string, body: unknown) => {
    setBusy(true);
    setErr('');
    try {
      const r = await fetch(api(url), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j as { error?: string }).error || t('sprint.delib.errorStatus', { n: r.status }, 'Hata {n}'));
      await loadHistory();
      return j;
    } catch (e) { setErr((e as Error).message); return null; } finally { setBusy(false); }
  };
  const approve = async () => {
    if (!shown) return;
    const j = await post('/api/deliberation/approve', { session_id: shown.session_id, plan_id: pickedPlan || shown.consensus_summary?.proposed_plan_id || '', apply: applyMode });
    if (j) setReviseOpen(false);
  };
  const revise = async () => {
    if (!shown) return;
    const j = await post('/api/deliberation/revise', { session_id: shown.session_id, feedback });
    if (j) { setFeedback(''); setReviseOpen(false); }
  };
  const openFromHistory = async (id: string) => {
    const r = await fetch(api(`/api/deliberation/session/${encodeURIComponent(id)}`));
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.session) setViewed(j.session as DeliberationSession);
  };

  const handleStart = async () => {
    try {
      setIsStarting(true);
      await onStartDeliberation(customTopic || undefined, undefined);
      setCustomTopic('');
    } catch (e) {
      console.error(e);
    } finally {
      setIsStarting(false);
    }
  };

  const isConsensus = shown?.status === 'CONSENSUS_REACHED';
  const awaitingChoice = shown?.status === 'AWAITING_PLAN_CHOICE';
  const awaitingApproval = shown?.status === 'AWAITING_APPROVAL' || awaitingChoice;
  const proposals = shown?.proposals || [];
  const proposedId = shown?.consensus_summary?.proposed_plan_id || '';
  const roundNo = shown?.round || 1;

  const handleChoose = async (planId: string) => {
    if (!session || !onChoosePlan) return;
    setChoosing(planId);
    try {
      await onChoosePlan(session.session_id, planId);
    } catch (e) {
      console.error(e);
    } finally {
      setChoosing(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in">
      <div className="bg-panel border border-line rounded-panel shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-scale-up">
        
        {/* Modal Başlığı */}
        <div className="px-5 py-3.5 border-b border-line flex items-center justify-between bg-panel2 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-card bg-acd border border-ac/20 text-ac">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-ink">{t('sprint.delib.title', undefined, 'Ajanlar Arası Müzakere Masası (Deliberation Room)')}</h2>
                {isConsensus ? (
                  <span className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-okd text-ok border border-ok/30 font-semibold">
                    <CheckCircle2 className="w-3 h-3" />
                    {t('sprint.delib.finalApproved', undefined, 'Nihai Karar · yönetici onayladı')}{shown?.decision_ref ? ` (${shown.decision_ref})` : ''}
                  </span>
                ) : awaitingApproval ? (
                  <span className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-warnd text-warn border border-warn/40 font-semibold animate-pulse">
                    <ThumbsUp className="w-3 h-3" />
                    {awaitingChoice ? t('sprint.delib.awaitingPlan', undefined, 'Plan seçiminiz bekleniyor') : t('sprint.delib.awaitingDecision', undefined, 'Ajan önerisi · kararınız bekleniyor')}
                  </span>
                ) : shown?.status === 'SUPERSEDED' ? (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-sunk text-ink3 border border-line font-semibold">{t('sprint.delib.interrupted', undefined, 'Yarım kaldı')}</span>
                ) : (
                  <span className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-warnd text-warn border border-warn/30 font-semibold animate-pulse">
                    <Sparkles className="w-3 h-3" />
                    {t('sprint.delib.deliberating', undefined, 'Müzakere Ediliyor')}{roundNo > 1 ? t('sprint.delib.roundSuffix', { n: roundNo }, ' · tur {n}') : ''}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-ink3 font-mono">
                {shown ? t('sprint.delib.sessionLine', { title: shown.title, id: shown.session_id }, '{title} • Oturum: {id}') : t('sprint.delib.tagline', undefined, 'Farklı disiplinlerdeki ajanlar şartname üzerinde ortak konsensüs kurar')}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label={t('sprint.delib.close', undefined, 'Kapat')}
            className="p-1.5 rounded-card hover:bg-sunk text-ink3 hover:text-ink transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Sekmeler: güncel oturum / geçmiş (tüm müzakereler ve nihai kararlar) */}
        <div className="px-5 pt-2.5 pb-0 border-b border-line bg-panel2/60 flex items-center gap-2 text-xs shrink-0">
          <button onClick={() => { setTab('current'); setViewed(null); }} className={`px-3 py-1.5 rounded-t-md border-b-2 font-semibold ${tab === 'current' ? 'border-ac text-ac' : 'border-transparent text-ink3 hover:text-ink'}`}>{t('sprint.delib.current', undefined, 'Güncel')}</button>
          <button onClick={() => { setTab('history'); loadHistory(); }} className={`px-3 py-1.5 rounded-t-md border-b-2 font-semibold inline-flex items-center gap-1 ${tab === 'history' ? 'border-ac text-ac' : 'border-transparent text-ink3 hover:text-ink'}`}>
            <History className="w-3.5 h-3.5" />{t('sprint.delib.history', { n: history.length }, 'Geçmiş ({n})')}
          </button>
          {readOnly && <button onClick={() => setViewed(null)} className="ml-auto text-[11px] text-ac hover:underline">{t('sprint.delib.backToList', undefined, '← listeye dön')}</button>}
        </div>

        {/* Canlı Müzakere Akışı */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3.5 bg-bg">
          {tab === 'history' && !viewed && (
            <div className="space-y-2">
              {history.length === 0 && <div className="text-xs text-ink3 italic">{t('sprint.delib.noHistory', undefined, 'Henüz müzakere kaydı yok.')}</div>}
              {history.map(h => (
                <button key={h.session_id} onClick={() => openFromHistory(h.session_id)} className="w-full text-left p-3 rounded-card border border-line bg-panel hover:border-ac transition flex items-center gap-3">
                  <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border shrink-0 ${h.status === 'CONSENSUS_REACHED' ? 'bg-okd text-ok border-ok/40' : h.status === 'SUPERSEDED' ? 'bg-sunk text-ink3 border-line' : 'bg-warnd text-warn border-warn/40'}`}>
                    {h.session_id.startsWith('M-') ? t('sprint.delib.badgeMeeting', undefined, 'TOPLANTI') : h.status === 'CONSENSUS_REACHED' ? t('sprint.delib.badgeFinal', undefined, 'NİHAİ') : h.status === 'SUPERSEDED' ? t('sprint.delib.badgeInterrupted', undefined, 'YARIM KALDI') : h.status === 'ACTIVE' ? t('sprint.delib.badgeActive', undefined, 'TARTIŞILIYOR') : t('sprint.delib.badgeAwaiting', undefined, 'KARAR BEKLİYOR')}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-bold text-ink truncate">{h.title}</span>
                    <span className="block text-[10px] font-mono text-ink3 truncate">{h.chosen_plan || '—'}{h.decision_ref ? ` · ${h.decision_ref}` : ''} · {t('sprint.delib.roundMessages', { round: h.round, n: h.messages }, 'tur {round} · {n} mesaj')}</span>
                  </span>
                  <span className="text-[10px] font-mono text-ink3 shrink-0">{h.updated_at ? new Date(h.updated_at).toLocaleString('tr-TR') : ''}</span>
                </button>
              ))}
            </div>
          )}
          {(tab === 'current' || viewed) && (<>
          {(!shown || !shown.messages || shown.messages.length === 0) ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-6 bg-panel border border-dashed border-line rounded-card">
              <MessageSquare className="w-10 h-10 text-ink3 mb-2 opacity-50" />
              <h3 className="text-sm font-bold text-ink">{t('sprint.delib.noSession', undefined, 'Henüz Aktif Bir Müzakere Oturumu Yok')}</h3>
              <p className="text-xs text-ink3 max-w-md mt-1 mb-4">
                {t('sprint.delib.noSessionHint', undefined, 'Bir şartname yüklendiğinde ajanlar otomatik olarak toplanıp tartışır veya aşağıdan özel bir konu başlatabilirsiniz.')}
              </p>
              <button
                onClick={handleStart}
                disabled={isStarting}
                className="px-4 py-2 bg-ac hover:bg-ac/90 text-onac rounded-card font-medium text-xs flex items-center gap-2 shadow-sm transition disabled:opacity-50"
              >
                <Sparkles className="w-4 h-4" />
                {isStarting ? t('sprint.delib.gathering', undefined, 'Ajanlar Toplanıyor...') : t('sprint.delib.startTable', undefined, 'Müzakere Masasını Başlat')}
              </button>
            </div>
          ) : (
            <>
              {/* C6: Alternatif mimari planlar */}
              {proposals.length > 0 && (
                <div className={`p-4 rounded-card border space-y-3 ${awaitingChoice ? 'bg-warnd/30 border-warn/40' : 'bg-panel2 border-line'}`}>
                  <div className="flex items-center gap-2 text-xs font-bold font-mono">
                    <Layers className={`w-4 h-4 ${awaitingChoice ? 'text-warn' : 'text-ac'}`} />
                    <span className={awaitingChoice ? 'text-warn' : 'text-ink'}>
                      {awaitingChoice ? t('sprint.delib.plansAwaiting', undefined, 'MİMAR 2-3 ALTERNATİF PLAN SUNDU — SEÇİMİNİZ BEKLENİYOR') : t('sprint.delib.plansEvaluated', undefined, 'DEĞERLENDİRİLEN ALTERNATİF PLANLAR')}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                    {proposals.map(p => {
                      const chosen = shown.chosen_plan_id === p.id;
                      const proposed = awaitingApproval && proposedId === p.id;
                      return (
                        <div key={p.id} className={`rounded-card border p-3 flex flex-col gap-2 ${chosen ? 'bg-okd/40 border-ok ring-2 ring-ok/30' : 'bg-panel border-line'}`}>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-acd text-ac border border-ac/30">{t('sprint.delib.planId', { id: p.id }, 'Plan {id}')}</span>
                            <span className="text-xs font-bold text-ink flex-1 truncate" title={p.title}>{p.title}</span>
                            <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${RISK_CLS[p.risk] || RISK_CLS.MEDIUM}`}>{t('sprint.delib.risk', { risk: p.risk }, 'risk: {risk}')}</span>
                          </div>
                          {p.summary && <p className="text-[11px] text-ink2">{p.summary}</p>}
                          {p.stack.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {p.stack.map((tech, i) => <span key={i} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-sunk border border-line text-ink">{tech}</span>)}
                            </div>
                          )}
                          <div className="grid grid-cols-2 gap-2 text-[10px]">
                            <ul className="space-y-0.5">{p.pros.map((x, i) => <li key={i} className="text-ok">+ {x}</li>)}</ul>
                            <ul className="space-y-0.5">{p.cons.map((x, i) => <li key={i} className="text-err">− {x}</li>)}</ul>
                          </div>
                          <div className="flex items-center gap-2 mt-auto">
                            {p.recommended && <span className="text-[9px] font-mono text-ac">{t('sprint.delib.architectPick', undefined, '★ mimarın önerisi')}</span>}
                            {proposed && <span className="text-[9px] font-mono text-warn">{t('sprint.delib.consensusPick', undefined, '⚑ ajanların konsensüs önerisi')}</span>}
                            {chosen && <span className="text-[10px] font-mono font-bold text-ok ml-auto">{t('sprint.delib.chosen', undefined, '✓ seçildi')}</span>}
                            {awaitingApproval && !readOnly && !chosen && (
                              <button
                                onClick={() => setPickedPlan(p.id)}
                                className={`ml-auto text-[11px] font-semibold px-2.5 py-1 rounded-md border ${(pickedPlan || proposedId) === p.id ? 'bg-ac text-onac border-ac' : 'bg-panel2 text-ink2 border-line hover:text-ink'}`}
                              >
                                {(pickedPlan || proposedId) === p.id ? t('sprint.delib.thisSelected', undefined, '✓ Bu plan seçili') : t('sprint.delib.selectThis', undefined, 'Bu planı seç')}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Tur geçmişi: yönetici revize istedikçe yeni tur açılır */}
              {(shown.rounds || []).length > 1 && (
                <div className="p-3 rounded-card bg-panel2 border border-line space-y-1.5">
                  <div className="text-[10px] font-mono font-bold text-ink3 uppercase tracking-wider">{t('sprint.delib.rounds', undefined, 'Müzakere turları')}</div>
                  {(shown.rounds || []).map(r => (
                    <div key={r.round} className="text-[11px] text-ink2"><span className="font-mono font-bold text-ac">{t('sprint.delib.roundN', { n: r.round }, 'Tur {n}')}</span>{r.feedback ? <> · {t('sprint.delib.managerFeedback', undefined, 'yönetici geri bildirimi:')} <span className="italic">“{r.feedback}”</span></> : t('sprint.delib.firstDiscussion', undefined, ' · ilk tartışma')}</div>
                  ))}
                </div>
              )}

              {/* Nihai karar (yönetici onayladı) */}
              {isConsensus && shown.consensus_summary && (
                <div className="p-4 rounded-card bg-okd/30 border border-ok/30 flex flex-col gap-2 shadow-sm">
                  <div className="flex items-center gap-2 text-ok text-xs font-bold font-mono">
                    <ShieldCheck className="w-4 h-4" />
                    <span>{t('sprint.delib.finalDecision', undefined, 'NİHAİ KARAR — yönetici onayladı')}{shown.decision_ref ? ` · ${shown.decision_ref}` : ''}:</span>
                  </div>
                  <div className="text-sm font-bold text-ink">{shown.consensus_summary.chosen_plan}</div>
                  <div className="flex items-center gap-1.5 flex-wrap mt-1">
                    <span className="text-[10px] text-ink3 font-mono">{t('sprint.delib.agreedStack', undefined, 'Kabul Edilen Teknoloji Yığını:')}</span>
                    {shown.consensus_summary.agreed_stack?.map((tech, idx) => (
                      <span key={idx} className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-panel border border-line text-ink font-semibold">{tech}</span>
                    ))}
                  </div>
                  <div className="text-[11px] text-ink2 mt-1">
                    {shown.consensus_summary.implementation_task
                      ? <>{t('sprint.delib.implTask', undefined, 'Uygulama işi:')} <span className="font-mono font-bold text-ink">{shown.consensus_summary.implementation_task.key}</span> — {shown.consensus_summary.implementation_task.when === 'now' ? t('sprint.delib.implNow', undefined, 'çalışan sprinte hemen alındı') : t('sprint.delib.implNext', undefined, 'sıradaki sprint planlamasında seçilecek')}.</>
                      : t('sprint.delib.noImplTask', undefined, 'Bu karar için uygulama işi açılmadı (yalnızca karar kaydı).')}
                  </div>
                  {!readOnly && <button onClick={() => setReviseOpen(true)} className="self-start text-[11px] text-ac hover:underline">{t('sprint.delib.reopen', undefined, 'Yeniden tartışmaya aç')}</button>}
                </div>
              )}

              {/* Ajan önerisi: nihai karar yöneticinin */}
              {awaitingApproval && shown.consensus_summary && (
                <div className="p-4 rounded-card bg-warnd/30 border border-warn/50 flex flex-col gap-2.5">
                  <div className="flex items-center gap-2 text-warn text-xs font-bold font-mono">
                    <ThumbsUp className="w-4 h-4" />
                    <span>{t('sprint.delib.agentsProposal', undefined, 'AJANLARIN ÖNERİSİ — nihai karar sizin (onaylamadan uygulamaya geçilmez)')}</span>
                  </div>
                  <div className="text-sm font-bold text-ink">{(proposals.find(p => p.id === (pickedPlan || proposedId))?.title) || shown.consensus_summary.chosen_plan}</div>
                  {!readOnly && (
                    <>
                      <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink2">
                        <span className="font-mono text-ink3">{t('sprint.delib.afterApproval', undefined, 'Onaydan sonra:')}</span>
                        {([['now', t('sprint.delib.applyNow', undefined, 'Çalışan sprinte hemen al (önce yap)')], ['next', t('sprint.delib.applyNext', undefined, 'Sıradaki planlamaya al')], ['none', t('sprint.delib.applyNone', undefined, 'Yalnızca kararı kaydet')]] as const).map(([k, l]) => (
                          <label key={k} className="inline-flex items-center gap-1 cursor-pointer"><input type="radio" name="applyMode" checked={applyMode === k} onChange={() => setApplyMode(k)} />{l}</label>
                        ))}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button onClick={approve} disabled={busy || (proposals.length > 0 && !(pickedPlan || proposedId))}
                          className="px-3.5 py-1.5 rounded-lg bg-ink text-bg text-xs font-bold hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1.5"><ThumbsUp className="w-3.5 h-3.5" />{t('sprint.delib.approve', undefined, 'Onayla (nihai karar)')}</button>
                        <button onClick={() => setReviseOpen(o => !o)} disabled={busy}
                          className="px-3.5 py-1.5 rounded-lg bg-panel2 border border-line text-ink2 text-xs font-semibold hover:text-ink inline-flex items-center gap-1.5"><MessageSquareWarning className="w-3.5 h-3.5" />{t('sprint.delib.requestRevision', undefined, 'Revize iste / tartışmaya devam')}</button>
                        {proposals.length > 0 && !(pickedPlan || proposedId) && <span className="text-[11px] text-warn">{t('sprint.delib.pickPlanFirst', undefined, 'Önce bir plan seçin.')}</span>}
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Revize isteği: geri bildirim yeni tur başlatır; ajanlar aynı oturumda devam eder */}
              {reviseOpen && !readOnly && (
                <div className="p-3 rounded-card border border-ac/40 bg-acd/30 space-y-2">
                  <div className="text-[11px] font-bold text-ac">{t('sprint.delib.feedbackHint', undefined, 'Geri bildiriminiz yeni bir tur başlatır (ajanlar aynı oturumda tartışmaya devam eder, geçmiş korunur)')}</div>
                  <textarea value={feedback} onChange={e => setFeedback(e.target.value)} rows={3} placeholder={t('sprint.delib.feedbackPh', undefined, 'Neyi değiştirmeli / neyi de değerlendirmeli?')}
                    className="w-full bg-sunk border border-line rounded-md px-3 py-2 text-xs text-ink focus:outline-none focus:border-ac" />
                  <button onClick={revise} disabled={busy || !feedback.trim()} className="px-3.5 py-1.5 rounded-lg bg-ac text-onac text-xs font-bold disabled:opacity-50">{t('sprint.delib.revise', undefined, 'Revize iste')}</button>
                </div>
              )}
              {err && <div className="text-[11px] text-err">{err}</div>}

              {/* Mesaj Akışı */}
              {shown.messages.map((msg, idx) => {
                const color = ROLE_COLORS[msg.agent_id] || { bg: 'bg-panel2', text: 'text-ink', border: 'border-line' };
                const isProposal = msg.sentiment === 'PROPOSAL';
                const isCritique = msg.sentiment === 'CRITIQUE';
                const isFinal = msg.sentiment === 'CONSENSUS';
                const isManager = msg.agent_id === 'MANAGER';

                return (
                  <div 
                    key={idx} 
                    className="p-3.5 bg-panel border border-line rounded-card shadow-xs flex flex-col gap-2 animate-fade-in"
                  >
                    {/* Ajan Bilgisi & Sentiment Rozeti */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${color.bg} ${color.text} ${color.border}`}>
                          {msg.agent_id}
                        </span>
                        <span className="text-xs font-bold text-ink">{msg.role}</span>
                        <span className="text-[10px] font-mono text-ink3">{msg.timestamp}</span>
                      </div>

                      <div>
                        {isManager && (
                          <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded-full bg-acd text-ac border border-ac/40">{t('sprint.delib.badgeManagerFeedback', undefined, 'YÖNETİCİ GERİ BİLDİRİMİ')}</span>
                        )}
                        {!isManager && isProposal && (
                          <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded-full bg-infod text-info border border-info/30 flex items-center gap-1">
                            <Lightbulb className="w-3 h-3" />
                            {t('sprint.delib.badgeProposal', undefined, 'MİMARİ ÖNERİ')}
                          </span>
                        )}
                        {!isManager && isCritique && (
                          <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded-full bg-warnd text-warn border border-warn/30 flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3" />
                            {t('sprint.delib.badgeCritique', undefined, 'RİSK & TEST DEĞERLENDİRMESİ')}
                          </span>
                        )}
                        {!isManager && isFinal && (
                          <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded-full bg-okd text-ok border border-ok/30 flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" />
                            {t('sprint.delib.badgeConsensus', undefined, 'KONSENSÜS KARARI')}
                          </span>
                        )}
                        {!isManager && !isProposal && !isCritique && !isFinal && (
                          <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded-full bg-panel2 text-ink3 border border-line flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3 text-ok" />
                            {t('sprint.delib.badgeAgreed', undefined, 'MUTABIK')}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Mesaj İçeriği */}
                    <div className="text-xs text-ink/90 leading-relaxed font-sans whitespace-pre-line pl-1 border-l-2 border-line/60">
                      {msg.message}
                    </div>
                  </div>
                );
              })}
            </>
          )}
          </>)}
        </div>

        {/* Alt Bar: Yeni Müzakere Başlatma Girişi */}
        <div className="p-3.5 border-t border-line bg-panel2 shrink-0 flex items-center gap-2">
          <input
            type="text"
            value={customTopic}
            onChange={(e) => setCustomTopic(e.target.value)}
            placeholder={t('sprint.delib.topicPh', undefined, 'Özel müzakere konusu (Boş bırakılırsa mevcut şartnameyi tartışırlar)...')}
            className="flex-1 bg-sunk border border-line rounded-md px-3 py-1.5 text-xs text-ink placeholder-ink3 focus:outline-none focus:border-ac font-sans"
            onKeyDown={(e) => e.key === 'Enter' && handleStart()}
          />
          <button
            onClick={handleStart}
            disabled={isStarting}
            className="px-4 py-1.5 bg-ac hover:bg-ac/90 text-onac rounded-md text-xs font-semibold flex items-center gap-1.5 transition shadow-xs disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" />
            <span>{isStarting ? t('sprint.delib.discussing', undefined, 'Tartışılıyor...') : t('sprint.delib.start', undefined, 'Müzakere Başlat')}</span>
          </button>
        </div>

      </div>
    </div>
  );
};
