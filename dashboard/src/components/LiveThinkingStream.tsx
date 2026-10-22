import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { TelemetryEvent, LiveThinking } from '../types/telemetry';
import { useI18n } from '../i18n';
import { 
  Brain, 
  Zap, 
  ArrowRight, 
  MessageSquare, 
  ChevronDown, 
  ChevronUp, 
  Terminal, 
  Sparkles,
  Bot,
  Maximize2,
  X
} from 'lucide-react';

interface LiveThinkingStreamProps {
  events: TelemetryEvent[];
  isExecuting?: boolean;
  /** MCP istemcisinin report_thinking ile gönderdigi canli dusunce (olay kaydi uretmez) */
  liveThinking?: LiveThinking | null;
  /** Ajan durumları: "şu an kim çalışıyor" göstergesi için */
  agents?: Array<{ id: string; status?: string }>;
}

export const LiveThinkingStream: React.FC<LiveThinkingStreamProps> = ({ events, isExecuting, liveThinking, agents }) => {
  const { t } = useI18n();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => { const iv = setInterval(() => setNowMs(Date.now()), 5000); return () => clearInterval(iv); }, []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const modalScrollRef = useRef<HTMLDivElement>(null);

  // Modal: Esc ile kapanır; açıkken sayfa kaydırması kilitlenir
  useEffect(() => {
    if (!isModalOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsModalOpen(false);
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [isModalOpen]);

  // Modal açıkken yeni olay gelince en alta (en yeni) kaydır
  useEffect(() => {
    if (isModalOpen && modalScrollRef.current) {
      modalScrollRef.current.scrollTop = modalScrollRef.current.scrollHeight;
    }
  }, [events.length, isModalOpen]);

  // En son gelen anlamlı olay
  // events dizisi YENİDEN ESKİYE sıralıdır (useTelemetryWS); en son olay ilk elemandır
  const latestEvent = events.length > 0 ? events[0] : null;

  // Otomatik aşağı kaydırma
  useEffect(() => {
    if (isExpanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length, isExpanded]);

  // Varsayılan / Fallback durumlar
  // Canli dusunce (MCP istemcisinden) en son olaydan daha yeniyse onu goster
  const liveIsNewer = !!liveThinking && (!latestEvent || liveThinking.timestamp >= latestEvent.timestamp);
  const thinkingText = (liveIsNewer ? liveThinking!.text : latestEvent?.thinking) ||
    (isExecuting
      ? t('run.lt.noPlanNote', undefined, 'Henüz modelden plan notu gelmedi (yalnızca modelin kendi notu gösterilir).')
      : t('run.lt.systemReady', undefined, 'Sistem hazır. Görev başlatıldığında modelin plan notları burada akacak.'));

  const actionText = (liveIsNewer && liveThinking!.what_doing) || latestEvent?.what_doing ||
    (isExecuting ? t('run.lt.executing', undefined, 'Geliştirme ve test pipeline icra ediliyor') : t('run.lt.idle', undefined, 'Boşta (İşlem bekleniyor)'));

  const nextText = latestEvent?.what_next || 
    (isExecuting ? t('run.lt.handoff', undefined, 'Sonraki aşamadaki ajana devredilecek') : t('run.lt.waitTrigger', undefined, 'Sıradaki görev için tetik bekleniyor'));

  const dialogueText = latestEvent?.friendly_dialogue || 
    (latestEvent ? t('run.lt.handshake', { from: latestEvent.from_agent, to: latestEvent.to_agent }, `${latestEvent.from_agent} ajanı ${latestEvent.to_agent} ile el sıkıştı.`) : t('run.lt.teamReady', undefined, 'Ekip hazır bekliyor.'));

  // "Kim düşünüyor?": canlı düşünce (report_thinking) en yeniyse onun ajanı, değilse son olayın ajanı; ayrıca durumu çalışıyor olan tüm ajanlar
  const thinkerId = liveIsNewer ? liveThinking!.agent_id : (latestEvent?.from_agent || '');
  const thinkerTs = liveIsNewer ? liveThinking!.timestamp : latestEvent?.timestamp;
  const thinkerOrder = liveIsNewer ? liveThinking!.order : (latestEvent?.payload as { order?: number } | undefined)?.order;
  const ageS = thinkerTs ? Math.max(0, Math.round((nowMs - new Date(thinkerTs).getTime()) / 1000)) : null;
  const ageLabel = ageS == null ? '' : ageS < 90 ? t('run.lt.agoSec', { n: ageS }, `${ageS} sn önce`) : ageS < 5400 ? t('run.lt.agoMin', { n: Math.round(ageS / 60) }, `${Math.round(ageS / 60)} dk önce`) : t('run.lt.agoHour', { n: Math.round(ageS / 3600) }, `${Math.round(ageS / 3600)} sa önce`);
  const workingAgents = (agents || []).filter(a => ['WORKING', 'BUG_FIX', 'PENDING_ACTION'].includes(a?.status || '')).map(a => a.id);
  const stale = ageS != null && ageS > 180;

  // Olay satırı: panel ve modal aynı görünümü kullanır; events yeniden eskiye sıralı, listede eskiden yeniye gösterilir
  const renderEvents = (list: TelemetryEvent[], wide = false) =>
    list.slice().reverse().map((evt, idx) => (
      <div key={idx} className="pt-2 first:pt-0 space-y-1">
        <div className="flex items-center justify-between text-ink3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-ac font-bold">[{evt.from_agent} → {evt.to_agent}]</span>
            <span className="text-ink bg-panel px-1.5 py-0.2 rounded border border-line">
              {evt.action}
            </span>
            {evt.current_file && (
              <span className="text-ac text-[10px]">📁 {evt.current_file}</span>
            )}
          </div>
          <span className="text-[10px] text-ink3 shrink-0">
            {new Date(evt.timestamp).toLocaleTimeString('tr-TR')}
          </span>
        </div>

        {/* İnsansı Diyalog */}
        {evt.friendly_dialogue && (
          <div className={`text-ac bg-acd px-2.5 py-1 rounded border border-ac/40 flex items-start gap-1.5 font-sans italic ${wide ? 'text-sm' : 'text-xs'}`}>
            <Bot className="w-3.5 h-3.5 text-ac mt-0.5 shrink-0" />
            <span>"{evt.friendly_dialogue}"</span>
          </div>
        )}

        {/* Thinking & Action */}
        <div className={`grid grid-cols-1 md:grid-cols-2 gap-2 text-ink2 bg-panel/40 p-1.5 rounded ${wide ? 'text-xs' : 'text-[10px]'}`}>
          <div>
            <span className="text-ac font-bold">🧠 {t('run.lt.thought', undefined, 'Düşünce:')} </span>
            <span className={evt.thinking ? '' : 'text-ink3 italic'}>{evt.thinking || t('run.lt.noModelNote', undefined, 'model notu yok')}</span>
          </div>
          <div>
            <span className="text-ok font-bold">⚡ {t('run.lt.action', undefined, 'Aksiyon:')} </span>
            <span>{evt.what_doing || evt.action}</span>
          </div>
        </div>
      </div>
    ));

  // Ayrıntı görünümleri için "kim aktif düşünüyor" özeti
  const activeStrip = (
    <div className="flex items-center gap-x-4 gap-y-1 flex-wrap text-[11px] font-mono px-3 py-2 bg-panel/60 border-b border-line/80">
      <span className="text-ink3">{t('run.lt.activeThinker', undefined, 'Aktif düşünen:')}</span>
      {thinkerId ? (
        <span className={`px-2 py-0.5 rounded-md border font-bold ${stale ? 'bg-sunk text-ink3 border-line' : 'bg-warnd text-warn border-warn/50'}`}>
          {thinkerId}{thinkerOrder ? ` · ${t('run.lt.stepNo', { n: thinkerOrder }, `adım #${thinkerOrder}`)}` : ''}{ageLabel ? ` · ${ageLabel}` : ''}
        </span>
      ) : <span className="text-ink3">—</span>}
      <span className="text-ink3">{t('run.lt.workingAgents', undefined, 'Durumu çalışan ajanlar:')}</span>
      <span className={workingAgents.length ? 'text-warn font-bold' : 'text-ink3'}>{workingAgents.length ? workingAgents.join(', ') : t('run.lt.none', undefined, 'yok')}</span>
      {stale && <span className="text-ink3 italic">{t('run.lt.noSignalNote', undefined, '(uzun süredir sinyal yok: ajan beklemede ya da koşu kopmuş olabilir)')}</span>}
    </div>
  );

  return (
    <div className="bg-sunk/90 border border-line rounded-xl overflow-hidden shadow-2xl backdrop-blur-md transition-all">
      {/* Üst Canlı Çubuk (Ticker Bar) */}
      <div className="px-4 py-2.5 bg-panel2 border-b border-line/80 flex flex-wrap items-center justify-between gap-3">
        {/* Sol: Thinking & Ne Yapıyor Özeti */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className="relative p-1.5 rounded-lg bg-acd border border-ac/30 text-ac shrink-0" title={t('run.lt.streamTitle', undefined, 'LLM düşünce akışı')}>
            <Brain className={`w-3.5 h-3.5 text-ac ${isExecuting ? 'animate-pulse' : ''}`} />
            {isExecuting && <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-ac animate-ping" />}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-xs">
              {thinkerId && (
                <span className={`shrink-0 px-2 py-0.5 rounded-md border font-mono text-[11px] font-bold ${stale ? 'bg-sunk text-ink3 border-line' : 'bg-warnd text-warn border-warn/50'}`}
                  title={stale ? t('run.lt.staleTitle', undefined, 'Uzun süredir yeni sinyal yok: ajan beklemede ya da koşu kopmuş olabilir') : t('run.lt.lastFrom', undefined, 'Son düşünce/olay bu ajandan geldi')}>
                  {thinkerId}{thinkerOrder ? ` · ${t('run.lt.stepNo', { n: thinkerOrder }, `adım #${thinkerOrder}`)}` : ''}{ageLabel ? ` · ${ageLabel}` : ''}
                </span>
              )}
              <span className="text-ink font-medium truncate flex items-center gap-1.5">
                <Sparkles className="w-3 h-3 text-warn shrink-0" />
                <strong className="text-ac font-mono">{t('run.lt.thought', undefined, 'Düşünce:')}</strong> {thinkingText}
              </span>
            </div>
            
            <div className="flex items-center gap-3 text-[11px] text-ink3 mt-0.5 font-mono truncate">
              <span className="flex items-center gap-1 text-ok">
                <Zap className="w-3 h-3 shrink-0" />
                <span>{t('run.lt.whatDoing', undefined, 'Ne Yapıyor:')} <span className="text-ink">{actionText}</span></span>
              </span>
              <span className="text-ink3">•</span>
              <span className="flex items-center gap-1 text-info">
                <ArrowRight className="w-3 h-3 shrink-0" />
                <span>{t('run.lt.next', undefined, 'Sırada:')} <span className="text-ink2">{nextText}</span></span>
              </span>
              <span className="text-ink3">•</span>
              <span className={workingAgents.length ? 'text-warn' : 'text-ink3'} title={t('run.lt.workingAgentsTitle', undefined, 'Durumu çalışıyor olan ajanlar')}>
                {t('run.lt.workingNow', undefined, 'Şu an çalışan:')} {workingAgents.length ? workingAgents.join(', ') : (stale ? t('run.lt.nobodyNoSignal', undefined, 'kimse (sinyal yok)') : t('run.lt.nobody', undefined, 'kimse'))}
              </span>
            </div>
          </div>
        </div>

        {/* Sağ: İnsansı Samimi Diyalog & Genişletme Butonu */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="hidden lg:flex items-center gap-1.5 px-3 py-1 bg-acd/60 border border-ac/40 rounded-lg text-ac text-xs max-w-sm truncate" title={dialogueText}>
            <MessageSquare className="w-3.5 h-3.5 text-ac shrink-0" />
            <span className="truncate italic">"{dialogueText}"</span>
          </div>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="px-2.5 py-1 text-[11px] font-semibold text-ink2 hover:text-ink bg-panel hover:bg-panel2 rounded-lg border border-line2/80 transition flex items-center gap-1"
          >
            <Terminal className="w-3 h-3 text-ok" />
            <span>{isExpanded ? t('common.close', undefined, 'Kapat') : t('run.lt.flow', { n: events.length }, `Akış (${events.length})`)}</span>
            {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>

          <button
            onClick={() => setIsModalOpen(true)}
            title={t('run.lt.openWide', undefined, 'Canlı akışı geniş pencerede aç')}
            aria-label={t('run.lt.openWide', undefined, 'Canlı akışı geniş pencerede aç')}
            className="p-1.5 text-ink2 hover:text-ink bg-panel hover:bg-panel2 rounded-lg border border-line2/80 transition"
          >
            <Maximize2 className="w-3.5 h-3.5 text-ac" />
          </button>
        </div>
      </div>

      {/* Genişletilebilir Detaylı Canlı Terminal Akışı */}
      {isExpanded && (
        <div 
          ref={scrollRef}
          className="max-h-56 overflow-y-auto bg-sunk font-mono text-[11px] animate-in slide-in-from-top-2 duration-150"
        >
          {activeStrip}
          <div className="p-3 space-y-2 divide-y divide-line">
          {events.length === 0 ? (
            <div className="text-ink3 text-center py-4 italic">
              {t('run.lt.noRecords', undefined, 'Henüz düşünce veya etkileşim kaydı oluşmadı.')}
            </div>
          ) : (
            renderEvents(events.slice(0, 20))
          )}
          </div>
        </div>
      )}

      {/* Geniş pencere: tüm olaylar, sayfanın üstünde */}
      {isModalOpen && createPortal(
        <div
          className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sm:p-8"
          onClick={() => setIsModalOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label={t('run.lt.modalAria', undefined, 'Canlı düşünce akışı')}
        >
          <div
            className="w-full max-w-6xl h-[88vh] bg-sunk border border-line rounded-2xl shadow-2xl flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-3 bg-panel2 border-b border-line flex items-center justify-between gap-3 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <Brain className={`w-4 h-4 text-ac ${isExecuting ? 'animate-pulse' : ''}`} />
                <span className="font-mono text-sm font-bold text-ink tracking-wide">{t('run.lt.modalTitle', undefined, 'Canlı Düşünce Akışı')}</span>
                <span className="text-[11px] text-ink3 font-mono">({t('run.lt.recordsN', { n: events.length }, `${events.length} kayıt`)})</span>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                aria-label={t('common.close', undefined, 'Kapat')}
                className="p-1.5 rounded-lg text-ink2 hover:text-ink hover:bg-panel border border-transparent hover:border-line2/80 transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {activeStrip}
            {/* Şu anki durum özeti */}
            <div className="px-5 py-3 border-b border-line/80 bg-panel/40 text-xs space-y-1 shrink-0">
              <div className="text-ink"><strong className="text-ac font-mono">{t('run.lt.thought', undefined, 'Düşünce:')}</strong> {thinkingText}</div>
              <div className="text-ink3 font-mono">
                <span className="text-ok">{t('run.lt.whatDoing', undefined, 'Ne Yapıyor:')}</span> <span className="text-ink">{actionText}</span>
                <span className="mx-2">•</span>
                <span className="text-info">{t('run.lt.next', undefined, 'Sırada:')}</span> <span className="text-ink2">{nextText}</span>
              </div>
            </div>

            <div
              ref={modalScrollRef}
              className="flex-1 overflow-y-auto p-5 space-y-3 font-mono text-[12px] divide-y divide-line"
            >
              {events.length === 0 ? (
                <div className="text-ink3 text-center py-8 italic">
                  {t('run.lt.noRecords', undefined, 'Henüz düşünce veya etkileşim kaydı oluşmadı.')}
                </div>
              ) : (
                renderEvents(events, true)
              )}
            </div>

            <div className="px-5 py-2 border-t border-line bg-panel2 text-[11px] text-ink3 shrink-0">
              {t('run.lt.closeHint', undefined, 'Kapatmak için Esc tuşuna basın ya da pencerenin dışına tıklayın.')}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};
