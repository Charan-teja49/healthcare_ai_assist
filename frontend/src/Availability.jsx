import { t } from "./i18n.js";
import React, { useEffect, useState } from 'react';
import { indiaDay } from './helpers.js';
export default function Availability({
  api
}) {
  const [profiles, setProfiles] = useState([]),
    [blocked, setBlocked] = useState([]),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  async function refresh() {
    const [p, b] = await Promise.all([api('/clinician/profiles'), api('/clinician/blocked-slots')]);
    setProfiles(p);
    setBlocked(b);
  }
  useEffect(() => {
    refresh().catch(e => setMessage(e.message));
  }, []);
  return <section className="panel"><h2>{t("Manage local availability")}</h2><p>{t("Block unbooked half-hour slots. Existing patient bookings cannot be silently removed.")}</p>{message && <div className="success" role="status">{t(message)}</div>}<form className="availability-form" onSubmit={async e => {
      e.preventDefault();
      setBusy(true);
      const f = new FormData(e.currentTarget);
      try {
        await api('/clinician/blocked-slots', {
          method: 'POST',
          body: JSON.stringify({
            doctor_id: +f.get('doctor'),
            slot: f.get('day') + 'T' + f.get('time'),
            reason: f.get('reason')
          })
        });
        setMessage(t('Slot blocked.'));
        await refresh();
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    }}><label>{t("Specialist profile")}<select name="doctor" required>{profiles.map(p => <option key={p.id} value={p.id}>{p.name} · {p.city}</option>)}</select></label><label>{t("Date")}<input name="day" type="date" min={indiaDay()} max={indiaDay(90)} defaultValue={indiaDay(1)} required /></label><label>{t("Time (IST)")}<select name="time">{Array.from({
            length: 18
          }, (_, i) => {
            const time = String(9 + Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 ? '30' : '00');
            return <option key={time}>{time}</option>;
          })}</select></label><label>{t("Reason")}<input name="reason" minLength="5" maxLength="200" required placeholder={t("Clinic unavailable")} /></label><button className="primary" disabled={busy}>{t("Block slot")}</button></form>{blocked.map(b => <div className="appointment" key={b.doctor_id + b.slot}><p>{b.name} · {b.city} · {b.slot.replace('T', ' ')} {t("IST \xB7")} {b.reason}</p><button className="text-link" disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          await api('/clinician/reopen-slot', {
            method: 'POST',
            body: JSON.stringify({
              doctor_id: b.doctor_id,
              slot: b.slot,
              reason: 'Reopen local slot'
            })
          });
          await refresh();
          setMessage(t('Slot reopened.'));
        } catch (e) {
          setMessage(e.message);
        } finally {
          setBusy(false);
        }
      }}>{t("Reopen slot")}</button></div>)}</section>;
}
