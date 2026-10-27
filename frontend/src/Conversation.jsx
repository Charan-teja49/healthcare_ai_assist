import { t } from "./i18n.js";
import React, { useEffect, useRef, useState } from 'react';
export default function Conversation({
  api,
  blocked,
  language,
  onComplete
}) {
  const [session, setSession] = useState(null),
    [answer, setAnswer] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [previous, setPrevious] = useState(null),
    [listening, setListening] = useState(false);
  const speech = useRef(null);
  useEffect(() => {
    if (!blocked) api('/conversations').then(rows => setPrevious(rows.find(r => !r.complete))).catch(e => setError(e.message));
  }, [blocked]);
  useEffect(() => () => speech.current?.abort(), []);
  useEffect(() => {
    if (!session?.complete || blocked) return;
    const timer = setInterval(() => api('/conversations/' + session.id).then(setSession).catch(e => setError(e.message)), 3000);
    return () => clearInterval(timer);
  }, [session?.id, session?.complete, blocked]);
  async function act(fn) {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function voice() {
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      setError(t('Voice input is unavailable in this browser. Please type your answer.'));
      return;
    }
    if (listening) {
      speech.current?.stop();
      return;
    }
    if (!window.confirm(t('Use voice input? Your browser may send audio to its speech service. You can type instead.'))) return;
    const current = new Speech();
    speech.current = current;
    current.lang = language === 'hi' ? 'hi-IN' : 'en-IN';
    current.onresult = e => setAnswer(old => (old + ' ' + e.results[0][0].transcript).trim());
    current.onend = () => setListening(false);
    current.onerror = () => {
      setListening(false);
      setError(t('Voice input failed or was denied. Please type your answer.'));
    };
    current.start();
    setListening(true);
  }
  const field = session?.question?.field,
    numeric = field === 'age' || field === 'severity';
  return <section className="panel conversation"><h2>{t("Guided symptom conversation")}</h2><p>{t("We\u2019ll collect the details your doctor needs, one question at a time. Emergency warning signs are checked before any model call.")}</p>{error && <div role="alert" className="error">{t(error)}</div>}{!session ? <div className="sim-controls"><button className="primary" disabled={busy || blocked} onClick={() => act(async () => setSession(await api('/conversations', {
        method: 'POST',
        body: JSON.stringify({
          language
        })
      })))}>{t("Start guided intake")}</button>{previous && <button className="secondary" disabled={busy || blocked} onClick={() => act(async () => setSession(await api('/conversations/' + previous.id)))}>{t("Resume unfinished intake")}</button>}</div> : <><div className="messages" aria-live="polite">{session.messages.map((m, i) => <div key={i} className={'message ' + m.role}><small>{m.role === 'user' ? t("You") : t("MediAssist")}</small><p>{m.text}</p></div>)}</div>{session.complete ? <div className="assessment"><span className="badge">{t(session.assessment?.urgency?.replaceAll('_', ' '))}</span><p>{t(session.assessment?.guidance)}</p>{session.assessment?.possibilities?.map(p => <p key={p}>{p}</p>)}<div>{session.assessment?.ranked_conditions?.map(c=><article key={c.rank}><strong>{c.rank}. {c.name}</strong><p>{c.rationale}</p></article>)}</div><small>{t(({needs_info:"More information requested",rejected:"Assessment not approved",escalated:"Case escalated",timed_out:"Review window expired"})[session.assessment?.review_status] || (session.assessment?.pending_review?"Awaiting assigned doctor approval":"Guidance released"))}</small>{session.assessment?.doctor_note&&<blockquote><strong>{t("Clinician note")}</strong><p>{session.assessment.doctor_note}</p></blockquote>}<div><button className="text-link" onClick={() => {
            setSession(null);
            setAnswer('');
          }}>{t("Start a new intake")}</button></div></div> : <form onSubmit={e => {
        e.preventDefault();
        act(async () => {
          const next = await api('/conversations/' + session.id + '/answer', {
            method: 'POST',
            body: JSON.stringify({
              text: answer,
              field
            })
          });
          setSession(next);
          setAnswer('');
          if (next.complete) onComplete?.(next.assessment);
        });
      }}><label>{session.question?.text}{numeric ? <input aria-label={t("Your answer")} type="number" min="1" max={field === 'age' ? 120 : 10} step="1" required value={answer} onChange={e => setAnswer(e.target.value)} /> : <textarea aria-label={t("Your answer")} required minLength={field === 'symptoms' ? 3 : 1} maxLength={field === 'duration' ? 100 : 3000} value={answer} onChange={e => setAnswer(e.target.value)} placeholder={t("Type your answer; write none where appropriate")} />}</label><div className="sim-controls"><button className="primary" disabled={busy || blocked}>{t("Send answer")}</button><button type="button" className="secondary" disabled={busy || blocked} onClick={voice}>{listening ? t("Stop voice") : t("Use voice input")}</button></div></form>}</>}</section>;
}
