import React, { useState } from 'react';
import { JiraIssue } from '../types/telemetry';
import { useI18n } from '../i18n';
import { 
  X, 
  History, 
  CheckCircle2, 
  Clock, 
  User, 
  FileText, 
  Send, 
  ShieldCheck, 
  Tag,
  Layers,
  Sparkles
} from 'lucide-react';

interface TaskAuditModalProps {
  isOpen: boolean;
  onClose: () => void;
  issue: JiraIssue | null;
  onAddAuditNote: (issueId: string, notes: string) => Promise<any>;
}

export const TaskAuditModal: React.FC<TaskAuditModalProps> = ({
  isOpen,
  onClose,
  issue,
  onAddAuditNote
}) => {
  const { t } = useI18n();
  const [newNote, setNewNote] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  if (!isOpen || !issue) return null;

  const handleAddNote = async () => {
    if (!newNote.trim()) return;
    try {
      setIsSubmitting(true);
      await onAddAuditNote(issue.id, newNote.trim());
      setNewNote('');
    } catch (e) {
      console.error(e);
    } finally {
      setIsSubmitting(false);
    }
  };

  const auditList = issue.audit_trail || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in select-none">
      <div className="bg-panel border border-line rounded-panel shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-scale-up">
        
        {/* Modal Header */}
        <div className="px-5 py-3.5 border-b border-line flex items-center justify-between bg-panel2 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-card bg-acd border border-ac/20 text-ac">
              <History className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-bold text-ac">{issue.key || issue.id}</span>
                <span className="text-xs font-bold text-ink truncate max-w-[360px]">{issue.title}</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-sunk text-ink2 border border-line">
                  {issue.status}
                </span>
              </div>
              <p className="text-[10.5px] font-mono text-ink3 mt-0.5">
                {t('board.audit.assignee', undefined, 'Sorumlu:')} <strong className="text-ink">@{issue.assignee}</strong> • {t('board.audit.priority', undefined, 'Öncelik:')} <strong className="text-warn">{issue.priority}</strong>
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label={t('board.close', undefined, 'Kapat')}
            className="p-1.5 rounded-card hover:bg-sunk text-ink3 hover:text-ink transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body: Kabul Kriterleri & Denetim Tarihçesi */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-bg">
          
          {/* Kabul Kriterleri */}
          {issue.acceptance_criteria && issue.acceptance_criteria.length > 0 && (
            <div className="p-3.5 rounded-card bg-panel border border-line">
              <h4 className="text-[11px] font-bold font-mono text-ink uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-ok" />
                {t('board.audit.criteria', undefined, 'Kabul Kriterleri (Acceptance Criteria)')}
              </h4>
              <ul className="space-y-1.5">
                {issue.acceptance_criteria.map((crit, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-xs text-ink/90 font-sans">
                    <CheckCircle2 className="w-3.5 h-3.5 text-ok shrink-0 mt-0.5" />
                    <span>{crit}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Görev Denetim Tarihçesi (Audit Trail) */}
          <div className="space-y-2.5">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold font-mono text-ink uppercase tracking-wide flex items-center gap-1.5">
                <History className="w-3.5 h-3.5 text-ac" />
                {t('board.audit.trail', undefined, 'Kronolojik Denetim İzi (Audit Trail)')}
              </h4>
              <span className="text-[10px] font-mono text-ink3">
                {t('board.audit.records', { n: auditList.length }, `${auditList.length} İşlem Kaydı`)}
              </span>
            </div>

            {auditList.length === 0 ? (
              <div className="py-8 text-center border border-dashed border-line rounded-card bg-panel p-4">
                <Clock className="w-8 h-8 text-ink3 mx-auto mb-2 opacity-50" />
                <p className="text-xs text-ink3 font-mono">{t('board.audit.none', undefined, 'Bu görev için henüz işlem geçmişi kaydedilmedi.')}</p>
              </div>
            ) : (
              <div className="space-y-2 relative before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-line">
                {auditList.map((entry, idx) => (
                  <div key={idx} className="relative pl-7 group">
                    {/* Checkpoint Noktası */}
                    <div className="absolute left-1.5 top-2 w-3.5 h-3.5 rounded-full bg-panel border-2 border-ac transform -translate-x-1/2 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-ac" />
                    </div>

                    <div className="p-3 rounded-card bg-panel border border-line shadow-xs">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-full bg-acd text-ac border border-ac/20">
                            @{entry.agent_id}
                          </span>
                          <span className="text-xs font-semibold text-ink font-mono">{entry.action}</span>
                        </div>
                        <span className="text-[10px] font-mono text-ink3">{entry.timestamp}</span>
                      </div>

                      {entry.notes && (
                        <p className="text-xs text-ink/90 font-sans mt-1 leading-relaxed bg-sunk/60 p-2 rounded border border-line/40">
                          {entry.notes}
                        </p>
                      )}

                      {entry.files_affected && entry.files_affected.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap mt-1.5">
                          {entry.files_affected.map((f, fi) => (
                            <span key={fi} className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-panel2 text-ink2 border border-line">
                              {f}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>

        {/* Modal Alt Bar: Denetim Notu Ekle */}
        <div className="p-3.5 border-t border-line bg-panel2 shrink-0 flex items-center gap-2">
          <input
            type="text"
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            placeholder={t('board.audit.notePh', undefined, 'Bu göreve denetim notu veya ilerleme açıklaması ekleyin...')}
            className="flex-1 bg-sunk border border-line rounded-md px-3 py-1.5 text-xs text-ink placeholder-ink3 focus:outline-none focus:border-ac font-sans"
            onKeyDown={(e) => e.key === 'Enter' && handleAddNote()}
          />
          <button
            onClick={handleAddNote}
            disabled={isSubmitting || !newNote.trim()}
            className="px-4 py-1.5 bg-ac hover:bg-ac/90 text-onac rounded-md text-xs font-semibold flex items-center gap-1.5 transition shadow-xs disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" />
            <span>{isSubmitting ? t('board.audit.saving', undefined, 'Kaydediliyor...') : t('board.audit.addNote', undefined, 'Not Ekle')}</span>
          </button>
        </div>

      </div>
    </div>
  );
};
