import { t, setUiLanguage, referenceLabel } from "./i18n.js";
import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Heart, LayoutDashboard, MessageCircle, FileText, Users, Calendar, ShieldCheck, ArrowUpRight, ArrowRight, Bell, LogOut, Settings, Stethoscope, Plus, Check, Download, Radio, Search, Wind, Thermometer, ChevronRight } from 'lucide-react';
import './style.css';
import { indiaDay, slotLabel, validateSymptoms, fillDemoAccount } from './helpers.js';
import { readApiResponse } from './http.js';
import LiveECG from './LiveECG.jsx';
import Conversation from './Conversation.jsx';
import Availability from './Availability.jsx';
import NotificationSettings from './NotificationSettings.jsx';
import PatientReply from './PatientReply.jsx';
import DemoPanel from './DemoPanel.tsx';
const cityCoordinates = {
  Mumbai: [19.076, 72.8777],
  Delhi: [28.6139, 77.209],
  Bengaluru: [12.9716, 77.5946],
  Chennai: [13.0827, 80.2707],
  Pune: [18.5204, 73.8567],
  Hyderabad: [17.385, 78.4867]
};
const navigation = [['Overview', LayoutDashboard], ['Symptom checker', MessageCircle], ['Health reports', FileText], ['Find a specialist', Users], ['Appointments', Calendar], ['Doctor review', ShieldCheck], ['Notifications', Bell], ['Health history', Activity], ['Integrations', Radio], ['Privacy & settings', Settings]];
function App() {
  const [token, setToken] = useState(sessionStorage.getItem('medi-token') || ''),
    [user, setUser] = useState(null),
    [page, setPage] = useState(location.pathname === '/demo' ? 'Demo' : 'Overview'),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [vital, setVital] = useState({
      hr: 72,
      spo2: 98,
      temperature: 36.7
    }),
    [history, setHistory] = useState([]),
    [scenario, setScenario] = useState('normal_rest'),
    [running, setRunning] = useState(false),
    [cases, setCases] = useState([]),
    [appointments, setAppointments] = useState([]),
    [doctors, setDoctors] = useState([]),
    [city, setCity] = useState(''),
    [specialty, setSpecialty] = useState(''),
    [result, setResult] = useState(null),
    [report, setReport] = useState(null),
    [busy, setBusy] = useState(false),
    [register, setRegister] = useState(false),
    [language, setLanguage] = useState(localStorage.getItem('medi-language') || 'en'),
    [notifications, setNotifications] = useState([]),
    [records, setRecords] = useState([]),
    [integrations, setIntegrations] = useState([]),
    [details, setDetails] = useState({}),
    [doctorLanguage, setDoctorLanguage] = useState(''),
    [outbox, setOutbox] = useState([]),
    [listening, setListening] = useState(false),
    [severity, setSeverity] = useState(4),
    [ecg, setEcg] = useState({
      samples: [],
      sample_rate: 250
    }),
    [trends, setTrends] = useState([]),
    [online, setOnline] = useState(navigator.onLine),
    [transport, setTransport] = useState('connecting'),
    [intakeMode, setIntakeMode] = useState('guided'),
    [nearCity, setNearCity] = useState(''),
    [radius, setRadius] = useState('100'),
    [availableDay, setAvailableDay] = useState('');
  const speechRef = React.useRef(null);
  useEffect(() => () => speechRef.current?.abort(), []);
  useEffect(() => {
    setUiLanguage(language);
  }, [language]);
  const hi = language === 'hi';
  async function api(path, options = {}) {
    const {
      binary = false,
      ...request
    } = options;
    let response;
    try {
      response = await fetch('/api' + path, {
        signal: AbortSignal.timeout(20000),
        ...request,
        headers: {
          ...(options.body instanceof FormData ? {} : {
            'Content-Type': 'application/json'
          }),
          ...(token ? {
            Authorization: 'Bearer ' + token
          } : {}),
          ...options.headers
        }
      });
    } catch {
      throw Error('Cannot reach the local application. Start both services with start.ps1, keep them running, then reload this page.');
    }
    if (token && sessionStorage.getItem('medi-token') !== token) throw Error('Account changed; the previous request was discarded.');
    if (binary && response.ok) return response.blob();
    try {
      return await readApiResponse(response);
    } catch (error) {
      if (error.status === 401 && token && !path.startsWith('/auth/')) {
        logout();
        throw Error('Your session has expired. Please sign in again.');
      }
      if (error.status === 403 && error.message.includes('Consent')) {
        setUser(old => old ? {
          ...old,
          consent: false
        } : old);
        setRunning(false);
      }
      throw error;
    }
  }
  async function downloadOriginal(id, name = 'report-original') {
    const blob = await api('/reports/documents/' + id, {
      binary: true
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  }
  async function act(fn) {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    await act(async () => {
      try {
        await api('/auth/logout', {
          method: 'POST'
        });
      } finally {
        logout();
      }
    });
  }
  function logout() {
    sessionStorage.removeItem('medi-token');
    setToken('');
    setUser(null);
    setRunning(false);
    setHistory([]);
    setCases([]);
    setResult(null);
    setReport(null);
    setNotifications([]);
    setRecords([]);
    setAppointments([]);
    setDetails({});
    setVital({
      hr: 72,
      spo2: 98,
      temperature: 36.7
    });
    setScenario('normal_rest');
    setDoctors([]);
    setIntegrations([]);
    setOutbox([]);
    setListening(false);
    setSeverity(4);
    setEcg({
      samples: [],
      sample_rate: 250
    });
    setTrends([]);
    received.current.clear();
    speechRef.current?.abort();
    setPage('Overview');
  }
  async function refresh() {
    const [c, a, n] = await Promise.all([api('/cases'), api('/appointments'), api('/notifications')]);
    setCases(c);
    setAppointments(a);
    setNotifications(n);
  }
  useEffect(() => {
    if (token) act(async () => {
      setUser(await api('/me'));
      await refresh();
    });
  }, [token]);
  useEffect(() => {
    if (!user) return;
    const timer = setInterval(() => {
      api('/me').then(fresh => {
        setUser(old => JSON.stringify(old) === JSON.stringify(fresh) ? old : fresh);
        if (!fresh.consent) setRunning(false);
      }).catch(e => setError(e.message));
      refresh().catch(e => setError(e.message));
    }, 15000);
    return () => clearInterval(timer);
  }, [user?.id, token]);
  useEffect(() => {
    if (page === 'Health history' && user?.consent) api('/records').then(setRecords).catch(e => setError(e.message));
    if (page === 'Integrations' && user) Promise.all([api('/integrations'), api('/integrations/outbox')]).then(([i, o]) => {
      setIntegrations(i);
      setOutbox(o);
    }).catch(e => setError(e.message));
  }, [page, user?.id, user?.consent]);
  useEffect(() => {
    if (user?.role === 'patient' && user.consent) api('/vitals').then(h => {
      setHistory(h);
      if (h.length) setVital(h.at(-1));
    }).catch(e => setError(e.message));
  }, [user]);
  useEffect(() => {
    if (page === 'Find a specialist' && user) api('/doctors?' + new URLSearchParams({
      city,
      specialty,
      language: doctorLanguage,
      ...(nearCity ? {
        latitude: cityCoordinates[nearCity][0],
        longitude: cityCoordinates[nearCity][1],
        radius_km: radius
      } : {}),
      ...(availableDay ? {
        available_on: availableDay
      } : {})
    })).then(setDoctors).catch(e => setError(e.message));
  }, [page, city, specialty, doctorLanguage, nearCity, radius, availableDay, user]);
  const received = React.useRef(new Set());
  function applyPacket(data) {
    if (data.event_id && received.current.has(data.event_id)) return;
    if (data.event_id) {
      received.current.add(data.event_id);
      if (received.current.size > 300) received.current.delete(received.current.values().next().value);
    }
    if (data.kind === 'vitals') {
      setVital(data);
      setHistory(old => [...old, data].slice(-720));
    }
    if (data.kind === 'ecg') setEcg(data);
    if (data.kind === 'event' && data.event === 'leads_off') {
      setVital(old => ({
        ...old,
        signal: false
      }));
      setEcg({
        samples: [],
        sample_rate: 250
      });
    }
  }
  useEffect(() => {
    const changed = () => setOnline(navigator.onLine);
    window.addEventListener('online', changed);
    window.addEventListener('offline', changed);
    return () => {
      window.removeEventListener('online', changed);
      window.removeEventListener('offline', changed);
    };
  }, []);
  useEffect(() => {
    if (user?.role !== 'patient' || !user.consent || !token) return;
    let stopped = false,
      ws,
      timer;
    const connect = () => {
      if (stopped) return;
      ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/vitals');
      ws.onopen = () => ws.send(JSON.stringify({
        token
      }));
      ws.onmessage = e => {
        const data = JSON.parse(e.data);
        if (data.type === 'ready') setTransport('connected');else if (data.type === 'case_changed') refresh().catch(e => setError(e.message));else if (!data.type) applyPacket(data);
      };
      ws.onclose = () => {
        setTransport('reconnecting');
        if (!stopped) timer = setTimeout(connect, 2500);
      };
      ws.onerror = () => setTransport('unavailable');
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [user?.id, user?.consent, token]);
  useEffect(() => {
    if (user?.role === 'patient' && user.consent && page === 'Overview') api('/devices/trends').then(r => setTrends(r.buckets)).catch(e => setError(e.message));
  }, [page, user?.id, user?.consent, running]);
  useEffect(() => {
    if (!running || !token) return;
    const controller = new AbortController();
    let stopped = false;
    async function read() {
      try {
        const response = await fetch('/api/devices/simulator?scenario=' + scenario, {
          headers: {
            Authorization: 'Bearer ' + token
          },
          signal: controller.signal
        });
        if (!response.ok) throw Error('Cannot start the device simulator. Check health consent.');
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let buffer = '';
        while (!stopped) {
          const {
            done,
            value
          } = await reader.read();
          if (done) {
            setRunning(false);
            break;
          }
          buffer += decoder.decode(value, {
            stream: true
          });
          let index;
          while ((index = buffer.indexOf('\n\n')) >= 0) {
            const line = buffer.slice(0, index);
            buffer = buffer.slice(index + 2);
            if (line.startsWith('event: consent_required')) {
              setRunning(false);
              throw Error('Consent withdrawn; simulator stopped.');
            }
            if (line.startsWith('data: ')) applyPacket(JSON.parse(line.slice(6)));
          }
        }
      } catch (e) {
        if (e.name !== 'AbortError') {
          setError(e.message);
          setRunning(false);
        }
      }
    }
    read();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [running, scenario, token]);
  useEffect(() => {
    if (!user || user.role === 'patient' || !token) return;
    let stopped = false,
      ws,
      timer;
    function connect() {
      if (stopped) return;
      ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/cases');
      ws.onopen = () => {
        ws.send(JSON.stringify({
          token
        }));
        refresh().catch(e => setError(e.message));
      };
      ws.onmessage = e => {
        if (JSON.parse(e.data).type === 'case_changed') refresh().catch(e => setError(e.message));
      };
      ws.onclose = () => {
        if (!stopped) timer = setTimeout(connect, 2500);
      };
    }
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [user?.id, token]);
  useEffect(() => {
    if (!result?.case_id) return;
    const changed = cases.find(c => c.id === result.case_id);
    if (changed && changed.status !== result.review_status) api('/cases/' + result.case_id).then(data => {
      if (data.original) setResult(data.original);
    }).catch(e => setError(e.message));
  }, [cases, result?.case_id]);
  async function authenticate(e) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    await act(async () => {
      const body = {
        email: data.get('email'),
        password: data.get('password'),
        name: data.get('name'),
        consent: data.get('consent') === 'on'
      };
      const response = await api('/auth/' + (register ? 'register' : 'login'), {
        method: 'POST',
        body: JSON.stringify(body)
      });
      sessionStorage.setItem('medi-token', response.token);
      setToken(response.token);
    });
  }
  if (!user) return <div className="login"><div className="login-story"><Logo /><span className="eyebrow">{t("CARE THAT CONNECTS")}</span><h1>{t("A little clarity.")}<br />{t("A healthier tomorrow.")}</h1><p>{t("Understand your symptoms, follow your health, and connect with the right care \u2014 all in one place.")}</p><div className="login-art"><Heart size={90} /><Activity size={130} /></div><small>{t("Educational prototype \xB7 Use fictional health data")}</small></div><form className="login-form" onSubmit={authenticate}><label>{t("Language")}<select value={language} onChange={e => {
          setUiLanguage(e.target.value);
          setLanguage(e.target.value);
        }}><option value="en">English</option><option value="hi">हिन्दी</option></select></label><span className="eyebrow">{t("WELCOME TO MEDIASSIST")}</span><h2>{register ? t("Create your account") : t("Your health journey starts here.")}</h2><p>{t("Sign in to your personal care space.")}</p>{error && <div className="error" role="alert">{t(error)}</div>}{register && <label>{t("Full name")}<input name="name" required minLength="2" maxLength="100" /></label>}<label>{t("Email address")}<input name="email" type="email" required maxLength="200" defaultValue="patient@demo.local" /></label><label>{t("Password")}<input name="password" type="password" required maxLength="200" minLength={register ? 10 : 1} defaultValue="Demo@12345" /></label>{register && <label className="inline"><input type="checkbox" name="consent" required />{t("I consent to local processing of my health data for this prototype.")}</label>}<button className="primary" disabled={busy}>{busy ? t("Please wait\u2026") : register ? t("Create account") : t("Sign in")}<ArrowRight size={18} /></button><button type="button" className="text-button" onClick={() => setRegister(!register)}>{register ? t("Already registered? Sign in") : t("New here? Create an account")}</button><div className="demo-box"><strong>{t("Explore the demo")}</strong><p>{t("Password: Demo@12345")}</p><button type="button" onClick={e => {
          fillDemoAccount(e.currentTarget.form, 'patient@demo.local');
        }}>{t("Patient account")}</button><button type="button" onClick={e => {
          fillDemoAccount(e.currentTarget.form, 'doctor@demo.local');
        }}>{t("Doctor account")}</button><button type="button" onClick={e => fillDemoAccount(e.currentTarget.form, 'cardio@demo.local')}>{t("Cardiologist account")}</button><small>{t("Demo accounts are local and pre-consented. No real appointments are sent.")}</small></div></form></div>;
  const pending = cases.filter(c => c.status === 'pending');
  const blocked = user.role === 'patient' && !user.consent;
  async function enableConsent() {
    await act(async () => {
      const r = await api('/me/consent', {
        method: 'PUT',
        body: JSON.stringify({
          consent: true
        })
      });
      setUser({
        ...user,
        consent: r.consent
      });
      setNotice(t('Health processing enabled. You can now submit this form. Sharing records with an appointment remains optional.'));
    });
  }
  function voice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setError(t('Speech recognition is not supported by this browser. Please type your symptoms.'));
      return;
    }
    if (listening) {
      speechRef.current?.stop();
      return;
    }
    if (!window.confirm(t('Start voice input? Your browser may send audio to its speech recognition service. Typed input is also available.'))) return;
    const recognition = new Recognition();
    speechRef.current = recognition;
    recognition.lang = hi ? 'hi-IN' : 'en-IN';
    recognition.onresult = e => {
      const field = document.querySelector('textarea[name="symptoms"]');
      if (field) field.value += (field.value ? ' ' : '') + e.results[0][0].transcript;
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => {
      setListening(false);
      setError(t('Voice input failed or permission was denied. Please type your symptoms.'));
    };
    try {
      recognition.start();
      setListening(true);
    } catch {
      setError(t('Could not start voice input. Please type instead.'));
    }
  }
  return <div className="app"><aside><Logo /><span className="sidebar-caption">{t("YOUR HEALTH SPACE")}</span><nav>{navigation.filter(([n]) => user.role === 'patient' || ['Overview', 'Doctor review', 'Appointments', 'Notifications', 'Integrations', 'Privacy & settings'].includes(n)).map(([name, Icon]) => <button key={name} className={page === name ? 'active' : ''} onClick={() => {
          setPage(name);
          setError('');
          setNotice('');
        }}><Icon size={19} />{t(name)}{name === 'Doctor review' && pending.length > 0 && <b>{pending.length}</b>}</button>)}</nav><div className="care-card"><ShieldCheck size={25} /><strong>{t("Better together.")}</strong><p>{t("AI-assisted insights.")}<br />{t("Human-led care.")}</p><span>{t("Always a doctor in the loop")}</span></div><div className="profile"><div className="avatar">{user.name.replace('Dr. ', '').split(' ').map(x => x[0]).join('').slice(0, 2)}</div><div><strong>{user.name}</strong><small>{t(user.role)} {t("account")}</small></div><button aria-label={t("Sign out")} onClick={signOut}><LogOut size={17} /></button></div></aside><div className="workspace"><header><div><span className="breadcrumb">{t("My workspace")}</span><ChevronRight size={13} /><span>{t(page)}</span></div><div><span className="local-tag">{t("LOCAL PROTOTYPE")}</span><select aria-label={t("Language")} value={language} onChange={e => {
            setUiLanguage(e.target.value);
            setLanguage(e.target.value);
          }}><option value="en">{t("English")}</option><option value="hi">{t("\u0939\u093F\u0928\u094D\u0926\u0940")}</option></select><button aria-label={t("Open review notifications")} onClick={() => setPage('Notifications')}><Bell size={20} />{notifications.some(n => !n.seen) && <i />}</button></div></header><main>{!online && <div className="error" role="status">{t("You are offline. Reconnect before submitting health data. No clinical records are cached offline.")}</div>}{blocked && <section className="consent-banner" role="status"><div><strong>{hi ? 'स्वास्थ्य डेटा की अनुमति बंद है' : t("Health processing is paused")}</strong><p>{t("Your account consent is off. Enable local health-data processing to submit symptoms, reports, sensor readings or bookings. The appointment sharing checkbox is a separate choice.")}</p></div><button className="primary" disabled={busy} onClick={enableConsent}>{t("Enable health processing")}</button><button className="text-link" onClick={() => setPage('Privacy & settings')}>{t("Review privacy settings")}</button></section>}{error && <div className="error" role="alert">{t(error)}</div>}{notice && <div className="success" role="status">{t(notice)}</div>}

 {page === 'Overview' && user.role === 'patient' && <><div className="page-heading"><div><span className="eyebrow">{t("YOUR WELLNESS, AT A GLANCE")}</span><h1>{hi ? 'नमस्ते' : t("Hello")}, {user.name.replace('Dr. ', '').split(' ')[0]} <span className="wave">✺</span></h1><p>{t("Small insights today. Better health every day.")}</p></div><div className="today">{new Date().toLocaleDateString('en-IN', {
                weekday: 'long',
                day: 'numeric',
                month: 'long'
              })}<small><span className="dot" /> {t("Your connected care space")}</small></div></div><section className="hero"><div><span className="pill"><span className="dot" /> {t("MADE FOR YOUR PEACE OF MIND")}</span><h2>{t("Your health has a story.")}<br />{t("Let\u2019s understand it together.")}</h2><p>{t("From a symptom to the next step \u2014 find clarity")}<br className="desktop" /> {t("with support that keeps you at the centre.")}</p><button onClick={() => setPage(user.role === 'patient' ? 'Symptom checker' : 'Doctor review')}>{user.role === 'patient' ? t("Start a health check") : t("Open care queue")}<ArrowUpRight size={18} /></button></div><div className="hero-art"><div className="orbit o1" /><div className="orbit o2" /><div className="heart-disc"><Heart size={72} strokeWidth={1.5} /></div><span className="floating f1"><ShieldCheck size={21} />{t("Care you can understand")}</span><span className="floating f2"><Activity size={20} />{t("Connected to your wellbeing")}</span><span className="spark">✧</span></div></section>

 <div className="section-title"><div><h2>{t("Your health snapshot")}</h2><p>{running ? t("Live simulated readings \xB7 not a connected wearable") : history.length ? t("Latest stored simulated readings \xB7 not a live measurement") : t("Illustrative readings \xB7 start the simulator to record data")}</p></div><span className="subtle"><Radio size={15} />{running ? t("Simulator live") : t("Demo device")}</span></div><div className="vital-grid"><Vital icon={Heart} label={t("Heart rate")} value={vital.signal === false ? '—' : vital.hr} unit="bpm" color="rose" data={history.map(x => x.hr)} note={t("Pulse rate")} /><Vital icon={Wind} label={t("Blood oxygen")} value={vital.signal === false ? '—' : vital.spo2} unit="%" color="blue" data={history.map(x => x.spo2)} note={t("Oxygen saturation")} /><Vital icon={Thermometer} label={t("Body temperature")} value={vital.signal === false ? '—' : vital.temperature} unit="°C" color="amber" data={history.map(x => x.temperature)} note={t("Temperature reading")} /></div>

 <div className="dashboard-grid"><section className="panel ecg"><div className="section-title"><div><h2><Activity size={18} /> {t("Heart rhythm")}</h2><p>{t("Streaming ECG packets \xB7 synthetic simulator is not diagnostic")}</p><small>{vital.baseline_ready ? t("Personal baseline ready") : t("Personal baseline calibrating") + ": " + (vital.baseline_samples || 0) + " / 10 " + t("resting samples")}</small></div><span className="badge">{running ? t("SIMULATING") : t("DEMO PREVIEW")}</span></div><LiveECG samples={ecg.samples} sampleRate={ecg.sample_rate} signal={vital.signal !== false} /><div className="ecg-bottom"><span><span className="dot" /> {vital.signal === false ? t("Leads disconnected") : t("Synthetic signal")}</span><span>{t("WebSocket:")} {t(transport)}</span></div><div className="sim-controls"><select aria-label={t("Sensor scenario")} value={scenario} onChange={e => {
                  setRunning(false);
                  setScenario(e.target.value);
                }}>{['normal_rest', 'arrhythmia_episode', 'low_spo2', 'fever', 'fall', 'leads_off'].map(s => <option key={s} value={s}>{t(s.replaceAll('_', ' '))}</option>)}</select><button className="primary" disabled={user.role !== 'patient' || busy || blocked} onClick={() => act(async () => {
                  setRunning(!running);
                })}>{running ? t("Stop simulator") : t("Start simulator")}</button></div></section><section className="panel next-step"><span className="icon-circle"><Stethoscope size={24} /></span><span className="eyebrow">{t("A LITTLE SUPPORT GOES A LONG WAY")}</span><h2>{t("Not sure where")}<br />{t("to start?")}</h2><p>{t("Tell us what\u2019s on your mind. We\u2019ll help you understand a sensible next step.")}</p><button className="text-link" onClick={() => setPage(user.role === 'patient' ? 'Symptom checker' : 'Doctor review')}>{t("Let\u2019s talk about your health")}<ArrowRight size={18} /></button></section></div>

 <section className="panel"><h2>{t("24-hour recorded trends")}</h2><p>{t("Hourly averages from stored readings; blank hours have no measurements.")}</p><div className="trend-bars">{trends.map(t => <div key={t.hour} title={new Date(t.hour).toLocaleTimeString() + ' · ' + t.count + ' readings'}><span style={{
                  height: t.hr ? Math.min(t.hr.mean, 180) / 2 : 2,
                  background: t.hr ? '#78a38a' : '#e5ece7'
                }} /><small>{new Date(t.hour).getHours()}</small></div>)}</div></section><div className="section-title"><h2>{t("Your care, connected")}</h2><span className="subtle">{t("One place for your next steps")}</span></div><div className="quick-grid">{[[FileText, 'Make sense of your reports', 'Plain-language explanations', 'Health reports'], [Users, 'Find the right specialist', 'Explore your care options', 'Find a specialist'], [Calendar, 'Keep your care on track', t("Appointments planned")+": "+appointments.filter(a => a.status === 'booked').length, 'Appointments']].map(([Icon, title, desc, target]) => <button className="quick-card" key={title} onClick={() => setPage(user.role === 'patient' ? target : 'Doctor review')}><span className="icon-circle"><Icon size={22} /></span><div><strong>{t(title)}</strong><p>{t(desc)}</p></div><ArrowUpRight size={18} /></button>)}</div></>}

 {page === 'Overview' && user.role !== 'patient' && <><Heading eyebrow={t("CLINICIAN WORKSPACE")} title={t("Your care queue")} text={t("Review assigned cases and manage local appointment availability.")} /><div className="vital-grid"><section className="panel"><h2>{t("Pending reviews")}</h2><h1>{pending.length}</h1><button className="text-link" onClick={() => setPage('Doctor review')}>{t("Open review queue")}</button></section><section className="panel"><h2>{t("Urgent or emergency")}</h2><h1>{cases.filter(c => ['URGENT', 'EMERGENCY'].includes(c.urgency) && c.status === 'pending').length}</h1></section><section className="panel"><h2>{t("Local appointments")}</h2><h1>{appointments.filter(a => a.status === 'booked').length}</h1><button className="text-link" onClick={() => setPage('Appointments')}>{t("Manage appointments")}</button></section></div>{user.role === 'admin' && <button className="secondary" onClick={() => act(async () => {
            const result = await api('/audit/integrity');
            setNotice(result.valid ? 'Audit chain verified: ' + result.checked + ' rows.' : 'Audit integrity failure detected.');
          })}>{t("Verify audit integrity")}</button>}</>}
 {page === 'Symptom checker' && <><Heading eyebrow={t("LET\u2019S LISTEN")} title={t("How are you feeling?")} text={t("Share what you\u2019ve noticed. This preliminary assessment uses transparent prototype rules.")} /><div className="sim-controls"><button className="secondary" onClick={() => setIntakeMode("guided")}>{t("Guided conversation")}</button><button className="secondary" onClick={() => setIntakeMode("form")}>{t("Detailed form")}</button></div>{intakeMode === "guided" ? <Conversation api={api} blocked={blocked} language={language} onComplete={assessment => {
            setResult(assessment);
            refresh().catch(e => setError(e.message));
          }} /> : <div className="two-col"><form className="panel form" onSubmit={e => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const invalid = validateSymptoms(Object.fromEntries(f));
              if (invalid) {
                setError(invalid);
                return;
              }
              act(async () => {
                setResult(await api('/symptoms', {
                  method: 'POST',
                  body: JSON.stringify({
                    symptoms: f.get('symptoms'),
                    duration: f.get('duration'),
                    age: +f.get('age'),
                    severity: +f.get('severity')
                  })
                }));
                await refresh();
              });
            }}><label>{t("Describe your symptoms")}<textarea name="symptoms" minLength="3" maxLength="3000" required placeholder={t("For example: a cough and sore throat for two days\u2026")} /></label><button type="button" className="secondary" disabled={busy || blocked} onClick={async e => {
                const form = e.currentTarget.form;
                const text = form.elements.symptoms.value;
                await act(async () => {
                  const data = await api('/integrations/intake', {
                    method: 'POST',
                    body: JSON.stringify({
                      text
                    })
                  });
                  if (data.emergency) {
                    setResult({
                      ...data.emergency,
                      mode: data.mode
                    });
                    setNotice(t('Emergency guidance applies now. No model was called.'));
                    return;
                  }
                  if (data.duration !== 'Not specified') form.elements.duration.value = data.duration;
                  if (data.age) form.elements.age.value = data.age;
                  if (data.severity) setSeverity(data.severity);
                  setNotice(data.mode + '. Check the suggested fields before submitting.');
                });
              }}>{t("Suggest intake fields (local NLP)")}</button><button type="button" className="secondary" onClick={voice} disabled={blocked}>{listening ? t("Stop voice input") : t("Use voice input (optional)")}</button><div className="two-col"><label>{t("How long?")}<input name="duration" placeholder={t("2 days")} maxLength="100" required /></label><label>{t("Age")}<input name="age" type="number" min="1" max="120" defaultValue="30" required /></label></div><label>{t("Severity:")} {severity} {t("/ 10 (1 mild \u2014 10 severe)")}<input name="severity" type="range" min="1" max="10" value={severity} onChange={e => setSeverity(+e.target.value)} /></label><p className="subtle">{t("Include associated symptoms and existing conditions in your description.")}</p><button className="primary" disabled={busy || blocked}>{t("Get preliminary guidance")}<ArrowRight size={17} /></button></form><section className="panel"><span className="icon-circle"><MessageCircle /></span><h2>{result ? t("Your next step") : t("A starting point for care")}</h2>{result ? <><span className={'badge ' + (result.urgency === 'EMERGENCY' ? 'danger' : '')}>{t(result.urgency.replaceAll('_', ' '))}</span><p>{t(result.guidance)}</p>{result.possibilities.map(x => <p key={x}>{x}</p>)}<p><strong>{t("Suggested care:")}</strong> {result.specialist}</p><small>{result.mode}</small><hr /><p>{result.pending_review ? t("Awaiting assigned doctor review. Unapproved condition suggestions are withheld.") : result.urgency === "EMERGENCY" ? t("Emergency guidance applies immediately.") : t("Approved guidance released by your doctor.")}</p></> : <p>{t("Your results will appear here. This tool cannot rule out serious illness. For an emergency, seek local emergency care immediately.")}</p>}</section></div>}</>}

 {page === 'Health reports' && <><Heading eyebrow={t("LESS JARGON. MORE CLARITY.")} title={t("Understand your health reports")} text={t("Your original numbers stay unchanged. Explanations help you prepare for a doctor\u2019s conversation.")} /><div className="two-col"><form className="panel form" onSubmit={e => {
              e.preventDefault();
              const text = new FormData(e.currentTarget).get('text');
              act(async () => {
                setReport(await api('/reports', {
                  method: 'POST',
                  body: JSON.stringify({
                    text
                  })
                }));
                await refresh();
              });
            }}><label>{t("Paste labelled lab values with units")}<textarea name="text" required minLength="3" maxLength="30000" defaultValue={'Hemoglobin: 11.2 g/dL\nGlucose: 108 mg/dL\nCholesterol: 185 mg/dL\nTSH: 2.1 mIU/L'} /></label><button className="primary" disabled={busy || blocked}>{t("Explain these values")}<ArrowRight size={17} /></button><hr /><label>{t("Or upload a PDF / .txt / PNG / JPEG (up to 5 MB)")}<input type="file" accept=".pdf,.txt,.png,.jpg,.jpeg" disabled={busy || blocked} onChange={e => {
                  const file = e.target.files[0];
                  if (file) act(async () => {
                    if (file.size > 5000000) throw Error('Maximum file size is 5 MB. Choose a smaller report.');
                    const body = new FormData();
                    body.append('file', file);
                    setReport(await api('/reports/upload', {
                      method: 'POST',
                      body,
                      signal: AbortSignal.timeout(90000)
                    }));
                    await refresh();
                  });
                }} /></label><small>{t("Image OCR requires local Tesseract. Scanned PDFs also need PyMuPDF. If unavailable, paste text or upload a readable PDF.")}</small></form><section className="panel"><h2>{t("Your report, in plain language")}</h2>{report ? <><p>{t(report.summary)}</p>{report.document_id && <button className="secondary" onClick={() => act(() => downloadOriginal(report.document_id, report.document_name))}>{t("Download original report")}</button>}{report.source_text && <details><summary>{t("Original extracted text")}</summary><pre className="record-detail">{report.source_text}</pre></details>}{report.values.map((r, i) => <div className="lab" key={i}><div><strong>{t(r.name)}</strong><b>{r.display_value || r.value} {r.unit}</b></div><span className={"badge " + (r.flag.includes("within") ? "" : "danger")}>{t(r.flag)}</span><p>{t(r.explanation)}</p><small>{referenceLabel(r.reference)}</small></div>)}<h3>{t("Questions for your doctor")}</h3>{report.questions.map(q => <p key={q}>• {t(q)}</p>)}<small>{t("Submitted for clinician review.")}</small></> : <p>{t("Try the fictional example to see extracted values, illustrative ranges, and questions to ask.")}</p>}</section></div></>}

 {page === 'Find a specialist' && <><Heading eyebrow={t("THE RIGHT SUPPORT, CLOSER")} title={t("Find your care team")} text={t("Fictional specialists for demonstration. Bookings stay inside this local prototype.")} /><div className="filters"><Search size={19} /><select aria-label={t("City")} value={city} onChange={e => setCity(e.target.value)}><option value="">{t("All cities")}</option>{['Mumbai', 'Delhi', 'Bengaluru', 'Chennai', 'Pune', 'Hyderabad'].map(x => <option key={x}>{x}</option>)}</select><select aria-label={t("Specialty")} value={specialty} onChange={e => setSpecialty(e.target.value)}><option value="">{t("All specialties")}</option>{['General physician', 'Cardiology', 'Dermatology', 'Pulmonology', 'Endocrinology'].map(x => <option key={x}>{x}</option>)}</select><select aria-label={t("Specialist language")} value={doctorLanguage} onChange={e => setDoctorLanguage(e.target.value)}><option value="">{t("All languages")}</option>{['English', 'Hindi', 'Tamil', 'Marathi'].map(x => <option key={x}>{x}</option>)}</select><select aria-label={t("Near city")} value={nearCity} onChange={e => setNearCity(e.target.value)}><option value="">{t("No distance filter")}</option>{Object.keys(cityCoordinates).map(c => <option key={c}>{c}</option>)}</select>{nearCity && <select aria-label={t("Radius in kilometres")} value={radius} onChange={e => setRadius(e.target.value)}>{[25, 50, 100, 250, 1000].map(k => <option key={k} value={k}>{k} {t("km")}</option>)}</select>}<label>{t("Available on")}<input type="date" aria-label={t("Available on")} value={availableDay} min={indiaDay()} max={indiaDay(90)} onChange={e => setAvailableDay(e.target.value)} /></label><span>{doctors.length} {t("demo specialists")}</span></div><div className="doctor-grid">{doctors.map(d => <BookingCard key={d.id + '-' + availableDay} doctor={d} initialDay={availableDay} api={api} blocked={blocked} onBooked={async () => {
              await refresh();
              setNotice(t('Your local appointment is booked. See Appointments for details.'));
            }} />)}{!doctors.length && <p>{t("No specialists match these filters. Try another city, specialty or language.")}</p>}</div></>}

 {page === 'Appointments' && <>{user.role !== 'patient' && <Availability api={api} />}<Heading eyebrow={t("MAKE TIME FOR YOUR HEALTH")} title={t("Your appointments")} text={user.role === 'patient' ? 'Manage your local demonstration bookings.' : 'Shared demo clinician-team appointment view. Only explicitly shared records can be opened.'} />{appointments.length ? appointments.map(a => <section className="panel appointment" key={a.id}><span className="icon-circle"><Calendar /></span><div><h3>{a.name}</h3><p>{a.specialty} · {a.slot.replace('T', ' at ')} {t("IST")}</p><small>{a.share ? t("Sharing consent recorded") : t("Health sharing not selected")} {t("\xB7 Demo booking")}</small></div><span className="badge">{a.status === 'cancelled' ? t("CANCELLED") : t("BOOKED LOCALLY")}</span>{user.role === 'patient' && a.status === 'booked' && <button className="secondary" disabled={busy} onClick={() => act(async () => {
              await api(`/appointments/${a.id}/cancel`, {
                method: 'POST'
              });
              await refresh();
              setNotice(t('Appointment cancelled. The slot is available again.'));
            })}>{t("Cancel appointment")}</button>}{user.role !== 'patient' && a.status === 'booked' && <button className="secondary" onClick={() => act(async () => {
              const data = await api(`/appointments/${a.id}/shared-records`);
              setDetails(old => ({
                ...old,
                ['appointment' + a.id]: data
              }));
            })}>{t("View consented records")}</button>}{details['appointment' + a.id] && <pre className="record-detail">{JSON.stringify(details['appointment' + a.id], null, 2)}</pre>}</section>) : <Empty icon={Calendar} text={t("No appointments yet")} action={() => setPage('Find a specialist')} label={t("Explore specialists")} />}</>}

 {page === 'Doctor review' && <><Heading eyebrow={t("HUMAN-LED CARE")} title={user.role === 'patient' ? 'Your clinician reviews' : 'Clinical review queue'} text={t("Emergency instructions are immediate. Other prototype outputs await a clinician\u2019s review.")} /><button className="text-link" onClick={() => act(refresh)}>{t("Refresh queue")} <Radio size={16} /></button>{cases.length ? cases.map(c => <section className="panel case" key={c.id}><div className="section-title"><div><span className={'badge ' + (c.urgency === 'EMERGENCY' ? 'danger' : '')}>{t(c.urgency.replaceAll('_', ' '))}</span><h3>{t("Case #")}{c.id} · {c.source.replaceAll('_', ' ')}</h3></div><span className="subtle">{t(c.status.replaceAll('_', ' '))}</span></div><p>{c.summary}</p><small>{new Date(c.created * 1000).toLocaleString()}</small><div><button className="text-link" onClick={() => act(async () => {
                const d = await api(`/cases/${c.id}`);
                setDetails(old => ({
                  ...old,
                  [c.id]: d.original,
                  ["followups"+c.id]:d.followups
                }));
              })}>{t("View original submitted data")}</button></div>{details[c.id] && <pre className="record-detail">{JSON.stringify(details[c.id], null, 2)}</pre>}{details[c.id]?.document_id && <button className="text-link" onClick={() => act(() => downloadOriginal(details[c.id].document_id, details[c.id].document_name))}>{t("Download original report")}</button>}{user.role === 'doctor' && <button className="text-link" onClick={() => act(async () => {
              const data = await api('/cases/' + c.id + '/ecg-window');
              setDetails(old => ({
                ...old,
                ['ecg' + c.id]: data
              }));
            })}>{t("View ECG around alert")}</button>}{details['ecg' + c.id] && <div><LiveECG staticWindow samples={details['ecg' + c.id].samples} sampleRate={250} highlight={details['ecg' + c.id].highlight} /><small>{details['ecg' + c.id].description}</small></div>}{details["followups"+c.id]?.map((f,i)=><blockquote key={i}><strong>{t("Patient follow-up")}</strong><p>{f.text}</p></blockquote>)}{c.review && <blockquote><strong>{t("Clinician note")}</strong><p>{c.review}</p></blockquote>}{user.role==='patient' && c.status==='needs_info' && <PatientReply api={api} caseId={c.id} onSaved={async response=>{if(response.emergency)setError(response.emergency.guidance);await refresh();}}/>}{user.role === 'doctor' && <form className="review-form" onSubmit={e => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              act(async () => {
                await api(`/cases/${c.id}/review`, {
                  method: 'POST',
                  body: JSON.stringify({
                    action: f.get('action'),
                    note: f.get('note'),
                    edited_guidance: f.get('edited_guidance') || null
                  })
                });
                await refresh();
                setNotice(t('Review saved to the audit trail.'));
              });
            }}><select name="action" aria-label={t("Review action")}><option value="approved">{t("Approve guidance")}</option><option value="edited_approved">{t("Edit & approve")}</option><option value="needs_info">{t("Request information")}</option><option value="rejected">{t("Reject with reason")}</option><option value="escalated">{t("Escalate")}</option></select><input name="note" aria-label={t("Clinician note")} required minLength="5" maxLength="2000" placeholder={t("Add clinical guidance or reason\u2026")} /><textarea name="edited_guidance" aria-label={t("Edited guidance")} maxLength="3000" placeholder={t("Final guidance, required for Edit & approve")} /><button className="primary" disabled={busy}>{t("Save review")}<Check size={16} /></button></form>}</section>) : <Empty icon={ShieldCheck} text={t("No reviews in your queue")} />}</>}

 {page === 'Notifications' && <><Heading eyebrow={t("YOUR CARE UPDATES")} title={t("Notifications")} text={t("Local updates about your bookings, alerts and clinician reviews.")} /><button className="text-link" onClick={() => act(refresh)}>{t("Refresh notifications")}</button>{notifications.length ? notifications.map(n => <section className="panel" key={n.id}><span className="badge">{n.seen ? t("READ") : t("NEW")}</span><p>{n.message}</p><small>{new Date(n.created * 1000).toLocaleString()}</small>{!n.seen && <button className="text-link" onClick={() => act(async () => {
              await api(`/notifications/${n.id}/read`, {
                method: 'POST'
              });
              await refresh();
            })}>{t("Mark as read")}</button>}</section>) : <Empty icon={Bell} text={t("You\u2019re all caught up")} />}</>}

 {page === 'Health history' && <><Heading eyebrow={t("YOUR RECORDS")} title={t("Health history")} text={t("Saved symptoms, reports and readings from your own account.")} />{records.length ? records.map(r => <details className="panel" key={r.id}><summary>{r.kind.replaceAll('_', ' ')} · {new Date(r.created * 1000).toLocaleString()}</summary><pre className="record-detail">{JSON.stringify(JSON.parse(r.payload), null, 2)}</pre></details>) : <Empty icon={Activity} text={blocked ? 'Enable consent to load your health history' : 'No health records yet'} />}</>}

 {page === 'Demo' && user.role === 'patient' && <DemoPanel api={api} blocked={blocked} onComplete={refresh} />}
 {page === 'Integrations' && <><Heading eyebrow={t("CONNECTED CARE ROADMAP")} title={t("Integrations & capabilities")} text={t("See exactly what runs locally and what requires additional hardware or configuration.")} /><div className="two-col">{integrations.map(i => <section className="panel" key={i.name}><span className="badge">{t(i.state)}</span><h3>{t(i.name)}</h3><p>{t(i.detail)}</p></section>)}</div><section className="panel"><h2>{t("Notification outbox")}</h2><p>{t("Mock messages stay local. Configured delivery requires consent. Accepted means provider acceptance, not confirmed delivery.")}</p>{outbox.length ? outbox.map(o => <pre className="record-detail" key={o.id}>{o.status} {t("\xB7 attempts:")} {o.attempts} · {o.payload}</pre>) : <p>{t("No emergency mock messages yet.")}</p>}</section></>}

 {page === 'Privacy & settings' && <>{user.role === 'patient' && <NotificationSettings api={api} blocked={blocked} />}<Heading eyebrow={t("YOUR DATA. YOUR CHOICE.")} title={t("Privacy & preferences")} text={t("This local prototype stores records in a SQLite database on this computer.")} /><section className="panel settings"><h2>{t("Health data consent")}</h2><p>{t("Consent is required to submit symptoms, reports, sensor readings, or appointments. You can withdraw it at any time.")}</p><button className="primary" disabled={busy} onClick={() => act(async () => {
              const r = await api('/me/consent', {
                method: 'PUT',
                body: JSON.stringify({
                  consent: !user.consent
                })
              });
              setUser({
                ...user,
                consent: r.consent
              });
              setRunning(false);
              setNotice(t('Your consent preference was updated.'));
            })}>{user.consent ? t("Withdraw consent") : t("Give consent")}</button><hr /><h2>{t("Take a copy of your data")}</h2><p>{t("Download your profile, health records, reviews, and appointments as JSON.")}</p><button className="secondary" disabled={busy} onClick={() => act(async () => {
              const data = await api('/me/export');
              const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {
                type: 'application/json'
              }));
              const a = document.createElement('a');
              a.href = url;
              a.download = 'mediassist-export.json';
              a.click();
              URL.revokeObjectURL(url);
            })}><Download size={17} />{t("Export my data")}</button><hr /><h2>{t("Delete your account")}</h2><p>{t("Deletes your stored health records, appointments, and account. This cannot be undone.")}</p><button className="delete" disabled={busy} onClick={() => {
              if (window.confirm(t('Permanently delete this local account and all its health records?'))) act(async () => {
                await api('/me', {
                  method: 'DELETE'
                });
                logout();
              });
            }}>{t("Delete account and records")}</button></section></>}

 <footer><ShieldCheck size={16} /><span>{hi ? 'चिकित्सा निदान का विकल्प नहीं।' : t("A support tool, never a substitute for professional medical care.")} <a href="https://www.nhsinform.scot/illnesses-and-conditions/lungs-and-airways/shortness-of-breath" target="_blank" rel="noreferrer">{t("Emergency warning signs \u2197")}</a></span><span>{t("MediAssist AI \xB7 Prototype")}</span></footer></main></div></div>;
}
function BookingCard({
  doctor: d,
  api,
  blocked,
  onBooked,
  initialDay
}) {
  const [day, setDay] = useState(initialDay || indiaDay(1)),
    [slots, setSlots] = useState([]),
    [selected, setSelected] = useState(''),
    [loading, setLoading] = useState(false),
    [saving, setSaving] = useState(false),
    [message, setMessage] = useState(''),
    [success, setSuccess] = useState(''),
    [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSelected('');
    setMessage('');
    api(`/doctors/${d.id}/slots?day=${day}`).then(r => {
      if (!cancelled) setSlots(r.slots);
    }).catch(e => {
      if (!cancelled) {
        setSlots([]);
        setMessage(e.message);
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [day, d.id, version]);
  return <form className="panel doctor" aria-label={'Book ' + d.name + ' in ' + d.city} onSubmit={async e => {
    e.preventDefault();
    setMessage('');
    setSuccess('');
    if (blocked) {
      setMessage(t('Enable health processing using the banner above before booking.'));
      return;
    }
    if (!selected) {
      setMessage(t('Choose an available appointment time.'));
      return;
    }
    const f = new FormData(e.currentTarget);
    setSaving(true);
    try {
      await api('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          doctor_id: d.id,
          slot: selected,
          share: f.get('share') === 'on'
        })
      });
      setSuccess('Booked successfully. Find it in Appointments.');
      setVersion(v => v + 1);
      await onBooked();
    } catch (e) {
      setMessage(e.message);
      setVersion(v => v + 1);
    } finally {
      setSaving(false);
    }
  }}>

 <div className="doctor-head"><div className="doctor-avatar"><Stethoscope size={28} /></div><div><h3>{d.name}</h3><span>{t(d.specialty)}</span></div></div><p>{d.city} · {d.language}</p>{d.distance_km !== undefined && <small>{d.distance_km} {t("km \xB7 approximate city-centre location")}</small>}<span className="badge">{t("FICTIONAL DEMO PROFILE")}</span>

 <label>{t("Appointment date (India)")}<input type="date" required min={indiaDay()} max={indiaDay(90)} value={day} onChange={e => {
        if (e.target.value) setDay(e.target.value);
      }} /></label>

 <label>{t("Available time (24-hour, IST)")}<select name="slot" required value={selected} disabled={loading || saving || !slots.length} onChange={e => setSelected(e.target.value)}><option value="">{loading ? t("Loading available times\u2026") : slots.length ? t("Select a time") : t("No available times on this date")}</option>{slots.map(slot => <option key={slot} value={slot}>{slotLabel(slot)}</option>)}</select></label>

 <small>{t("Only available future slots appear \xB7 09:00\u201317:30 IST")}</small><label className="inline"><input type="checkbox" name="share" />{t("Also allow the demo clinician team to read my records for this appointment (optional)")}</label>

 {blocked && <small className="field-error">{t("Health processing is paused. Enable consent in the banner above.")}</small>}{message && <div className="error" role="alert">{t(message)}</div>}{success && <div className="success" role="status">{success}</div>}<button className="primary" disabled={saving || blocked || loading || !selected}>{saving ? t("Booking\u2026") : t("Book demo appointment")}<Plus size={16} /></button><button type="button" className="text-link" disabled={loading || saving} onClick={() => setVersion(v => v + 1)}>{t("Refresh available times")}</button></form>;
}
function Logo() {
  return <div className="logo"><span><Plus size={26} strokeWidth={3} /></span><strong>{t("MediAssist")}<span>{t("AI")}</span></strong></div>;
}
function Heading({
  eyebrow,
  title,
  text
}) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{t(title)}</h1><p>{t(text)}</p></div></div>;
}
function Empty({
  icon: Icon,
  text,
  action,
  label
}) {
  return <section className="panel empty"><Icon size={45} /><h2>{t(text)}</h2>{action && <button className="primary" onClick={action}>{label}<ArrowRight size={17} /></button>}</section>;
}
function Vital({
  icon: Icon,
  label,
  value,
  unit,
  color,
  data,
  note
}) {
  const min = Math.min(...data),
    max = Math.max(...data),
    points = data.length > 1 ? data.map((n, i) => `${i / (data.length - 1) * 140},${37 - (n - min) / (max - min || 1) * 28}`).join(' ') : '0,30 20,28 35,32 50,20 65,24 80,12 95,17 110,10 125,18 140,14';
  return <section className={'vital ' + color}><div className="vital-label"><span className="icon-circle"><Icon size={19} /></span><span>{label}</span><span>↗</span></div><div className="vital-reading"><strong>{value}</strong><span>{unit}</span><svg viewBox="0 0 140 45"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /></svg></div><div className="vital-foot"><span className="dot" />{note}<small>{t("Simulated")}</small></div></section>;
}
createRoot(document.getElementById('root')).render(<App />);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
