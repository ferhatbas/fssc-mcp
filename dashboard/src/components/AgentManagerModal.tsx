import React, { useState, useEffect } from 'react';
import { notify, confirmDialog } from '../lib/dialog';
import { Agent, AgentRole, AgentPromptInfo, ProjectInfo } from '../types/telemetry';
import { AgentCapabilityFields, CapabilityDraft, agentScope, draftFromAgent, draftToPayload, emptyDraft, BASE_ROLES } from './AgentCapabilityFields';
import { AgentToolsBar } from './AgentToolsBar';
import { SkillSettings } from './SkillSettings';
import { api } from '../config';
import { useI18n } from '../i18n';
import { 
  X, 
  UserPlus, 
  Users, 
  CheckCircle2, 
  Edit3, 
  RotateCcw, 
  Trash2, 
  FileCode, 
  Bot,
  GitBranch,
  GitCommit,
  History,
  Globe,
  FileText,
  RefreshCw,
  AlertTriangle,
  Terminal,
  Layers,
  Sparkles
} from 'lucide-react';

interface AgentManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  agents: Agent[];
  currentProject?: ProjectInfo | null;
  onAddAgent: (data: { id?: string; name: string; role: string; active_file?: string; description?: string; [key: string]: unknown }) => Promise<void>;
  onUpdateAgent?: (agentId: string, updates: Partial<Agent>) => Promise<void>;
  onDeleteAgent?: (agentId: string) => Promise<void>;
  fetchAgentPrompt?: (agentId: string, projectId?: string) => Promise<AgentPromptInfo>;
  saveAgentPrompt?: (agentId: string, content: string, commitMessage: string, author?: string, projectId?: string) => Promise<AgentPromptInfo>;
  restoreAgentVersion?: (agentId: string, versionId: string, author?: string, projectId?: string) => Promise<AgentPromptInfo>;
  inheritAgentStandard?: (agentId: string, author?: string, projectId?: string) => Promise<AgentPromptInfo>;
  promoteAgentToGlobal?: (agentId: string, projectId?: string) => Promise<{ success: boolean; standard_file: string; backup_file?: string }>;
}

