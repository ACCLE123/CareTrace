"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Role = "patient" | "staff" | "clinician" | "admin";
type Identity = { id: string; display_name: string; role: Role };
type Patient = { id: string; display_name: string; date_of_birth: string; synthetic: boolean };
type Highlight = { id: string; entry_id: string; excerpt: string; risk_reason: string; importance: number; status: string };
type TimelineEntry = { id: string; author_role: string; author_name: string; entry_type: string; visibility: string; content: string; provenance_pointer?: string; risk_level: string; version: number; created_at: string };
type Glance = { highlights: Highlight[]; open_actions: { id: string; content: string }[]; policy: string };
type Version = { version: number; content: string; created_at: string };
type ScribeSource = "patient_session" | "nurse_consult" | "doctor_consult";

const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));

export default function CareTracePage() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [actor, setActor] = useState<Identity>();
  const [patient, setPatient] = useState<Patient>();
  const [glance, setGlance] = useState<Glance>();
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [noteOpen, setNoteOpen] = useState(false);
  const [scribeOpen, setScribeOpen] = useState(false);
  const [scribeBusy, setScribeBusy] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<TimelineEntry>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [message, setMessage] = useState("");

  const request = useCallback(async <T,>(path: string, options: RequestInit = {}, identity = actor): Promise<T> => {
    const headers = new Headers(options.headers);
    if (identity) headers.set("X-Demo-User", identity.id);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Request failed");
    }
    return response.json() as Promise<T>;
  }, [actor]);

  const refresh = useCallback(async () => {
    if (!actor || !patient) return;
    const [freshGlance, freshTimeline] = await Promise.all([
      request<Glance>(`/api/patients/${patient.id}/glance`),
      request<TimelineEntry[]>(`/api/patients/${patient.id}/timeline`)
    ]);
    setGlance(freshGlance);
    setTimeline(freshTimeline);
  }, [actor, patient, request]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/demo-identities`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load demo identities.");
        return response.json() as Promise<Identity[]>;
      })
      .then((people) => {
        setIdentities(people);
        setActor(people.find((person) => person.role === "clinician") || people[0]);
      })
      .catch((error: Error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    if (!actor) return;
    request<Patient[]>("/api/patients", {}, actor)
      .then((patients) => setPatient(patients[0]))
      .catch((error: Error) => setMessage(error.message));
  }, [actor, request]);

  useEffect(() => { refresh().catch((error: Error) => setMessage(error.message)); }, [refresh]);
  useEffect(() => { if (!message) return; const timer = window.setTimeout(() => setMessage(""), 3500); return () => window.clearTimeout(timer); }, [message]);

  const canAdd = actor && ["staff", "clinician"].includes(actor.role);
  const selectedCurrent = useMemo(() => timeline.find((entry) => entry.id === selectedEntry?.id), [timeline, selectedEntry]);

  async function showVersions(entry: TimelineEntry) {
    try {
      setSelectedEntry(entry);
      setVersions(await request<Version[]>(`/api/entries/${entry.id}/versions`));
    } catch (error) { setMessage((error as Error).message); }
  }

  async function submitNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patient) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await request(`/api/patients/${patient.id}/entries`, { method: "POST", body: JSON.stringify(Object.fromEntries(form)) });
      formElement.reset(); setNoteOpen(false); setMessage("Saved with version 1 and an audit record."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function submitScribe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patient) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setScribeBusy(true);
    try {
      await request(`/api/patients/${patient.id}/scribe`, {
        method: "POST",
        body: JSON.stringify({ interaction_type: form.get("interaction_type") as ScribeSource, source_text: form.get("source_text") })
      });
      formElement.reset(); setScribeOpen(false);
      setMessage("DeepSeek created a traceable internal candidate note."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
    finally { setScribeBusy(false); }
  }

  async function recordHighlightFeedback(highlightId: string, accepted: boolean) {
    try {
      await request(`/api/highlights/${highlightId}/feedback`, { method: "POST", body: JSON.stringify({ accepted }) });
      setMessage(accepted ? "Suggestion accepted; future similar suggestions receive a bounded boost." : "Suggestion rejected; deterministic safety floors remain unchanged.");
      await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function revert(targetVersion: number) {
    if (!selectedCurrent) return;
    try {
      await request(`/api/entries/${selectedCurrent.id}/revert`, { method: "POST", body: JSON.stringify({ target_version: targetVersion, expected_version: selectedCurrent.version }) });
      setSelectedEntry(undefined); setMessage("Reverted — a new version and audit event were created."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function addComment(entryId: string) {
    const body = window.prompt("Internal comment (visible only to staff / clinicians):");
    if (!body) return;
    try { await request(`/api/entries/${entryId}/comments`, { method: "POST", body: JSON.stringify({ body, mention_role: "clinician" }) }); setMessage("Comment added to the internal audit trail."); }
    catch (error) { setMessage((error as Error).message); }
  }

  return <main className="shell">
    <header className="topbar"><div className="brand"><span>✦</span>CareTrace <small>clinical collaboration prototype</small></div>
      <label>Demo role <select value={actor?.id || ""} onChange={(event) => setActor(identities.find((person) => person.id === event.target.value))}>{identities.map((person) => <option key={person.id} value={person.id}>{person.display_name} — {person.role}</option>)}</select></label>
    </header>
    <div className="layout"><aside><p className="eyebrow">One shared care note</p><h1>{patient?.display_name || "Loading…"}</h1><p className="muted">Synthetic patient · Never for diagnosis</p><nav><a href="#glance">Glance view</a><a href="#timeline">Longitudinal timeline</a><a href="#trust">Trust & provenance</a></nav><section className="guardrail"><b>Safety boundary</b><p>AI extracts traceable candidate facts. The care team decides; the patient only sees clinician-approved instructions.</p></section></aside>
      <section className="workspace"><section id="glance"><div className="sectionHeading"><div><p className="eyebrow">Consult snapshot</p><h2>What needs attention now</h2></div><span className="latency">Warm path <b>8ms</b></span></div><p className="muted">{glance?.policy}</p><div className="cards">{glance?.highlights.map((highlight) => <article className={`card ${highlight.importance >= 90 ? "critical" : ""}`} key={highlight.id}><span>{highlight.importance >= 90 ? "Critical safety floor" : "Attention suggested"} · {highlight.importance}/100</span><p>{highlight.excerpt}</p><small>{highlight.risk_reason}</small><button onClick={() => document.getElementById(`entry-${highlight.entry_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>View source in timeline ↓</button>{canAdd && highlight.status === "suggested" && <div className="feedback"><button onClick={() => recordHighlightFeedback(highlight.id, true)}>Accept</button><button onClick={() => recordHighlightFeedback(highlight.id, false)}>Reject</button></div>}{highlight.status !== "suggested" && <small className="feedbackStatus">Care team: {highlight.status}</small>}</article>)}</div><div className="actions"><h3>Open actions</h3>{glance?.open_actions.map((action) => <p key={action.id}>{action.content}</p>)}</div></section>
        <section id="timeline" className="timeline"><div className="sectionHeading"><div><p className="eyebrow">Source of truth</p><h2>Longitudinal timeline</h2></div>{canAdd && <div className="timelineButtons"><button className="quiet" onClick={() => setScribeOpen(true)}>AI scribe</button><button className="primary" onClick={() => setNoteOpen(true)}>Add care note</button></div>}</div>{scribeOpen && <form className="noteForm" onSubmit={submitScribe}><p className="eyebrow">Synthetic source only · redacted before DeepSeek</p><select name="interaction_type" defaultValue="doctor_consult"><option value="patient_session">AI-patient session</option><option value="nurse_consult">Nurse-patient consult</option><option value="doctor_consult">Doctor-patient consult</option></select><textarea name="source_text" placeholder="Paste a synthetic interaction source. Names, IDs and phone numbers are redacted before the provider call." minLength={12} required /><div><button type="button" className="quiet" onClick={() => setScribeOpen(false)}>Cancel</button><button className="primary" disabled={scribeBusy}>{scribeBusy ? "Generating…" : "Generate DeepSeek note"}</button></div></form>}{noteOpen && <form className="noteForm" onSubmit={submitNote}><select name="entry_type" defaultValue={actor?.role === "staff" ? "staff_note" : "clinician_note"}><option value="staff_note">Staff note</option><option value="clinician_note">Clinician note</option><option value="instruction">Patient instruction</option></select><select name="visibility"><option value="internal">Internal</option><option value="patient">Patient-facing</option></select><textarea name="content" placeholder="Add a concise, attributable note…" minLength={4} required /><div><button type="button" className="quiet" onClick={() => setNoteOpen(false)}>Cancel</button><button className="primary">Save note</button></div></form>}<div className="timelineList">{timeline.map((entry) => <article className={`entry ${entry.author_role}`} id={`entry-${entry.id}`} key={entry.id}><div><header><span>{entry.author_name} · {entry.entry_type.replaceAll("_", " ")}</span><time>{formatDate(entry.created_at)}</time></header><p>{entry.content}</p><footer><em>{entry.visibility === "patient" ? "Patient-facing" : "Internal"}</em>{entry.provenance_pointer && <em>Source: {entry.provenance_pointer}</em>}{canAdd && <><button onClick={() => showVersions(entry)}>History · v{entry.version}</button><button onClick={() => addComment(entry.id)}>Comment</button></>}</footer></div></article>)}</div></section>
        <section id="trust" className="trust"><p className="eyebrow">Trust model</p><h2>Auditable by design</h2><div><p><b>Provenance</b><br />Every highlight links directly to its source entry.</p><p><b>Permissions</b><br />The API checks role and clinic scope, not just the screen.</p><p><b>Calibration</b><br />Feedback is bounded; critical classes keep a safety floor.</p></div></section>
      </section></div>
    {selectedEntry && <div className="modalBackdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true"><button className="close" onClick={() => setSelectedEntry(undefined)}>×</button><p className="eyebrow">Revision history</p><h2>Note versions</h2>{versions.map((version) => <article className="version" key={version.version}><b>Version {version.version}</b> · {formatDate(version.created_at)}<p>{version.content}</p>{version.version !== selectedCurrent?.version && <button onClick={() => revert(version.version)}>Revert to this version</button>}</article>)}</section></div>}
    {message && <div className="toast">{message}</div>}
  </main>;
}
