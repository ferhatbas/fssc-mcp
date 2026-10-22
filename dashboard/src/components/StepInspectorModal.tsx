import React, { useState } from 'react';
import { notify } from '../lib/dialog';
import { StepApprovalInfo, StepArtifact } from '../types/telemetry';
import { api } from '../config';
import { useI18n } from '../i18n';

import { 
  CheckCircle2, 
  Clock, 
  FileCode, 
  Copy, 
  Check, 
  ExternalLink, 
  ArrowRight, 
  Layers, 
  Sparkles, 
  Zap, 
  X, 
  Image as ImageIcon,
  ShieldCheck,
  Terminal,
  Activity,
  RotateCcw,
  XCircle,
  MinusCircle
} from 'lucide-react';

/** Ekran görüntüleri proje başına /api/projects/<id>/screenshots altında sunulur; eski ham dosya yolları eski kökle eşlenir. */
const screenshotUrl = (s: string): string => {
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith('/')) return api(s);
  const basename = s.split(/[\\/]/).pop() || s;
  return api(`/reports/screenshots/${basename}`);
};

interface StepInspectorModalProps {
  stepInfo: StepApprovalInfo | null;
  isOpen: boolean;
  onClose: () => void;
  /** REVISE: `comment` ile adım aynı sıra numarasıyla yeniden üretilir. Sunucu reddederse `{ status: 'INVALID', error }` döner. */
  onApprove?: (decision: 'PROCEED' | 'AUTO_ALL' | 'REVISE', comment?: string) => Promise<any>;
  isPendingApproval?: boolean;
  /** Engelleyici soru adımında: soruları cevaplama penceresini açar */
  onOpenQuestions?: () => void;
}

