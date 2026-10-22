import React, { useState } from 'react';
import { Layers, History, ChevronUp, ChevronDown, Radio } from 'lucide-react';
import { KanbanBoard } from './KanbanBoard';
import { TimelinePlayer } from './TimelinePlayer';
import { JiraIssue, KanbanTask, TelemetryEvent } from '../types/telemetry';
import { useI18n } from '../i18n';

interface BottomDockProps {
  tasks: KanbanTask[];
  issues: JiraIssue[];
  onAddAuditNote?: (issueId: string, notes: string) => Promise<any>;
  events: TelemetryEvent[];
  isReplayMode: boolean;
  replayIndex: number;
  onToggleReplayMode: (active: boolean) => void;
  onSeek: (action: number | ((prev: number) => number)) => void;
}

const COLS: { id: string; label: string }[] = [
  { id: 'BACKLOG', label: 'Backlog' }, { id: 'ARCHITECTURE', label: 'Arch' }, { id: 'DEVELOPMENT', label: 'Dev' },
  { id: 'QA_TESTING', label: 'QA' }, { id: 'DEVOPS_DEPLOY', label: 'DevOps' }, { id: 'RELEASED', label: 'Live' },
];

/** Alta sabit çubuk: solda Timeline düğmesi, yanında Canlı Sprint & Kanban. İkisi de kapalı başlar; açılınca çubuğun üstünde panel olarak görünür (sayfa düzenini itmez). */
export const BottomDock: React.FC<BottomDockProps> = ({ tasks, issues, onAddAuditNote, events, isReplayMode, replayIndex, onToggleReplayMode, onSeek }) => {
  const { t: tr } = useI18n();
  const [kanbanOpen, setKanbanOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const counts = COLS.map(c => ({ ...c, n: tasks.filter(t => t.state === c.id).length }));

  return (
    <div className="relative shrink-0">
      {(kanbanOpen || timelineOpen) && (
        <div className="absolute left-0 right-0 bottom-full mb-1 z-30 flex flex-col gap-2 pointer-events-none">
          {kanbanOpen && (
            <div className="pointer-events-auto h-[340px] bg-panel border border-line rounded-panel shadow-2xl overflow-hidden">
              <KanbanBoard tasks={tasks} issues={issues} onAddAuditNote={onAddAuditNote} />
            </div>
          )}
          {timelineOpen && (
            <div className="pointer-events-auto bg-panel border border-line rounded-panel shadow-2xl overflow-hidden">
              <TimelinePlayer events={events} isReplayMode={isReplayMode} replayIndex={replayIndex} onToggleReplayMode={onToggleReplayMode} onSeek={onSeek} />
            </div>
          )}
        </div>
      )}

      <div className="relative z-30 h-9 px-3 flex items-center gap-2 bg-panel border border-line rounded-panel shadow-panel text-xs select-none">
        <button
          type="button"
          onClick={() => setTimelineOpen(o => !o)}
          title={tr('misc.bottom.timelineTip', undefined, 'Zaman tüneli (geçmiş olayları oynat)')}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border font-semibold transition ${timelineOpen ? 'bg-acd border-ac/40 text-ac' : 'bg-panel2 border-line text-ink2 hover:text-ink'}`}
        >
          {isReplayMode ? <History className="w-3.5 h-3.5 text-warn" /> : <Radio className="w-3.5 h-3.5 text-ok" />}
          Timeline{isReplayMode ? ` · ${tr('misc.bottom.replay', undefined, 'tekrar')}` : ` · ${tr('misc.bottom.live', undefined, 'canlı')}`}
          {timelineOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
        </button>

        <button
          type="button"
          onClick={() => setKanbanOpen(o => !o)}
          title={tr('misc.bottom.kanbanTip', undefined, 'Canlı sprint ve Kanban durum panosu')}
          className={`flex items-center gap-2 px-2.5 py-1 rounded-md border font-semibold transition ${kanbanOpen ? 'bg-acd border-ac/40 text-ac' : 'bg-panel2 border-line text-ink2 hover:text-ink'}`}
        >
          <Layers className="w-3.5 h-3.5 text-ac" />
          {tr('misc.bottom.kanban', undefined, 'Canlı Sprint & Kanban')}
          <span className="font-mono text-ink3">· {tr('misc.bottom.taskCount', { n: tasks.length }, '{n} görev')}</span>
          <span className="hidden lg:flex items-center gap-1">
            {counts.map(c => (
              <span key={c.id} className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${c.n ? 'bg-sunk text-ink border-line' : 'text-ink3 border-transparent'}`} title={c.id}>{c.label} {c.n}</span>
            ))}
          </span>
          {kanbanOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
        </button>
      </div>
    </div>
  );
};
