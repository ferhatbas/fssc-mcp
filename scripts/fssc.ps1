<#
.SYNOPSIS
  FS-SC (fssc-visual-observer) çalıştırma, test ve bakım betiği — Windows PowerShell 5.1 uyumlu.

.DESCRIPTION
  Tek giriş noktası: sunucuyu başlat/durdur, durumunu gör, dashboard'u derle, testleri koş, Claude Desktop'a kaydet,
  çevrimdışı (şablon motoru) uçtan uca kuru koşu yap, üretilen uygulamayı ve konteynerlerini test et.

  Kullanım:  powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 <komut> [seçenekler]

  Komutlar:
    start        [-Port 8099] [-Background] [-NoBrowser]   Web sunucusunu (API + dashboard + WebSocket) başlatır
    stop         [-Port 8099]                              Bu porttaki FS-SC sunucusunu durdurur (yabancı süreçlere dokunmaz)
    status       [-Port 8099]                              Sunucu / aktif proje / koşu / bağlı istemci özeti; port çakışmasını bildirir
    install                                                pip (dev), Playwright Chromium ve dashboard npm bağımlılıklarını kurar
    build                                                  Dashboard'u derler (dashboard/dist → sunucu bunu servis eder)
    dev                                                    Vite geliştirme sunucusu (http://127.0.0.1:5173, /api ve /ws proxy'lenir)
    test         [-Lifecycle] [-K <ifade>]                 pytest (tümü, yalnızca yaşam döngüsü testleri veya -k süzgeci)
    register-desktop [-Restart]                            MCP sunucusunu Claude Desktop'a kaydeder (OBSERVER_PORT = -Port)
    set-port     -Port <n>                                 .mcp.json içindeki OBSERVER_PORT değerini değiştirir
    migrate-docs -ProjectId <id> [-Apply]   docs/ -> FS-docs/ göçü (varsayılan: kuru önizleme; yalnızca FS-SC'nin bilinen dosyaları)
    dry-run      [-Port 8099] [-ProjectDir <klasör>] [-Steps 1,2,3]   Şablon motoruyla tam döngü kuru koşusu (LLM yok)
    dry-run      -Sprints <n> [-MaxTasks 3] [-NotesFile <dosya>] [-Strict]   Sprint kipi kuru koşusu: not yüklemesiyle başlar, n sprinte kadar zincirlenir (-Strict: sıkı DoD)
                 (sunucu FSSC_DRY_RUN=1 ile; bilerek başarısız görev için FSSC_DRY_RUN_FAIL_TASK=<sprint no>; 2 = prompt geri alma denemesi)
    app-test     -ProjectDir <klasör>                      Üretilen uygulamada kurulum/lint/build/test komutlarını koşar
    app-run      -ProjectDir <klasör>                      Üretilen uygulamayı 'run' komutuyla başlatır ve sağlık adresini açar
    compose      -ProjectDir <klasör> [-Action up|down|ps|logs|build]   Üretilen uygulamanın konteynerleri (docker compose)
    e2e          [-Port 8099] -Url <http://...> [-ProfileId <id>]       Çalışan bir adrese karşı Playwright E2E koşturur
    runner       status|prompt [-Port 8099]                Runner'ın son görülmesi ve son sonucu | zamanlanmış görev talimatı (§9.3)
    sprint       status [-Port 8099]                       Aktif sprint, harcama/bütçe, engel nedeni, açık sorular
    help                                                   Bu yardım

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 start -Port 8090 -Background
  powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 dry-run -Port 8090
  powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 compose -ProjectDir D:\projects\my-app -Action up
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('start', 'stop', 'status', 'install', 'build', 'dev', 'test', 'register-desktop', 'set-port', 'dry-run', 'migrate-docs', 'app-test', 'app-run', 'compose', 'e2e', 'runner', 'sprint', 'help')]
  [string]$Command = 'help',
  [Parameter(Position = 1)]
  [string]$Sub = '',
  [int]$Port = 0,
  [string]$ProjectDir = '',
  [string]$Steps = '',
  [string]$Url = '',
  [string]$ProfileId = '',
  [ValidateSet('up', 'down', 'ps', 'logs', 'build')]
  [string]$Action = 'up',
  [string]$K = '',
  [switch]$Lifecycle,
  [switch]$Background,
  [switch]$NoBrowser,
  [switch]$Restart,
  [switch]$Apply,
  [switch]$Strict,
  [string]$ProjectId = '',
  [int]$Sprints = 0,
  [int]$MaxTasks = 3,
  [string]$NotesFile = ''
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Dashboard = Join-Path $Root 'dashboard'
$McpJson = Join-Path $Root '.mcp.json'

# --------------------------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------------------------
function Write-Info($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[X] $msg" -ForegroundColor Red }

function Get-DefaultPort {
  # .mcp.json → OBSERVER_PORT, yoksa ortam değişkeni, yoksa 8099
  if ($Port -gt 0) { return $Port }
  try {
    $cfg = Get-Content $McpJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $p = $cfg.mcpServers.'fssc-visual-observer'.env.OBSERVER_PORT
    if ($p) { return [int]$p }
  } catch {}
  if ($env:OBSERVER_PORT) { return [int]$env:OBSERVER_PORT }
  return 8099
}

function Get-Python {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return 'py' }
  throw 'python bulunamadı. Python 3.12+ kurun ve PATH''e ekleyin.'
}

function Invoke-Native {
  # Yerel komutu çalıştırır; çıkış kodunu döner (stderr yakalanmaz, doğrudan akar)
  param([string]$Exe, [string[]]$Arguments, [string]$Cwd = $Root)
  Push-Location $Cwd
  try {
    & $Exe @Arguments | Out-Host
    return $LASTEXITCODE
  } finally { Pop-Location }
}

function Get-ListenerPids([int]$p) {
  try {
    return @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique)
  } catch { return @() }
}

