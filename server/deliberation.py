"""
Deliberation Engine (Ajanlar Arası Müzakere & Konsensüs Motoru)
Şartname ve toplantı notları yüklendiğinde veya kullanıcı talep ettiğinde
farklı disiplinlerdeki ajanları (PM, Mimar, Geliştiriciler, QA, PO, DevOps, SCM)
bir araya getirir, her ajanın uzmanlık perspektifinden fikir teatisi yapmasını sağlar
ve ortak bir konsensüs ile görev/mimari planı üretir.
"""

import asyncio
import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, N_, matches
from .paths import docs_path, hub_docs_path


class DeliberationMessage:
    def __init__(self, agent_id: str, role: str, message: str, sentiment: str = "AGREE", timestamp: Optional[str] = None):
        self.agent_id = agent_id
        self.role = role
        self.message = message
        self.sentiment = sentiment  # "PROPOSAL" | "CRITIQUE" | "AGREE" | "CONSENSUS"
        self.timestamp = timestamp or datetime.datetime.now().strftime("%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "message": self.message,
            "sentiment": self.sentiment,
            "timestamp": self.timestamp
        }


class DeliberationSession:
    def __init__(self, session_id: str, title: str, spec_summary: str):
        self.session_id = session_id
        self.title = title
        self.spec_summary = spec_summary
        # "ACTIVE" (tartışılıyor) | "AWAITING_APPROVAL" (ajanlar öneri çıkardı, yönetici kararı bekleniyor) | "AWAITING_PLAN_CHOICE" (plan seçilmedi, yönetici seçecek)
        # | "CONSENSUS_REACHED" (NİHAİ: yönetici onayladı) | "SUPERSEDED" (yeni konuya geçilince yarım kaldı)
        self.status = "ACTIVE"
        self.round = 1                                # yönetici revize istedikçe artan tur numarası
        self.rounds: List[Dict[str, Any]] = [{"round": 1, "started_at": datetime.datetime.now().isoformat(), "feedback": None}]
        self.decision_ref: Optional[str] = None       # onayla kaydedilen resmî karar (DEC-n)
        self.messages: List[Dict[str, Any]] = []
        self.proposals: List[Dict[str, Any]] = []   # 2-3 alternatif mimari plan (ARCHITECT turu)
        self.chosen_plan_id: Optional[str] = None
        self.approval_token: Optional[str] = None   # plan seçimi bekleme token'ı (ApprovalGate)
        self.consensus_summary: Optional[Dict[str, Any]] = None
        self.auto_rounds = False                      # sunucu üretimli (şablon) oturum: yönetici revize isteyince sunucu yeni turu kendisi üretir
        self.created_at = datetime.datetime.now().isoformat()
        self.updated_at = self.created_at

    def add_message(self, agent_id: str, role: str, message: str, sentiment: str = "AGREE") -> Dict[str, Any]:
        msg = DeliberationMessage(agent_id, role, message, sentiment)
        d = msg.to_dict()
        self.messages.append(d)
        self.updated_at = datetime.datetime.now().isoformat()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeliberationSession":
        s = cls(d.get("session_id", ""), d.get("title", ""), d.get("spec_summary", ""))
        for key in ("status", "messages", "proposals", "chosen_plan_id", "approval_token", "consensus_summary", "created_at", "updated_at", "round", "rounds", "decision_ref", "auto_rounds"):
            if key in d:
                setattr(s, key, d[key])
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "spec_summary": self.spec_summary,
            "status": self.status,
            "messages": self.messages,
            "proposals": self.proposals,
            "chosen_plan_id": self.chosen_plan_id,
            "approval_token": self.approval_token,
            "consensus_summary": self.consensus_summary,
            "round": self.round,
            "rounds": self.rounds,
            "decision_ref": self.decision_ref,
            "auto_rounds": self.auto_rounds,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class DeliberationEngine:
    """Ajanlar arası müzakere ve konsensüs motoru"""

    def __init__(self, telemetry_hub=None):
        self.hub = telemetry_hub
        self.active_session: Optional[DeliberationSession] = None
        self.meeting_session: Optional[DeliberationSession] = None   # F4: toplantı adımlarının oturumu
        self.history: List[Dict[str, Any]] = []
        self.auto_round_delay = 0.4                  # sunucu üretimli revize turunda konuşmalar arası bekleme (canlı akış hissi)

    def _approved_stack(self) -> Dict[str, str]:
        """Yöneticinin onayladığı teknoloji kararları (TR kalemleri): müzakere bunlara uyar, kendi yığınını dayatmaz.
        Onaylı karar yoksa eski varsayılan (FastAPI + React) kullanılır."""
        req = (self.hub.tech_requirements() if self.hub is not None and hasattr(self.hub, "tech_requirements") else None) or {}
        got = {str(i.get("category")): str(i.get("value") or "").strip() for i in req.get("items", []) if i.get("status") == "ONAYLANDI" and i.get("value")}
        be = got.get("backend") or "FastAPI"
        node = any(k in be.lower() for k in ("nest", "node", "express"))
        return {"backend": be, "database": got.get("database") or "SQLite/PostgreSQL", "client": got.get("client") or "React 18 + TailwindCSS",
                "auth": got.get("auth") or "JWT", "test": "Jest + Supertest" if node else "Pytest"}

    async def run_deliberation(
        self, 
        spec_data: Dict[str, Any], 
        project_dir: Optional[str] = None,
        delay_between_messages: float = 0.8
    ) -> Dict[str, Any]:
        """
        Şartnameyi alır, çoklu ajan müzakeresi koşturur ve konsensüs görevleri çıkarır.
        """
        title = spec_data.get("title") or tx("Yeni Proje Müzakeresi")
        notes = spec_data.get("meeting_notes") or ""
        session_id = f"DELIB-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        tech = self._approved_stack()
        be, db, cl, au, tt = tech["backend"], tech["database"], tech["client"], tech["auth"], tech["test"]

        session = DeliberationSession(
            session_id=session_id,
            title=title,
            spec_summary=notes[:300] if notes else tx("Şartname ve teknik isterler inceleniyor.")
        )
        session.auto_rounds = True
        self.active_session = session

        # Müzakere adımları
        steps = [
            {
                "agent_id": "PM",
                "role": "Product Manager",
                "message": tx("Ekip toplanalım! Müşterimizin '{title}' başlıklı şartnamesini ve toplantı notlarını aldım. Temel hedefimiz; ölçeklenebilir, güvenli ve kullanıcı deneyimi üst düzey bir çözüm üretmek. Mimar, teknik vizyonun nedir?", title=title),
                "sentiment": "PROPOSAL"
            },
            {
                "agent_id": "ARCHITECT",
                "role": "Tech Lead / Architect",
                "message": tx("Şartnameyi inceledim. 2 alternatif değerlendirebiliriz:\nPlan A: Çok katmanlı {be} + {cl} modüler monolit. (Hızlı MVP ve düşük karmaşıklık)\nPlan B: Event-driven mikroservis mimarisi. Şartnamedeki ölçek için Plan A'yı (Katmanlı Modüler Servis) öneriyorum. Teknoloji kararları yönetici onaylı yığına bağlı kalır. Backend ve Frontend, OpenAPI 3.0 sözleşmesi üzerinden ayrışacak.", be=be, cl=cl),
                "sentiment": "PROPOSAL"
            },
            {
                "agent_id": "BACKEND_DEV",
                "role": "Senior Backend Developer",
                "message": tx("Plan A kesinlikle en isabetli olanı. {be} ile girdi doğrulama, {db} veritabanı katmanı ve {au} tabanlı yetkilendirme kuralım. REST uç noktalarını CRUD standartlarına göre inşa edeceğim.", be=be, db=db, au=au),
                "sentiment": "AGREE"
            },
            {
                "agent_id": "FRONTEND_DEV",
                "role": "Senior Frontend Developer",
                "message": tx("Katılıyorum. İstemci tarafında onaylı karar: {cl}. Buna uygun modern bir arayüz kuralım. Form validasyonları anlık geri bildirim vermeli ve yükleme (loading) durumları kullanıcıya şeffaf yansıtılmalı.", cl=cl),
                "sentiment": "AGREE"
            },
            {
                "agent_id": "QA",
                "role": "Lead QA Engineer",
                "message": tx("Benim açımdan en kritik nokta: Her API uç noktasının negatif senaryolarla (hatalı parola, eksik alan, yetkisiz erişim) test edilmesi. {tt} süitini %90 üzeri coverage ile kurgulayacağım ve E2E testine yeşil ışık yakacağım.", tt=tt),
                "sentiment": "CRITIQUE"
            },
            {
                "agent_id": "PO",
                "role": "Product Owner",
                "message": tx("Teknik kararlar kullanıcı beklentisini karşılıyor. Ancak dikkat: Kullanıcının ilk karşılaştığı onboarding ve bildirim mesajları sade Türkçe olmalı. UAT denetiminde müşteri kabul kriterlerini bizzat doğrulayacağım."),
                "sentiment": "AGREE"
            },
            {
                "agent_id": "SCM",
                "role": "SCM Manager",
                "message": tx("Git stratejisi olarak 'feature/JIRA-X-[gorev-adi]' dallanmasını uygulayacağız. Çakışma (merge conflict) riskini sıfırlamak için kontrat dosyası dondurulduktan sonra geliştirmeye başlanacak."),
                "sentiment": "AGREE"
            },
            {
                "agent_id": "DEVOPS",
                "role": "DevOps & SRE",
                "message": tx("Harika. Dockerfile ve multi-stage build yapılandırmasını, environment (.env) şablonunu ve sağlık kontrolü (healthcheck) endpoint'ini hazırlayacağım. Staging dağıtımı hazır olduğunda release onayını vereceğiz."),
                "sentiment": "AGREE"
            },
            {
                "agent_id": "PM",
                "role": "Product Manager",
                "message": tx("Tüm ekip hemfikir! Müzakere tamamlandı ve konsensüs sağlandı: Plan A (Katmanlı Modüler Mimari) seçildi. Görevleri ve kabul kriterlerini Jira panosuna taşıyorum."),
                "sentiment": "CONSENSUS"
            }
        ]

        # Tek tek mesajları yayınla
        for step in steps:
            msg_dict = session.add_message(
                agent_id=step["agent_id"],
                role=step["role"],
                message=step["message"],
                sentiment=step["sentiment"]
            )

            # Telemetriye canlı yayın yap
            if self.hub:
                await self.hub.broadcast({
                    "type": "DELIBERATION_MESSAGE",
                    "session_id": session_id,
                    "message": msg_dict
                })
                # Ayrıca ajan konuşma baloncuğu olarak telemetriye yansıt
                if hasattr(self.hub, "record_event"):
                    await self.hub.record_event(
                        trace_id=f"delib-{session_id}",
                        from_agent=step["agent_id"],
                        to_agent="ALL",
                        action="DELIBERATION_SPEECH",
                        status="SUCCESS",
                        friendly_dialogue=step["message"][:120] + ("..." if len(step["message"]) > 120 else ""),
                        what_doing=tx("Müzakere masasında {sentiment} bildiriyor", sentiment=step["sentiment"]),
                        payload={"full_message": step["message"], "sentiment": step["sentiment"]}
                    )

            if delay_between_messages > 0:
                await asyncio.sleep(delay_between_messages)

        session.proposals = [
            {"id": "A", "title": tx("Plan A: Çok Katmanlı Modüler Monolit"), "summary": tx("{be} + {cl}, OpenAPI 3.0 sözleşmesiyle ayrışmış katmanlar.", be=be, cl=cl),
             "stack": [be, cl, db, "Docker"], "pros": [tx("Hızlı MVP"), tx("Düşük karmaşıklık"), tx("Tek dağıtım birimi")],
             "cons": [tx("Çok büyük ölçekte bölünmesi gerekir")], "risk": "LOW", "recommended": True},
            {"id": "B", "title": tx("Plan B: Olay Güdümlü Mikroservisler"), "summary": tx("Servis başına bağımsız dağıtım, mesaj kuyruğu ile gevşek bağlılık."),
             "stack": [be, "RabbitMQ/Kafka", cl, "Kubernetes"], "pros": [tx("Bağımsız ölçekleme"), tx("Ekip başına sahiplik")],
             "cons": [tx("Operasyon yükü"), tx("Dağıtık izleme gereksinimi"), tx("MVP süresi uzar")], "risk": "MEDIUM", "recommended": False},
        ]
        # Ajanlar konsensüs ÖNERİSİ çıkarır; nihai karar yöneticinindir (onay → CONSENSUS_REACHED, revize → yeni tur)
        session.status = "AWAITING_APPROVAL"
        session.consensus_summary = {
            "chosen_plan": tx("Plan A: Çok Katmanlı Modüler {be} Servisi", be=be),
            "proposed_plan_id": "A",
            "decision": "PROPOSED_BY_CONSENSUS",
            "agreed_stack": [be, cl, db, tt, "Playwright", "Docker"],
            "total_participants": 8,
            "completed_at": datetime.datetime.now().isoformat()
        }
        if self.hub:
            token = self.hub.gate.mint()
            self.hub.gate.register(token, {"session_id": session_id})
            session.approval_token = token

        session_dict = session.to_dict()

        if self.hub:
            await self.hub.broadcast({
                "type": "DELIBERATION_AWAITING_APPROVAL",
                "session": session_dict
            })

        # Dokümanı proje diskine de kaydet
        if project_dir and os.path.isdir(project_dir):
            try:
                docs_rel = hub_docs_path(self.hub, "deliberation", project_dir) if self.hub else docs_path(project_dir, "deliberation")
                docs_dir = os.path.join(project_dir, *docs_rel.split("/"))
                os.makedirs(docs_dir, exist_ok=True)
                md_path = os.path.join(docs_dir, f"{session_id}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(tx("# 🤝 Ajanlar Arası Müzakere & Konsensüs Tutanağı") + "\n\n")
                    f.write(tx("**Proje:** {title}", title=title) + "  \n")
                    f.write(tx("**Oturum ID:** `{session_id}`", session_id=session_id) + "  \n")
                    f.write(tx("**Tarih:** {date}", date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')) + "  \n")
                    f.write(tx("**Durum:** konsensüs önerisi, yönetici onayı bekliyor") + "  \n" + tx("**Öneri:** {plan}", plan=session.consensus_summary['chosen_plan']) + "  \n\n")
                    f.write(tx("## 💬 Görüşme Akışı") + "\n\n")
                    for m in session.messages:
                        f.write(f"### [{m['timestamp']}] {m['role']} ({m['agent_id']}) - `{m['sentiment']}`\n")
                        f.write(f"{m['message']}\n\n")
            except Exception as e:
                print(f"[DeliberationEngine] Doküman kaydetme hatası: {e}")

        return session_dict

    # ------------------------------------------------------------------
    # MCP istemcisi tarafından yürütülen müzakere (turları istemci üretir)
    # ------------------------------------------------------------------
    def open(self, spec_data: Dict[str, Any]) -> Dict[str, Any]:
        """Yeni bir müzakere oturumu açar; mesajları istemci `add_turn` ile ekler."""
        title = spec_data.get("title") or tx("Yeni Proje Müzakeresi")
        notes = spec_data.get("meeting_notes") or ""
        session_id = spec_data.get("session_id") or f"DELIB-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        taken = {x.get("session_id") for x in self.history} | {getattr(c, "session_id", None) for c in (self.active_session, getattr(self, "meeting_session", None))}
        base, n = session_id, 1
        while session_id in taken:                       # aynı saniyede açılan oturumlar çakışmasın (geçmişte biri diğerini ezmesin)
            n += 1
            session_id = f"{base}-{n}"
        session = DeliberationSession(
            session_id=session_id,
            title=title,
            spec_summary=notes[:300] if notes else tx("Şartname ve teknik isterler inceleniyor."),
        )
        if spec_data.get("kind") == "meeting":
            # Toplantı oturumları (F4) mimari plan müzakeresinin "son oturum" bağlamını ezmesin diye ayrı tutulur
            self.meeting_session = session
        else:
            prev = self.active_session
            if prev is not None and prev.status != "CONSENSUS_REACHED" and not any(h.get("session_id") == prev.session_id for h in self.history):
                prev.status = "SUPERSEDED"                       # yarım kalan müzakere geçmişte görünür kalır (kaybolmaz)
                self.history.append(prev.to_dict())
            self.active_session = session
        return session.to_dict()

    def _session(self, session_id: str) -> DeliberationSession:
        for cand in (self.active_session, getattr(self, "meeting_session", None)):
            if cand is not None and cand.session_id == session_id:
                return cand
        raise ValueError(tx("Aktif müzakere oturumu bulunamadı: {session_id}", session_id=session_id))

    @staticmethod
    def _normalize_proposals(proposals: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(proposals, list):
            return out
        for i, p in enumerate(proposals[:3]):
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "ABC"[i] if i < 3 else str(i + 1)).upper()[:3]
            out.append({
                "id": pid,
                "title": str(p.get("title") or tx("Plan {pid}", pid=pid)),
                "summary": str(p.get("summary") or ""),
                "stack": [str(x) for x in (p.get("stack") or [])][:12],
                "pros": [str(x) for x in (p.get("pros") or [])][:8],
                "cons": [str(x) for x in (p.get("cons") or [])][:8],
                "risk": str(p.get("risk") or "MEDIUM").upper(),
                "recommended": bool(p.get("recommended", False)),
            })
        return out

    async def add_turn(self, session_id: str, agent_id: str, message: str, sentiment: str = "AGREE",
                       proposals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        session = self._session(session_id)
        agent_id = (agent_id or "PM").upper()
        if proposals:
            session.proposals = self._normalize_proposals(proposals)
            session.updated_at = datetime.datetime.now().isoformat()
            if self.hub:
                await self.hub.broadcast({"type": "DELIBERATION_PLANS_PROPOSED", "session_id": session_id, "proposals": session.proposals, "session": session.to_dict()})
        role = (self.hub.agents.get(agent_id, {}) if self.hub else {}).get("name", agent_id)
        sentiment = (sentiment or "AGREE").upper()
        if sentiment not in ("PROPOSAL", "CRITIQUE", "AGREE", "CONSENSUS"):
            sentiment = "AGREE"
        msg_dict = session.add_message(agent_id=agent_id, role=role, message=message, sentiment=sentiment)
        if self.hub:
            await self.hub.broadcast({"type": "DELIBERATION_MESSAGE", "session_id": session_id, "message": msg_dict})
            await self.hub.record_event(
                trace_id=f"delib-{session_id}",
                from_agent=agent_id,
                to_agent="ALL",
                action="DELIBERATION_SPEECH",
                status="SUCCESS",
                friendly_dialogue=message[:120] + ("..." if len(message) > 120 else ""),
                what_doing=tx("Müzakere masasında {sentiment} bildiriyor", sentiment=sentiment),
                payload={"full_message": message, "sentiment": sentiment, "session_id": session_id},
            )
        return msg_dict

    async def close(self, session_id: str, consensus: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ajanlar müzakereyi bir ÖNERİYLE kapatır; nihai karar yöneticidendir. Mimari müzakere her zaman `AWAITING_APPROVAL` olur
        (öneri `proposed_plan_id`; plan seçilmediyse `AWAITING_PLAN_CHOICE`). Toplantı oturumları (F4) eski davranışı korur."""
        session = self._session(session_id)
        summary = dict(consensus or {})
        chosen = str(summary.get("chosen_plan_id") or "").upper()
        valid_ids = {p["id"] for p in session.proposals}
        if session is getattr(self, "meeting_session", None):
            session.status = "CONSENSUS_REACHED"
            summary.setdefault("decision", "APPROVED_BY_CONSENSUS")
            summary.setdefault("chosen_plan", tx("Konsensüs planı"))
            summary["completed_at"] = datetime.datetime.now().isoformat()
            session.consensus_summary = summary
            session_dict = session.to_dict()
            self.history.append(session_dict)
            if self.hub:
                await self.hub.broadcast({"type": "DELIBERATION_COMPLETED", "session": session_dict})
            return session_dict
        awaiting_choice = bool(session.proposals) and chosen not in valid_ids
        if chosen in valid_ids:
            plan = next(p for p in session.proposals if p["id"] == chosen)
            summary["proposed_plan_id"] = chosen
            summary.setdefault("chosen_plan", plan["title"])
            summary.setdefault("agreed_stack", plan.get("stack", []))
        summary.setdefault("chosen_plan", tx("Konsensüs önerisi"))
        summary.pop("chosen_plan_id", None)
        summary["decision"] = "AWAITING_USER_PLAN_CHOICE" if awaiting_choice else "PROPOSED_BY_CONSENSUS"
        summary.setdefault("total_participants", len({m["agent_id"] for m in session.messages}))
        summary["completed_at"] = datetime.datetime.now().isoformat()
        session.status = "AWAITING_PLAN_CHOICE" if awaiting_choice else "AWAITING_APPROVAL"
        session.consensus_summary = summary
        session.chosen_plan_id = None
        if self.hub:
            token = self.hub.gate.mint()
            self.hub.gate.register(token, {"session_id": session_id})
            session.approval_token = token
            await self.hub.broadcast({"type": "DELIBERATION_AWAITING_APPROVAL", "session_id": session_id, "proposals": session.proposals,
                                      "awaiting_choice": awaiting_choice, "session": session.to_dict()})
        return session.to_dict()

    async def approve(self, session_id: str, plan_id: str = "", chosen_by: str = "USER") -> Dict[str, Any]:
        """NİHAİ karar: yönetici öneriyi (ya da seçtiği başka planı) onaylar. Kayıt resmî karar (DEC-n) olarak da işlenir; bekleyen istemci serbest kalır."""
        session = self._session(session_id)
        if session.status not in ("AWAITING_APPROVAL", "AWAITING_PLAN_CHOICE", "ACTIVE", "CONSENSUS_REACHED"):
            raise ValueError(tx("Bu oturum onaylanamaz (durum: {status}).", status=session.status))
        summary = dict(session.consensus_summary or {})
        pid = str(plan_id or summary.get("proposed_plan_id") or "").upper()
        plan = next((p for p in session.proposals if p["id"] == pid), None)
        if (session.proposals or plan_id) and plan is None:
            raise ValueError(tx("Plan bulunamadı: {plan}", plan=plan_id or tx("(seçilmedi)")))
        if plan is not None:
            session.chosen_plan_id = pid
            summary.update({"chosen_plan": plan["title"], "chosen_plan_id": pid, "agreed_stack": plan.get("stack") or summary.get("agreed_stack") or []})
        summary.update({"decision": "APPROVED_BY_USER" if chosen_by == "USER" else "APPROVED_BY_CONSENSUS",
                        "total_participants": summary.get("total_participants") or len({m["agent_id"] for m in session.messages}),
                        "completed_at": datetime.datetime.now().isoformat(), "approved_by": chosen_by, "round": session.round})
        session.status = "CONSENSUS_REACHED"
        session.consensus_summary = summary
        session.decision_ref = self._record_decision(session, plan, chosen_by)
        summary["decision_ref"] = session.decision_ref
        session_dict = session.to_dict()
        self.history = [h for h in self.history if h.get("session_id") != session_id] + [session_dict]
        if self.hub:
            if session.approval_token:
                self.hub.gate.resolve(session.approval_token, pid or "APPROVED")
            await self.hub.record_event(
                trace_id=f"delib-{session_id}", from_agent="PM", to_agent="ARCHITECT", action="PLAN_CHOSEN", status="SUCCESS",
                payload={"session_id": session_id, "plan_id": pid, "plan": summary.get("chosen_plan"), "chosen_by": chosen_by, "decision_ref": session.decision_ref},
                friendly_dialogue=tx("Karar verildi ({ref}): {plan}. Mimar, kontratı bu plana göre yazabilirsin!", ref=session.decision_ref or tx("yönetici onayı"), plan=summary.get("chosen_plan")),
            )
            await self.hub.broadcast({"type": "DELIBERATION_COMPLETED", "session": session_dict})
        return session_dict

    async def choose_plan(self, session_id: str, plan_id: str, chosen_by: str = "USER") -> Dict[str, Any]:
        """Eski ad: yönetici bir plan seçer = o planı onaylar."""
        return await self.approve(session_id, plan_id, chosen_by)

    async def request_revision(self, session_id: str, feedback: str, by: str = "USER") -> Dict[str, Any]:
        """Yönetici öneriyi kabul etmez: geri bildirimi oturuma yazılır, tur numarası artar, oturum yeniden `ACTIVE` olur (ajanlar aynı oturumda tartışmaya devam eder)."""
        session = self._session(session_id)
        feedback = str(feedback or "").strip()
        if not feedback:
            raise ValueError(tx("Revize isteği için geri bildirim yazın."))
        if session.status not in ("AWAITING_APPROVAL", "AWAITING_PLAN_CHOICE", "CONSENSUS_REACHED"):
            raise ValueError(tx("Bu oturum için revize istenemez (durum: {status}).", status=session.status))
        token = session.approval_token
        session.round += 1
        session.rounds.append({"round": session.round, "started_at": datetime.datetime.now().isoformat(), "feedback": feedback})
        session.status = "ACTIVE"
        session.chosen_plan_id = None
        session.approval_token = None
        session.consensus_summary = {**(session.consensus_summary or {}), "decision": "REVISION_REQUESTED", "revision_feedback": feedback}
        msg = session.add_message("MANAGER", tx("Yönetici"), feedback, "CRITIQUE")
        self.history = [h for h in self.history if h.get("session_id") != session_id]       # nihaiyse geri açıldı: geçmişten çıkar (yeniden kapanınca eklenir)
        if self.hub:
            if token:
                self.hub.gate.resolve(token, "REVISE")
            await self.hub.broadcast({"type": "DELIBERATION_MESSAGE", "session_id": session_id, "message": msg})
            await self.hub.broadcast({"type": "DELIBERATION_REVISION_REQUESTED", "session": session.to_dict()})
            await self.hub.record_event(trace_id=f"delib-{session_id}", from_agent="MANAGER", to_agent="ALL", action="DELIBERATION_REVISION", status="SUCCESS",
                                        payload={"session_id": session_id, "round": session.round, "feedback": feedback[:600]},
                                        friendly_dialogue=tx("Yönetici revize istedi (tur {round}): {feedback}", round=session.round, feedback=feedback[:120]))
        out = session.to_dict()
        if session.auto_rounds:                       # sunucu üretimli oturumda yeni turu bekleyen bir Claude oturumu yoktur: sunucu kendisi üretir
            asyncio.get_running_loop().create_task(self._auto_revision_round(session_id))
        return out

    async def _auto_revision_round(self, session_id: str) -> None:
        """Yönetici geri bildirimine göre yeni turu sunucu üretir (LLM kullanmaz: kısıtları anahtar sözcüklerden çıkarır, planları buna göre günceller).
        Şablon turu geri bildirimi yalnızca yansıtır; derin yeniden değerlendirme isteniyorsa bir Claude oturumu `deliberation_turn` ile turu kendisi yazabilir."""
        delay = self.auto_round_delay
        session = self.active_session if self.active_session is not None and self.active_session.session_id == session_id else None
        if session is None or session.status != "ACTIVE":
            return
        fb = str((session.rounds[-1] or {}).get("feedback") or "")
        low = fb.lower()
        web_only = "mobil" in low and any(k in low for k in ("olmadan", "olmasın", "hariç", "sadece web", "yalnızca web", "yalnız web", "kaldır", "çıkar", "yok"))
        wants_test_server = any(k in low for k in ("test sunucu", "staging", "test ortam", "test etme"))

        def strip_mobile(t: Any) -> str:
            return re.sub(r"\s*\+\s*mobil[^,\]\)]*(\([^)]*\))?", "", str(t), flags=re.I).strip() if web_only else str(t)

        # Planlar geri bildirime göre güncellenir (özet + yığın + artı/eksi)
        plans = []
        for p in session.proposals or []:
            q = {**p, "stack": [strip_mobile(x) for x in p.get("stack", [])], "pros": list(p.get("pros", [])), "cons": list(p.get("cons", []))}
            q["summary"] = strip_mobile(q.get("summary", ""))
            if web_only:
                q["summary"] = (q["summary"] + " " + tx("Yalnızca web istemcisi (mobil kapsam dışı).")).strip()
                q["pros"].append(tx("Mobil kapsam çıkınca odak ve teslim hızı artar"))
            if wants_test_server and p.get("id") == "A":
                q["summary"] += " " + tx("Tamamlanan API'ler + web arayüzü MVP kapısını geçince test sunucusu yöneticiye sunulur.")
                q["pros"].append(tx("Yönetici MVP'yi erken test sunucusunda deneyebilir"))
                # üretilip sonra aranan metin (eşleştirme tuzağı): kontrol her dildeki biçimi kabul eder
                if not any("test sunucu" in str(x).lower() or matches(str(x), "Test sunucusu (docker compose)") for x in q["stack"]):
                    q["stack"] = [*q["stack"], tx("Test sunucusu (docker compose)")]
            plans.append(q)

        scope = tx("yalnızca web (mobil kapsam dışı)") if web_only else tx("geri bildirimdeki kapsam")
        turns = [
            ("PM", "Product Manager", tx("Yönetici geri bildirimi (tur {round}): “{fb}”. Kapsamı {scope} olarak yeniden çerçeveliyorum", round=session.round, fb=fb[:300], scope=scope)
                                      + (tx("; ayrıca MVP hazır olunca test sunucusunda deneme imkânı bir teslim şartı.") if wants_test_server else "."), "PROPOSAL"),
            ("BACKEND_DEV", "Senior Backend Developer", (tx("Mobil istemciye özel uçlar ertelenir; sözleşme yalnızca web'in kullandığı uçlarla sınırlanır. ") if web_only else tx("Sözleşmeyi geri bildirime göre güncelliyorum. "))
                                                        + (tx("Test sunucusu için tohum veri, ortam yapılandırması ve /health ucu hazırlanır.") if wants_test_server else ""), "AGREE"),
            ("FRONTEND_DEV", "Senior Frontend Developer", (tx("Yalnızca web: masaüstü öncelikli, duyarlı tek arayüz; mobil ekranlar kapsam dışı. ") if web_only else tx("Arayüz kapsamını geri bildirime göre ayarlıyorum. "))
                                                          + (tx("Test sunucusunda yalnızca tamamlanmış API'ye bağlı ekranlar açılır.") if wants_test_server else ""), "AGREE"),
            ("QA", "Lead QA Engineer", (tx("Mobil test senaryoları düşer; tarayıcı genişlik kontrolü eklenir. ") if web_only else "")
                                       + (tx("Test sunucusuna çıkış kapısı: tamamlanan API'lerin testleri ve sağlık kontrolü yeşil olmalı.") if wants_test_server else tx("Kabul testlerini güncel kapsama göre yeniden hizalıyorum.")), "CRITIQUE"),
            ("DEVOPS", "DevOps & SRE", (tx("devops/ altında docker-compose ile tek komutlu test sunucusu; adresi panoya yazılır, üretim ortamına dokunulmaz.") if wants_test_server
                                        else tx("Dağıtım yapılandırmasını güncel kapsama göre sadeleştiriyorum.")), "PROPOSAL"),
            ("PO", "Product Owner", (tx("Mobil kabul kriterleri silinmeden “kapsam dışı (yönetici kararı)” işaretlenir; ileride geri açılabilir.") if web_only else tx("Kabul kriterlerini geri bildirime göre gözden geçiriyorum.")), "AGREE"),
            ("ARCHITECT", "Tech Lead / Architect", tx("Planları geri bildirime göre güncelledim ({count} alternatif). Önerim değişmedi: Plan A; nihai karar yöneticinin.", count=len(plans)), "PROPOSAL"),
        ]
        for agent_id, role, text, sentiment in turns:
            if not text.strip():
                continue
            msg = session.add_message(agent_id, role, text.strip(), sentiment)
            if self.hub:
                await self.hub.broadcast({"type": "DELIBERATION_MESSAGE", "session_id": session_id, "message": msg})
            if delay > 0:
                await asyncio.sleep(delay)
        session.proposals = plans
        rec = next((p for p in plans if p.get("recommended")), plans[0] if plans else None)
        session.status = "AWAITING_APPROVAL"
        session.consensus_summary = {**(session.consensus_summary or {}), "decision": "PROPOSED_BY_CONSENSUS", "proposed_plan_id": (rec or {}).get("id", "A"),
                                     "chosen_plan": (rec or {}).get("title") or (session.consensus_summary or {}).get("chosen_plan"), "revision_round": session.round,
                                     "completed_at": datetime.datetime.now().isoformat()}
        if self.hub:
            token = self.hub.gate.mint()
            self.hub.gate.register(token, {"session_id": session_id})
            session.approval_token = token
            await self.hub.broadcast({"type": "DELIBERATION_AWAITING_APPROVAL", "session": session.to_dict()})
            self.hub.mark_dirty()

    def _record_decision(self, session: "DeliberationSession", plan: Optional[Dict[str, Any]], by: str) -> Optional[str]:
        """Onaylanan müzakere kararı resmî karar kaydı (DEC-n, insan onaylı) olur; metindeki kütüphaneler bağımlılık denetiminde onaylı sayılır."""
        if not self.hub:
            return None
        try:
            from . import meetings as M
            from . import sprint as SP
            title = (plan or {}).get("title") or (session.consensus_summary or {}).get("chosen_plan") or session.title
            stack = ", ".join((plan or {}).get("stack") or (session.consensus_summary or {}).get("agreed_stack") or [])
            dec = {"id": M.next_decision_id(self.hub), "text": tx("Müzakere {sid} ({stitle}) → {plan}", sid=session.session_id, stitle=session.title, plan=title) + (f" [{stack}]" if stack else ""),
                   "meeting": None, "sprint": None, "adr": None, "question": None, "decided_by": by,
                   "basis": tx("Ajanlar arası müzakere (tur {round}); yönetici onayladı.", round=session.round), "alternatives": [p["title"] for p in session.proposals if not plan or p["id"] != plan["id"]],
                   "human_approved": True}
            SP.ensure_state(self.hub)["decisions"].append(dec)
            self.hub.mark_dirty()
            return dec["id"]
        except Exception:
            return None

    def set_implementation_task(self, session_id: str, task: Dict[str, Any]) -> None:
        """Onaylanan kararın uygulama işi (backlog) kayda bağlanır: 'ne zaman uygulamaya geçecek' sorusunun cevabı oturumda görünür."""
        s = self.get_session_dict(session_id)
        if s is None:
            return
        info = {"issue_id": task.get("issue_id"), "key": task.get("key"), "title": task.get("title"), "when": ((task.get("expedite") or {}).get("mode") or "next_sprint")}
        if self.active_session is not None and self.active_session.session_id == session_id:
            self.active_session.consensus_summary = {**(self.active_session.consensus_summary or {}), "implementation_task": info}
        for h in self.history:
            if h.get("session_id") == session_id:
                h["consensus_summary"] = {**(h.get("consensus_summary") or {}), "implementation_task": info}

    def history_list(self) -> List[Dict[str, Any]]:
        """Müzakere geçmişi (yeniden eskiye): nihai kararlar, yarım kalanlar ve güncel oturum; mesajlar gövdede gelmez (özet)."""
        rows: Dict[str, Dict[str, Any]] = {}
        for h in self.history:
            rows[h.get("session_id")] = h
        if self.active_session is not None:
            rows[self.active_session.session_id] = self.active_session.to_dict()
        out = []
        for sid, d in rows.items():
            cs = d.get("consensus_summary") or {}
            out.append({"session_id": sid, "title": d.get("title"), "status": d.get("status"), "round": d.get("round", 1), "rounds": d.get("rounds") or [],
                        "messages": len(d.get("messages") or []), "chosen_plan": cs.get("chosen_plan"), "decision": cs.get("decision"), "decision_ref": d.get("decision_ref"),
                        "created_at": d.get("created_at"), "updated_at": d.get("updated_at")})
        return sorted(out, key=lambda r: str(r.get("updated_at") or ""), reverse=True)

    def get_session_dict(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self.active_session is not None and self.active_session.session_id == session_id:
            return self.active_session.to_dict()
        return next((h for h in self.history if h.get("session_id") == session_id), None)

    def snapshot(self) -> Dict[str, Any]:
        """Kalıcılık için: açık oturumlar ve kapanmış oturum geçmişi (son 50)."""
        return {"active": self.active_session.to_dict() if self.active_session else None,
                "meeting": self.meeting_session.to_dict() if self.meeting_session else None,
                "history": self.history[-50:]}

    def restore(self, data: Optional[Dict[str, Any]]) -> None:
        """`snapshot()` çıktısını geri yükler (sunucu yeniden başlayınca müzakere odası boş kalmasın)."""
        data = dict(data or {})
        # Eski sürümde ajanlar kendi aralarında "konsensüs" kapatıp kararı nihai sayıyordu (yönetici onayı yoktu): bunlar artık yönetici kararı bekleyen ÖNERİdir.
        def legacy(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not d or not str(d.get("session_id", "")).startswith("DELIB-") or d.get("status") != "CONSENSUS_REACHED":
                return d
            cs = dict(d.get("consensus_summary") or {})
            if cs.get("decision") != "APPROVED_BY_CONSENSUS" or cs.get("approved_by"):
                return d
            d = dict(d)
            cs.update({"decision": "PROPOSED_BY_CONSENSUS", "proposed_plan_id": d.get("chosen_plan_id") or cs.get("chosen_plan_id"), "legacy": True})
            cs.pop("chosen_plan_id", None)
            d.update({"status": "AWAITING_APPROVAL", "chosen_plan_id": None, "consensus_summary": cs, "approval_token": None})
            return d
        data["active"] = legacy(data.get("active"))
        data["history"] = [h for h in (data.get("history") or []) if legacy(h) is h]            # geçmişte yalnızca gerçekten nihai (onaylı) kararlar kalır
        self.active_session = DeliberationSession.from_dict(data["active"]) if data.get("active") else None
        self.meeting_session = DeliberationSession.from_dict(data["meeting"]) if data.get("meeting") else None
        self.history = list(data.get("history") or [])

    def get_latest_session(self) -> Optional[Dict[str, Any]]:
        return self.active_session.to_dict() if self.active_session else None
