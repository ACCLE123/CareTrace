"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Role = "patient" | "staff" | "clinician" | "admin";
type Identity = { id: string; display_name: string; role: Role };
type Patient = { id: string; display_name: string; date_of_birth: string; synthetic: boolean };
type Highlight = { id: string; entry_id: string; excerpt: string; risk_reason: string; importance: number; status: string };
type TimelineEntry = { id: string; author_role: string; author_name: string; entry_type: string; visibility: string; content: string; provenance_pointer?: string; risk_level: string; version: number; created_at: string };
type CareComment = { id: string; entry_id: string; body: string; mention_role?: Role; resolved: boolean; created_at: string; author_name: string; author_role: Role };
type ClinicalConflict = { id: string; category: string; reason: string; status: string; created_at: string; newer_entry_id: string; newer_content: string; newer_pointer?: string; prior_entry_id: string; prior_content: string; prior_pointer?: string };
type Glance = { highlights: Highlight[]; open_actions: { id: string; content: string }[]; policy: string };
type Version = { version: number; content: string; created_at: string };
type AuditEvent = { action: string; entity_type: string; entity_id: string; metadata: Record<string, unknown>; created_at: string };
type ScribeSource = "patient_session" | "nurse_consult" | "doctor_consult";

const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));

export default function CareTracePage() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [actor, setActor] = useState<Identity>();
  const [patient, setPatient] = useState<Patient>();
  const [glance, setGlance] = useState<Glance>();
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [comments, setComments] = useState<CareComment[]>([]);
  const [conflicts, setConflicts] = useState<ClinicalConflict[]>([]);
  const [commentOpen, setCommentOpen] = useState<string>();
  const [editingEntry, setEditingEntry] = useState<TimelineEntry>();
  const [editContent, setEditContent] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [scribeOpen, setScribeOpen] = useState(false);
  const [scribeBusy, setScribeBusy] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<TimelineEntry>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [compareVersion, setCompareVersion] = useState<Version>();
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
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
    const [freshGlance, freshTimeline, freshComments, freshConflicts] = await Promise.all([
      request<Glance>(`/api/patients/${patient.id}/glance`),
      request<TimelineEntry[]>(`/api/patients/${patient.id}/timeline`),
      ["staff", "clinician", "admin"].includes(actor.role)
        ? request<CareComment[]>(`/api/patients/${patient.id}/comments`)
        : Promise.resolve([] as CareComment[]),
      ["staff", "clinician", "admin"].includes(actor.role)
        ? request<ClinicalConflict[]>(`/api/patients/${patient.id}/conflicts`)
        : Promise.resolve([] as ClinicalConflict[]),
    ]);
    setGlance(freshGlance);
    setTimeline(freshTimeline);
    setComments(freshComments);
    setConflicts(freshConflicts);
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
  const canCollaborate = actor && ["staff", "clinician"].includes(actor.role);
  const canAudit = actor && ["clinician", "admin"].includes(actor.role);
  const canViewConflicts = actor && ["staff", "clinician", "admin"].includes(actor.role);
  const canResolveConflicts = actor?.role === "clinician";
  const selectedCurrent = useMemo(() => timeline.find((entry) => entry.id === selectedEntry?.id), [timeline, selectedEntry]);

  async function showVersions(entry: TimelineEntry) {
    try {
      setSelectedEntry(entry);
      setCompareVersion(undefined);
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

  function beginEdit(entry: TimelineEntry) {
    setEditingEntry(entry);
    setEditContent(entry.content);
  }

  async function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingEntry) return;
    try {
      await request(`/api/entries/${editingEntry.id}`, { method: "PATCH", body: JSON.stringify({ content: editContent, expected_version: editingEntry.version }) });
      setEditingEntry(undefined); setMessage("Saved as a new version with an audit record."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function showAudit() {
    if (!patient) return;
    try {
      setAuditEvents(await request<AuditEvent[]>(`/api/patients/${patient.id}/audit`));
      setAuditOpen(true);
    } catch (error) { setMessage((error as Error).message); }
  }

  async function submitComment(entryId: string, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await request(`/api/entries/${entryId}/comments`, { method: "POST", body: JSON.stringify({ body: form.get("body"), mention_role: form.get("mention_role") || null }) });
      formElement.reset(); setCommentOpen(undefined); setMessage("Internal comment added to the audit trail."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function setCommentResolution(commentId: string, resolved: boolean) {
    try {
      await request(`/api/comments/${commentId}`, { method: "PATCH", body: JSON.stringify({ resolved }) });
      setMessage(resolved ? "Comment resolved and recorded." : "Comment reopened for follow-up."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function resolveConflict(conflictId: string, decision: "confirmed_new" | "retained_existing") {
    try {
      await request(`/api/conflicts/${conflictId}`, { method: "PATCH", body: JSON.stringify({ decision }) });
      setMessage(decision === "confirmed_new" ? "Clinician confirmed the newer record." : "Clinician retained the earlier record."); await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  return <main className="shell">
    <header className="topbar"><div className="brand"><span>✦</span>CareTrace <small>clinical collaboration prototype</small></div>
      <label>Demo role <select value={actor?.id || ""} onChange={(event) => setActor(identities.find((person) => person.id === event.target.value))}>{identities.map((person) => <option key={person.id} value={person.id}>{person.display_name} — {person.role}</option>)}</select></label>
    </header>
    <div className="layout"><aside><p className="eyebrow">One shared care note</p><h1>{patient?.display_name || "Loading…"}</h1><p className="muted">Synthetic patient · Never for diagnosis</p><nav><a href="#glance">Glance view</a><a href="#timeline">Longitudinal timeline</a><a href="#trust">Trust & provenance</a></nav><section className="guardrail"><b>Safety boundary</b><p>AI extracts traceable candidate facts. The care team decides; the patient only sees clinician-approved instructions.</p></section></aside>
      <section className="workspace"><section id="glance"><div className="sectionHeading"><div><p className="eyebrow">Consult snapshot</p><h2>What needs attention now</h2></div><span className="latency">Measured P95 <b>6.97s</b></span></div><p className="muted">{glance?.policy}</p><div className="cards">{glance?.highlights.map((highlight) => <article className={`card ${highlight.importance >= 90 ? "critical" : ""}`} key={highlight.id}><span>{highlight.importance >= 90 ? "Critical safety floor" : "Attention suggested"} · {highlight.importance}/100</span><p>{highlight.excerpt}</p><small>{highlight.risk_reason}</small><button onClick={() => document.getElementById(`entry-${highlight.entry_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>View source in timeline ↓</button>{canAdd && highlight.status === "suggested" && <div className="feedback"><button onClick={() => recordHighlightFeedback(highlight.id, true)}>Accept</button><button onClick={() => recordHighlightFeedback(highlight.id, false)}>Reject</button></div>}{highlight.status !== "suggested" && <small className="feedbackStatus">Care team: {highlight.status}</small>}</article>)}</div><div className="actions"><h3>Open actions</h3>{glance?.open_actions.map((action) => <p key={action.id}>{action.content}</p>)}</div>{canViewConflicts && conflicts.some((conflict) => conflict.status === "needs_clinician_review") && <section className="conflictReview"><p className="eyebrow">Human decision required</p><h3>Conflicting source records</h3>{conflicts.filter((conflict) => conflict.status === "needs_clinician_review").map((conflict) => <article key={conflict.id}><span>Needs clinician review · {conflict.category.replaceAll("_", " ")}</span><p>{conflict.reason}</p><div><button onClick={() => document.getElementById(`entry-${conflict.prior_entry_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>Earlier source ↓</button><button onClick={() => document.getElementById(`entry-${conflict.newer_entry_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>Newer source ↓</button>{canResolveConflicts && <><button onClick={() => resolveConflict(conflict.id, "confirmed_new")}>Confirm newer record</button><button onClick={() => resolveConflict(conflict.id, "retained_existing")}>Retain earlier record</button></>}</div></article>)}</section>}</section>
        <section id="timeline" className="timeline"><div className="sectionHeading"><div><p className="eyebrow">Source of truth</p><h2>Longitudinal timeline</h2></div>{canAdd && <div className="timelineButtons"><button className="quiet" onClick={() => setScribeOpen(true)}>AI scribe</button><button className="primary" onClick={() => setNoteOpen(true)}>Add care note</button></div>}</div>{scribeOpen && <form className="noteForm" onSubmit={submitScribe}><p className="eyebrow">Synthetic source only · redacted before DeepSeek</p><select name="interaction_type" defaultValue="doctor_consult"><option value="patient_session">AI-patient session</option><option value="nurse_consult">Nurse-patient consult</option><option value="doctor_consult">Doctor-patient consult</option></select><textarea name="source_text" placeholder="Paste a synthetic interaction source. Names, IDs and phone numbers are redacted before the provider call." minLength={12} required /><div><button type="button" className="quiet" onClick={() => setScribeOpen(false)}>Cancel</button><button className="primary" disabled={scribeBusy}>{scribeBusy ? "Generating…" : "Generate DeepSeek note"}</button></div></form>}{noteOpen && <form className="noteForm" onSubmit={submitNote}><select name="entry_type" defaultValue={actor?.role === "staff" ? "staff_note" : "clinician_note"}><option value="staff_note">Staff note</option><option value="clinician_note">Clinician note</option><option value="instruction">Patient instruction</option></select><select name="visibility"><option value="internal">Internal</option><option value="patient">Patient-facing</option></select><textarea name="content" placeholder="Add a concise, attributable note…" minLength={4} required /><div><button type="button" className="quiet" onClick={() => setNoteOpen(false)}>Cancel</button><button className="primary">Save note</button></div></form>}<div className="timelineList">{timeline.map((entry) => {
          const entryComments = comments.filter((comment) => comment.entry_id === entry.id);
          return <article className={`entry ${entry.author_role}`} id={`entry-${entry.id}`} key={entry.id}><div><header><span>{entry.author_name} · {entry.entry_type.replaceAll("_", " ")}</span><time>{formatDate(entry.created_at)}</time></header><p>{entry.content}</p><footer><em>{entry.visibility === "patient" ? "Patient-facing" : "Internal"}</em>{entry.provenance_pointer && <em>Source: {entry.provenance_pointer}</em>}{canAdd && <button onClick={() => showVersions(entry)}>History · v{entry.version}</button>}{canCollaborate && <button onClick={() => setCommentOpen(commentOpen === entry.id ? undefined : entry.id)}>Comment{entryComments.length ? ` · ${entryComments.length}` : ""}</button>}</footer>{canCollaborate && entryComments.length > 0 && <section className="commentThread" aria-label="Internal collaboration comments">{entryComments.map((comment) => <article className={`comment ${comment.resolved ? "resolved" : ""}`} key={comment.id}><div><b>{comment.author_name}</b>{comment.mention_role && <span>@{comment.mention_role}</span>}<time>{formatDate(comment.created_at)}</time></div><p>{comment.body}</p><button onClick={() => setCommentResolution(comment.id, !comment.resolved)}>{comment.resolved ? "Reopen" : "Resolve"}</button></article>)}</section>}{canCollaborate && commentOpen === entry.id && <form className="commentForm" onSubmit={(event) => submitComment(entry.id, event)}><textarea name="body" placeholder="Internal collaboration comment…" minLength={2} maxLength={1200} required /><div><select name="mention_role" defaultValue=""><option value="">No role mention</option><option value="clinician">@clinician</option><option value="staff">@staff</option></select><button type="button" className="quiet" onClick={() => setCommentOpen(undefined)}>Cancel</button><button className="primary">Add comment</button></div></form>}</div></article>;
        })}</div></section>
        <section id="trust" className="trust"><p className="eyebrow">Trust model</p><h2>Auditable by design</h2><div><p><b>Provenance</b><br />Every highlight links directly to its source entry.</p><p><b>Permissions</b><br />The API checks role and clinic scope, not just the screen.</p><p><b>Calibration</b><br />Feedback is bounded; critical classes keep a safety floor.</p></div>{canAudit && <button className="primary auditButton" onClick={showAudit}>Open audit trail</button>}</section>
      </section></div>
    {selectedEntry && <div className="modalBackdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true"><button className="close" onClick={() => { setSelectedEntry(undefined); setCompareVersion(undefined); }}>×</button><p className="eyebrow">Revision history</p><h2>Note versions</h2>{selectedCurrent && actor?.role === selectedCurrent.author_role && <button className="primary modalAction" onClick={() => { beginEdit(selectedCurrent); setSelectedEntry(undefined); }}>Edit current note</button>}{versions.map((version) => <article className="version" key={version.version}><b>Version {version.version}</b> · {formatDate(version.created_at)}<p>{version.content}</p><div className="versionActions"><button onClick={() => setCompareVersion(version)}>Compare to current</button>{version.version !== selectedCurrent?.version && <button onClick={() => revert(version.version)}>Revert to this version</button>}</div></article>)}{compareVersion && selectedCurrent && <section className="diffView"><p className="eyebrow">Change comparison</p><h3>Version {compareVersion.version} → current v{selectedCurrent.version}</h3><div><article><b>Earlier snapshot</b><p>{compareVersion.content}</p></article><article><b>Current content</b><p>{selectedCurrent.content}</p></article></div></section>}</section></div>}
    {editingEntry && <div className="modalBackdrop" role="presentation"><form className="modal editModal" role="dialog" aria-modal="true" onSubmit={submitEdit}><button type="button" className="close" onClick={() => setEditingEntry(undefined)}>×</button><p className="eyebrow">Audited edit</p><h2>Edit note</h2><p className="muted">Saving creates version {editingEntry.version + 1}; it never overwrites history.</p><textarea value={editContent} onChange={(event) => setEditContent(event.target.value)} minLength={4} maxLength={4000} required /><div><button type="button" className="quiet" onClick={() => setEditingEntry(undefined)}>Cancel</button><button className="primary">Save new version</button></div></form></div>}
    {auditOpen && <div className="modalBackdrop" role="presentation"><section className="modal auditModal" role="dialog" aria-modal="true"><button className="close" onClick={() => setAuditOpen(false)}>×</button><p className="eyebrow">Clinic-scoped oversight</p><h2>Audit trail</h2>{auditEvents.length ? auditEvents.map((event) => <article className="auditEvent" key={`${event.entity_id}-${event.created_at}`}><b>{event.action.replaceAll("_", " ")}</b><time>{formatDate(event.created_at)}</time><p>{event.entity_type} · {event.entity_id.slice(0, 8)}{Object.keys(event.metadata).length ? ` · ${JSON.stringify(event.metadata)}` : ""}</p></article>) : <p className="muted">No audit events yet.</p>}</section></div>}
    {message && <div className="toast">{message}</div>}
  </main>;
}