function Get-ProcessCommandLine([int]$processId) {
  try { return (Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop).CommandLine } catch { return '' }
}

function Test-FsscServer([int]$p) {
  # Porttaki sunucu FS-SC mi? (/api/state → agents + active_project döner)
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$p/api/state" -TimeoutSec 4 -ErrorAction Stop
    $state = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json
    if ($null -ne $state.agents -and $null -ne $state.active_project) { return $state }
    return $null
  } catch { return $null }
}

function Show-PortConflict([int]$p) {
  $pids = Get-ListenerPids $p
  if ($pids.Count -eq 0) { return }
  Write-Warn2 "Port $p başka bir uygulama tarafından kullanılıyor; FS-SC sunucusu değil:"
  foreach ($procId in $pids) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { '?' }
    Write-Host ("     pid={0} {1}" -f $procId, $name)
  }
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if ($docker) {
    try {
      $rows = & docker ps --format '{{.Names}}  {{.Ports}}' 2>$null
      $hits = @($rows | Where-Object { $_ -match "[:\s]$p->" })
      if ($hits.Count -gt 0) {
        Write-Warn2 'Bu portu yayınlayan Docker konteyner(ler)i:'
        $hits | ForEach-Object { Write-Host "     $_" }
      }
    } catch {}
  }
  Write-Warn2 "Çözüm: konteyneri durdurun ya da FS-SC'yi başka portta çalıştırın:"
  Write-Host "     scripts\fssc.ps1 set-port -Port 8090      (.mcp.json güncellenir; Claude Code için yeni oturum gerekir)"
  Write-Host "     scripts\fssc.ps1 start -Port 8090 -Background"
  Write-Host "     scripts\fssc.ps1 register-desktop -Port 8090 -Restart   (Claude Desktop kullanıyorsanız)"
}

function Invoke-Api {
  # Windows PowerShell 5.1 charset'siz JSON'u ISO-8859-1 sanır; gövdeyi ham baytlardan UTF-8 olarak çözüyoruz
  param([string]$Method, [int]$p, [string]$Path, $Body = $null)
  $uri = "http://127.0.0.1:$p$Path"
  if ($null -ne $Body) {
    $json = $Body | ConvertTo-Json -Depth 8 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $uri -Body $bytes -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
  } else {
    $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $uri -TimeoutSec 120
  }
  $text = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
  return ($text | ConvertFrom-Json)
}

function Read-ProjectVerification([string]$dir) {
  # .fs-workspace/settings.json → settings.verification (mimar/DevOps/kullanıcı komutları)
  $file = Join-Path $dir '.fs-workspace\settings.json'
  if (Test-Path $file) {
    try {
      $s = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($s.settings -and $s.settings.verification) { return $s.settings.verification }
      if ($s.verification) { return $s.verification }
    } catch {}
  }
  return $null
}

function Get-InferredCommands([string]$dir) {
  $py = Get-Python
  $cmds = @{}
  if (Test-Path (Join-Path $dir 'requirements.txt')) {
    $cmds.install = "$py -m pip install -q -r requirements.txt"
    if ((Test-Path (Join-Path $dir 'tests')) -or (Get-ChildItem $dir -Filter 'test_*.py' -ErrorAction SilentlyContinue)) {
      $cmds.test = "$py -m pytest -q"
    }
  }
  if (Test-Path (Join-Path $dir 'package.json')) {
    $cmds.install = 'npm install --no-audit --no-fund'
    try {
      $pkg = Get-Content (Join-Path $dir 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($pkg.scripts.build) { $cmds.build = 'npm run build' }
      if ($pkg.scripts.test -and ($pkg.scripts.test -notmatch 'no test specified')) { $cmds.test = 'npm test' }
      if ($pkg.scripts.lint) { $cmds.lint = 'npm run lint' }
    } catch {}
  }
  if (Test-Path (Join-Path $dir 'composer.json')) {
    $cmds.install = 'composer install --no-interaction'
    if (Test-Path (Join-Path $dir 'phpunit.xml')) { $cmds.test = 'vendor\bin\phpunit' }
  }
  if (Test-Path (Join-Path $dir 'go.mod')) { $cmds.build = 'go build ./...'; $cmds.test = 'go test ./...' }
  return $cmds
}

function Invoke-ShellIn([string]$dir, [string]$cmd) {
  Write-Info "> $cmd   (cwd: $dir)"
  Push-Location $dir
  try {
    cmd /c $cmd | Out-Host
    return $LASTEXITCODE
  } finally { Pop-Location }
}

function Wait-Url([string]$u, [int]$timeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
      return [int]$r.StatusCode
    } catch {
      if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
      Start-Sleep -Seconds 1
    }
  }
  return 0
}

