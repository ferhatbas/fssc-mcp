import React, { useState } from 'react';
import { TelemetryEvent } from '../types/telemetry';
import { useI18n } from '../i18n';
import { 
  Terminal, 
  Search, 
  ArrowRight, 
  AlertCircle, 
  CheckCircle2, 
  Clock, 
  Code2, 
  Sparkles
} from 'lucide-react';

interface EventLogProps {
  events: TelemetryEvent[];
  /** Projeler arası mesaj rozetini göstermek için aktif proje kimliği */
  currentProjectId?: string;
}

export const EventLog: React.FC<EventLogProps> = ({ events, currentProjectId }) => {
  const { t } = useI18n();
  const [selectedEvent, setSelectedEvent] = useState<TelemetryEvent | null>(null);
  const [filterType, setFilterType] = useState<'ALL' | 'ERRORS' | 'SUCCESS'>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');

  const filteredEvents = events.filter(evt => {
    if (filterType === 'ERRORS' && evt.status !== 'FAILED') return false;
    if (filterType === 'SUCCESS' && evt.status !== 'SUCCESS') return false;
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      const matchTrace = evt.trace_id.toLowerCase().includes(term);
      const matchAction = evt.action.toLowerCase().includes(term);
      const matchAgent = evt.from_agent.toLowerCase().includes(term) || evt.to_agent.toLowerCase().includes(term);
      return matchTrace || matchAction || matchAgent;
    }
    return true;
  });

  return (
    <div className="w-full h-full flex flex-col bg-panel select-none">
      {/* Header */}
      <div className="p-3 border-b border-line flex items-center justify-between bg-panel2/60">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-ac" />
          <h2 className="text-xs font-bold font-mono text-ink tracking-wider uppercase">
            {t('board.log.title', undefined, 'Canlı Telemetri Log Akışı')}
          </h2>
        </div>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-sunk text-ink3 border border-line">
          {t('board.log.count', { n: filteredEvents.length }, `${filteredEvents.length} Kayıt`)}
        </span>
      </div>

      {/* Filters & Search */}
      <div className="p-2.5 border-b border-line bg-panel flex flex-col gap-2">
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-ink3 absolute left-2.5 top-2.5" />
          <input 
            type="text"
            placeholder={t('board.log.searchPh', undefined, 'Trace, ajan veya action ara...')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-8 pr-2.5 py-1.5 bg-sunk border border-line rounded-md text-xs text-ink placeholder-ink3 focus:outline-none focus:border-ac transition font-sans"
          />
        </div>

        <div className="flex items-center gap-1.5 text-[10px] font-mono">
          <button 
            onClick={() => setFilterType('ALL')}
            className={`px-2.5 py-1 rounded-md transition font-medium ${
              filterType === 'ALL' 
                ? 'bg-ac text-onac shadow-xs' 
                : 'bg-sunk text-ink3 hover:text-ink border border-line'
            }`}
          >
            {t('board.log.all', undefined, 'Tümü')}
          </button>
          <button 
            onClick={() => setFilterType('ERRORS')}
            className={`px-2.5 py-1 rounded-md transition flex items-center gap-1 font-medium ${
              filterType === 'ERRORS' 
                ? 'bg-err text-onac shadow-xs' 
                : 'bg-errd text-err border border-err/30 hover:opacity-80'
            }`}
          >
            <AlertCircle className="w-3 h-3 text-current" />
            {t('board.log.errors', undefined, 'Hatalar / Bugs')}
          </button>
          <button 
            onClick={() => setFilterType('SUCCESS')}
            className={`px-2.5 py-1 rounded-md transition flex items-center gap-1 font-medium ${
              filterType === 'SUCCESS' 
                ? 'bg-ok text-onac shadow-xs' 
                : 'bg-okd text-ok border border-ok/30 hover:opacity-80'
            }`}
          >
            <CheckCircle2 className="w-3 h-3 text-current" />
            {t('board.log.success', undefined, 'Başarılı')}
          </button>
        </div>
      </div>

      {/* Event Stream List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {filteredEvents.length === 0 ? (
          <div className="h-40 flex flex-col items-center justify-center text-xs font-mono text-ink3 gap-1.5">
            <Clock className="w-5 h-5 text-ink3 animate-spin" />
            <span>{t('board.log.waiting', undefined, 'Olay bekleniyor...')}</span>
          </div>
        ) : (
          filteredEvents.map((evt) => {
            const isSelected = selectedEvent?.id === evt.id;
            const isError = evt.status === 'FAILED';

            return (
              <div
                key={evt.id}
                onClick={() => setSelectedEvent(evt)}
                className={`p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                  isSelected 
                    ? 'border-ac bg-acd shadow-xs' 
                    : isError 
                      ? 'border-err/40 bg-errd hover:border-err/60' 
                      : 'border-line bg-panel2 hover:border-line2'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5 font-mono font-bold text-[11px]">
                    <span className="text-ink">{evt.from_agent}</span>
                    <ArrowRight className="w-3 h-3 text-ink3" />
                    <span className={isError ? 'text-err' : 'text-ac'}>{evt.to_agent}</span>
                    {evt.from_project && evt.from_project !== (currentProjectId || evt.to_project) && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-infod text-info border border-info/40" title={t('board.log.fromProject', undefined, 'Başka projeden gelen ekip mesajı')}>
                        ⇄ {evt.from_project}
                      </span>
                    )}
                    {evt.to_project && evt.to_project !== (currentProjectId || evt.from_project) && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-infod text-info border border-info/40" title={t('board.log.toProject', undefined, 'Başka projeye giden ekip mesajı')}>
                        → {evt.to_project}
                      </span>
                    )}
                  </div>
                  <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded font-bold ${
                    isError ? 'bg-errd text-err border border-err/30' : 'bg-okd text-ok border border-ok/30'
                  }`}>
                    {evt.status}
                  </span>
                </div>

                <div className="flex items-center justify-between text-[10px] font-mono text-ink3">
                  <span className="text-ink font-semibold">{evt.action}</span>
                  <span>{new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                </div>

                {evt.tokens_used > 0 && (
                  <div className="flex items-center gap-1 text-[9px] font-mono text-warn mt-1">
                    <Sparkles className="w-2.5 h-2.5" />
                    {t('board.log.tokens', { n: evt.tokens_used }, `${evt.tokens_used} tokens`)}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Selected Event Payload Inspector Drawer */}
      {selectedEvent && (
        <div className="border-t border-line bg-sunk p-3 max-h-[260px] overflow-y-auto shadow-inner">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Code2 className="w-4 h-4 text-ac" />
              <span className="text-[11px] font-mono font-bold text-ink">
                {t('board.log.inspector', { action: selectedEvent.action }, `JSON Payload Inspector (${selectedEvent.action})`)}
              </span>
            </div>
            <button 
              onClick={() => setSelectedEvent(null)}
              className="text-[10px] font-mono text-ink3 hover:text-ink px-2 py-0.5 rounded bg-panel border border-line"
            >
              {t('board.close', undefined, 'Kapat')}
            </button>
          </div>

          <div className="space-y-1 mb-2 text-[10px] font-mono text-ink3">
            <div><span className="text-ink3 font-semibold">{t('board.log.traceId', undefined, 'Trace ID:')}</span> <span className="text-ink font-mono">{selectedEvent.trace_id}</span></div>
            {selectedEvent.current_file && (
              <div><span className="text-ink3 font-semibold">{t('board.log.file', undefined, 'File:')}</span> <span className="text-ac">{selectedEvent.current_file}</span></div>
            )}
          </div>

          <pre className="text-[10px] font-mono bg-panel p-2 rounded-md border border-line text-ink overflow-x-auto select-text leading-relaxed">
            {JSON.stringify(selectedEvent.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