const CORE_AGENT_IDS = ['PM', 'ARCHITECT', 'BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'QA', 'E2E_TESTER', 'DEVOPS'];
const KNOWN_ROLES = ['E2E_TESTER', 'QA', 'BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'ARCHITECT', 'PM', 'DEVOPS'];

/** Ad'dan okunur kimlik (örn. "Mobil Geliştirici" → MOBIL_GELISTIRICI); çakışırsa sayı eklenir. Backlog'da `role` alanına bu kimlik yazılır. */
function makeAgentId(name: string, role: string, taken: string[]): string {
  const base = name.trim().toUpperCase()
    .replace(/İ/g, 'I').replace(/Ş/g, 'S').replace(/Ğ/g, 'G').replace(/Ü/g, 'U').replace(/Ö/g, 'O').replace(/Ç/g, 'C')
    .replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 30) || role;
  let id = base;
  for (let n = 2; taken.includes(id); n += 1) id = `${base}_${n}`;
  return id;
}

type ModalTab = 'PROFILE' | 'MARKDOWN_MEMORY';

export const AgentManagerModal: React.FC<AgentManagerModalProps> = ({
  isOpen,
  onClose,
  agents,
  currentProject,
  onAddAgent,
  onUpdateAgent,
  onDeleteAgent,
  fetchAgentPrompt,
  saveAgentPrompt,
  restoreAgentVersion,
  inheritAgentStandard,
  promoteAgentToGlobal
}) => {
  const { t } = useI18n();
  // Düzenleme modu: Hangi ajan düzenleniyor?
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ModalTab>('PROFILE');

  // Profil Form State
  const [name, setName] = useState('');
  const [role, setRole] = useState<AgentRole>('BACKEND_DEV');
  const [activeFile, setActiveFile] = useState('src/service.py');
  const [description, setDescription] = useState('');
  const [draft, setDraft] = useState<CapabilityDraft>(emptyDraft());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  // Markdown & Git-Tree State
  const [promptInfo, setPromptInfo] = useState<AgentPromptInfo | null>(null);
  const [promptContent, setPromptContent] = useState('');
  const [commitMessage, setCommitMessage] = useState('');
  const [isLoadingPrompt, setIsLoadingPrompt] = useState(false);
  const [isSavingPrompt, setIsSavingPrompt] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);

  // Global Terfi Onay Modal State
  const [showPromoteConfirm, setShowPromoteConfirm] = useState(false);
  const [isPromoting, setIsPromoting] = useState(false);

  // Ajan havuzu (şirket geneli tanımlar): projeye istenince eklenir
  interface PoolAgent { id: string; name: string; role?: string; role_base?: string; description?: string; capabilities?: string[]; projects: string[]; in_project: boolean }
  const [pool, setPool] = useState<PoolAgent[]>([]);
  const loadPool = async () => {
    try { setPool((await fetch(api('/api/agents/global')).then(r => r.json())).agents || []); } catch { /* havuz okunamazsa liste boş kalır */ }
  };
  useEffect(() => { if (isOpen) void loadPool(); }, [isOpen, agents.length]);
  const poolCall = async (url: string, method: string, body: unknown, ok: string) => {
    try {
      const r = await fetch(api(url), { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { notify(j.error || t('agents.mgr.opFailed', undefined, 'İşlem başarısız')); return; }
      notify(ok, 'success');
      await loadPool();
    } catch { notify(t('agents.mgr.unreachable', undefined, 'Sunucuya ulaşılamadı')); }
  };
  const addFromPool = (p: PoolAgent, mode: 'linked' | 'copy') => {
    const id = mode === 'copy' ? makeAgentId(`${p.id}_KOPYA`, p.id, agents.map(a => a.id)) : undefined;
    void poolCall(`/api/agents/pool/${p.id}/add`, 'POST', { mode, id }, mode === 'copy' ? t('agents.mgr.copyAdded', { name: p.name }, '{name}: bağımsız kopya projeye eklendi.') : t('agents.mgr.linkedAdded', { name: p.name }, '{name} projeye eklendi (havuza bağlı).'));
  };
  const removeFromPool = async (p: PoolAgent) => {
    if (!await confirmDialog(t('agents.mgr.poolDeleteConfirm', { name: p.name }, '"{name}" ajan havuzundan silinsin mi? Projelerdeki kopyaları silinmez, proje ajanı olarak kalır.'), { title: t('agents.mgr.poolDeleteTitle', undefined, 'Havuzdan sil'), confirmLabel: t('agents.mgr.delete', undefined, 'Sil') })) return;
    void poolCall(`/api/agents/global/${p.id}`, 'DELETE', null, t('agents.mgr.poolDeleted', { name: p.name }, '{name} havuzdan silindi.'));
  };
  const promoteToPool = async (a: Agent) => {
    if (!await confirmDialog(t('agents.mgr.promoteConfirm', { name: a.name }, '"{name}" ajanının tanımı ajan havuzuna aktarılsın mı? Diğer projeler onu havuzdan istediğinde ekleyebilir (bu proje etkilenmez).'), { title: t('agents.mgr.promoteTitle', undefined, 'Havuza aktar'), confirmLabel: t('agents.mgr.promoteLabel', undefined, 'Aktar') })) return;
    void poolCall(`/api/agents/${a.id}/promote-definition`, 'POST', null, t('agents.mgr.promoted', { name: a.name }, '{name} ajan havuzuna aktarıldı.'));
  };

  // Seçili ajan veya tab değiştiğinde prompt bilgisini getir
  useEffect(() => {
    if (editingAgentId && activeTab === 'MARKDOWN_MEMORY' && fetchAgentPrompt) {
      loadPromptData(editingAgentId);
    }
  }, [editingAgentId, activeTab]);

  const loadPromptData = async (agentId: string) => {
    if (!fetchAgentPrompt) return;
    setIsLoadingPrompt(true);
    setPromptError(null);
    try {
      const data = await fetchAgentPrompt(agentId, currentProject?.id);
      setPromptInfo(data);
      setPromptContent(data.active_content || '');
      setCommitMessage('');
    } catch (err: any) {
      console.error(err);
      setPromptError(err.message || t('agents.mgr.loadGuideFailed', undefined, 'Ajan hafıza kılavuzu yüklenirken hata oluştu.'));
    } finally {
      setIsLoadingPrompt(false);
    }
  };

  if (!isOpen) return null;

  const editingAgent = editingAgentId ? agents.find(a => a.id === editingAgentId) : undefined;
  const isCoreId = (id: string) => {
    const a = agents.find(x => x.id === id);
    return a ? agentScope(a) === 'core' : CORE_AGENT_IDS.includes(id);
  };

  // Bir ajanı düzenleme moduna al
  const handleStartEdit = (agent: Agent, defaultTab: ModalTab = 'PROFILE') => {
    setEditingAgentId(agent.id);
    setActiveTab(defaultTab);
    setName(agent.name);
    setRole(agent.role);
    setActiveFile(agent.active_file || '');
    setDescription(agent.description || '');
    setDraft(draftFromAgent(agent));
    setStatusMsg('');
  };

  // Düzenleme modundan çık / formu temizle
  const handleCancelEdit = () => {
    setEditingAgentId(null);
    setActiveTab('PROFILE');
    setName('');
    setRole('BACKEND_DEV');
    setActiveFile('src/service.py');
    setDescription('');
    setDraft(emptyDraft());
    setPromptInfo(null);
    setPromptContent('');
    setCommitMessage('');
    setPromptError(null);
  };

  const handleSubmitProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      notify(t('agents.mgr.enterName', undefined, 'Lütfen ajan adını girin.'));
      return;
    }

    setIsSubmitting(true);
    try {
      if (editingAgentId) {
        if (onUpdateAgent) {
          await onUpdateAgent(editingAgentId, {
            name: name.trim(),
            role,
            active_file: activeFile.trim(),
            description: description.trim(),
            ...(draftToPayload(draft, editingAgent) as Partial<Agent>)
          });
          setStatusMsg(t('agents.mgr.profileUpdated', { id: editingAgentId }, '✓ [{id}] profil bilgileri başarıyla güncellendi.'));
        }
      } else {
        const generatedId = makeAgentId(name, role, agents.map(a => a.id));
        await onAddAgent({
          id: generatedId,
          name: name.trim(),
          role,
          active_file: activeFile.trim(),
          description: description.trim(),
          ...draftToPayload(draft)
        });
        setStatusMsg(t('agents.mgr.agentAdded', { name, role }, '✓ Yeni kıdemli ajan eklendi: {name} ({role})'));
      }
      handleCancelEdit();
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err) {
      console.error(err);
      notify(t('agents.mgr.agentOpError', undefined, 'Ajan işlemi sırasında hata oluştu.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteOrReset = async (agentId: string) => {
    const isCore = isCoreId(agentId);
    const confirmMsg = isCore 
      ? t('agents.mgr.resetConfirm', { id: agentId }, 'Bu ana ajanın ({id}) profilini varsayılan fabrika ayarlarına sıfırlamak istiyor musunuz?')
      : t('agents.mgr.removeConfirm', { id: agentId }, 'Bu ajanı ({id}) sistemden tamamen kaldırmak istiyor musunuz?');
    
    if (!await confirmDialog(confirmMsg)) return;

    if (onDeleteAgent) {
      try {
        await onDeleteAgent(agentId);
        if (editingAgentId === agentId) handleCancelEdit();
        setStatusMsg(isCore ? t('agents.mgr.resetDone', { id: agentId }, '✓ [{id}] varsayılan ayarlarına sıfırlandı.') : t('agents.mgr.removeDone', { id: agentId }, '✓ [{id}] sistemden kaldırıldı.'));
        setTimeout(() => setStatusMsg(''), 4000);
      } catch (err) {
        console.error(err);
        notify(t('agents.mgr.opFailedShort', undefined, 'İşlem başarısız oldu.'));
      }
    }
  };

  // Yeni Versiyon Kaydet (Commit)
  const handleSavePromptVersion = async () => {
    if (!editingAgentId || !saveAgentPrompt) return;
    if (!commitMessage.trim()) {
      notify(t('agents.mgr.enterCommit', undefined, 'Lütfen bu versiyon için bir değişiklik/commit mesajı girin.'));
      return;
    }

    setIsSavingPrompt(true);
    setPromptError(null);
    try {
      const updated = await saveAgentPrompt(
        editingAgentId,
        promptContent,
        commitMessage.trim(),
        'User',
        currentProject?.id
      );
      setPromptInfo(updated);
      setPromptContent(updated.active_content);
      setCommitMessage('');
      setStatusMsg(t('agents.mgr.versionSaved', { v: updated.current_version }, '✓ Yeni versiyon [{v}] başarıyla oluşturuldu ve kaydedildi.'));
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err: any) {
      console.error(err);
      setPromptError(err.message || t('agents.mgr.versionSaveFailed', undefined, 'Versiyon kaydedilirken hata oluştu.'));
    } finally {
      setIsSavingPrompt(false);
    }
  };

  // Belirli Bir Versiyona Geri Dön (Restore / Rollback)
  const handleRestoreVersion = async (versionId: string) => {
    if (!editingAgentId || !restoreAgentVersion) return;
    if (!await confirmDialog(t('agents.mgr.restoreConfirm', { v: versionId }, 'Bu ajanı [{v}] versiyonuna geri döndürmek istediğinizden emin misiniz?'))) return;

    setIsSavingPrompt(true);
    setPromptError(null);
    try {
      const updated = await restoreAgentVersion(editingAgentId, versionId, 'User', currentProject?.id);
      setPromptInfo(updated);
      setPromptContent(updated.active_content);
      setStatusMsg(t('agents.mgr.restored', { v: versionId }, '✓ Ajan başarıyla [{v}] versiyonuna geri döndürüldü.'));
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err: any) {
      console.error(err);
      setPromptError(err.message || t('agents.mgr.restoreFailed', undefined, 'Versiyona dönerken hata oluştu.'));
    } finally {
      setIsSavingPrompt(false);
    }
  };

  // Şirket Standart Şablonundan Yeniden Kalıt (Inherit)
  const handleInheritStandard = async () => {
    if (!editingAgentId || !inheritAgentStandard) return;
    if (!await confirmDialog(t('agents.mgr.inheritConfirm', { std: promptInfo?.parent_standard }, 'Standart şablondan ({std}) güncel kuralları çekip öğrenilen notlarla birleştirmek istiyor musunuz?'))) return;

    setIsSavingPrompt(true);
    setPromptError(null);
    try {
      const updated = await inheritAgentStandard(editingAgentId, 'User', currentProject?.id);
      setPromptInfo(updated);
      setPromptContent(updated.active_content);
      setStatusMsg(t('agents.mgr.inherited', { std: updated.parent_standard }, '✓ Standart şablondan ({std}) başarıyla kalıtıldı.'));
      setTimeout(() => setStatusMsg(''), 4000);
    } catch (err: any) {
      console.error(err);
      setPromptError(err.message || t('agents.mgr.inheritFailed', undefined, 'Standarttan kalıtılırken hata oluştu.'));
    } finally {
      setIsSavingPrompt(false);
    }
  };

  // Global Standartlara Terfi Et (Promote to Global)
  const handleConfirmPromoteGlobal = async () => {
    if (!editingAgentId || !promoteAgentToGlobal) return;
    setIsPromoting(true);
    try {
      const res = await promoteAgentToGlobal(editingAgentId, currentProject?.id);
      setShowPromoteConfirm(false);
      setStatusMsg(t('agents.mgr.promotedGlobal', { file: res.standard_file }, '🌍 Başarılı! Ajanın bu projedeki kuralları global standarda ({file}) terfi ettirildi.'));
      setTimeout(() => setStatusMsg(''), 6000);
    } catch (err: any) {
      console.error(err);
      notify(t('agents.mgr.promoteError', { msg: err.message || t('agents.mgr.unknownError', undefined, 'Bilinmeyen hata') }, 'Terfi sırasında hata: {msg}'));
    } finally {
      setIsPromoting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="bg-panel border border-line2 rounded-2xl w-full max-w-4xl max-h-[94vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
        
        {/* Modal Üst Başlık */}
        <div className="px-6 py-4 bg-sunk border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-acd border border-ac/40 flex items-center justify-center">
              <Bot className="w-5 h-5 text-ac" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-ink tracking-wide">
                  {t('agents.mgr.title', undefined, 'Şirket Ajanları & Uzman Yönetim Merkezi')}
                </h3>
                {currentProject && (
                  <span className="text-[10px] bg-acd/80 text-ac border border-ac/60 px-2 py-0.5 rounded-full font-mono flex items-center gap-1">
                    <Layers className="w-3 h-3 text-ac" />
                    {currentProject.name} (.fs-workspace)
                  </span>
                )}
              </div>
              <p className="text-xs text-ink3">
                {t('agents.mgr.subtitle', undefined, 'Ajan profillerini düzenleyin, projeye özel Markdown kılavuzlarını (.md) ve Git-Tree versiyon hafızasını yönetin')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink3 hover:text-ink p-1.5 rounded-lg hover:bg-panel2 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Gövdesi */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {statusMsg && (
            <div className="p-3 bg-okd/80 border border-ok/60 rounded-lg text-ok text-xs flex items-center gap-2 animate-fadeIn">
              <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
              <span>{statusMsg}</span>
            </div>
          )}

          {/* Düzenleme / Ekleme Bölümü */}
          <div className={`p-4 rounded-xl border transition-all space-y-4 ${
            editingAgentId 
              ? 'bg-acd border-ac/50 shadow-lg shadow-panel' 
              : 'bg-sunk/60 border-line'
          }`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h4 className="text-xs font-bold text-ink uppercase tracking-wider flex items-center gap-2">
                  {editingAgentId ? (
                    <>
                      <Edit3 className="w-4 h-4 text-warn" />
                      <span>{t('agents.mgr.manage', undefined, 'Ajanı Yönet:')}</span>
                      <span className="bg-acd text-ac border border-ac/40 px-2 py-0.5 rounded font-mono text-[10px]">
                        {editingAgentId}
                      </span>
                    </>
                  ) : (
                    <>
                      <UserPlus className="w-4 h-4 text-ac" />
                      <span>{t('agents.mgr.newAgent', undefined, 'Yeni Kıdemli Geliştirici / Uzman Tanımla')}</span>
                    </>
                  )}
                </h4>

                {/* Tab Değiştirici (Sadece bir ajan düzenlenirken görünür) */}
                {editingAgentId && (
                  <div className="flex items-center bg-panel border border-line p-0.5 rounded-lg">
                    <button
                      type="button"
                      onClick={() => setActiveTab('PROFILE')}
                      className={`px-3 py-1 text-xs rounded-md font-medium transition flex items-center gap-1.5 ${
                        activeTab === 'PROFILE'
                          ? 'bg-ac text-onac shadow'
                          : 'text-ink3 hover:text-ink'
                      }`}
                    >
                      <Bot className="w-3.5 h-3.5" />
                      {t('agents.mgr.tabProfile', undefined, 'Profil Ayarları')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveTab('MARKDOWN_MEMORY')}
                      className={`px-3 py-1 text-xs rounded-md font-medium transition flex items-center gap-1.5 ${
                        activeTab === 'MARKDOWN_MEMORY'
                          ? 'bg-ok text-onac shadow'
                          : 'text-ink3 hover:text-ink'
                      }`}
                    >
                      <FileText className="w-3.5 h-3.5" />
                      {t('agents.mgr.tabMd', undefined, 'Proje Kılavuzu & Git Ağacı (.md)')}
                      {promptInfo && (
                        <span className="bg-okd text-ok text-[10px] px-1.5 py-0.2 rounded font-mono border border-ok/40">
                          {promptInfo.current_version}
                        </span>
                      )}
                    </button>
                  </div>
                )}
              </div>

              {editingAgentId && (
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  className="text-xs text-ink3 hover:text-ink underline font-mono"
                >
                  {t('agents.mgr.backToList', undefined, 'Vazgeç (Listeye Dön)')}
                </button>
              )}
            </div>

            {/* TAB 1: PROFİL FORMU */}
            {(!editingAgentId || activeTab === 'PROFILE') && (
              <form onSubmit={handleSubmitProfile} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-ink3 mb-1">
                      {t('agents.mgr.labelName', undefined, 'Ajan Adı / Görünen Ünvan')}
                    </label>
                    <input
                      type="text"
                      placeholder={t('agents.mgr.namePh', undefined, 'Örn: Playwright Canlı Tarayıcı Tester veya Senior Backend Dev')}
                      value={name}
                      onChange={e => setName(e.target.value)}
                      className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none font-sans"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-ink3 mb-1">
                      {t('agents.mgr.labelRole', undefined, 'Ajan Rolü & Sorumluluk')}
                    </label>
                    <select
                      value={role}
                      onChange={e => {
                        const r = e.target.value as AgentRole;
                        setRole(r);
                        if (!editingAgentId && BASE_ROLES.includes(r)) setDraft(d => ({ ...d, roleBase: r }));
                        if (!editingAgentId) {
                          if (r === 'BACKEND_DEV') setActiveFile('src/api/service.py');
                          else if (r === 'FRONTEND_DEV') setActiveFile('frontend/src/App.tsx');
                          else if (r === 'QA') setActiveFile('tests/test_app.py');
                          else if (r === 'E2E_TESTER') setActiveFile('tests/e2e/login.spec.ts');
                        }
                      }}
                      className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink focus:border-ac focus:outline-none cursor-pointer font-mono"
                    >
                      <option value="E2E_TESTER">E2E_TESTER ({t('agents.mgr.roleE2E', undefined, 'Playwright Canlı Tarayıcı Tester')})</option>
                      <option value="QA">QA ({t('agents.mgr.roleQA', undefined, 'Lead QA & Birim/Regresyon Testi')})</option>
                      <option value="BACKEND_DEV">BACKEND_DEV ({t('agents.mgr.roleBE', undefined, 'Senior Backend Developer')})</option>
                      <option value="FRONTEND_DEV">FRONTEND_DEV ({t('agents.mgr.roleFE', undefined, 'Senior Frontend Developer')})</option>
                      <option value="ARCHITECT">ARCHITECT ({t('agents.mgr.roleArch', undefined, 'Tech Lead & Sistem Mimarı')})</option>
                      <option value="PM">PM ({t('agents.mgr.rolePM', undefined, 'Product Manager & Gereksinim')})</option>
                      <option value="DEVOPS">DEVOPS ({t('agents.mgr.roleDevops', undefined, 'DevOps & SRE Dağıtım')})</option>
                      {!KNOWN_ROLES.includes(role) && <option value={role}>{role}</option>}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-ink3 mb-1">
                      {t('agents.mgr.labelFile', undefined, 'Sorumlu Olduğu Çalışma Dosyası')}
                    </label>
                    <div className="relative">
                      <FileCode className="w-3.5 h-3.5 text-ink3 absolute left-2.5 top-2.5" />
                      <input
                        type="text"
                        placeholder={t('agents.mgr.filePh', undefined, 'Örn: tests/e2e/login.spec.ts')}
                        value={activeFile}
                        onChange={e => setActiveFile(e.target.value)}
                        className="w-full bg-panel border border-line2 rounded-lg pl-8 pr-3 py-2 text-xs text-ink focus:border-ac focus:outline-none font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-ink3 mb-1">
                      {t('agents.mgr.labelDesc', undefined, 'Ajan Açıklaması / Talimat Özeti')}
                    </label>
                    <input
                      type="text"
                      placeholder={t('agents.mgr.descPh', undefined, 'Örn: Gerçek Chromium ile login formlarını test eder ve screenshot alır')}
                      value={description}
                      onChange={e => setDescription(e.target.value)}
                      className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none"
                    />
                  </div>
                </div>

                <AgentCapabilityFields
                  draft={draft}
                  onChange={setDraft}
                  core={!!editingAgent && agentScope(editingAgent) === 'core'}
                  editing={!!editingAgentId}
                  inherited={!!editingAgent && agentScope(editingAgent) === 'global'}
                />

                <AgentToolsBar agent={editingAgent ?? null} />

                {editingAgentId && (
                  <div className="rounded-xl border border-line bg-sunk/60 p-3 space-y-2">
                    <div>
                      <div className="text-[11px] font-bold uppercase tracking-wider text-ink2">{t('agents.mgr.skillTitle', undefined, 'Skill rehberleri (bu ajan)')}</div>
                      <div className="text-[10px] text-ink3">{t('agents.mgr.skillHint', undefined, 'Ajanın kendi tanımına EK bilgi olarak verilir (en çok 4). Seçim yoksa çekirdek varsayılanlar kullanılır. Bu bölümün düğmeleri profil formundan bağımsız kaydeder.')}</div>
                    </div>
                    <SkillSettings key={editingAgentId} fixedRole={editingAgentId} inputCls="w-full bg-panel border rounded-lg px-2 py-1.5 text-ink text-xs focus:outline-none focus:border-ac" />
                  </div>
                )}

                <div className="flex items-center justify-between pt-2 border-t border-line">
                  {editingAgentId ? (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleDeleteOrReset(editingAgentId)}
                        className="px-3 py-1.5 bg-errd/60 hover:bg-errd text-err border border-err/40 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
                      >
                        {isCoreId(editingAgentId) ? (
                          <>
                            <RotateCcw className="w-3.5 h-3.5" />
                            {t('agents.mgr.resetDefault', undefined, 'Varsayılana Sıfırla')}
                          </>
                        ) : agentScope(editingAgent ?? { id: editingAgentId }) === 'global' ? (
                          <>
                            <Trash2 className="w-3.5 h-3.5" />
                            {t('agents.mgr.deactivate', undefined, 'Bu Projede Pasifleştir')}
                          </>
                        ) : (
                          <>
                            <Trash2 className="w-3.5 h-3.5" />
                            {t('agents.mgr.deleteAgent', undefined, 'Ajanı Sil')}
                          </>
                        )}
                      </button>
                    </div>
                  ) : <div />}

                  <div className="flex items-center gap-2">
                    {editingAgentId && (
                      <button
                        type="button"
                        onClick={handleCancelEdit}
                        className="px-3.5 py-1.5 bg-panel2 hover:bg-sunk text-ink2 rounded-lg text-xs font-medium transition"
                      >
                        {t('agents.mgr.cancel', undefined, 'İptal')}
                      </button>
                    )}
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className={`px-4 py-2 text-ink text-xs font-semibold rounded-lg shadow-lg flex items-center gap-2 transition ${
                        editingAgentId
                          ? 'bg-warn hover:opacity-90 border border-warn/30'
                          : 'bg-ac hover:opacity-90 border border-ac/30'
                      }`}
                    >
                      {editingAgentId ? <CheckCircle2 className="w-3.5 h-3.5" /> : <UserPlus className="w-3.5 h-3.5" />}
                      {isSubmitting 
                        ? t('agents.mgr.saving', undefined, 'Kaydediliyor...') 
                        : editingAgentId 
                        ? t('agents.mgr.saveProfile', undefined, 'Profil Değişikliklerini Kaydet') 
                        : t('agents.mgr.addToTeam', undefined, 'Ajanı Şirket Takımına Ekle')}
                    </button>
                  </div>
                </div>
              </form>
            )}

            {/* TAB 2: PROJE BAZLI MARKDOWN & GİT-TREE HAFIZASI */}
            {editingAgentId && activeTab === 'MARKDOWN_MEMORY' && (
              <div className="space-y-4">
                {isLoadingPrompt ? (
                  <div className="p-8 text-center text-ink3 text-xs flex flex-col items-center justify-center gap-2">
                    <RefreshCw className="w-6 h-6 animate-spin text-ac" />
                    <span>{t('agents.mgr.loadingGuide', undefined, 'Ajanın proje kılavuzu (.md) ve Git versiyon geçmişi yükleniyor...')}</span>
                  </div>
                ) : promptError ? (
                  <div className="p-4 bg-errd/60 border border-err/40 text-err rounded-lg text-xs flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-err" />
                      <span>{promptError}</span>
                    </div>
                    <button
                      onClick={() => loadPromptData(editingAgentId)}
                      className="px-2.5 py-1 bg-errd hover:bg-errd rounded text-ink text-[11px]"
                    >
                      {t('agents.mgr.retry', undefined, 'Tekrar Dene')}
                    </button>
                  </div>
                ) : promptInfo ? (
                  <div className="space-y-4">
                    {/* Bilgi & Eylem Çubuğu */}
                    <div className="bg-panel/90 border border-line rounded-xl p-3 flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="text-ink3">{t('agents.mgr.scopeFile', undefined, 'Kapsam Dosyası:')}</span>
                        <span className="bg-sunk text-ac border border-line px-2 py-0.5 rounded font-mono text-[11px] flex items-center gap-1">
                          <Terminal className="w-3 h-3 text-ac" />
                          {promptInfo.file_path}
                        </span>

                        <span className="bg-okd text-ok border border-ok/40 px-2 py-0.5 rounded font-mono text-[11px] font-bold">
                          {promptInfo.current_version}
                        </span>

                        <span className="bg-acd/80 text-ac border border-ac/40 px-2 py-0.5 rounded font-mono text-[11px]" title={t('agents.mgr.stdTitle', undefined, 'Kalıtılan şirket global standart şablonu')}>
                          {t('agents.mgr.standard', undefined, 'Standart')}: {promptInfo.parent_standard}
                        </span>
                      </div>

                      {/* Kalıt & Terfi Butonları */}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={handleInheritStandard}
                          disabled={isSavingPrompt}
                          className="px-2.5 py-1.5 bg-acd/60 hover:bg-acd text-ac border border-ac/60 rounded-lg text-xs font-medium flex items-center gap-1.5 transition"
                          title={t('agents.mgr.inheritTitle', undefined, 'Şirket standart şablonundaki en son kuralları projeye çek ve öğrenilen derslerle birleştir')}
                        >
                          <RefreshCw className="w-3.5 h-3.5 text-ac" />
                          {t('agents.mgr.inheritBtn', undefined, 'Standarttan Kalıt')}
                        </button>

                        <button
                          type="button"
                          onClick={() => setShowPromoteConfirm(true)}
                          disabled={isSavingPrompt || isPromoting}
                          className="px-3 py-1.5 bg-warn hover:opacity-90 text-onac font-semibold rounded-lg text-xs flex items-center gap-1.5 shadow-md transition"
                          title={t('agents.mgr.promoteGlobalTitle', undefined, 'Bu ajanın geliştirdiği kuralları şirketin tüm projelerde geçerli global standardına terfi ettir')}
                        >
                          <Globe className="w-3.5 h-3.5" />
                          🌍 {t('agents.mgr.promoteGlobalBtn', undefined, 'Global Standartlara Terfi Et')}
                        </button>
                      </div>
                    </div>

                    {/* Ana Düzenleyici & Git Ağacı İki Kolonlu Yerleşim */}
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                      {/* Sol Kolon: Markdown Düzenleyici */}
                      <div className="lg:col-span-7 space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-[11px] font-bold text-ink2 uppercase tracking-wider flex items-center gap-1.5">
                            <FileCode className="w-3.5 h-3.5 text-ok" />
                            {t('agents.mgr.activeGuide', undefined, 'Aktif Proje Kılavuzu & Hafızası (.md)')}
                          </label>
                          <span className="text-[10px] text-ink3 font-mono">
                            {t('agents.mgr.chars', { n: promptContent.length }, '{n} karakter')} • {t('agents.mgr.versioned', undefined, 'Değişiklikler versiyonlanır')}
                          </span>
                        </div>

                        <textarea
                          rows={13}
                          value={promptContent}
                          onChange={e => setPromptContent(e.target.value)}
                          className="w-full bg-sunk border border-line2 rounded-xl p-3 text-xs text-ink font-mono leading-relaxed focus:border-ok focus:outline-none resize-y"
                          placeholder={t('agents.mgr.mdPh', undefined, 'Ajanın bu projeye özel davranış kuralları, dosya yolları, mimari tercihler ve öğrenilen dersler...')}
                        />

                        {/* Commit Alanı */}
                        <div className="bg-panel/90 border border-line rounded-xl p-3 space-y-2.5">
                          <div className="flex items-center gap-2">
                            <GitCommit className="w-4 h-4 text-ok shrink-0" />
                            <input
                              type="text"
                              placeholder={t('agents.mgr.commitPh', undefined, 'Commit Mesajı: Örn: Playwright timeout süresi 3sn yapıldı ve modal bekleme kuralı eklendi')}
                              value={commitMessage}
                              onChange={e => setCommitMessage(e.target.value)}
                              className="w-full bg-sunk border border-line2 rounded-lg px-3 py-1.5 text-xs text-ink placeholder-ink3 focus:border-ok focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={handleSavePromptVersion}
                              disabled={isSavingPrompt || !commitMessage.trim()}
                              className="px-4 py-1.5 bg-ok hover:bg-ok disabled:opacity-50 disabled:hover:bg-ok text-onac font-semibold rounded-lg text-xs whitespace-nowrap flex items-center gap-1.5 shadow transition"
                            >
                              <GitBranch className="w-3.5 h-3.5" />
                              {isSavingPrompt ? t('agents.mgr.saving', undefined, 'Kaydediliyor...') : t('agents.mgr.saveVersion', undefined, '✓ Versiyon Kaydet')}
                            </button>
                          </div>

                          <div className="text-[10px] text-ink3 flex items-center gap-1.5">
                            <Sparkles className="w-3.5 h-3.5 text-warn shrink-0" />
                            <span>
                              <strong>{t('agents.mgr.autoLearn', undefined, 'Otonom Öğrenme:')}</strong> {t('agents.mgr.autoLearnText', undefined, 'Ajan görevleri tamamladıkça veya hata çözdükçe bu dosyanın altındaki "## 🧠 Öğrenilen Dersler" bölümüne otomatik ekleme yapar ve kendini geliştirir.')}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Sağ Kolon: Git-Tree Versiyon Zaman Çizelgesi */}
                      <div className="lg:col-span-5 bg-sunk/70 border border-line rounded-xl p-3 flex flex-col max-h-[460px]">
                        <div className="flex items-center justify-between pb-2 mb-3 border-b border-line">
                          <h5 className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-1.5">
                            <History className="w-3.5 h-3.5 text-ac" />
                            {t('agents.mgr.gitTree', undefined, 'Git Ağacı')} ({t('agents.mgr.versionCount', { n: promptInfo.versions.length }, '{n} Versiyon')})
                          </h5>
                          <span className="text-[10px] text-ink3 font-mono">
                            .fs-workspace/history
                          </span>
                        </div>

                        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                          {promptInfo.versions.length === 0 ? (
                            <p className="text-xs text-ink3 italic text-center py-6">
                              {t('agents.mgr.noVersions', undefined, 'Henüz kayıtlı bir versiyon bulunmuyor.')}
                            </p>
                          ) : (
                            promptInfo.versions.slice().reverse().map((ver, idx) => {
                              const isCurrent = ver.version_id === promptInfo.current_version;

                              return (
                                <div 
                                  key={ver.version_id} 
                                  className={`relative pl-5 pb-3 border-l-2 ${
                                    isCurrent ? 'border-ok' : 'border-line'
                                  }`}
                                >
                                  {/* Node Noktası */}
                                  <div className={`absolute -left-[7px] top-0 w-3 h-3 rounded-full border-2 ${
                                    isCurrent 
                                      ? 'bg-ok border-ok ring-2 ring-ok/30' 
                                      : 'bg-panel border-line2'
                                  }`} />

                                  <div className={`p-2.5 rounded-lg border transition ${
                                    isCurrent 
                                      ? 'bg-okd border-ok/60 shadow-sm' 
                                      : 'bg-panel/80 border-line/80 hover:border-line2'
                                  }`}>
                                    <div className="flex items-center justify-between gap-1.5 mb-1">
                                      <div className="flex items-center gap-1.5">
                                        <span className={`text-[11px] font-bold font-mono px-1.5 py-0.2 rounded ${
                                          isCurrent 
                                            ? 'bg-okd text-ok' 
                                            : 'bg-panel2 text-ink2'
                                        }`}>
                                          {ver.version_id}
                                        </span>
                                        {isCurrent && (
                                          <span className="text-[9px] text-ok font-semibold font-mono">
                                            ● {t('agents.mgr.active', undefined, 'AKTİF')}
                                          </span>
                                        )}
                                      </div>
                                      <span className="text-[10px] text-ink3 font-mono">
                                        {new Date(ver.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                      </span>
                                    </div>

                                    <p className="text-[11px] text-ink font-sans mb-1.5">
                                      {ver.commit_message}
                                    </p>

                                    <div className="flex items-center justify-between text-[9px] font-mono text-ink3 pt-1 border-t border-line/80">
                                      <span>{t('agents.mgr.author', undefined, 'Yazar')}: <strong>{ver.author}</strong></span>
                                      <span className="text-ink3">#{ver.hash.substring(0, 7)}</span>
                                    </div>

                                    {!isCurrent && (
                                      <button
                                        type="button"
                                        onClick={() => handleRestoreVersion(ver.version_id)}
                                        disabled={isSavingPrompt}
                                        className="mt-2 w-full py-1 bg-panel2 hover:bg-sunk text-ink2 hover:text-ink rounded text-[10px] font-medium flex items-center justify-center gap-1 transition"
                                      >
                                        <RotateCcw className="w-3 h-3 text-warn" />
                                        {t('agents.mgr.restoreBtn', undefined, 'Bu Versiyona Dön (Restore)')}
                                      </button>
                                    )}
                                  </div>
                                </div>
                              );
                            })
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          {/* Mevcut Ajanlar Listesi (Tıklanabilir ve Düzenlenebilir Kartlar) */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-2">
                <Users className="w-4 h-4 text-ac" />
                {t('agents.mgr.registered', { n: agents.length }, 'Kayıtlı Şirket Ajanları ({n}) — Bilgileri ve Proje Hafızasını (.md) Yönetin')}
              </h4>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {agents.map(agent => {
                const isSelected = editingAgentId === agent.id;
                const scope = agentScope(agent);
                const isCore = scope === 'core';

                return (
                  <div
                    key={agent.id}
                    className={`p-3.5 rounded-xl border flex flex-col justify-between space-y-2.5 transition shadow-md ${
                      isSelected
                        ? 'bg-acd/40 border-warn ring-2 ring-warn/30'
                        : 'bg-sunk/80 border-line hover:border-line2'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-ink">{agent.name}</span>
                          <span className="text-[10px] bg-panel2 text-ink2 px-1.5 py-0.2 rounded font-mono font-bold">
                            {agent.id}
                          </span>
                          {isCore && (
                            <span className="text-[9px] bg-acd text-ac border border-ac/40 px-1.5 py-0.2 rounded font-mono">
                              Core
                            </span>
                          )}
                          {scope === 'global' && (
                            <span className="text-[9px] bg-okd text-ok border border-ok/40 px-1.5 py-0.2 rounded font-mono" title={t('agents.mgr.poolLinkedTitle', undefined, 'Ajan havuzuna bağlı: havuzdaki tanım değişirse farksız alanlar güncellenir')}>
                              {t('agents.mgr.pool', undefined, 'Havuz')}{agent.overrides && Object.keys(agent.overrides).length > 0 ? ` · ${t('agents.mgr.hasDiff', undefined, 'fark var')}` : ''}
                            </span>
                          )}
                          {agent.active === false && (
                            <span className="text-[9px] bg-sunk text-ink3 border border-line px-1.5 py-0.2 rounded font-mono">{t('agents.mgr.inactive', undefined, 'Pasif')}</span>
                          )}
                        </div>
                        <span className="text-[11px] text-ac font-mono font-semibold">{agent.role}</span>
                        {!isCore && (agent.capabilities?.length ?? 0) > 0 && (
                          <span className="ml-2 text-[10px] text-ink3 font-mono">
                            {agent.role_base} · {agent.capabilities!.join(' ')}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleStartEdit(agent, 'MARKDOWN_MEMORY')}
                          className="p-1.5 rounded-lg border text-xs font-medium flex items-center gap-1 transition bg-okd/60 hover:bg-okd text-ok hover:text-ink border-ok/40"
                          title={t('agents.mgr.openMemTitle', undefined, 'Ajanın proje hafıza dosyasını (.md) ve Git versiyon ağacını aç')}
                        >
                          <FileText className="w-3 h-3 text-ok" />
                          <span>{t('agents.mgr.mdMemory', undefined, '.md Hafıza')}</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => handleStartEdit(agent, 'PROFILE')}
                          className={`p-1.5 rounded-lg border text-xs font-medium flex items-center gap-1 transition ${
                            isSelected && activeTab === 'PROFILE'
                              ? 'bg-warn text-onac border-warn shadow'
                              : 'bg-panel hover:bg-panel2 text-ink2 hover:text-ink border-line2'
                          }`}
                          title={t('agents.mgr.editProfileTitle', undefined, 'Ajan profilini düzenle')}
                        >
                          <Edit3 className="w-3 h-3" />
                          <span>{t('agents.mgr.edit', undefined, 'Düzenle')}</span>
                        </button>
                        {scope === 'project' && (
                          <button type="button" onClick={() => void promoteToPool(agent)} className="p-1.5 rounded-lg border text-xs font-medium flex items-center gap-1 transition bg-panel hover:bg-panel2 text-ink2 hover:text-ink border-line2" title={t('agents.mgr.promoteAgentTitle', undefined, 'Bu ajanın tanımını ajan havuzuna aktar')}>
                            <Globe className="w-3 h-3" />
                            <span>{t('agents.mgr.promoteLabelLong', undefined, 'Havuza aktar')}</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {agent.description && (
                      <p className="text-[11px] text-ink3 leading-relaxed line-clamp-2">
                        {agent.description}
                      </p>
                    )}

                    {agent.active_file && (
                      <div className="text-[10px] text-ink3 font-mono truncate flex items-center gap-1.5 bg-panel/90 px-2 py-1 rounded border border-line">
                        <Terminal className="w-3 h-3 text-ink3 shrink-0" />
                        <span className="truncate">{agent.active_file}</span>
                      </div>
                    )}

                    <div className="text-[10px] text-ink3 font-mono flex items-center justify-between border-t border-line pt-2">
                      <span className="flex items-center gap-1">
                        {t('agents.mgr.statusLabel', undefined, 'Status')}:
                        <strong className={
                          agent.status === 'WORKING' ? 'text-warn' :
                          agent.status === 'ERROR' ? 'text-err' : 'text-ink2'
                        }>
                          {agent.status}
                        </strong>
                      </span>
                      <span>
                        {t('agents.mgr.tokenLabel', undefined, 'Token')}: <strong className="text-ink">{agent.total_tokens.toLocaleString()}</strong>
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Ajan havuzu: şirket geneli tanımlar; projeye yalnızca istenince eklenir */}
          <div className="p-4 rounded-xl border border-line bg-sunk/60 space-y-3">
            <div>
              <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-2"><Globe className="w-4 h-4 text-ac" />{t('agents.mgr.poolTitle', undefined, 'Ajan havuzu')} ({pool.length})</h4>
              <p className="text-[11px] text-ink3 mt-0.5">{t('agents.mgr.poolDesc', undefined, 'Şirket geneli ajan tanımları. Projeye bağlı eklenirsen havuzdaki güncellemeleri alır (projeye özgü fark korunur); bağımsız kopya eklersen havuzdan kopar, tamamen bu projeye ait olur. Proje ajanını "Havuza aktar" ile havuza koyabilirsin.')}</p>
            </div>
            {pool.length === 0 && <div className="text-[11px] text-ink3">{t('agents.mgr.poolEmpty', undefined, 'Havuz boş. Bir proje ajanında "Havuza aktar"ı ya da yeni ajan eklerken "Ajan havuzuna da ekle"yi kullan.')}</div>}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {pool.map(p => (
                <div key={p.id} className="p-3 rounded-xl border border-line bg-panel space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold text-ink">{p.name}</span>
                    <span className="text-[10px] bg-panel2 text-ink2 px-1.5 rounded font-mono font-bold">{p.id}</span>
                    {p.in_project && <span className="text-[9px] bg-okd text-ok border border-ok/40 px-1.5 rounded font-mono">{t('agents.mgr.inThisProject', undefined, 'bu projede')}</span>}
                  </div>
                  <div className="text-[10px] text-ink3 font-mono">{p.role_base} · {(p.capabilities || []).join(' ')}</div>
                  {p.description && <p className="text-[11px] text-ink3 line-clamp-2">{p.description}</p>}
                  <div className="flex flex-wrap gap-1.5">
                    <button type="button" disabled={p.in_project} onClick={() => addFromPool(p, 'linked')} className="px-2 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 text-[11px] disabled:opacity-40">{t('agents.mgr.addLinked', undefined, 'Projeye ekle (bağlı)')}</button>
                    <button type="button" onClick={() => addFromPool(p, 'copy')} className="px-2 py-1 rounded-lg border border-line2 text-ink2 hover:text-ink text-[11px]">{t('agents.mgr.addCopy', undefined, 'Bağımsız kopya ekle')}</button>
                    <button type="button" onClick={() => void removeFromPool(p)} className="px-2 py-1 rounded-lg border border-line text-ink3 hover:text-err text-[11px] ml-auto">{t('agents.mgr.poolDelBtn', undefined, 'Havuzdan sil')}</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* GLOBAL STANDARDA TERFİ ONAY MODALI */}
      {showPromoteConfirm && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-fadeIn">
          <div className="bg-panel border border-warn/60 rounded-2xl max-w-md w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-warnd border border-warn/40 flex items-center justify-center text-warn">
                <Globe className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-ink">{t('agents.mgr.promoModalTitle', undefined, 'Global Şirket Standardına Terfi')}</h4>
                <p className="text-xs text-ink3">{t('agents.mgr.promoModalSub', undefined, 'Ekstra Güvenlik & Doğrulama Onayı')}</p>
              </div>
            </div>

            <div className="bg-sunk/80 border border-line rounded-xl p-3 text-xs text-ink2 space-y-2">
              <p>
                {t('agents.mgr.promoHead', undefined, 'Bu projedeki')} (<strong className="text-ac">.fs-workspace</strong>) {t('agents.mgr.promoTail', undefined, 'ajanın güncel davranış kuralları ve öğrendiği yeni yetenekler, şirketin ana şablonuna aktarılacak:')}
              </p>
              <div className="bg-panel p-2 rounded font-mono text-[11px] text-warn border border-warn/20">
                agents/prompts/{promptInfo?.parent_standard}
              </div>
              <p className="text-ink3 text-[11px]">
                🛡️ <strong>{t('agents.mgr.autoBackup', undefined, 'Otomatik Yedekleme:')}</strong> {t('agents.mgr.backupHead', undefined, 'Mevcut standart şablon')} <code className="text-ink2">agents/prompts/backup/</code> {t('agents.mgr.backupTail', undefined, 'altına tarihli olarak yedeklenecektir. Bundan sonra açılacak tüm yeni projeler bu yeni kuralları miras alacaktır.')}
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setShowPromoteConfirm(false)}
                disabled={isPromoting}
                className="px-4 py-2 bg-panel2 hover:bg-sunk text-ink2 rounded-lg text-xs font-medium transition"
              >
                {t('agents.mgr.giveUp', undefined, 'Vazgeç')}
              </button>
              <button
                type="button"
                onClick={handleConfirmPromoteGlobal}
                disabled={isPromoting}
                className="px-4 py-2 bg-warn hover:opacity-90 text-onac font-bold rounded-lg text-xs shadow-lg transition flex items-center gap-1.5"
              >
                {isPromoting ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    {t('agents.mgr.promoting', undefined, 'Terfi Ediliyor...')}
                  </>
                ) : (
                  <>
                    <Globe className="w-3.5 h-3.5" />
                    {t('agents.mgr.confirmPromote', undefined, 'Onayla ve Global Standart Yap')}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