# --------------------------------------------------------------------------------------------
# Komutlar
# --------------------------------------------------------------------------------------------
function Cmd-Status {
  $p = Get-DefaultPort
  $state = Test-FsscServer $p
  if ($null -eq $state) {
    $pids = Get-ListenerPids $p
    if ($pids.Count -eq 0) { Write-Warn2 "Port $p dinlenmiyor: FS-SC sunucusu çalışmıyor. Başlatın: scripts\fssc.ps1 start -Port $p -Background" }
    else { Show-PortConflict $p }
    return
  }
  Write-Ok "FS-SC sunucusu çalışıyor: http://127.0.0.1:$p"
  $proj = $state.active_project
  Write-Host ("     Aktif proje : {0}  ({1})" -f $proj.name, $proj.path)
  Write-Host ("     Motor/onay  : {0} / {1}  · doğrulama={2} commit={3} backlog={4}" -f $state.settings.execution_engine, $state.settings.approval_mode, $state.settings.auto_verify, $state.settings.auto_commit, $state.settings.auto_backlog)
  if ($state.settings.verification) { Write-Host ("     Komutlar    : {0}" -f (($state.settings.verification | ConvertTo-Json -Compress))) }
  if ($state.active_run) {
    $r = $state.active_run
    Write-Host ("     Aktif koşu  : {0} {1} adım {2}/{3} (şu an #{4})" -f $r.run_id, $r.status, $r.progress.done, $r.progress.total, $r.progress.current_order)
  } else { Write-Host '     Aktif koşu  : yok' }
  if ($state.connected_clients -and $state.connected_clients.Count -gt 0) {
    foreach ($c in $state.connected_clients) { Write-Host ("     İstemci     : {0} v{1} · son görülme {2} · {3} çağrı" -f $c.name, $c.version, $c.last_seen, $c.calls) }
  } else { Write-Host '     İstemci     : henüz bağlanmadı (Claude Code/Desktop ilk araç çağrısında görünür)' }
  Write-Host ("     Jira        : {0} madde · şartname: {1} · koşu geçmişi: {2}" -f $state.jira_issues.Count, $state.uploaded_specs.Count, $state.runs.Count)
}

function Cmd-Start {
  $p = Get-DefaultPort
  $py = Get-Python
  if (Test-FsscServer $p) { Write-Ok "FS-SC sunucusu zaten çalışıyor: http://127.0.0.1:$p"; return }
  if ((Get-ListenerPids $p).Count -gt 0) { Show-PortConflict $p; exit 2 }
  if (-not (Test-Path (Join-Path $Dashboard 'dist\index.html'))) {
    Write-Warn2 'dashboard/dist yok; sunucu arayüzü servis edemez. Önce: scripts\fssc.ps1 build'
  }
  $env:OBSERVER_PORT = "$p"
  $env:PYTHONIOENCODING = 'utf-8'
  $env:PYTHONUNBUFFERED = '1'
  if ($Background) {
    $proc = Start-Process -FilePath $py -ArgumentList '-m', 'server.main', '--mode', 'web' -WorkingDirectory $Root -PassThru -WindowStyle Minimized
    Write-Info "Sunucu arka planda başlatıldı (pid=$($proc.Id)); hazır olması bekleniyor..."
    $code = Wait-Url "http://127.0.0.1:$p/api/state" 40
    if ($code -eq 200) {
      Write-Ok "Hazır: http://127.0.0.1:$p"
      if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$p" }
    } else { Write-Err 'Sunucu 40 sn içinde yanıt vermedi; pencereyi/konsolu kontrol edin.' }
    return
  }
  Write-Info "Sunucu ön planda başlatılıyor: http://127.0.0.1:$p  (durdurmak için Ctrl+C)"
  if (-not $NoBrowser) { Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList "http://127.0.0.1:$p" | Out-Null }
  Invoke-Native $py @('-m', 'server.main', '--mode', 'web') | Out-Null
}

function Cmd-Stop {
  $p = Get-DefaultPort
  $pids = Get-ListenerPids $p
  if ($pids.Count -eq 0) { Write-Info "Port $p dinlenmiyor; durdurulacak sunucu yok."; return }
  $stopped = 0
  foreach ($procId in $pids) {
    $cl = Get-ProcessCommandLine $procId
    if ($cl -match 'server\.main') {
      Stop-Process -Id $procId -Force -Confirm:$false
      Write-Ok "FS-SC sunucusu durduruldu (pid=$procId)"
      $stopped++
    } else {
      Write-Warn2 "pid=$procId FS-SC değil, dokunulmadı: $cl"
    }
  }
  if ($stopped -eq 0) { Show-PortConflict $p }
}

function Cmd-Install {
  $py = Get-Python
  Write-Info 'Python bağımlılıkları (requirements-dev.txt)...'
  $c = Invoke-Native $py @('-m', 'pip', 'install', '-q', '-r', 'requirements-dev.txt'); if ($c -ne 0) { throw 'pip install başarısız' }
  Write-Info 'Playwright Chromium...'
  Invoke-Native $py @('-m', 'playwright', 'install', 'chromium') | Out-Null
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Info 'Dashboard npm bağımlılıkları...'
    $c = Invoke-Native 'npm' @('install', '--no-audit', '--no-fund') $Dashboard; if ($c -ne 0) { throw 'npm install başarısız' }
  } else { Write-Warn2 'npm bulunamadı; dashboard derlemesi için Node.js 20+ kurun.' }
  Write-Ok 'Kurulum tamam. Sonraki adım: scripts\fssc.ps1 build  →  scripts\fssc.ps1 start'
}

