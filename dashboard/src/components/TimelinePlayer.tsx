import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Pause, 
  SkipBack, 
  SkipForward, 
  RotateCcw, 
  Radio, 
  Clock, 
  FastForward, 
  Sparkles, 
  FileCode2, 
  ArrowRight,
  History
} from 'lucide-react';
import { TelemetryEvent } from '../types/telemetry';
import { useI18n } from '../i18n';

interface TimelinePlayerProps {
  events: TelemetryEvent[];
  isReplayMode: boolean;
  replayIndex: number;
  onToggleReplayMode: (active: boolean) => void;
  onSeek: (action: number | ((prev: number) => number)) => void;
}

export const TimelinePlayer: React.FC<TimelinePlayerProps> = ({
  events,
  isReplayMode,
  replayIndex,
  onToggleReplayMode,
  onSeek,
}) => {
  const { t } = useI18n();
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1); // 1x, 2x, 4x
  const playTimerRef = useRef<any>(null);

  // Kronolojik sıralı olaylar (en eskiden en yeniye)
  const sortedEvents = React.useMemo(() => {
    return [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [events]);

  const totalSteps = sortedEvents.length;
  const currentEvent = sortedEvents[replayIndex] || sortedEvents[sortedEvents.length - 1];

  // Zaman farkı hesaplama (başlangıçtan itibaren)
  const startTime = sortedEvents.length > 0 ? new Date(sortedEvents[0].timestamp).getTime() : 0;
  const currentTime = currentEvent ? new Date(currentEvent.timestamp).getTime() : 0;
  const elapsedSeconds = startTime > 0 && currentTime >= startTime 
    ? Math.round((currentTime - startTime) / 1000) 
    : 0;

  // Otomatik Oynatma Mantığı
  useEffect(() => {
    if (isPlaying && isReplayMode) {
      const intervalMs = Math.round(2000 / playbackSpeed);
      playTimerRef.current = setInterval(() => {
        onSeek((prev: number) => {
          if (prev >= totalSteps - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, intervalMs);
    } else {
      if (playTimerRef.current) clearInterval(playTimerRef.current);
    }

    return () => {
      if (playTimerRef.current) clearInterval(playTimerRef.current);
    };
  }, [isPlaying, isReplayMode, totalSteps, playbackSpeed, onSeek]);

  const handleTogglePlay = () => {
    if (!isReplayMode) {
      onToggleReplayMode(true);
      if (replayIndex >= totalSteps - 1) {
        onSeek(0);
      }
      setIsPlaying(true);
    } else {
      if (replayIndex >= totalSteps - 1) {
        onSeek(0);
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleStepBack = () => {
    if (!isReplayMode) onToggleReplayMode(true);
    setIsPlaying(false);
    onSeek(Math.max(0, replayIndex - 1));
  };

  const handleStepForward = () => {
    if (!isReplayMode) onToggleReplayMode(true);
    setIsPlaying(false);
    onSeek(Math.min(totalSteps - 1, replayIndex + 1));
  };

  const handleGoToStart = () => {
    if (!isReplayMode) onToggleReplayMode(true);
    setIsPlaying(false);
    onSeek(0);
  };

  const handleGoToEnd = () => {
    setIsPlaying(false);
    onSeek(totalSteps - 1);
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!isReplayMode) onToggleReplayMode(true);
    setIsPlaying(false);
    onSeek(parseInt(e.target.value, 10));
  };

  if (totalSteps === 0) {
    return null;
  }

  return (
    <div className="w-full bg-panel border border-line rounded-panel shadow-panel px-4 py-2.5 flex flex-col gap-2.5 select-none z-20">
      {/* Üst Satır: Kontroller & Zaman Bilgisi */}
      <div className="flex items-center justify-between text-xs font-mono">
        {/* Sol: Mod Değiştirici (Canlı vs Replay) */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              if (isReplayMode) {
                setIsPlaying(false);
                onToggleReplayMode(false);
              } else {
                onToggleReplayMode(true);
                onSeek(0);
              }
            }}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full font-bold transition text-[11px] border ${
              !isReplayMode 
                ? 'bg-errd text-err border-err/50 animate-pulse' 
                : 'bg-panel2 text-ink3 border border-line hover:text-ink'
            }`}
          >
            <Radio className="w-3.5 h-3.5" />
            {!isReplayMode ? t('run.tl.live', undefined, 'CANLI YAYIN (LIVE)') : t('run.tl.goLive', undefined, 'CANLIYA GEÇ')}
          </button>

          <span className="text-line2">|</span>

          <div className="flex items-center gap-1.5 text-ac font-semibold text-[11px]">
            <History className="w-3.5 h-3.5 text-ac" />
            <span className="text-ink3">{t('run.tl.title', undefined, 'Zaman Tüneli:')}</span>
            <span className="text-ink font-bold">
              {isReplayMode ? t('run.tl.stepOf', { i: replayIndex + 1, n: totalSteps }, `Adım ${replayIndex + 1} / ${totalSteps}`) : t('run.tl.latest', { n: totalSteps }, `Son Durum (${totalSteps} Olay)`)}
            </span>
          </div>
        </div>

        {/* Orta: Video / Player Kontrol Düğmeleri */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleGoToStart}
            title={t('run.tl.toStart', undefined, 'En Başa Dön')}
            className="p-1.5 rounded-lg bg-panel2 border border-line text-ink hover:bg-sunk transition"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={handleStepBack}
            title={t('run.tl.back', undefined, '1 Adım Geri')}
            disabled={replayIndex <= 0 && isReplayMode}
            className="p-1.5 rounded-lg bg-panel2 border border-line text-ink hover:bg-sunk transition disabled:opacity-40"
          >
            <SkipBack className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={handleTogglePlay}
            className="px-4 py-1.5 rounded-lg font-bold flex items-center gap-1.5 text-xs transition shadow-sm bg-ac text-onac hover:opacity-90"
          >
            {isPlaying ? (
              <>
                <Pause className="w-4 h-4 fill-current" /> {t('run.tl.pause', undefined, 'Duraklat')}
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-current" /> {isReplayMode && replayIndex >= totalSteps - 1 ? t('run.tl.replay', undefined, 'Tekrar Oynat') : t('run.tl.play', undefined, 'Timeline Oynat')}
              </>
            )}
          </button>

          <button
            onClick={handleStepForward}
            title={t('run.tl.forward', undefined, '1 Adım İleri')}
            disabled={replayIndex >= totalSteps - 1 && isReplayMode}
            className="p-1.5 rounded-lg bg-panel2 border border-line text-ink hover:bg-sunk transition disabled:opacity-40"
          >
            <SkipForward className="w-3.5 h-3.5" />
          </button>

          {/* Hız Seçici */}
          <div className="flex items-center ml-2 bg-sunk border border-line rounded-lg p-0.5 text-[10px]">
            {[1, 2, 4].map(speed => (
              <button
                key={speed}
                onClick={() => setPlaybackSpeed(speed)}
                className={`px-2 py-0.5 rounded transition font-medium ${
                  playbackSpeed === speed 
                    ? 'bg-panel text-ink shadow-panel font-bold' 
                    : 'text-ink3 hover:text-ink'
                }`}
              >
                {speed}x
              </button>
            ))}
          </div>
        </div>

        {/* Sağ: O Anki Olayın Özet Bilgisi */}
        {currentEvent && (
          <div className="flex items-center gap-3 text-[11px] font-mono">
            <div className="flex items-center gap-1 text-ink3">
              <Clock className="w-3 h-3 text-ink3" />
              <span>{new Date(currentEvent.timestamp).toLocaleTimeString()}</span>
              <span className="text-ink3">(+{elapsedSeconds}s)</span>
            </div>

            <div className={`px-2 py-0.5 rounded border flex items-center gap-1 font-bold ${
              currentEvent.status === 'FAILED' 
                ? 'bg-errd text-err border-err/40' 
                : 'bg-okd text-ok border border-ok/40'
            }`}>
              <span>{currentEvent.from_agent}</span>
              <ArrowRight className="w-2.5 h-2.5" />
              <span>{currentEvent.to_agent}</span>
              <span className="opacity-80">({currentEvent.action})</span>
            </div>
          </div>
        )}
      </div>

      {/* Alt Satır: Özel Tasarım Slider (Ray + Dolu Kısım + Checkpointler + Topuz) */}
      <div className="relative flex items-center w-full h-5 group">
        {/* Ray (Track Background) */}
        <div className="absolute left-0 right-0 h-2 bg-sunk rounded-full border border-line overflow-hidden">
          {/* Dolu Kısım (Filled Progress) */}
          <div 
            className="h-full bg-ac transition-all duration-75"
            style={{ 
              width: `${((isReplayMode ? replayIndex : totalSteps - 1) / (totalSteps - 1 || 1)) * 100}%` 
            }}
          />
        </div>

        {/* Adım İşaretçileri (Timeline Checkpoints) */}
        <div className="absolute inset-0 pointer-events-none flex justify-between items-center px-1">
          {sortedEvents.map((evt, idx) => {
            const isBug = evt.status === 'FAILED';
            const isDeploy = evt.action === 'DEPLOY_CONFIRM';
            const isPassed = (isReplayMode ? replayIndex : totalSteps - 1) >= idx;

            return (
              <div 
                key={evt.id || idx}
                style={{ left: `${(idx / (totalSteps - 1 || 1)) * 100}%` }}
                className={`w-2.5 h-2.5 rounded-full border-2 border-panel transition-all transform -translate-x-1/2 z-10 ${
                  isBug 
                    ? 'bg-err scale-110 shadow-xs' 
                    : isDeploy 
                      ? 'bg-ok scale-110 shadow-xs' 
                      : isPassed 
                        ? 'bg-ac' 
                        : 'bg-ink3'
                }`}
                title={`${t('run.tl.stepWord', undefined, 'Adım')} ${idx + 1}: ${evt.from_agent} -> ${evt.to_agent} (${evt.action})`}
              />
            );
          })}
        </div>

        {/* Topuz (Thumb Indicator) */}
        <div
          style={{ 
            left: `${((isReplayMode ? replayIndex : totalSteps - 1) / (totalSteps - 1 || 1)) * 100}%` 
          }}
          className="absolute w-4 h-4 rounded-full bg-panel border-[3px] border-ac shadow-panel transform -translate-x-1/2 pointer-events-none z-20 transition-all duration-75 group-hover:scale-110"
        />

        {/* Görünmez Yerel Input (Erişilebilirlik ve Sürükleme için) */}
        <input
          type="range"
          min={0}
          max={totalSteps - 1}
          value={isReplayMode ? replayIndex : totalSteps - 1}
          onChange={handleSliderChange}
          className="w-full h-full opacity-0 cursor-pointer absolute inset-0 z-30"
        />
      </div>
    </div>
  );
};
