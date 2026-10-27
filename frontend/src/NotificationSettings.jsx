import { t } from "./i18n.js";
import React, { useEffect, useState } from 'react';
export default function NotificationSettings({
  api,
  blocked
}) {
  const [contact, setContact] = useState(null),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api('/me/emergency-contact').then(setContact).catch(e => setMessage(e.message));
  }, [blocked]);
  async function act(fn) {
    setBusy(true);
    setMessage('');
    try {
      await fn();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }
  if (!contact) return <p>{t(message || 'Loading notification preferences…')}</p>;
  async function enablePush() {
    const config = await api('/notifications/push/config');
    if (!config.configured) throw Error('Web Push is not configured. In-app notifications remain available.');
    if (!('Notification' in window) || !('serviceWorker' in navigator)) throw Error('This browser does not support Web Push.');
    if ((await Notification.requestPermission()) !== 'granted') throw Error('Notification permission was not granted.');
    const registration = await navigator.serviceWorker.ready;
    const normalized = config.public_key.replace(/-/g, '+').replace(/_/g, '/');
    const key = Uint8Array.from(atob(normalized + '='.repeat((4 - normalized.length % 4) % 4)), c => c.charCodeAt(0));
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: key
    });
    try {
      await api('/notifications/push/subscription', {
        method: 'POST',
        body: JSON.stringify(subscription.toJSON())
      });
    } catch (e) {
      await subscription.unsubscribe();
      throw e;
    }
    setMessage(t('Browser notifications enabled.'));
  }
  return <section className="panel form"><h2>{t("Emergency contact & notifications")}</h2><p>{t("External delivery requires provider setup and consent from the contact. Messages contain a generic alert, without report values or symptoms. In-app alerts work locally.")}</p><p>{contact.sms_configured ? t("SMS provider configured") : t("SMS uses the local mock outbox; no message is sent.")}</p><form onSubmit={e => {
      e.preventDefault();
      act(async () => {
        setContact(await api('/me/emergency-contact', {
          method: 'PUT',
          body: JSON.stringify(contact)
        }));
        setMessage(t('Notification preferences saved.'));
      });
    }}><label>{t("Contact name")}<input maxLength="100" value={contact.name} onChange={e => setContact({
          ...contact,
          name: e.target.value
        })} /></label><label>{t("International phone number")}<input type="tel" placeholder={t("+919876543210")} maxLength="16" value={contact.phone} onChange={e => setContact({
          ...contact,
          phone: e.target.value
        })} /></label><label className="inline"><input type="checkbox" disabled={blocked && !contact.consent} checked={!!contact.consent} onChange={e => setContact({
          ...contact,
          consent: e.target.checked
        })} />{t("My contact has agreed to receive these alerts.")}</label><button className="primary" disabled={busy}>{t("Save notification preferences")}</button></form><div className="sim-controls"><button className="secondary" disabled={busy || !contact.push_configured} onClick={() => act(enablePush)}>{t("Enable browser notifications")}</button><button className="secondary" disabled={busy} onClick={() => act(async () => {
        await api('/notifications/push/subscription', {
          method: 'DELETE'
        });
        const reg = await navigator.serviceWorker?.getRegistration();
        await (await reg?.pushManager.getSubscription())?.unsubscribe();
        setMessage(t('Browser notifications disabled.'));
      })}>{t("Disable browser notifications")}</button></div><p role="status">{t(message)}</p></section>;
}
