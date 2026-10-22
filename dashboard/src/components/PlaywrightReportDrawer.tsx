import React, { useState, useEffect } from 'react';
import { notify } from '../lib/dialog';
import { PlaywrightReport, TestUserProfile } from '../types/telemetry';
import { 
  X, 
  Play, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  Maximize2, 
  Terminal, 
  Image as ImageIcon,
  MonitorCheck,
  Sparkles,
  Shield,
  User,
  Edit3,
  CreditCard,
  ShieldAlert,
  Globe,
  Lock,
  Eye,
  EyeOff,
  Save,
  Trash2,
  Layers,
  Check
} from 'lucide-react';
import { api, DEFAULT_TARGET_URL } from '../config';
import { useI18n } from '../i18n';

interface PlaywrightReportDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  reports: PlaywrightReport[];
  testProfiles?: TestUserProfile[];
  onRunTest: (targetUrl?: string, scenario?: string, credentials?: any) => Promise<any>;
  onRunQaSuite?: (targetUrl?: string, credentials?: any, scenario?: string) => Promise<any>;
  onSaveProfile?: (profile: Partial<TestUserProfile>) => Promise<any>;
  onDeleteProfile?: (profileId: string) => Promise<any>;
}

export const PlaywrightReportDrawer: React.FC<PlaywrightReportDrawerProps> = ({
  isOpen,
  onClose,
  reports,
  testProfiles = [],
  onRunTest,
  onRunQaSuite,
  onSaveProfile,
  onDeleteProfile
}) => {
  const { t } = useI18n();
  const [selectedProfileId, setSelectedProfileId] = useState<string>('preset-admin');
  const [targetUrl, setTargetUrl] = useState<string>(DEFAULT_TARGET_URL);
  const [scenario, setScenario] = useState<string>(() => t('run.pw.defaultScenario', undefined, 'Kullanıcı Giriş & Arayüz Doğrulama'));
  const [username, setUsername] = useState<string>('admin@enterprise.local');
  const [password, setPassword] = useState<string>('');
  const [role, setRole] = useState<string>('ADMIN');
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [customProfileName, setCustomProfileName] = useState<string>('');
  
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [isSuiteRunning, setIsSuiteRunning] = useState<boolean>(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string>('');
  const [selectedImage, setSelectedImage] = useState<string | null>(null);

  // Profil değiştiğinde form alanlarını doldur
  const handleSelectProfile = (p: TestUserProfile) => {
    setSelectedProfileId(p.id);
    if (p.target_url) setTargetUrl(p.target_url);
    if (p.username) setUsername(p.username);
    // Şifre istemciye gelmez (has_password); boş bırakılırsa sunucu profil kaydındaki şifreyi kullanır
    setPassword(p.password || '');
    if (p.role) setRole(p.role);
    setScenario(t('run.pw.profileScenario', { name: p.name }, `${p.name} - Form & Arayüz Doğrulama`));
  };

  // İlk yüklemede veya profiller geldiğinde aktif olanı senkronize et
  useEffect(() => {
    if (testProfiles.length > 0 && !testProfiles.find(p => p.id === selectedProfileId)) {
      handleSelectProfile(testProfiles[0]);
    }
  }, [testProfiles]);

  if (!isOpen) return null;

  // Sadece Playwright E2E Testi Koştur
  const handleTriggerRun = async () => {
    setIsRunning(true);
    try {
      await onRunTest(targetUrl, scenario, {
        username,
        password: password || undefined,
        role,
        profile_id: selectedProfileId
      });
    } catch (err) {
      console.error(err);
      notify(t('run.pw.runErr', undefined, 'Playwright testi koşturulurken hata oluştu.'));
    } finally {
      setIsRunning(false);
    }
  };

  // Geliştirme Ajanları Olmadan SADECE Test Süitini (QA Lead + Playwright) Koştur
  const handleTriggerQaSuite = async () => {
    if (!onRunQaSuite) return;
    setIsSuiteRunning(true);
    try {
      await onRunQaSuite(targetUrl, {
        username,
        password: password || undefined,
        role,
        profile_id: selectedProfileId
      }, scenario);
    } catch (err) {
      console.error(err);
      notify(t('run.pw.suiteErr', undefined, 'QA Test süiti koşturulurken hata oluştu.'));
    } finally {
      setIsSuiteRunning(false);
    }
  };

  // Mevcut Profili Kaydet
  const handleSaveProfile = async () => {
    if (!onSaveProfile) return;
    try {
      const profileData: Partial<TestUserProfile> = {
        id: selectedProfileId.startsWith('preset-') ? undefined : selectedProfileId,
        name: customProfileName.trim() || t('run.pw.defaultProfileName', { role }, `${role} Test Kullanıcısı`),
        target_url: targetUrl,
        username,
        password,
        role,
        is_preset: false
      };
      await onSaveProfile(profileData);
      setCustomProfileName('');
      setSaveSuccessMsg(t('run.pw.profileSaved', undefined, '✓ Profil kaydedildi!'));
      setTimeout(() => setSaveSuccessMsg(''), 3000);
    } catch (err) {
      console.error(err);
      notify(t('run.pw.profileSaveErr', undefined, 'Profil kaydedilemedi.'));
    }
  };

  const latestReport = reports[0];

  const getProfileIcon = (roleName: string) => {
    switch (roleName.toUpperCase()) {
      case 'ADMIN':
        return <Shield className="w-3.5 h-3.5 text-err" />;
      case 'EDITOR':
        return <Edit3 className="w-3.5 h-3.5 text-warn" />;
      case 'FINANCE':
        return <CreditCard className="w-3.5 h-3.5 text-ok" />;
      case 'GUEST':
        return <ShieldAlert className="w-3.5 h-3.5 text-ac" />;
      default:
        return <User className="w-3.5 h-3.5 text-info" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md">
      <div className="bg-panel border border-line2 rounded-2xl w-full max-w-5xl max-h-[94vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
        {/* Modal Başlık */}
        <div className="px-6 py-4 bg-sunk border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-infod border border-info/40 flex items-center justify-center">
              <MonitorCheck className="w-5 h-5 text-info" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-ink tracking-wide">
                  {t('run.pw.title', undefined, 'Playwright E2E & Bağımsız Test Merkezi')}
                </h3>
                <span className="text-[10px] bg-infod text-info border border-info/40 px-2 py-0.5 rounded font-mono font-bold">
                  Chromium E2E + QA Lead
                </span>
              </div>
              <p className="text-xs text-ink3">
                {t('run.pw.subtitle', undefined, 'Hazır test kullanıcı şablonları, hedef web adresi yapılandırması ve canlı form testi')}
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

        {/* Modal İçerik */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* 1. BÖLÜM: Hazır Test Kullanıcı Şablonları */}
          <div className="p-4 bg-sunk/70 border border-line rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-info" />
                {t('run.pw.templates', undefined, 'Hazır Test Kullanıcı Şablonları (Tek Tıkla Seçin)')}
              </span>
              <span className="text-[11px] text-ink3 font-mono">
                {t('run.pw.templatesN', { n: testProfiles.length }, `${testProfiles.length} Kayıtlı Şablon`)}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
              {testProfiles.map(p => {
                const isSelected = selectedProfileId === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => handleSelectProfile(p)}
                    className={`p-2.5 rounded-lg border text-left transition relative flex flex-col justify-between ${
                      isSelected
                        ? 'bg-infod/40 border-info shadow-md shadow-panel'
                        : 'bg-panel/80 border-line hover:border-line2 hover:bg-panel2/60'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-ink truncate">
                          {getProfileIcon(p.role)}
                          {p.name.split('/')[0].trim()}
                        </span>
                        {isSelected && (
                          <span className="w-4 h-4 rounded-full bg-info flex items-center justify-center text-onac">
                            <Check className="w-2.5 h-2.5 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-ink3 truncate font-mono">
                        {p.username}
                      </p>
                    </div>

                    <div className="mt-2 flex items-center justify-between pt-1.5 border-t border-line/80">
                      <span className="text-[9px] bg-sunk px-1.5 py-0.5 rounded font-mono text-ink3">
                        {p.role}
                      </span>
                      {p.is_preset ? (
                        <span className="text-[9px] text-ink3 font-mono">Preset</span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (onDeleteProfile) onDeleteProfile(p.id);
                          }}
                          className="text-err hover:text-err p-0.5"
                          title={t('run.pw.delete', undefined, 'Sil')}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 2. BÖLÜM: Hedef Web Adresi & Kimlik Bilgileri Ayarları */}
          <div className="p-4 bg-sunk/70 border border-line rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-ac" />
                {t('run.pw.targetAndCreds', undefined, 'Hedef Web Adresi & Test Kimlik Bilgileri')}
              </span>
              {saveSuccessMsg && (
                <span className="text-xs text-ok font-semibold animate-pulse">
                  {saveSuccessMsg}
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              {/* Hedef Web Adresi (URL) */}
              <div className="md:col-span-2">
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.pw.targetUrl', undefined, 'Hedef Web Adresi (Test Edilecek URL)')}
                </label>
                <div className="relative">
                  <Globe className="w-3.5 h-3.5 text-ink3 absolute left-2.5 top-2.5" />
                  <input
                    type="text"
                    value={targetUrl}
                    onChange={e => setTargetUrl(e.target.value)}
                    placeholder={t('run.pw.targetUrlPh', undefined, 'Örn: http://127.0.0.1:8099 veya http://localhost:3000/login')}
                    className="w-full bg-panel border border-line2 rounded-lg pl-8 pr-3 py-2 text-xs text-ink focus:border-info focus:outline-none font-mono"
                  />
                </div>
              </div>

              {/* Kullanıcı Adı / E-posta */}
              <div className="md:col-span-1">
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.pw.username', undefined, 'Kullanıcı Adı / E-posta')}
                </label>
                <div className="relative">
                  <User className="w-3.5 h-3.5 text-ink3 absolute left-2.5 top-2.5" />
                  <input
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="admin@test.com"
                    className="w-full bg-panel border border-line2 rounded-lg pl-8 pr-3 py-2 text-xs text-ink focus:border-info focus:outline-none font-mono"
                  />
                </div>
              </div>

              {/* Şifre */}
              <div className="md:col-span-1">
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.pw.password', undefined, 'Şifre')}
                </label>
                <div className="relative">
                  <Lock className="w-3.5 h-3.5 text-ink3 absolute left-2.5 top-2.5" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full bg-panel border border-line2 rounded-lg pl-8 pr-8 py-2 text-xs text-ink focus:border-info focus:outline-none font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-2.5 text-ink3 hover:text-ink2"
                  >
                    {showPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-1">
              {/* Test Senaryosu */}
              <div className="md:col-span-2">
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.pw.scenario', undefined, 'Test Senaryosu / Açıklaması')}
                </label>
                <input
                  type="text"
                  value={scenario}
                  onChange={e => setScenario(e.target.value)}
                  className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink focus:border-info focus:outline-none"
                />
              </div>

              {/* Rol */}
              <div className="md:col-span-1">
                <label className="block text-[11px] font-medium text-ink3 mb-1">
                  {t('run.pw.roleLevel', undefined, 'Rol / Yetki Seviyesi')}
                </label>
                <select
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  className="w-full bg-panel border border-line2 rounded-lg px-3 py-2 text-xs text-ink focus:border-info focus:outline-none font-mono"
                >
                  <option value="ADMIN">{t('run.pw.roleAdmin', undefined, 'ADMIN (Tam Yetki)')}</option>
                  <option value="USER">{t('run.pw.roleUser', undefined, 'USER (Standart Müşteri)')}</option>
                  <option value="EDITOR">{t('run.pw.roleEditor', undefined, 'EDITOR (İçerik & Mağaza)')}</option>
                  <option value="FINANCE">{t('run.pw.roleFinance', undefined, 'FINANCE (Finans & Fatura)')}</option>
                  <option value="GUEST">{t('run.pw.roleGuest', undefined, 'GUEST (Negatif / Saldırı Testi)')}</option>
                </select>
              </div>

              {/* Yeni Şablon Kaydetme Butonu */}
              <div className="md:col-span-1 flex items-end">
                <button
                  type="button"
                  onClick={handleSaveProfile}
                  className="w-full py-2 px-3 bg-panel2 hover:bg-sunk text-ink border border-line2 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition"
                >
                  <Save className="w-3.5 h-3.5 text-ac" />
                  {t('run.pw.saveAsTemplate', undefined, 'Şablon Olarak Kaydet')}
                </button>
              </div>
            </div>

            {/* Çalıştırma Aksiyon Butonları (İki Seçenek) */}
            <div className="pt-3 border-t border-line/80 flex flex-wrap items-center justify-end gap-3">
              {/* Aksiyon 1: Yalnızca Playwright E2E */}
              <button
                onClick={handleTriggerRun}
                disabled={isRunning || isSuiteRunning}
                className={`px-4 py-2.5 rounded-lg text-xs font-semibold text-ink flex items-center gap-2 shadow-lg transition whitespace-nowrap ${
                  isRunning
                    ? 'bg-infod/60 text-info cursor-not-allowed border border-info animate-pulse'
                    : 'bg-info hover:opacity-90 border border-info/30'
                }`}
              >
                <Play className={`w-3.5 h-3.5 ${isRunning ? 'animate-spin' : 'fill-current'}`} />
                {isRunning ? t('run.pw.running', undefined, 'Tarayıcı Açılıyor & Form Dolduruluyor...') : t('run.pw.runE2E', undefined, '🚀 Playwright E2E Testini Koştur')}
              </button>

              {/* Aksiyon 2: Geliştirme Ajanları Olmadan SADECE Test Süitini Koştur (QA Lead + Playwright E2E) */}
              <button
                onClick={handleTriggerQaSuite}
                disabled={isRunning || isSuiteRunning}
                className={`px-4 py-2.5 rounded-lg text-xs font-bold text-ink flex items-center gap-2 shadow-lg transition whitespace-nowrap ${
                  isSuiteRunning
                    ? 'bg-acd/60 text-ac cursor-not-allowed border border-ac animate-pulse'
                    : 'bg-ac hover:opacity-90 border border-ac/30'
                }`}
                title={t('run.pw.suiteTitle', undefined, "Geliştirme ajanları çalışmadan doğrudan Madde 6 (QA) ve Madde 7 (Playwright)'yi koşturur")}
              >
                <Layers className={`w-3.5 h-3.5 ${isSuiteRunning ? 'animate-spin' : ''}`} />
                {isSuiteRunning ? t('run.pw.suiteRunning', undefined, 'QA & Tarayıcı Test Ediyor...') : t('run.pw.runSuite', undefined, '🧪 Sadece Test Süitini Koştur (QA Lead + E2E)')}
              </button>
            </div>
          </div>

          {/* 3. BÖLÜM: En Son Test Raporu & Kanıt Ekran Görüntüleri */}
          {latestReport ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider flex items-center gap-2">
                  <ImageIcon className="w-4 h-4 text-info" />
                  {t('run.pw.latestResult', undefined, 'Son Test Sonucu & Ekran Görüntüleri')} ({latestReport.id})
                </h4>
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-[11px] font-bold ${
                    latestReport.status === 'PASSED'
                      ? 'bg-okd text-ok border border-ok/40'
                      : 'bg-errd text-err border border-err/40'
                  }`}>
                    {latestReport.status === 'PASSED' ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                    {latestReport.status}
                  </span>
                  <span className="text-[11px] text-ink3 font-mono flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {latestReport.duration_ms ? `${(latestReport.duration_ms / 1000).toFixed(2)}s` : ''}
                  </span>
                </div>
              </div>

              {/* Ekran Görüntüleri Galerisi */}
              {latestReport.screenshots && latestReport.screenshots.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {latestReport.screenshots.map((shot, idx) => (
                    <div
                      key={idx}
                      onClick={() => setSelectedImage(api(shot))}
                      className="group relative bg-sunk border border-line hover:border-info rounded-xl overflow-hidden cursor-pointer shadow-lg transition"
                    >
                      <div className="h-44 bg-panel flex items-center justify-center overflow-hidden">
                        <img
                          src={api(shot)}
                          alt={`Screenshot ${idx + 1}`}
                          className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                        />
                      </div>
                      <div className="p-2.5 bg-sunk flex items-center justify-between border-t border-line/80">
                        <span className="text-[11px] font-mono text-ink2 truncate">
                          {t('run.pw.stepWord', undefined, 'Adım')} {idx + 1}: {shot.split('/').pop()}
                        </span>
                        <Maximize2 className="w-3.5 h-3.5 text-ink3 group-hover:text-info transition" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-6 text-center border border-dashed border-line rounded-xl text-ink3 text-xs">
                  {t('run.pw.noShots', undefined, 'Bu test koşusunda kaydedilmiş ekran görüntüsü yok.')}
                </div>
              )}

              {/* Terminal Log Çıktısı */}
              {latestReport.logs && latestReport.logs.length > 0 && (
                <div className="bg-black/90 rounded-xl p-3.5 border border-line font-mono text-[11px] text-ink2 space-y-1 max-h-48 overflow-y-auto">
                  <div className="flex items-center gap-1.5 text-ink3 text-[10px] pb-1 border-b border-line uppercase tracking-wider">
                    <Terminal className="w-3 h-3" />
                    Playwright Engine Console Logs
                  </div>
                  {latestReport.logs.map((log, idx) => (
                    <div key={idx} className="leading-relaxed">
                      {log}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="p-10 text-center border border-dashed border-line rounded-xl text-ink3 text-xs">
              {t('run.pw.noTestYet', undefined, 'Henüz bir E2E Playwright testi koşturulmadı. Yukarıdaki şablonlardan birini seçip test butonuna basarak canlı tarayıcı testini başlatabilirsiniz.')}
            </div>
          )}

          {/* Geçmiş Koşular */}
          {reports.length > 1 && (
            <div>
              <h4 className="text-xs font-bold text-ink2 uppercase tracking-wider mb-2">
                {t('run.pw.history', undefined, 'Geçmiş E2E Test Koşuları')} ({reports.length})
              </h4>
              <div className="space-y-2">
                {reports.slice(1).map(r => (
                  <div
                    key={r.id}
                    className="p-3 bg-sunk/70 border border-line rounded-lg flex items-center justify-between text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${r.status === 'PASSED' ? 'bg-ok' : 'bg-err'}`} />
                      <span className="font-mono text-ink2">{r.id}</span>
                      <span className="text-ink3 truncate max-w-xs">{r.scenario}</span>
                    </div>
                    <div className="flex items-center gap-3 text-ink3 text-[11px] font-mono">
                      <span>{r.screenshots?.length || 0} {t('run.pw.images', undefined, 'Görsel')}</span>
                      <span>{new Date(r.timestamp).toLocaleTimeString('tr-TR')}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Ekran Görüntüsü Büyütme Modalı */}
      {selectedImage && (
        <div
          onClick={() => setSelectedImage(null)}
          className="fixed inset-0 z-60 bg-black/95 flex items-center justify-center p-4 cursor-pointer"
        >
          <div className="relative max-w-5xl max-h-[90vh] overflow-hidden rounded-xl border border-line2 shadow-2xl">
            <img src={selectedImage} alt="Full Screenshot" className="w-full h-auto object-contain" />
            <button
              onClick={() => setSelectedImage(null)}
              className="absolute top-3 right-3 bg-black/80 hover:bg-black text-ink p-2 rounded-full border border-line2"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