export const StepInspectorModal: React.FC<StepInspectorModalProps> = ({
  stepInfo,
  isOpen,
  onClose,
  onApprove,
  isPendingApproval = true,
  onOpenQuestions,
}) => {
  const { t } = useI18n();
  const [activeArtifactIdx, setActiveArtifactIdx] = useState<number>(0);
  const [copied, setCopied] = useState<boolean>(false);
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(null);
  const [isApproving, setIsApproving] = useState<boolean>(false);
  const [reviseOpen, setReviseOpen] = useState<boolean>(false);
  const [reviseText, setReviseText] = useState<string>('');
  const [reviseError, setReviseError] = useState<string>('');

  if (!isOpen || !stepInfo) return null;

  const artifacts = stepInfo.artifacts || [];
  const screenshots = stepInfo.screenshots || [];
  const activeArtifact: StepArtifact | undefined = artifacts[activeArtifactIdx];

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApproveStep = async (decision: 'PROCEED' | 'AUTO_ALL') => {
    if (!onApprove) return;
    try {
      setIsApproving(true);
      await onApprove(decision);
    } catch (err) {
      console.error(err);
      notify(t('run.si.approveErr', undefined, 'Onay iletilirken hata oluştu.'));
    } finally {
      setIsApproving(false);
    }
  };

  const handleRevise = async () => {
    if (!onApprove) return;
    const text = reviseText.trim();
    if (!text) {
      setReviseError(t('run.si.reviseEmpty', undefined, 'Ne düzeltilsin? Geri bildirim yazın.'));
      return;
    }
    setReviseError('');
    try {
      setIsApproving(true);
      const res = await onApprove('REVISE', text);
      if (res && res.status === 'INVALID') {
        setReviseError(res.error || t('run.si.reviseRejected', undefined, 'Revize isteği kabul edilmedi.'));
      } else if (res && res.status === 'NO_PENDING_STEP') {
        setReviseError(t('run.si.noPending', undefined, 'Bekleyen onay bulunamadı (adım zaten ilerlemiş olabilir).'));
      } else {
        setReviseText('');
        setReviseOpen(false);
      }
    } catch (err) {
      console.error(err);
      setReviseError(t('run.si.reviseErr', undefined, 'Revize isteği iletilirken hata oluştu.'));
    } finally {
      setIsApproving(false);
    }
  };

  const getAgentColor = (role: string) => {
    switch (role) {
      case 'PM': return 'text-ac bg-acd/60 border-ac/40';
      case 'ARCHITECT': return 'text-ac bg-acd/60 border-ac/40';
      case 'BACKEND_DEV': return 'text-ac bg-acd/60 border-ac/40';
      case 'FRONTEND_DEV': return 'text-info bg-infod/60 border-info/40';
      case 'DESIGNER': return 'text-ac bg-acd/60 border-ac/40';
      case 'QA': return 'text-warn bg-warnd/60 border-warn/40';
      case 'E2E_TESTER': return 'text-err bg-errd/60 border-err/40';
      case 'DEVOPS': return 'text-ok bg-okd/60 border-ok/40';
      default: return 'text-ink2 bg-panel2 border-line2';
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col bg-panel border border-line2/80 rounded-2xl shadow-2xl shadow-panel overflow-hidden">
        
        {/* MODAL HEADER */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-line bg-sunk/70">
          <div className="flex items-center space-x-3">
            <div className={`p-2 rounded-xl border ${isPendingApproval ? 'bg-warnd border-warn/40 text-warn animate-pulse' : 'bg-okd border-ok/40 text-ok'}`}>
              {isPendingApproval ? <Clock className="w-6 h-6" /> : <ShieldCheck className="w-6 h-6" />}
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xs font-mono font-semibold px-2 py-0.5 rounded bg-acd/80 text-ac border border-ac/40">
                  {stepInfo.issue_id || `JIRA-${stepInfo.order}`}
                </span>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-panel2 text-ink3">
                  {t('run.si.stepWord', undefined, 'Adım')} #{stepInfo.order}{stepInfo.step_index && stepInfo.total_steps ? ` · ${stepInfo.step_index} / ${stepInfo.total_steps}` : ''}
                </span>
                {stepInfo.kind === 'task' && (
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-acd text-ac border border-ac/40">{t('run.si.backlogTask', undefined, 'backlog görevi')}</span>
                )}
                {stepInfo.kind === 'fix' && (
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-warnd text-warn border border-warn/40">{t('run.si.fixRound', { n: stepInfo.fix_round }, `düzeltme turu ${stepInfo.fix_round}`)}</span>
                )}
                {stepInfo.commit && (
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-sunk text-ink2 border border-line" title={t('run.si.scmCommit', undefined, 'SCM commit')}>{t('run.si.commit', undefined, 'commit')} {stepInfo.commit}</span>
                )}
                {isPendingApproval ? (
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-warnd text-warn border border-warn/40 flex items-center space-x-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-warn animate-ping mr-1"></span>
                    {t('run.si.waitingApproval', undefined, 'Devam Onayı Bekleniyor')}
                  </span>
                ) : (
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-okd text-ok border border-ok/40">
                    {t('run.si.doneVerified', undefined, 'Tamamlandı & Doğrulandı')}
                  </span>
                )}
              </div>
              <h2 className="text-base sm:text-lg font-bold text-ink mt-1">
                {stepInfo.title}
              </h2>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="text-ink3 hover:text-ink p-2 rounded-lg hover:bg-panel2 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* SUB-HEADER: AGENT HANDSHAKE PROGRESSION */}
        <div className="bg-sunk/40 border-b border-line/80 px-6 py-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          {/* Active Producer Agent */}
          <div className="flex items-center space-x-2.5">
            <div className={`px-2.5 py-1 rounded-lg border font-mono font-semibold text-xs ${getAgentColor(stepInfo.agent_id)}`}>
              {stepInfo.agent_name}
            </div>
            <span className="text-ink3">{t('run.si.executedBy', undefined, 'tarafından icra edildi:')}</span>
            <span className="font-mono text-ink bg-panel2/90 px-2 py-0.5 rounded border border-line2">
              {stepInfo.action}
            </span>
          </div>

          {/* Handshake Indicator */}
          {stepInfo.next_agent_name && (
            <div className="flex items-center space-x-2 text-ink3">
              <span className="text-ink3 font-mono">{t('run.si.handoffTo', undefined, 'Devredilecek:')}</span>
              <ArrowRight className="w-3.5 h-3.5 text-ac animate-pulse" />
              <div className={`px-2.5 py-1 rounded-lg border font-mono font-semibold text-xs ${getAgentColor(stepInfo.next_agent_id || '')}`}>
                {stepInfo.next_agent_name}
              </div>
            </div>
          )}

          {/* Quick Metrics */}
          <div className="flex items-center space-x-4 font-mono text-[11px] text-ink3">
            <span className="flex items-center space-x-1">
              <Zap className="w-3.5 h-3.5 text-warn" />
              <span>{stepInfo.tokens_used} Tokens</span>
            </span>
            <span className="flex items-center space-x-1">
              <Layers className="w-3.5 h-3.5 text-ac" />
              <span>{t('run.si.fileOutputs', { n: artifacts.length }, `${artifacts.length} Dosya Çıktısı`)}</span>
            </span>
            {screenshots.length > 0 && (
              <span className="flex items-center space-x-1">
                <ImageIcon className="w-3.5 h-3.5 text-err" />
                <span>{t('run.si.screenEvidence', { n: screenshots.length }, `${screenshots.length} Ekran Kanıtı`)}</span>
              </span>
            )}
          </div>
        </div>

        {/* MODAL BODY */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          
          {/* 1. AGENT SUMMARY & INTENT */}
          <div className="p-4 rounded-xl bg-panel2/40 border border-line2/60 space-y-2">
            <div className="flex items-center space-x-2 text-xs font-semibold text-ac uppercase tracking-wider">
              <Sparkles className="w-4 h-4" />
              <span>{t('run.si.whatDid', undefined, 'Ajan Ne Yaptı ve Ne Üretti?')}</span>
            </div>
            <p className="text-sm text-ink leading-relaxed font-sans">
              {stepInfo.summary}
            </p>
          </div>

          {/* Engelleyici sorular: adımın beklediği soruların metni ve seçenekleri */}
          {(() => {
            const qs = ((stepInfo as unknown as { questions?: Array<{ id: string; text?: string; question?: string; category?: string; options?: Array<{ key: string; label: string } | string>; recommended?: string | null; rationale?: string; why?: string }> }).questions) || [];
            if (!qs.length || !qs[0].text) return null;
            return (
              <div className="p-4 rounded-xl bg-warnd/40 border border-warn/50 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold text-warn uppercase tracking-wider">{t('run.si.blockingQs', { n: qs.length }, `Cevap bekleyen engelleyici sorular (${qs.length})`)}</div>
                  {onOpenQuestions && (
                    <button onClick={onOpenQuestions} className="px-3 py-1.5 text-xs font-bold rounded-lg bg-ink text-bg hover:opacity-90 transition">{t('run.si.answerQs', undefined, 'Soruları cevapla')}</button>
                  )}
                </div>
                {qs.map(q => (
                  <div key={q.id} className="rounded-lg border border-line bg-panel p-3 space-y-1.5">
                    <div className="flex items-start gap-2 text-sm text-ink"><span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-acd text-ac border border-ac/40 shrink-0">{q.id}</span><span>{q.text || q.question}</span></div>
                    <ul className="text-xs text-ink2 space-y-0.5 pl-1">
                      {(q.options || []).map((o, i) => {
                        const key = typeof o === 'string' ? String.fromCharCode(65 + i) : o.key;
                        const label = typeof o === 'string' ? o : o.label;
                        return <li key={key}><span className="font-mono font-bold">{key}</span> · {label}{q.recommended === key ? <span className="ml-1.5 text-ok font-semibold">{t('run.si.recommended', undefined, '(önerilen)')}</span> : null}</li>;
                      })}
                    </ul>
                    {(q.rationale || q.why) && <div className="text-[11px] text-ink3 italic">{q.rationale || q.why}</div>}
                  </div>
                ))}
              </div>
            );
          })()}

          {/* 2. ARTIFACTS / CODE / SCREENSHOTS VIEWER */}
          <div className="space-y-3">
            <div className="flex items-center justify-between border-b border-line pb-2">
              <div className="flex items-center space-x-2 text-xs font-semibold text-ink2 uppercase tracking-wider">
                <FileCode className="w-4 h-4 text-ok" />
                <span>{t('run.si.producedFiles', { n: artifacts.length }, `Üretilen Kod ve Çıktı Dosyaları (${artifacts.length})`)}</span>
              </div>

              {activeArtifact && (
                <button
                  onClick={() => handleCopy(activeArtifact.content)}
                  className="flex items-center space-x-1.5 text-xs text-ink3 hover:text-ink bg-panel2 hover:bg-sunk px-2.5 py-1 rounded transition-colors"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-ok" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? t('run.si.copied', undefined, 'Kopyalandı') : t('run.si.copyCode', undefined, 'Kodu Kopyala')}</span>
                </button>
              )}
            </div>

            {/* Artifact Tabs */}
            <div className="flex flex-wrap gap-2">
              {artifacts.map((art, idx) => (
                <button
                  key={idx}
                  onClick={() => setActiveArtifactIdx(idx)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all flex items-center space-x-2 border ${
                    activeArtifactIdx === idx
                      ? 'bg-ac text-onac border-ac shadow-md shadow-panel font-semibold'
                      : 'bg-panel2/80 hover:bg-sunk/80 text-ink2 border-line2'
                  }`}
                >
                  <FileCode className="w-3.5 h-3.5" />
                  <span>{art.name}</span>
                  <span className="text-[10px] opacity-70 px-1 rounded bg-black/30">
                    {art.type}
                  </span>
                </button>
              ))}

              {/* Ekran Görüntüleri Sekmesi (Varsa) */}
              {screenshots.length > 0 && (
                <button
                  onClick={() => setActiveArtifactIdx(artifacts.length)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all flex items-center space-x-2 border ${
                    activeArtifactIdx === artifacts.length
                      ? 'bg-err text-onac border-err shadow-md shadow-panel font-semibold'
                      : 'bg-panel2/80 hover:bg-sunk/80 text-err border-line2'
                  }`}
                >
                  <ImageIcon className="w-3.5 h-3.5" />
                  <span>{t('run.si.pwEvidence', { n: screenshots.length }, `Playwright Ekran Kanıtları (${screenshots.length})`)}</span>
                </button>
              )}
            </div>

            {/* Artifact Content Display */}
            {activeArtifactIdx < artifacts.length && activeArtifact ? (
              <div className="relative rounded-xl border border-line bg-sunk overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 border-b border-line/80 bg-panel/60 text-xs font-mono text-ink3">
                  <span className="truncate">{activeArtifact.path}</span>
                  <span className="text-ink3">{t('run.si.chars', { n: (activeArtifact.content || '').length }, `${(activeArtifact.content || '').length} karakter`)}</span>
                </div>
                {/\.html?$/i.test(activeArtifact.path) && activeArtifact.content && (
                  <div className="border-b border-line/80">
                    <div className="px-4 py-1.5 text-[11px] text-ink3 bg-panel/40">{t('run.si.previewNote', undefined, "Önizleme (tasarım mockup'ı; betik çalıştırılmaz)")}</div>
                    <iframe title={t('run.si.previewTitle', { path: activeArtifact.path }, `Önizleme: ${activeArtifact.path}`)} sandbox="" srcDoc={activeArtifact.content} className="w-full h-[420px] bg-white border-0" />
                  </div>
                )}
                <pre className="p-4 text-xs font-mono text-ink overflow-x-auto max-h-[380px] leading-relaxed select-text">
                  <code>{activeArtifact.content}</code>
                </pre>
              </div>
            ) : screenshots.length > 0 ? (
              /* Screenshots Gallery */
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {screenshots.map((s, sIdx) => {
                    const imgUrl = screenshotUrl(s);
                    return (
                      <div 
                        key={sIdx}
                        onClick={() => setSelectedScreenshot(imgUrl)}
                        className="group relative rounded-xl border border-line bg-sunk overflow-hidden cursor-pointer hover:border-ac transition-all shadow-md"
                      >
                        <img 
                          src={imgUrl} 
                          alt={t('run.si.pwProofAlt', { n: sIdx + 1 }, `Playwright kanıt #${sIdx + 1}`)} 
                          className="w-full h-36 object-cover object-top group-hover:scale-105 transition-transform duration-300"
                          onError={(e) => {
                            (e.target as HTMLElement).style.display = 'none';
                          }}
                        />
                        <div className="p-2 text-[11px] font-mono text-ink3 flex items-center justify-between bg-panel/90 border-t border-line">
                          <span className="truncate">{s.split(/[/\\\\]/).pop()}</span>
                          <ExternalLink className="w-3 h-3 text-ink3 group-hover:text-ac" />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>

          {/* 3a. SUNUCU DOĞRULAMASI (gerçek test/build sonuçları) */}
          {stepInfo.verification && (
            <div className={`p-4 rounded-xl border text-xs space-y-2.5 ${stepInfo.verification.status === 'FAILED' ? 'bg-errd/40 border-err/40' : stepInfo.verification.status === 'PASSED' ? 'bg-okd/40 border-ok/40' : 'bg-sunk/60 border-line'}`}>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="font-semibold text-ink uppercase tracking-wider font-mono flex items-center gap-1.5">
                  <Terminal className="w-3.5 h-3.5" />
                  {t('run.si.serverVerification', undefined, 'Sunucu doğrulaması:')} {stepInfo.verification.status}
                </span>
                <span className="text-ink2">{stepInfo.verification.summary}</span>
              </div>
              {stepInfo.fix_requested && (
                <div className="text-warn font-semibold">{t('run.si.verifyFailedFix', undefined, '⚠ Doğrulama başarısız: aynı görev için bir düzeltme turu koşuya eklendi; geliştirici hatayı çözecek.')}</div>
              )}
              {stepInfo.verification.tests && (
                <div className="text-[11px] font-mono text-ink2">
                  {t('run.si.testsJunit', { passed: stepInfo.verification.tests.passed, failed: stepInfo.verification.tests.failed + stepInfo.verification.tests.errors, skipped: stepInfo.verification.tests.skipped }, `Testler (junit): ${stepInfo.verification.tests.passed} geçti · ${stepInfo.verification.tests.failed + stepInfo.verification.tests.errors} kaldı · ${stepInfo.verification.tests.skipped} atlandı`)}
                  {stepInfo.verification.isolation ? ` · ${t('run.si.isolation', undefined, 'yalıtım:')} ${stepInfo.verification.isolation}` : ''}
                </div>
              )}
              {stepInfo.verification.failed_tests && stepInfo.verification.failed_tests.length > 0 && (
                <ul className="space-y-0.5 text-[11px] font-mono text-err">
                  {stepInfo.verification.failed_tests.slice(0, 15).map((ft, i) => (
                    <li key={i} title={ft.message || ''}>✗ {ft.id}{ft.message ? ` — ${ft.message.slice(0, 120)}` : ''}</li>
                  ))}
                </ul>
              )}
              <div className="space-y-1.5">
                {stepInfo.verification.results.map((r, i) => (
                  <details key={i} className="rounded-lg border border-line bg-panel/60 px-3 py-1.5">
                    <summary className="cursor-pointer flex items-center gap-2 font-mono text-[11px]">
                      <span className={`px-1.5 py-0.5 rounded border text-[10px] ${r.status === 'PASSED' ? 'bg-okd text-ok border-ok/40' : r.status === 'FAILED' ? 'bg-errd text-err border-err/40' : 'bg-sunk text-ink3 border-line'}`}>{r.status}</span>
                      <span className="text-ink font-semibold">{r.name}</span>
                      <span className="text-ink3 truncate">{r.cmd}</span>
                      {typeof r.duration_ms === 'number' && <span className="text-ink3 ml-auto shrink-0">{(r.duration_ms / 1000).toFixed(1)} {t('run.si.secShort', undefined, 'sn')}</span>}
                    </summary>
                    {r.output ? <pre className="mt-1.5 text-[10.5px] font-mono text-ink2 whitespace-pre-wrap max-h-48 overflow-auto">{r.output}</pre> : <div className="text-[10.5px] text-ink3 mt-1">{t('run.si.noOutput', undefined, 'çıktı yok')}</div>}
                  </details>
                ))}
              </div>
            </div>
          )}

          {/* 3. DOĞRULAMA DURUMU — adım kaydından türetilir; sabit "her zaman yeşil" liste yok (G0) */}
          {(() => {
            const v = stepInfo.verification;
            const fileCount = artifacts.length;
            const items: { ok: boolean | null; text: string }[] = [
              {
                ok: fileCount > 0 ? true : null,
                text: fileCount > 0 ? t('run.si.filesDelivered', { n: fileCount }, `${fileCount} dosya teslim edildi ve proje klasörüne yazıldı`) : t('run.si.noFiles', undefined, 'Dosya teslimi yok (adım dosya üretmedi ya da kayıt yok)'),
              },
              {
                ok: v ? (v.status === 'PASSED' ? true : v.status === 'FAILED' ? false : null) : null,
                text: v ? `${t('run.si.serverVerification', undefined, 'Sunucu doğrulaması:')} ${v.status}${v.summary ? ` · ${v.summary}` : ''}` : t('run.si.verifyNotRun', undefined, 'Sunucu doğrulaması koşmadı (komut tanımsız ya da auto_verify kapalı)'),
              },
              {
                ok: stepInfo.commit ? true : null,
                text: stepInfo.commit ? `${t('run.si.scmCommitColon', undefined, 'SCM commit:')} ${stepInfo.commit}` : t('run.si.noCommit', undefined, 'Commit yok'),
              },
              {
                ok: isPendingApproval ? null : (stepInfo.action === 'NO_RECORD' ? null : true),
                text: isPendingApproval ? t('run.si.managerApproval', undefined, 'Yönetici onayı bekliyor') : (stepInfo.action === 'NO_RECORD' ? t('run.si.noStepRecord', undefined, 'Bu madde için adım kaydı yok') : t('run.si.stepDone', undefined, 'Adım tamamlandı')),
              },
            ];
            return (
              <div className="p-4 rounded-xl bg-sunk/60 border border-line text-xs space-y-2.5">
                <span className="font-semibold text-ink3 uppercase tracking-wider font-mono">
                  {t('run.si.verifyStatus', undefined, 'Doğrulama durumu (sunucu verisi):')}
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-ink2">
                  {items.map((it, i) => (
                    <div key={i} className="flex items-center space-x-2">
                      {it.ok === true
                        ? <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
                        : it.ok === false
                          ? <XCircle className="w-4 h-4 text-err shrink-0" />
                          : <MinusCircle className="w-4 h-4 text-ink3 shrink-0" />}
                      <span>{it.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>

        {/* REVİZE İSTE: geri bildirimle adımı aynı sıra numarasıyla yeniden ürettirir */}
        {isPendingApproval && onApprove && reviseOpen && (
          <div className="px-6 py-3 border-t border-line bg-warnd/40 space-y-2">
            <label className="block text-[11px] font-semibold text-warn" htmlFor="revise-comment">
              {t('run.si.reviseLabel', undefined, 'Revize isteği: ne düzeltilsin? (ajan bu geri bildirimle aynı adımı yeniden üretir)')}
            </label>
            <textarea
              id="revise-comment"
              value={reviseText}
              onChange={(e) => { setReviseText(e.target.value); if (reviseError) setReviseError(''); }}
              rows={3}
              maxLength={2000}
              placeholder={t('run.si.revisePh', undefined, "Örn. Docker kullanılsın; Dockerfile ve docker-compose.yml ekle. / Backlog'u 15 göreve indir.")}
              className="w-full text-xs rounded-lg border border-line2 bg-sunk text-ink p-2 focus:outline-none focus:border-warn"
            />
            {reviseError && <div role="alert" className="text-[11px] text-err">{reviseError}</div>}
            <div className="flex items-center justify-end gap-2">
              <button
                disabled={isApproving}
                onClick={() => { setReviseOpen(false); setReviseError(''); }}
                className="px-3 py-1.5 rounded-lg text-xs text-ink2 hover:text-ink border border-line2"
              >
                {t('run.si.giveUp', undefined, 'Vazgeç')}
              </button>
              <button
                disabled={isApproving || !reviseText.trim()}
                onClick={handleRevise}
                className="px-4 py-1.5 rounded-lg bg-warn text-onac font-bold text-xs disabled:opacity-50 flex items-center gap-1.5"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>{t('run.si.sendRevise', undefined, 'Revize Gönder')}</span>
              </button>
            </div>
          </div>
        )}

        {/* MODAL FOOTER & APPROVAL BUTTONS */}
        <div className="px-6 py-4 border-t border-line bg-sunk/90 flex flex-wrap items-center justify-between gap-4">
          <div className="text-xs text-ink3 max-w-md">
            {isPendingApproval ? (
              <span>
                {t('run.si.approveHelp', undefined, 'Bu adımı inceledikten sonra devam onayı verebilir veya kalan tüm adımların beklemeden otomatik bitmesini seçebilirsiniz.')}
              </span>
            ) : (
              <span>{t('run.si.reviewMode', undefined, 'Geçmiş adım çıktısı inceleme modundasınız. Değişiklikler diskte hazırdır.')}</span>
            )}
          </div>

          <div className="flex items-center space-x-3">
            {isPendingApproval && onApprove ? (
              <>
                <button
                  disabled={isApproving}
                  onClick={() => setReviseOpen((o) => !o)}
                  className="px-4 py-2.5 rounded-xl border border-line2 hover:bg-panel2 text-ink2 font-semibold text-xs transition-all flex items-center space-x-1.5"
                  title={t('run.si.reviseTitle', undefined, 'Adımı geri bildirimle yeniden ürettir (aynı sıra numarası)')}
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>{t('run.si.requestRevise', undefined, 'Revize İste')}</span>
                </button>

                <button
                  disabled={isApproving}
                  onClick={() => handleApproveStep('AUTO_ALL')}
                  className="px-4 py-2.5 rounded-xl border border-warn/70 hover:bg-warnd text-warn font-semibold text-xs transition-all flex items-center space-x-1.5 shadow-sm"
                  title={t('run.si.autoAllTitle', undefined, 'Kalan tüm adımları duraklatmadan otomatik tamamlar')}
                >
                  <Zap className="w-3.5 h-3.5 text-warn" />
                  <span>{t('run.si.autoAll', undefined, '⚡ Kalanları Otomatik Tamamla')}</span>
                </button>

                <button
                  disabled={isApproving}
                  onClick={() => handleApproveStep('PROCEED')}
                  className="px-5 py-2.5 rounded-xl bg-ok hover:bg-ok text-onac font-bold text-xs transition-all flex items-center space-x-2 shadow-lg shadow-panel hover:scale-[1.02] active:scale-[0.98]"
                >
                  <CheckCircle2 className="w-4 h-4 text-ink" />
                  <span>
                    {stepInfo.is_last_step 
                      ? t('run.si.approveLast', undefined, '✓ Son Adımı Onayla ve Tamamla') 
                      : t('run.si.approveNext', { agent: stepInfo.next_agent_name || t('run.si.nextAgent', undefined, 'Sıradaki Ajan') }, `✓ Adımı Onayla & Sonrakine Geç (${stepInfo.next_agent_name || 'Sıradaki Ajan'})`)}
                  </span>
                </button>
              </>
            ) : (
              <button
                onClick={onClose}
                className="px-5 py-2 rounded-xl bg-panel2 hover:bg-sunk text-ink font-semibold text-xs transition-colors"
              >
                {t('common.close', undefined, 'Kapat')}
              </button>
            )}
          </div>
        </div>

        {/* FULL RESOLUTION SCREENSHOT LIGHTBOX */}
        {selectedScreenshot && (
          <div 
            className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/90 backdrop-blur-md"
            onClick={() => setSelectedScreenshot(null)}
          >
            <div className="relative max-w-4xl max-h-[90vh] bg-panel border border-line2 rounded-2xl overflow-hidden p-2 shadow-2xl">
              <img 
                src={selectedScreenshot} 
                alt={t('run.si.fullShotAlt', undefined, 'Playwright ekran görüntüsü tam boy')} 
                className="max-h-[82vh] w-auto rounded-xl object-contain"
              />
              <div className="text-center text-xs font-mono text-ink3 py-2">
                {t('run.si.clickToClose', undefined, 'Kapatmak için herhangi bir yere tıklayın')}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};
