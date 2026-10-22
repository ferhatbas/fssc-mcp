import React, { useState } from 'react';
import { KanbanState, KanbanTask, JiraIssue } from '../types/telemetry';
import { TaskAuditModal } from './TaskAuditModal';
import { useI18n } from '../i18n';
import { 
  FolderArchive, 
  Layers, 
  Code2, 
  CheckCircle2, 
  Rocket, 
  CheckCheck,
  History
} from 'lucide-react';

interface KanbanBoardProps {
  tasks: KanbanTask[];
  issues?: JiraIssue[];
  onAddAuditNote?: (issueId: string, notes: string) => Promise<any>;
}

const COLUMNS: { id: KanbanState; title: string; icon: React.ReactNode; topBorder: string }[] = [
  { id: 'BACKLOG', title: 'Backlog (PM)', icon: <FolderArchive className="w-4 h-4 text-ac" />, topBorder: 'border-t-ac' },
  { id: 'ARCHITECTURE', title: 'Architecture', icon: <Layers className="w-4 h-4 text-info" />, topBorder: 'border-t-info' },
  { id: 'DEVELOPMENT', title: 'In Development', icon: <Code2 className="w-4 h-4 text-ok" />, topBorder: 'border-t-ok' },
  { id: 'QA_TESTING', title: 'QA & Edge Cases', icon: <CheckCircle2 className="w-4 h-4 text-warn" />, topBorder: 'border-t-warn' },
  { id: 'DEVOPS_DEPLOY', title: 'DevOps & Deploy', icon: <Rocket className="w-4 h-4 text-ac" />, topBorder: 'border-t-ac' },
  { id: 'RELEASED', title: 'Released / Live', icon: <CheckCheck className="w-4 h-4 text-ok" />, topBorder: 'border-t-ok' },
];

const PRIORITY_BADGES: Record<string, string> = {
  P0: 'bg-errd text-err border-err/40 font-bold',
  P1: 'bg-warnd text-warn border-warn/40 font-bold',
  P2: 'bg-infod text-info border-info/40 font-bold',
};