function Cmd-Build {
  if (-not (Test-Path (Join-Path $Dashboard 'node_modules'))) { Invoke-Native 'npm' @('install', '--no-audit', '--no-fund') $Dashboard | Out-Null }
  $c = Invoke-Native 'npm' @('run', 'build') $Dashboard
  if ($c -ne 0) { throw 'Dashboard derlemesi başarısız' }
  Write-Ok 'dashboard/dist güncellendi (çalışan sunucu yeni dosyaları anında servis eder; sayfayı yenileyin).'
}

function Cmd-Dev {
  if (-not (Test-Path (Join-Path $Dashboard 'node_modules'))) { Invoke-Native 'npm' @('install', '--no-audit', '--no-fund') $Dashboard | Out-Null }
  Write-Info 'Vite dev sunucusu: http://127.0.0.1:5173 (API/WS çağrıları 8099''e proxy''lenir; sunucu çalışıyor olmalı)'
  Invoke-Native 'npm' @('run', 'dev') $Dashboard | Out-Null
}

function Cmd-Test {
  $py = Get-Python
  $pytestArgs = @('-m', 'pytest', '-q')
  if ($Lifecycle) { $pytestArgs += 'tests/test_lifecycle.py' }
  if ($K) { $pytestArgs += @('-k', $K) }
  $c = Invoke-Native $py $pytestArgs
  if ($c -ne 0) { Write-Err "pytest çıkış kodu $c"; exit $c }
  Write-Ok 'Testler geçti.'
}

function Cmd-RegisterDesktop {
  $py = Get-Python
  $env:OBSERVER_PORT = "$(Get-DefaultPort)"
  $regArgs = @('scripts/register_claude_desktop.py')
  if ($Restart) { $regArgs += '--restart' }
  Invoke-Native $py $regArgs | Out-Null
}

function Cmd-SetPort {
  if ($Port -le 0) { throw 'Kullanım: set-port -Port <n>' }
  $raw = Get-Content $McpJson -Raw -Encoding UTF8
  $cfg = $raw | ConvertFrom-Json
  $cfg.mcpServers.'fssc-visual-observer'.env.OBSERVER_PORT = "$Port"
  $out = $cfg | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($McpJson, $out + "`n", (New-Object System.Text.UTF8Encoding($false)))
  Write-Ok ".mcp.json → OBSERVER_PORT=$Port. Claude Code'da YENİ oturum açın (mevcut oturum .mcp.json'ı yeniden okumaz)."
  Write-Info "Claude Desktop için: scripts\fssc.ps1 register-desktop -Port $Port -Restart"
  Write-Info "Sunucu: scripts\fssc.ps1 start -Port $Port -Background"
}

function Cmd-MigrateDocs {
  if (-not $ProjectId) { throw 'Kullanım: migrate-docs -ProjectId <id> [-Apply]' }
  $p = Get-DefaultPort
  if ($null -eq (Test-FsscServer $p)) { Write-Err "Port $p'de FS-SC sunucusu yok."; exit 2 }
  $res = Invoke-Api 'POST' $p "/api/projects/$ProjectId/migrate-docs" @{ apply = [bool]$Apply }
  if ($Apply) { Write-Ok 'Göç uygulandı.' } else { Write-Info 'KURU ÖNİZLEME (uygulamak için -Apply):' }
  foreach ($m in $res.moved) { Write-Host "   $m" }
  foreach ($c in $res.conflicts) { Write-Warn2 $c }
  if ($res.prompts_updated.Count -gt 0) { Write-Info ("Prompt kopyaları: " + ($res.prompts_updated -join ', ')) }
  Write-Info "Dokunulmayan (projenin kendi) dosya sayısı: $($res.untouched_files)"
}

