"""Tek sayfalık bütçe ekranı (/budget): panodan bağımsız, önbellek/arayüz sorunlarından etkilenmez. Sınırı artırır ve engellenen sprinti sürdürür."""

PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title id="doc_title">Sprint Bütçesi</title><style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#14171f;--mut:#667085;--line:#e3e6ee;--ok:#16a34a;--err:#e11d48;--warn:#d97706;--ac:#3a48cc}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1218;--card:#181c25;--ink:#e8ebf2;--mut:#98a2b3;--line:#2a3040}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:640px;margin:0 auto;padding:20px 16px}
.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
h1{font-size:20px;margin:0 0 4px}
.lang-bar{display:flex;gap:4px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:3px}
.lang-btn{padding:4px 8px;font-size:12px;font-weight:600;border:none;border-radius:6px;background:transparent;color:var(--mut);cursor:pointer;margin:0}
.lang-btn.active{background:var(--ac);color:#fff}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.state{border-color:var(--err)}.state b{color:var(--err)}label{display:block;margin:8px 0;font-size:13px;color:var(--mut)}
input{width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
button{padding:9px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit;cursor:pointer;margin:4px 6px 4px 0}
.go{border-color:var(--ok);color:var(--ok)}#msg{font-size:13px;color:var(--mut);min-height:20px}.err{color:var(--err)!important}small{color:var(--mut)}
</style></head><body><main>
<div class="header">
  <div>
    <h1 id="h1_title">Sprint bütçesi</h1>
    <small id="sub_title">Sınır dolunca sprint durur; buradan artırıp sürdürürsün.</small>
  </div>
  <div class="lang-bar" id="lang_bar">
    <button class="lang-btn" data-lang="tr">🇹🇷 TR</button>
    <button class="lang-btn" data-lang="en">🇬🇧 EN</button>
    <button class="lang-btn" data-lang="es">🇪🇸 ES</button>
    <button class="lang-btn" data-lang="de">🇩🇪 DE</button>
  </div>
</div>
<div class="card state" id="state">Yükleniyor…</div>
<div class="card" id="form"></div>
<div class="card"><button class="go" id="save">1) Kaydet</button><button class="go" id="unblock">2) Engeli kaldır ve sürdür</button><div id="msg"></div></div>
</main><script>
const I18N = {
  tr: {
    title: "Sprint Bütçesi",
    sub: "Sınır dolunca sprint durur; buradan artırıp sürdürürsün.",
    loading: "Yükleniyor…",
    save: "1) Kaydet",
    unblock: "2) Engeli kaldır ve sürdür",
    noChange: "Değişiklik yok.",
    saved: "Kaydedildi",
    saveFail: "Kaydedilemedi",
    noBlocked: "Engelli sprint yok.",
    unblocked: "Sprint sürdürüldü. Claude oturumunda pipeline'ı çalıştırabilirsin.",
    unblockFail: "Engel kaldırılamadı",
    noSprint: "Sprint yok",
    sprintHalted: "durduruldu",
    noBlock: "engel yok",
    fields: {
      max_active_min_per_sprint: "Sprint etkin süresi (dk)",
      max_steps_per_sprint: "Sprint adım sayısı",
      max_tokens_per_sprint: "Sprint token sınırı",
      max_tokens_per_task: "Görev token sınırı",
      max_consecutive_failed_steps: "Art arda başarısız adım",
      stall_steps: "İlerlemesiz adım (takılma)",
      max_sprints: "Proje sprint sayısı",
      warn_at_percent: "Uyarı eşiği (%)"
    }
  },
  en: {
    title: "Sprint Budget",
    sub: "Sprint halts when limits are reached; increase here and resume.",
    loading: "Loading…",
    save: "1) Save",
    unblock: "2) Unblock and resume",
    noChange: "No changes.",
    saved: "Saved",
    saveFail: "Failed to save",
    noBlocked: "No blocked sprint.",
    unblocked: "Sprint resumed. You can run the pipeline in Claude session.",
    unblockFail: "Failed to unblock",
    noSprint: "No sprint",
    sprintHalted: "halted",
    noBlock: "no blocker",
    fields: {
      max_active_min_per_sprint: "Sprint active duration (min)",
      max_steps_per_sprint: "Sprint max step count",
      max_tokens_per_sprint: "Sprint token limit",
      max_tokens_per_task: "Task token limit",
      max_consecutive_failed_steps: "Consecutive failed steps",
      stall_steps: "Stall steps (no progress)",
      max_sprints: "Project sprint count",
      warn_at_percent: "Warning threshold (%)"
    }
  },
  es: {
    title: "Presupuesto del Sprint",
    sub: "El sprint se detiene al alcanzar el límite; aumente aquí y reanude.",
    loading: "Cargando…",
    save: "1) Guardar",
    unblock: "2) Desbloquear y reanudar",
    noChange: "Sin cambios.",
    saved: "Guardado",
    saveFail: "No se pudo guardar",
    noBlocked: "No hay sprint bloqueado.",
    unblocked: "Sprint reanudado. Puede ejecutar el pipeline en Claude.",
    unblockFail: "No se pudo desbloquear",
    noSprint: "No hay sprint",
    sprintHalted: "detenido",
    noBlock: "sin bloqueo",
    fields: {
      max_active_min_per_sprint: "Duración activa del sprint (min)",
      max_steps_per_sprint: "Número máx. de pasos por sprint",
      max_tokens_per_sprint: "Límite de tokens del sprint",
      max_tokens_per_task: "Límite de tokens por tarea",
      max_consecutive_failed_steps: "Pasos fallidos consecutivos",
      stall_steps: "Pasos sin progreso (estancamiento)",
      max_sprints: "Número de sprints del proyecto",
      warn_at_percent: "Umbral de advertencia (%)"
    }
  },
  de: {
    title: "Sprint-Budget",
    sub: "Sprint stoppt bei Grenzwertüberschreitung; hier erhöhen und fortsetzen.",
    loading: "Wird geladen…",
    save: "1) Speichern",
    unblock: "2) Entsperren und fortsetzen",
    noChange: "Keine Änderungen.",
    saved: "Gespeichert",
    saveFail: "Speichern fehlgeschlagen",
    noBlocked: "Kein blockierter Sprint.",
    unblocked: "Sprint fortgesetzt. Sie können die Pipeline in Claude ausführen.",
    unblockFail: "Entsperren fehlgeschlagen",
    noSprint: "Kein Sprint",
    sprintHalted: "gestoppt",
    noBlock: "keine Blockade",
    fields: {
      max_active_min_per_sprint: "Aktive Sprint-Dauer (Min.)",
      max_steps_per_sprint: "Maximale Sprint-Schrittanzahl",
      max_tokens_per_sprint: "Sprint-Token-Grenze",
      max_tokens_per_task: "Aufgaben-Token-Grenze",
      max_consecutive_failed_steps: "Aufeinanderfolgende Fehltritte",
      stall_steps: "Schritte ohne Fortschritt",
      max_sprints: "Projekt-Sprint-Anzahl",
      warn_at_percent: "Warnschwelle (%)"
    }
  }
};