export const KanbanBoard: React.FC<KanbanBoardProps> = ({ tasks, issues = [], onAddAuditNote }) => {
  const { t } = useI18n();
  const [selectedIssue, setSelectedIssue] = useState<JiraIssue | null>(null);
  const [openCol, setOpenCol] = useState<KanbanState | null>(null);
  const [colFilter, setColFilter] = useState('');

  const handleCardClick = (task: KanbanTask) => {
    const found = issues.find(i => i.id === task.id || i.key === task.id) || {
      id: task.id,
      key: task.id,
      order: 1,
      title: task.title,
      description: task.details || '',
      issue_type: 'TASK' as const,
      status: 'IN_PROGRESS' as const,
      priority: task.priority,
      assignee: task.assignee,
      acceptance_criteria: [],
      attachments: [],
      audit_trail: [],
      created_at: task.updated_at,
      updated_at: task.updated_at
    };
    setSelectedIssue(found);
  };

  return (
    <div className="w-full h-full bg-panel p-3 flex flex-col select-none">
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-line">
        <h2 className="text-xs font-bold font-mono tracking-wider text-ink flex items-center gap-2 uppercase">
          <span className="w-2 h-2 rounded-full bg-ac animate-pulse"></span>
          {t('board.kanban.title', undefined, 'Canlı Sprint & Kanban Durum Panosu')}
        </h2>
        <span className="text-[11px] font-mono text-ink3">
          {t('board.kanban.total', undefined, 'Toplam Görev:')} <strong className="text-ink">{tasks.length}</strong>
        </span>
      </div>

      <div className="grid grid-cols-6 gap-2.5 flex-1 min-h-[140px] overflow-x-auto">
        {COLUMNS.map(col => {
          const colTasks = tasks.filter(tk => tk.state === col.id);
          const colTitle = t(`board.kanban.col.${col.id}`, undefined, col.title);

          return (
            <div 
              key={col.id} 
              className={`bg-panel2 rounded-lg border border-line border-t-[2.5px] ${col.topBorder} p-2.5 flex flex-col`}
            >
              {/* Column Header */}
              <button
                type="button"
                onClick={() => { setColFilter(''); setOpenCol(col.id); }}
                title={t('board.kanban.openList', undefined, 'Tüm kartları liste olarak aç')}
                className="flex items-center justify-between pb-2 mb-2 border-b border-line w-full text-left hover:bg-sunk/60 rounded-t transition"
              >
                <div className="flex items-center gap-1.5">
                  {col.icon}
                  <span className="text-[11px] font-bold text-ink truncate">{colTitle}</span>
                </div>
                <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-sunk text-ink2 border border-line">
                  {colTasks.length}
                </span>
              </button>

              {/* Tasks List */}
              <div className="flex-1 overflow-y-auto space-y-2">
                {colTasks.length === 0 ? (
                  <div className="h-full min-h-[60px] border border-dashed border-line2 rounded-md flex items-center justify-center text-[10px] font-mono text-ink3 italic">
                    {t('board.kanban.noCards', undefined, 'kart yok')}
                  </div>
                ) : (
                  colTasks.map(task => (
                    <div 
                      key={task.id}
                      onClick={() => handleCardClick(task)}
                      className="bg-panel rounded-[9px] border border-line p-2 hover:border-ac hover:shadow-sm cursor-pointer transition shadow-xs group"
                      title={t('board.kanban.cardTitle', undefined, 'Detay & Denetim Tarihçesi (Audit Trail) için tıklayın')}
                    >
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span className="text-[10px] font-mono font-bold text-ac">{task.id}</span>
                        <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${PRIORITY_BADGES[task.priority] || PRIORITY_BADGES.P1}`}>
                          {task.priority}
                        </span>
                      </div>

                      <h4 className="text-[11px] font-semibold text-ink line-clamp-2 leading-snug mb-1 font-sans group-hover:text-ac transition">
                        {task.title}
                      </h4>

                      {task.details && (
                        <p className="text-[10px] text-ink3 line-clamp-2 leading-tight mb-1.5 font-mono">
                          {task.details}
                        </p>
                      )}

                      <div className="flex items-center justify-between pt-1 border-t border-line text-[9px] font-mono text-ink3">
                        <span className="text-ink2 font-semibold uppercase">@{task.assignee}</span>
                        <span className="flex items-center gap-1 text-[8.5px]">
                          <History className="w-2.5 h-2.5 text-ac" />
                          {new Date(task.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Sütun listesi penceresi: dar alanda 24 kartı okumak zor olduğundan tümü liste halinde */}
      {openCol && (() => {
        const col = COLUMNS.find(c => c.id === openCol)!;
        const all = tasks.filter(tk => tk.state === openCol);
        const openColTitle = t(`board.kanban.col.${col.id}`, undefined, col.title);
        const q = colFilter.trim().toLowerCase();
        const shown = q ? all.filter(tk => `${tk.id} ${tk.title} ${tk.assignee} ${tk.details || ''}`.toLowerCase().includes(q)) : all;
        return (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" onClick={() => setOpenCol(null)}>
            <div className="bg-panel border border-line rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line">
                <div className="flex items-center gap-2 text-sm font-bold text-ink">{col.icon}{openColTitle}
                  <span className="text-[11px] font-mono font-bold px-1.5 py-0.5 rounded bg-sunk text-ink2 border border-line">{all.length}</span>
                </div>
                <div className="flex items-center gap-2">
                  <input value={colFilter} onChange={e => setColFilter(e.target.value)} placeholder={t('board.kanban.searchPh', undefined, 'Ara: anahtar, başlık, ajan…')} autoFocus
                    className="w-64 text-xs bg-sunk border border-line rounded-md px-2.5 py-1 text-ink placeholder-ink3 focus:outline-none focus:border-ac" />
                  <button onClick={() => setOpenCol(null)} className="px-2.5 py-1 text-xs rounded-md border border-line text-ink2 hover:text-ink">{t('board.close', undefined, 'Kapat')}</button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto divide-y divide-line">
                {shown.length === 0 ? (
                  <div className="p-6 text-center text-xs text-ink3 italic">{all.length === 0 ? t('board.kanban.emptyCol', undefined, 'Bu sütunda kart yok.') : t('board.kanban.noMatch', undefined, 'Aramaya uyan kart yok.')}</div>
                ) : shown.map(task => (
                  <button key={task.id} type="button" onClick={() => { setOpenCol(null); handleCardClick(task); }}
                    className="w-full text-left px-4 py-2.5 hover:bg-sunk/70 transition flex items-start gap-3" title={t('board.kanban.rowTitle', undefined, 'Detay & denetim tarihçesi')}>
                    <span className="text-[11px] font-mono font-bold text-ac shrink-0 w-16">{task.id}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-semibold text-ink">{task.title}</span>
                      {task.details && <span className="block text-[11px] text-ink3 line-clamp-2 font-mono">{task.details}</span>}
                    </span>
                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded border shrink-0 ${PRIORITY_BADGES[task.priority] || PRIORITY_BADGES.P1}`}>{task.priority}</span>
                    <span className="text-[10px] font-mono text-ink2 font-semibold uppercase shrink-0 w-28 text-right">@{task.assignee}</span>
                    <span className="text-[10px] font-mono text-ink3 shrink-0 w-16 text-right">{new Date(task.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Task Audit Modal */}
      <TaskAuditModal
        isOpen={!!selectedIssue}
        onClose={() => setSelectedIssue(null)}
        issue={selectedIssue}
        onAddAuditNote={onAddAuditNote || (async () => {})}
      />
    </div>
  );
};
