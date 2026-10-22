import React, { useState } from 'react';
import { notify, confirmDialog } from '../lib/dialog';
import { UploadedSpec, PipelineRun } from '../types/telemetry';
import { 
  X, 
  UploadCloud, 
  FileText, 
  CheckCircle2, 
  Clock, 
  Download, 
  FolderPlus, 
  User, 
  Sparkles,
  Paperclip,
  Trash2,
  Edit3,
  Save,
  RotateCcw
} from 'lucide-react';
import { api } from '../config';
import { useI18n } from '../i18n';

interface SpecUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  specs: UploadedSpec[];
  runs?: PipelineRun[];
  onUpload: (formData: FormData) => Promise<void>;
  onAnalyzeSpec?: (specId?: string) => Promise<void>;
  onDeleteSpec?: (specId: string) => Promise<void>;
  onDeleteSpecFile?: (specId: string, filename: string) => Promise<void>;
  onUpdateSpec?: (specId: string, updates: { title?: string; client_name?: string; meeting_notes?: string }) => Promise<void>;
  projectName?: string;
}

export const SpecUploadModal: React.FC<SpecUploadModalProps> = ({
  isOpen,
  onClose,
  specs,
  runs = [],
  onUpload,
  onAnalyzeSpec,
  onDeleteSpec,
  onDeleteSpecFile,
  onUpdateSpec,
  projectName
}) => {
  const { t } = useI18n();
  const pName = projectName ?? t('run.sp.activeProject', undefined, 'Aktif Proje');
  const [title, setTitle] = useState('');
  const [clientName, setClientName] = useState('');
  const [meetingNotes, setMeetingNotes] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [autoGenerateTasks, setAutoGenerateTasks] = useState<boolean>(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analyzingSpecId, setAnalyzingSpecId] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState('');
  const [inlineStatus, setInlineStatus] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  // Düzenleme durumu
  const [editingSpecId, setEditingSpecId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editClient, setEditClient] = useState('');
  const [editNotes, setEditNotes] = useState('');

  if (!isOpen) return null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!meetingNotes.trim() && selectedFiles.length === 0) {
      notify(t('run.sp.needInput', undefined, 'Lütfen müşteri görüşme notu girin veya dosya seçin.'));
      return;
    }

    setIsSubmitting(true);
    setInlineStatus(null);
    try {
      const formData = new FormData();
      formData.append('title', title || 'Müşteri Keşif ve Gereksinim Toplantısı');
      formData.append('client_name', clientName || 'Kurumsal Müşteri');
      formData.append('meeting_notes', meetingNotes);
      formData.append('auto_generate_tasks', autoGenerateTasks ? 'true' : 'false');
      selectedFiles.forEach(file => {
        formData.append('files', file);
      });

      await onUpload(formData);
      setSuccessMessage(
        autoGenerateTasks 
          ? t('run.sp.okAnalyzed', undefined, '✓ Müşteri şartnamesi yüklendi, analiz edildi ve Jira tahtasına özel görevler eklendi!')
          : t('run.sp.okSaved', undefined, '✓ Müşteri şartnamesi ve dosyalar başarıyla kasaya kaydedildi.')
      );
      setTitle('');
      setClientName('');
      setMeetingNotes('');
      setSelectedFiles([]);
      setInlineStatus({ kind: 'ok', text: t('run.sp.inlineSaved', undefined, '✓ Kaydedildi — aşağıdaki listede "Kayıtlı Müşteri Şartnameleri"nde görünür.') });
      setTimeout(() => setSuccessMessage(''), 8000);
      setTimeout(() => setInlineStatus(null), 8000);
    } catch (err) {
      console.error(err);
      setInlineStatus({ kind: 'err', text: t('run.sp.uploadErr', undefined, 'Yükleme sırasında hata oluştu; tekrar deneyin.') });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="bg-panel border border-line2 rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
        {/* Başlık */}
        <div className="px-6 py-4 bg-sunk border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-acd border border-ac/40 flex items-center justify-center">
              <FolderPlus className="w-5 h-5 text-ac" />
            </div>
            <div>
              <h3 className="text-base font-bold text-ink tracking-wide">
                {t('run.sp.title', undefined, 'Müşteri Görüşmeleri & Şartname Kasası (Vault)')}
              </h3>
              <p className="text-xs text-ink3">
                {t('run.sp.project', undefined, 'Proje:')} <span className="text-ac font-mono">{pName}</span> — {t('run.sp.filesKept', undefined, 'Dosyalar kalıcı olarak saklanır ve ajanlara iletilir')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink3 hover:text-ink p-1 rounded-lg hover:bg-panel2 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* İçerik */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {successMessage && (
            <div className="p-3 bg-okd/80 border border-ok/60 rounded-lg text-ok text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4" />
              {successMessage}
            </div>
          )}

          {/* Yeni Şartname Formu */}
          <form onSubmit={handleSubmit} className="space-y-4 bg-sunk/60 p-4 rounded-xl border border-line">
            <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-ac" />
              {t('run.sp.addNew', undefined, 'Yeni Görüşme / Şartname Dosyası Ekle')}
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.sp.clientLabel', undefined, 'Müşteri / Kurum Adı')}
                </label>
                <input
                  type="text"
                  placeholder={t('run.sp.clientPh', undefined, 'Örn: FinTech Corp / Dr. Smith')}
                  value={clientName}
                  onChange={e => setClientName(e.target.value)}
                  className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.sp.titleLabel', undefined, 'Görüşme Başlığı')}
                </label>
                <input
                  type="text"
                  placeholder={t('run.sp.titlePh', undefined, 'Örn: V2 Kimlik Doğrulama & Raporlama Keşif Toplantısı')}
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-ink3 mb-1">
                {t('run.sp.notesLabel', undefined, 'Görüşme Notları & İş Kuralları (Markdown formatı desteklenir)')}
              </label>
              <textarea
                rows={4}
                placeholder={t('run.sp.notesPh', undefined, 'Toplantıda konuşulan hedefler, istenen fonksiyonlar, UI beklentileri ve edge-case gereksinimleri buraya yazın...')}
                value={meetingNotes}
                onChange={e => setMeetingNotes(e.target.value)}
                className="w-full bg-panel border border-line2 rounded-lg p-3 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none font-sans leading-relaxed"
              />
            </div>

            {/* Dosya Yükleme Alanı */}
            <div>
              <label className="block text-[11px] font-medium text-ink3 mb-1">
                {t('run.sp.filesLabel', undefined, 'Şartname / Tasarım / Mockup Dosyaları (Word .docx, MD, TXT, JSON okunur; PNG/JPG yalnızca kasada saklanır, içeriği okunmaz)')}
              </label>
              <div className="border border-dashed border-line2 hover:border-ac/60 rounded-xl p-4 text-center bg-panel/40 transition cursor-pointer">
                <input
                  type="file"
                  multiple
                  onChange={handleFileChange}
                  className="hidden"
                  id="spec-file-input"
                />
                <label htmlFor="spec-file-input" className="cursor-pointer flex flex-col items-center">
                  <UploadCloud className="w-8 h-8 text-ac mb-2" />
                  <span className="text-xs font-semibold text-ink">
                    {t('run.sp.dropHint', undefined, 'Dosya seçmek için tıklayın veya sürükleyip bırakın')}
                  </span>
                  <span className="text-[10px] text-ink3 mt-0.5">
                    {t('run.sp.allFormats', undefined, 'Tüm formatlar kalıcı olarak proje klasöründe saklanır')}
                  </span>
                </label>
              </div>

              {selectedFiles.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedFiles.map((file, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-acd/70 border border-ac/40 text-ac text-[11px] rounded-lg"
                    >
                      <Paperclip className="w-3 h-3" />
                      {file.name} ({(file.size / 1024).toFixed(1)} KB)
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Otomatik Analiz & Jira Görevi Üretme Seçeneği */}
            <label className="flex items-center gap-2 cursor-pointer bg-panel/90 border border-line p-2.5 rounded-xl hover:border-ac/50 transition">
              <input 
                type="checkbox"
                checked={autoGenerateTasks}
                onChange={e => setAutoGenerateTasks(e.target.checked)}
                className="rounded bg-sunk border-line2 text-ac focus:ring-ac w-4 h-4 cursor-pointer"
              />
              <div>
                <div className="text-xs font-semibold text-ac flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-ac" />
                  <span>{t('run.sp.autoLabel', undefined, 'Yüklenen Belgeleri Otomatik Analiz Et ve Jira Görevlerini Üret')}</span>
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-acd/60 text-ac border border-ac">{t('run.sp.recommended', undefined, 'Önerilen')}</span>
                </div>
                <div className="text-[10px] text-ink3">
                  {t('run.sp.autoHelp', undefined, 'PM ve Architect ajanları yüklenen dosyaları ve notları tarayarak tahtadaki görevleri bu talebe göre özelleştirir.')}
                </div>
              </div>
            </label>

            <div className="flex items-center justify-end gap-3 pt-2">
              {isSubmitting && (
                <span className="text-[11px] text-ink2 flex items-center gap-1.5" role="status">
                  <span className="inline-block w-3 h-3 rounded-full border-2 border-ac border-t-transparent animate-spin" />
                  {t('run.sp.processing', undefined, 'İşleniyor… (dosyalar kaydediliyor, görevler çıkarılıyor)')}
                </span>
              )}
              {!isSubmitting && inlineStatus && (
                <span className={`text-[11px] font-semibold flex items-center gap-1.5 ${inlineStatus.kind === 'ok' ? 'text-ok' : 'text-err'}`} role="status">
                  {inlineStatus.kind === 'ok' && <CheckCircle2 className="w-4 h-4" />}
                  {inlineStatus.text}
                </span>
              )}
              <button
                type="submit"
                disabled={isSubmitting}
                className="px-5 py-2.5 bg-ac hover:opacity-90 disabled:opacity-60 text-onac text-xs font-semibold rounded-lg shadow-lg border border-ac/30 flex items-center gap-2"
              >
                <UploadCloud className="w-4 h-4" />
                {isSubmitting 
                  ? t('run.sp.submitBusy', undefined, 'Analiz Edilip Kaydediliyor...') 
                  : autoGenerateTasks 
                    ? t('run.sp.submitAuto', undefined, '🤖 Kaydet, Analiz Et & Jira Görevlerini Üret') 
                    : t('run.sp.submitSave', undefined, 'Şartnameyi ve Dosyaları Kasaya Kaydet')}
              </button>
            </div>
          </form>

          {/* Mevcut Yüklenmiş Şartnameler Listesi */}
          <div>
            <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider mb-3 flex items-center gap-2">
              <FileText className="w-3.5 h-3.5 text-ac" />
              {t('run.sp.saved', undefined, 'Kayıtlı Müşteri Şartnameleri')} ({specs.length})
            </h4>

            {specs.length === 0 ? (
              <div className="p-6 text-center border border-dashed border-line rounded-xl text-ink3 text-xs">
                {t('run.sp.none', undefined, 'Henüz bu projeye eklenmiş müşteri şartnamesi veya görüşme notu bulunmuyor.')}
              </div>
            ) : (
              <div className="space-y-3">
                {[...specs].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')).map(spec => {
                  const isEditing = editingSpecId === spec.id;
                  const specRuns = runs
                    .filter(r => (r.intake_spec_ids || []).includes(spec.id))
                    .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
                  return (
                    <div
                      key={spec.id}
                      className="p-4 bg-sunk/80 rounded-xl border border-line hover:border-line2 transition space-y-2.5"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] bg-acd text-ac border border-ac/40 px-2 py-0.5 rounded font-mono">
                            {spec.id}
                          </span>
                          {!isEditing ? (
                            <h5 className="text-xs font-bold text-ink">{spec.title}</h5>
                          ) : (
                            <input
                              type="text"
                              value={editTitle}
                              onChange={e => setEditTitle(e.target.value)}
                              className="bg-panel border border-ac rounded px-2 py-0.5 text-xs text-ink"
                            />
                          )}
                        </div>
                        
                        <div className="flex items-center gap-2">
                          {isEditing ? (
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={async () => {
                                  if (onUpdateSpec) {
                                    await onUpdateSpec(spec.id, {
                                      title: editTitle,
                                      client_name: editClient,
                                      meeting_notes: editNotes
                                    });
                                    setEditingSpecId(null);
                                    setSuccessMessage(t('run.sp.updated', undefined, '✓ Şartname güncellendi.'));
                                    setTimeout(() => setSuccessMessage(''), 3000);
                                  }
                                }}
                                className="px-2 py-1 bg-ok hover:bg-ok text-onac rounded text-[11px] font-medium flex items-center gap-1"
                              >
                                <Save className="w-3 h-3" />
                                <span>{t('common.save', undefined, 'Kaydet')}</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingSpecId(null)}
                                className="px-2 py-1 bg-panel2 hover:bg-sunk text-ink2 rounded text-[11px]"
                              >
                                {t('run.sp.giveUp', undefined, 'Vazgeç')}
                              </button>
                            </div>
                          ) : (
                            <>
                              {onUpdateSpec && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditingSpecId(spec.id);
                                    setEditTitle(spec.title);
                                    setEditClient(spec.client_name);
                                    setEditNotes(spec.meeting_notes || '');
                                  }}
                                  className="p-1 hover:bg-panel2 text-ink3 hover:text-ink rounded transition"
                                  title={t('run.sp.edit', undefined, 'Şartnameyi düzenle')}
                                >
                                  <Edit3 className="w-3.5 h-3.5" />
                                </button>
                              )}

                              {onDeleteSpec && (
                                <button
                                  type="button"
                                  onClick={async () => {
                                    if (await confirmDialog(t('run.sp.confirmDelete', { title: spec.title }, `'${spec.title}' şartnamesini silmek istediğinize emin misiniz?`))) {
                                      await onDeleteSpec(spec.id);
                                      setSuccessMessage(t('run.sp.deleted', undefined, '✓ Şartname silindi.'));
                                      setTimeout(() => setSuccessMessage(''), 3000);
                                    }
                                  }}
                                  className="p-1 hover:bg-errd/60 text-ink3 hover:text-err rounded transition"
                                  title={t('run.sp.delete', undefined, 'Şartnameyi sil')}
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}

                              {onAnalyzeSpec && (
                                <button
                                  type="button"
                                  disabled={analyzingSpecId === spec.id}
                                  onClick={async () => {
                                    setAnalyzingSpecId(spec.id);
                                    try {
                                      await onAnalyzeSpec(spec.id);
                                      setSuccessMessage(t('run.sp.analyzedOne', { title: spec.title }, `✓ '${spec.title}' analiz edildi ve Jira tahtasına özel görevler eklendi!`));
                                      setTimeout(() => setSuccessMessage(''), 4000);
                                    } catch (err) {
                                      console.error(err);
                                      notify(t('run.sp.analyzeErr', undefined, 'Analiz sırasında hata oluştu.'));
                                    } finally {
                                      setAnalyzingSpecId(null);
                                    }
                                  }}
                                  className="px-2.5 py-1 bg-acd/60 hover:bg-acd/80 text-ac border border-ac text-[11px] font-semibold rounded-lg transition flex items-center gap-1.5 shadow"
                                  title={t('run.sp.analyzeTitle', undefined, 'Bu şartnameyi analiz edip Jira tahtasındaki görevleri baştan oluştur')}
                                >
                                  <Sparkles className="w-3 h-3 text-ac" />
                                  <span>{analyzingSpecId === spec.id ? t('run.sp.analyzing', undefined, 'Analiz Ediliyor...') : t('run.sp.extractTasks', undefined, 'Jira Görevlerini Çıkar')}</span>
                                </button>
                              )}
                            </>
                          )}

                          <span className="text-[10px] text-ink3 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {new Date(spec.created_at).toLocaleString('tr-TR')}
                          </span>
                        </div>
                      </div>

                      {/* Geçmiş: bu yüklemeyi değerlendiren koşular */}
                      <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-mono">
                        <span className="text-ink3">{t('run.sp.history', undefined, 'Geçmiş:')}</span>
                        <span className="px-1.5 py-0.5 rounded bg-panel border border-line text-ink2">
                          ➕ {t('run.sp.uploaded', undefined, 'Yüklendi')} {new Date(spec.created_at).toLocaleDateString('tr-TR')}
                        </span>
                        {specRuns.length === 0 ? (
                          <span className="px-1.5 py-0.5 rounded bg-warnd text-warn border border-warn/40">{t('run.sp.notRun', undefined, 'Henüz çalıştırılmadı')}</span>
                        ) : specRuns.map(r => (
                          <span
                            key={r.run_id}
                            title={t('run.sp.runTitle', { id: r.run_id }, `Koşu ${r.run_id}`)}
                            className={`px-1.5 py-0.5 rounded border ${r.status === 'COMPLETED' ? 'bg-okd text-ok border-ok/40' : r.status === 'FAILED' || r.status === 'CANCELLED' ? 'bg-errd text-err border-err/40' : 'bg-acd text-ac border-ac/40'}`}
                          >
                            ▶ {new Date(r.created_at).toLocaleDateString('tr-TR')} · {r.status}
                          </span>
                        ))}
                      </div>

                      <div className="flex items-center gap-2 text-[11px] text-ink3">
                        <User className="w-3 h-3 text-ac" />
                        <span>{t('run.sp.client', undefined, 'Müşteri:')} {!isEditing ? (
                          <strong className="text-ink">{spec.client_name}</strong>
                        ) : (
                          <input
                            type="text"
                            value={editClient}
                            onChange={e => setEditClient(e.target.value)}
                            className="bg-panel border border-ac rounded px-1.5 py-0.5 text-xs text-ink"
                          />
                        )}</span>
                      </div>

                      {!isEditing ? (
                        spec.meeting_notes && (
                          <p className="text-xs text-ink2 whitespace-pre-wrap bg-panel/90 p-3 rounded-lg border border-line/80 leading-relaxed font-sans">
                            {spec.meeting_notes}
                          </p>
                        )
                      ) : (
                        <textarea
                          rows={3}
                          value={editNotes}
                          onChange={e => setEditNotes(e.target.value)}
                          className="w-full bg-panel border border-ac rounded-lg p-2 text-xs text-ink"
                        />
                      )}

                      {spec.files && spec.files.length > 0 && (
                        <div className="pt-2 flex flex-wrap gap-2">
                          {spec.files.map((f, idx) => (
                            <div
                              key={idx}
                              className="inline-flex items-center gap-1.5 px-3 py-1 bg-panel hover:bg-panel2 text-ink2 hover:text-ink text-[11px] rounded-lg border border-line2 transition group"
                            >
                              <a
                                href={api(f.file_url)}
                                target="_blank"
                                rel="noreferrer"
                                className="flex items-center gap-1"
                              >
                                <Download className="w-3 h-3 text-ac" />
                                <span>{f.filename}</span>
                                <span className="text-[9px] text-ink3">
                                  ({(f.size / 1024).toFixed(1)} KB)
                                </span>
                              </a>
                              {onDeleteSpecFile && (
                                <button
                                  type="button"
                                  onClick={async (e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    if (await confirmDialog(t('run.sp.confirmRemoveFile', { name: f.filename }, `'${f.filename}' dosyasını bu şartnameden çıkarmak istediğinize emin misiniz?`))) {
                                      await onDeleteSpecFile(spec.id, f.filename);
                                      setSuccessMessage(t('run.sp.fileRemoved', { name: f.filename }, `✓ '${f.filename}' dosyası çıkarıldı.`));
                                      setTimeout(() => setSuccessMessage(''), 3000);
                                    }
                                  }}
                                  className="ml-1 text-ink3 hover:text-err p-0.5 rounded transition"
                                  title={t('run.sp.removeFile', undefined, 'Dosyayı kaldır')}
                                >
                                  <X className="w-3 h-3" />
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