let currentLang = 'en';
try {
  const saved = localStorage.getItem('ag_lang');
  if (saved && I18N[saved]) currentLang = saved;
} catch(e){}

const KEYS = ["max_active_min_per_sprint", "max_steps_per_sprint", "max_tokens_per_sprint", "max_tokens_per_task", "max_consecutive_failed_steps", "stall_steps", "max_sprints", "warn_at_percent"];
let cur=null,orig={};
const $=i=>document.getElementById(i),msg=(t,e)=>{$("msg").textContent=t;$("msg").className=e?"err":""};

function setLanguage(lang) {
  if (!I18N[lang]) return;
  currentLang = lang;
  try { localStorage.setItem('ag_lang', lang); } catch(e){}
  document.documentElement.lang = lang;
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });
  const t = I18N[lang];
  $("doc_title").textContent = t.title;
  $("h1_title").textContent = t.title;
  $("sub_title").textContent = t.sub;
  $("save").textContent = t.save;
  $("unblock").textContent = t.unblock;
  renderForm();
  renderState();
}

function renderForm() {
  const t = I18N[currentLang];
  $("form").innerHTML = KEYS.map(k => `<label>${t.fields[k] || k}<input type="number" id="f_${k}" value="${orig[k] ?? ''}"></label>`).join("");
}

function renderState() {
  const t = I18N[currentLang];
  if (cur && cur.status === "BLOCKED") {
    $("state").innerHTML = `<b>Sprint ${cur.sprint_number} ${t.sprintHalted}:</b> ${cur.blocked.reason} · ${cur.blocked.detail || ""}`;
  } else if (cur) {
    $("state").innerHTML = `Sprint ${cur.sprint_number}: ${cur.status} (${t.noBlock})`;
  } else {
    $("state").innerHTML = t.noSprint;
  }
}

async function load(){
  const t = I18N[currentLang];
  $("state").textContent = t.loading;
  try {
    const a = await (await fetch("/api/settings/autonomy")).json();
    orig = a.autonomy.budget;
  } catch(e){}
  renderForm();
  try {
    const b = await (await fetch("/api/sprints/board")).json();
    cur = b.current;
  } catch(e){}
  renderState();
}

document.querySelectorAll('.lang-btn').forEach(b => {
  b.onclick = () => setLanguage(b.dataset.lang);
});

$("save").onclick=async()=>{
  const t = I18N[currentLang];
  const body={};
  KEYS.forEach(k => {
    const v = Number($("f_" + k).value);
    if(v !== orig[k]) body[k] = v;
  });
  if(!Object.keys(body).length) return msg(t.noChange);
  const r = await fetch("/api/settings/autonomy", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({budget:body}) });
  r.ok ? msg(t.saved + ": " + Object.entries(body).map(([k,v])=>k+"="+v).join(", ")) : msg(t.saveFail, 1);
  await load();
};

$("unblock").onclick=async()=>{
  const t = I18N[currentLang];
  if(!cur || cur.status !== "BLOCKED") return msg(t.noBlocked);
  const r = await fetch("/api/sprints/" + cur.sprint_number + "/unblock", { method:"POST", headers:{"Content-Type":"application/json"}, body:"{}" });
  const j = await r.json().catch(()=>({}));
  r.ok ? msg(t.unblocked) : msg(j.error || t.unblockFail, 1);
  await load();
};

setLanguage(currentLang);
load();
</script></body></html>"""