function Cmd-SprintDryRun {
  # F3: yükleme ile başlayan sprint kipi kuru koşusu (düğme ve sabit adım listesi yok). Gereken: sunucu FSSC_DRY_RUN=1 ile başlatılmış olmalı.
  $p = Get-DefaultPort
  $state = Test-FsscServer $p
  if ($null -eq $state) { Write-Err "Port $p'de FS-SC sunucusu yok. Önce: scripts\fssc.ps1 start -Port $p -Background"; exit 2 }
  $tr = Invoke-Api 'GET' $p '/api/tech-requirements'
  if (-not $tr.dry_run_enabled) { Write-Err "Sunucu FSSC_DRY_RUN=1 olmadan çalışıyor; teknoloji kapısı kuru koşuda onaysız geçilemez."; exit 4 }
  if (-not $ProjectDir) { $ProjectDir = Join-Path $env:TEMP ("fssc_sprint_" + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
  New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null
  $ProjectDir = (Resolve-Path $ProjectDir).Path
  if ($state.active_run) { Write-Err "Zaten aktif bir koşu var ($($state.active_run.run_id))."; exit 3 }
  $prev = $state.settings
  $prevSprint = (Invoke-Api 'GET' $p '/api/settings/sprint').sprint
  $prevAuto = (Invoke-Api 'GET' $p '/api/settings/autonomy').autonomy
  Invoke-Api 'POST' $p '/api/settings/engine' @{ execution_engine = 'template'; approval_mode = 'auto'; pacing = 'instant'; auto_verify = $true; auto_commit = $true } | Out-Null
  Invoke-Api 'POST' $p '/api/settings/sprint' @{ enabled = $true; commit_approval = 'auto'; auto_chain = $true; max_tasks = $MaxTasks; max_sprints = $Sprints } | Out-Null
  # Sıfır bekleme (L3 davranışı): teknoloji dışı sorular önerilen cevapla DEFAULTED olur (VARSAYIM ADR'si)
  Invoke-Api 'POST' $p '/api/settings/autonomy' @{ question_timeout_s = 0; strict_dod = [bool]$Strict } | Out-Null
  $notes = "Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. Her işlem için denetim kaydı tutulmalı. API tarafı Python ile yazılsın, FastAPI olabilir. Veritabanı tercihen PostgreSQL. Teslim Docker ile yapılacak."
  if ($NotesFile -and (Test-Path $NotesFile)) { $notes = Get-Content $NotesFile -Raw -Encoding UTF8 }
  Write-Info "Kuru koşu hedefi: $ProjectDir · sprint sayısı üst sınırı: $Sprints · kapasite: $MaxTasks"
  # Yükleme yalnızca kasaya girer ve değerlendirmeyi kuyruğa alır; koşuyu hedef klasörle biz başlatırız (düğme/sabit liste yok)
  $tmp = Join-Path $env:TEMP "fssc_notes_$([guid]::NewGuid().ToString('N')).txt"
  [System.IO.File]::WriteAllText($tmp, $notes, (New-Object System.Text.UTF8Encoding($false)))
  try {
    & curl.exe -s -S -X POST "http://127.0.0.1:$p/api/specs/upload" -F "title=Kuru kosu notlari" -F "client_name=Kuru Kosu" -F "start_run=false" -F "meeting_notes=<$tmp;type=text/plain; charset=utf-8" | Out-Null
  } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
  $res = Invoke-Api 'POST' $p '/api/runs' @{ engine = 'template'; step_by_step = $false; project_dir = $ProjectDir; prompt = 'FS-SC sprint kuru koşusu' }
  $rid = $res.run.run_id
  Write-Info "Sprint koşusu başladı: $rid (mod=$($res.run.mode))"
  $t0 = Get-Date
  $run = $null
  while ($true) {
    Start-Sleep -Seconds 3
    $run = (Invoke-Api 'GET' $p "/api/runs/$rid").run
    $sp = (Invoke-Api 'GET' $p '/api/sprints').state
    Write-Host ("     {0}  adım {1}/{2}  sprint: {3}  ({4:n0} sn)" -f $run.status, $run.progress.done, $run.progress.total, $sp.current_sprint, ((Get-Date) - $t0).TotalSeconds)
    if ($run.is_terminal) { break }
    if (((Get-Date) - $t0).TotalMinutes -gt 30) { Write-Err 'Zaman aşımı (30 dk)'; break }
  }
  $st = (Invoke-Api 'GET' $p '/api/sprints').state
  Write-Host ''
  Write-Host ('{0,-7} {1,-12} {2,-9} {3,-10} {4,-9} {5}' -f 'Sprint', 'Durum', 'Taahhüt', 'Tamamlanan', 'Taşınan', 'Hedef')
  foreach ($s in $st.sprints) {
    $m = $s.metrics
    $c = if ($m) { $m.committed } else { $s.committed_issue_ids.Count }
    $d = if ($m) { $m.completed } else { '-' }
    $g = if ($s.goal.Length -gt 60) { $s.goal.Substring(0, 60) } else { $s.goal }
    Write-Host ('{0,-7} {1,-12} {2,-9} {3,-10} {4,-9} {5}' -f $s.sprint_number, $s.status, $c, $d, $s.carried_over.Count, $g)
    foreach ($co in $s.carried_over) { Write-Host ("         ↳ taşındı: {0} ({1}, {2}. kez)" -f $co.issue_id, $co.reason, $co.count) }
    if ($Strict) {
      $d = (Invoke-Api 'GET' $p "/api/sprints/$($s.sprint_number)").sprint.dod
      if ($d) { Write-Host ("         ↳ DoD: ok={0} · E2E {1} · konteyner {2} · mimar gözden geçirmesi {3} · PO kararları {4}" -f $d.ok, $d.e2e.status, $d.container.status, $d.arch_review.done, $d.po.decided) }
    }
  }
  Write-Host ''
  Write-Info "Proje durumu: $($st.project_status). Koşu: $($run.status) $($run.cancel_reason)"
  $mt = (Invoke-Api 'GET' $p '/api/meetings').meetings
  Write-Info ("Toplantı tutanağı: {0} ({1})" -f $mt.Count, (($mt | ForEach-Object { $_.type + '#' + $_.sprint }) -join ', '))
  $qs = (Invoke-Api 'GET' $p '/api/questions').questions
  foreach ($q in $qs) { Write-Host ("     {0} {1,-9} {2,-10} cevap={3} ({4}) {5}" -f $q.id, $q.category, $q.status, $q.answer, $q.answered_by, $q.adr_ref) }
  $lr = Invoke-Api 'GET' $p '/api/learning'
  foreach ($t in $lr.trend) { Write-Host ("     Öğrenme  S{0}: taahhüt {1} · ilk seferde geçme {2} · düzeltme turu {3} · reddedilen teslim {4}" -f $t.sprint, $t.committed, $t.first_pass_rate, $t.fix_rounds, $t.rejected_deliveries) }
  foreach ($a in $lr.retro_actions) { Write-Host ("     Retro    {0} {1,-8} {2,-9} {3}" -f $a.id, $a.type, $a.status, $a.detail) }
  foreach ($c in $lr.prompt_changes) { Write-Host ("     Prompt   {0} {1} {2}→{3}: {4}" -f $c.id, $c.agent, $c.prev_version, $c.new_version, $c.status) }
  $adr = (Invoke-Api 'GET' $p '/api/adr').adr
  Write-Info ("ADR: {0} ({1})" -f $adr.Count, (($adr | ForEach-Object { $_.number + ' ' + $_.status }) -join ', '))
  if (Test-Path (Join-Path $ProjectDir '.git')) { Write-Info 'git log:'; Push-Location $ProjectDir; try { git --no-pager log --oneline -n 12; git --no-pager tag } finally { Pop-Location } }
  Invoke-Api 'POST' $p '/api/settings/sprint' @{ enabled = [bool]$prevSprint.enabled; commit_approval = $prevSprint.commit_approval; auto_chain = [bool]$prevSprint.auto_chain; max_tasks = $prevSprint.max_tasks; max_sprints = $prevSprint.max_sprints } | Out-Null
  Invoke-Api 'POST' $p '/api/settings/autonomy' @{ question_timeout_s = $prevAuto.question_timeout_s; strict_dod = [bool]$prevAuto.strict_dod } | Out-Null
  Invoke-Api 'POST' $p '/api/settings/engine' @{ execution_engine = $prev.execution_engine; approval_mode = $prev.approval_mode; pacing = $prev.pacing } | Out-Null
  Write-Info 'Ayarlar geri alındı.'
}

function Cmd-Runner {
  $p = Get-DefaultPort
  if ($Sub -eq 'prompt') {
    @'
FS-SC ekibinin sıradaki işini yürüt. Yalnızca fssc-visual-observer MCP araçlarını
kullan; dosya düzenleme, komut çalıştırma.

0. get_runner_schedule çağır. Zamanlanmış görev araçların varsa (update_scheduled_task) bu görevin aralığını schedule.interval_minutes'a eşitle
   (duraklatılmışsa daha uzun, örn. 30 dk). Araç yoksa bu adımı atla.
1. claim_work çağır. Yanıt IDLE ya da BLOCKED ise nedenini tek satırla yaz ve bitir.
2. get_next_step çağır. Yanıttaki display_md metnini aynen yaz.
3. Adımı, verilen rol promptu ve bağlamla üret. Yalnızca bu bağlama dayan.
4. submit_step_result ile teslim et. Yanıttaki display_md metnini aynen yaz.
5. Yanıt NEXT ise 2. adıma dön. Başka bir durumda (SESSION_BOUNDARY, BLOCKED, WAITING_APPROVAL, RUN_COMPLETE) durumu tek satırla yaz ve bitir.

Kullanıcıya soru sorma. Sorunun yeri teslimdeki questions alanıdır.
'@ | Write-Host
    Write-Info 'Kurulum: Code sekmesi → Routines → New routine → Local; klasör: FS-SC deposunun kökü; izin kipi: Manual; aralık: pano → Başlat & Bağlan → Koşu bekçisi ekranındaki değer (varsayılan 10 dk, duraklatılmışken 30 dk; get_runner_schedule aracı da bunu söyler); Run now; yalnızca FS-SC araçlarına always allow; Keep computer awake.'
    return
  }
  $state = Test-FsscServer $p
  if ($null -eq $state) { Write-Err "Port $p'de FS-SC sunucusu yok."; exit 2 }
  $r = Invoke-Api 'GET' $p '/api/runner/status'
  $c = if ($r.client) { $r.client.name } else { '-' }
  Write-Host ("     Son görülme : {0} ({1})" -f $r.last_seen, $(if ($r.fresh) { 'güncel' } else { 'istemci bekleniyor' }))
  Write-Host ("     İstemci     : {0} · çağrı: {1} · son sonuç: {2}" -f $c, $r.claims, $(if ($r.last_result) { "$($r.last_result.status) $($r.last_result.reason)" } else { '-' }))
  Write-Host ("     Kira        : {0}" -f $(if ($r.lease) { "$($r.lease.run_id) → $($r.lease.expires_at)" } else { 'yok' }))
}

function Cmd-SprintStatus {
  $p = Get-DefaultPort
  $state = Test-FsscServer $p
  if ($null -eq $state) { Write-Err "Port $p'de FS-SC sunucusu yok."; exit 2 }
  $s = Invoke-Api 'GET' $p '/api/sprints/state'
  Write-Host ("     Proje       : {0} · seviye: {1}" -f $s.project_status, $s.level)
  if ($s.current_sprint) {
    $cs = $s.current_sprint
    Write-Host ("     Sprint {0}    : {1} · {2}" -f $cs.sprint_number, $cs.status, $cs.goal)
    if ($cs.blocked) { Write-Host ("     ENGEL       : {0} — {1}" -f $cs.blocked.reason, $cs.blocked.detail) }
  }
  if ($s.usage) { Write-Host ("     Harcama     : {0} dk / {1} · {2} token / {3} · {4} adım / {5}" -f $s.usage.active_min, $s.budget.max_active_min_per_sprint, $s.usage.tokens, $s.budget.max_tokens_per_sprint, $s.usage.steps, $s.budget.max_steps_per_sprint) }
  $q = Invoke-Api 'GET' $p '/api/questions?status=OPEN'
  Write-Host ("     Açık soru   : {0} (engelleyici: {1})" -f $q.questions.Count, $q.open_blocking.Count)
}

function Cmd-DryRun {
  $p = Get-DefaultPort
  $state = Test-FsscServer $p
  if ($null -eq $state) { Write-Err "Port $p'de FS-SC sunucusu yok. Önce: scripts\fssc.ps1 start -Port $p -Background"; Show-PortConflict $p; exit 2 }
  if (-not $ProjectDir) { $ProjectDir = Join-Path $env:TEMP ("fssc_dry_" + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
  New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null
  $ProjectDir = (Resolve-Path $ProjectDir).Path
  Write-Info "Kuru koşu hedefi: $ProjectDir (aktif projenin Jira/ayar durumu kullanılır; dosyalar BU klasöre yazılır)"
  # F2: teknoloji kapısı hiçbir modda atlanmaz; kuru koşu yalnızca sunucu FSSC_DRY_RUN=1 ile başlatıldıysa yönetici onayını simüle eder
  $tr = Invoke-Api 'GET' $p '/api/tech-requirements'
  if (-not $tr.dry_run_enabled) { Write-Err "Sunucu FSSC_DRY_RUN=1 olmadan çalışıyor; teknoloji kapısı kuru koşuda onaysız geçilemez. Sunucuyu `$env:FSSC_DRY_RUN='1'` ile yeniden başlatın."; exit 4 }
  if ($state.active_run) { Write-Err "Zaten aktif bir koşu var ($($state.active_run.run_id)); önce bitmesini bekleyin ya da dashboard'dan iptal edin."; exit 3 }

  $prev = $state.settings
  Invoke-Api 'POST' $p '/api/settings/engine' @{ execution_engine = 'template'; approval_mode = 'auto'; pacing = 'instant'; auto_backlog = $true; auto_verify = $true; auto_commit = $true } | Out-Null
  $stepList = @()
  if ($Steps) { $stepList = @($Steps -split ',' | ForEach-Object { [int]$_.Trim() }) }
  $body = @{ engine = 'template'; step_by_step = $false; project_dir = $ProjectDir; prompt = 'FS-SC kuru koşu' }
  if ($stepList.Count -gt 0) { $body.steps = $stepList }
  $res = Invoke-Api 'POST' $p '/api/runs' $body
  $rid = $res.run.run_id
  Write-Info "Koşu başladı: $rid — ilerleme için dashboard'u izleyin (http://127.0.0.1:$p)"
  $t0 = Get-Date
  $run = $null
  while ($true) {
    Start-Sleep -Seconds 2
    $run = (Invoke-Api 'GET' $p "/api/runs/$rid").run
    Write-Host ("     {0}  adım {1}/{2}  şu an #{3}  ({4:n0} sn)" -f $run.status, $run.progress.done, $run.progress.total, $run.progress.current_order, ((Get-Date) - $t0).TotalSeconds)
    if ($run.is_terminal) { break }
    if (((Get-Date) - $t0).TotalMinutes -gt 20) { Write-Err 'Zaman aşımı (20 dk)'; break }
  }
  Write-Host ''
  Write-Host ('{0,-5} {1,-6} {2,-4} {3,-13} {4,-6} {5,-8} {6,-8} {7}' -f 'Adım', 'Tür', 'Düz', 'Ajan', 'Durum', 'Doğrula', 'Commit', 'Özet')
  foreach ($s in $run.steps) {
    $v = '-'; if ($s.verification) { $v = $s.verification.status }
    $c = '-'; if ($s.commit) { $c = $s.commit }
    $sum = ''; if ($s.summary) { $sum = $s.summary.Substring(0, [Math]::Min(70, $s.summary.Length)) }
    Write-Host ('#{0,-4} {1,-6} {2,-4} {3,-13} {4,-6} {5,-8} {6,-8} {7}' -f $s.order, $s.kind, $s.fix_round, $s.role, $s.status, $v, $c, $sum)
  }
  Write-Host ''
  if ($run.status -eq 'COMPLETED') { Write-Ok "Kuru koşu tamamlandı: $($run.steps.Count) adım. Üretilen proje: $ProjectDir" } else { Write-Err "Koşu $($run.status) ile bitti: $($run.cancel_reason)" }
  if (Test-Path (Join-Path $ProjectDir '.git')) {
    Write-Info 'git log:'
    Push-Location $ProjectDir; try { git --no-pager log --oneline -n 12 } finally { Pop-Location }
  }
  # Önceki motor/onay ayarını geri al (doğrulama/commit anahtarlarına dokunma)
  Invoke-Api 'POST' $p '/api/settings/engine' @{ execution_engine = $prev.execution_engine; approval_mode = $prev.approval_mode; pacing = $prev.pacing } | Out-Null
  Write-Info "Ayarlar geri alındı (motor=$($prev.execution_engine), onay=$($prev.approval_mode)). Sonraki: scripts\fssc.ps1 app-test -ProjectDir `"$ProjectDir`""
}

function Resolve-ProjectDir {
  if (-not $ProjectDir) { throw 'Bu komut -ProjectDir <üretilen proje klasörü> ister.' }
  if (-not (Test-Path $ProjectDir)) { throw "Klasör yok: $ProjectDir" }
  return (Resolve-Path $ProjectDir).Path
}

function Cmd-AppTest {
  $dir = Resolve-ProjectDir
  $cmds = Read-ProjectVerification $dir
  $source = 'ayarlar (.fs-workspace/settings.json → verification)'
  if ($null -eq $cmds) { $cmds = Get-InferredCommands $dir; $source = 'manifestlerden çıkarsandı' }
  Write-Info "Komut kaynağı: $source"
  $failed = $false
  foreach ($name in @('install', 'lint', 'build', 'test')) {
    $cmd = $null
    if ($cmds -is [hashtable]) { $cmd = $cmds[$name] } else { $cmd = $cmds.$name }
    if (-not $cmd) { continue }
    $code = Invoke-ShellIn $dir $cmd
    if ($code -eq 0) { Write-Ok "$name geçti" }
    elseif ($name -eq 'test' -and $code -eq 5) { Write-Warn2 'test: hiç test toplanmadı (pytest 5) — atlandı' }
    else { Write-Err "$name başarısız (çıkış kodu $code)"; $failed = $true; break }
  }
  if ($failed) { exit 1 }
  Write-Ok 'Uygulama doğrulaması tamam.'
}

function Cmd-AppRun {
  $dir = Resolve-ProjectDir
  $cmds = Read-ProjectVerification $dir
  $run = $null; $health = $null
  if ($cmds) { $run = $cmds.run; $health = $cmds.health_url; if (-not $health) { $health = $cmds.app_url } }
  if (-not $run) { throw 'Ayarlarda run komutu yok (.fs-workspace/settings.json → verification.run). Dashboard model penceresi 0c''den girin.' }
  Write-Info "Başlatılıyor: $run"
  Push-Location $dir
  try { $proc = Start-Process -FilePath 'cmd' -ArgumentList '/c', $run -WorkingDirectory $dir -PassThru } finally { Pop-Location }
  if ($health) {
    $code = Wait-Url $health 90
    if ($code -gt 0) { Write-Ok "Sağlık adresi yanıt verdi: $health (HTTP $code)"; Start-Process $health }
    else { Write-Err "Uygulama 90 sn içinde $health adresinde yanıt vermedi." }
  }
  Write-Info "Uygulama ayrı pencerede çalışıyor (pid=$($proc.Id)); kapatmak için o pencereyi kapatın. E2E: scripts\fssc.ps1 e2e -Url $health"
}

function Cmd-Compose {
  $dir = Resolve-ProjectDir
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'docker bulunamadı (Docker Desktop kurulu ve açık olmalı).' }
  $hasCompose = (Test-Path (Join-Path $dir 'docker-compose.yml')) -or (Test-Path (Join-Path $dir 'compose.yml')) -or (Test-Path (Join-Path $dir 'docker-compose.yaml'))
  if (-not $hasCompose) { throw "Compose dosyası yok: $dir (DevOps adımı 8 docker-compose.yml üretir)" }
  Push-Location $dir
  try {
    switch ($Action) {
      'build' { docker compose build }
      'up' {
        docker compose up --build -d
        if ($LASTEXITCODE -ne 0) { throw 'docker compose up başarısız' }
        docker compose ps
        $cmds = Read-ProjectVerification $dir
        $health = $null; if ($cmds) { $health = $cmds.health_url }
        if ($health) {
          Write-Info "Sağlık adresi bekleniyor: $health (konteyner portu compose dosyasındaki eşlemeye göre farklı olabilir)"
          $code = Wait-Url $health 60
          if ($code -gt 0) { Write-Ok "Yanıt: HTTP $code" } else { Write-Warn2 'Sağlık adresi yanıt vermedi; docker compose logs ile bakın.' }
        }
        Write-Info "E2E için: scripts\fssc.ps1 e2e -Url http://127.0.0.1:<port>   ·  loglar: scripts\fssc.ps1 compose -ProjectDir `"$dir`" -Action logs"
      }
      'down' { docker compose down }
      'ps' { docker compose ps }
      'logs' { docker compose logs --tail 200 }
    }
  } finally { Pop-Location }
}

function Cmd-E2E {
  $p = Get-DefaultPort
  if (-not $Url) { throw 'Kullanım: e2e -Url http://127.0.0.1:<port> [-ProfileId <profil>]' }
  if ($null -eq (Test-FsscServer $p)) { Write-Err "Port $p'de FS-SC sunucusu yok."; exit 2 }
  $body = @{ target_url = $Url; scenario = 'fssc.ps1 Playwright E2E' }
  if ($ProfileId) { $body.profile_id = $ProfileId }
  $res = Invoke-Api 'POST' $p '/api/tester/run-playwright' $body
  $r = $res.report
  Write-Host ("Durum: {0}  hedef: {1}  ekran görüntüsü: {2}" -f $r.status, $r.target_url, $r.screenshots.Count)
  foreach ($s in $r.screenshots) { Write-Host "   http://127.0.0.1:$p$s" }
  if ($r.logs) { $r.logs | Select-Object -Last 6 | ForEach-Object { Write-Host "   $_" } }
  if ($r.status -ne 'PASSED') { Write-Warn2 'PASSED değil: Playwright/Chromium kurulumunu (scripts\fssc.ps1 install) ve hedef adresi kontrol edin.' }
}

function Cmd-Help { Get-Help $PSCommandPath -Detailed }

switch ($Command) {
  'start' { Cmd-Start }
  'stop' { Cmd-Stop }
  'status' { Cmd-Status }
  'install' { Cmd-Install }
  'build' { Cmd-Build }
  'dev' { Cmd-Dev }
  'test' { Cmd-Test }
  'register-desktop' { Cmd-RegisterDesktop }
  'set-port' { Cmd-SetPort }
  'dry-run' { if ($Sprints -gt 0) { Cmd-SprintDryRun } else { Cmd-DryRun } }
  'runner' { Cmd-Runner }
  'sprint' { Cmd-SprintStatus }
  'migrate-docs' { Cmd-MigrateDocs }
  'app-test' { Cmd-AppTest }
  'app-run' { Cmd-AppRun }
  'compose' { Cmd-Compose }
  'e2e' { Cmd-E2E }
  default { Cmd-Help }
}
