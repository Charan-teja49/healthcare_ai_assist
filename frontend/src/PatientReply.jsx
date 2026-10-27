import React,{useState} from 'react';
import {t} from './i18n.js';
export default function PatientReply({api,caseId,onSaved}){
 const [text,setText]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[emergency,setEmergency]=useState(null);
 return <div>{emergency&&<div className="error" role="alert"><strong>{t('EMERGENCY')}</strong><p>{t(emergency.guidance)}</p></div>}<form className="form" onSubmit={async e=>{e.preventDefault();setBusy(true);setMessage('');try{const result=await api('/cases/'+caseId+'/followup',{method:'POST',body:JSON.stringify({text})});setEmergency(result.emergency);setMessage(t('Your reply was sent to the assigned doctor.'));setText('');await onSaved(result);}catch(e){setMessage(e.message);}finally{setBusy(false);}}}><label>{t('Reply to your doctor')}<textarea required minLength="3" maxLength="3000" value={text} onChange={e=>setText(e.target.value)}/></label><button className="primary" disabled={busy}>{t('Send information')}</button><p role="status">{t(message)}</p></form></div>;
}
