export function errorMessage(data){
 if(typeof data?.detail==='string')return data.detail;
 if(Array.isArray(data?.detail))return data.detail.map(x=>`${(x.loc||[]).filter(k=>!['body','query','path'].includes(k)).join('.')||'Input'}: ${x.msg}`).join('; ');
 return 'The request could not be completed. Please try again.';
}
export function indiaDay(offset=0,now=new Date()){
 const d=new Date(now.getTime()+330*60000+offset*86400000);
 return d.toISOString().slice(0,10);
}
export function slotLabel(slot){return slot.slice(11)+' IST (24-hour clock)';}
export function fillDemoAccount(form,email){
 form.elements.namedItem('email').value=email;
 form.elements.namedItem('password').value='Demo@12345';
}
export function validateSymptoms({symptoms,duration,age,severity}){
 if(symptoms.trim().length<3)return 'Describe your symptoms using at least 3 characters.';
 if(!duration.trim())return 'Please enter how long you have had these symptoms.';
 if(!Number.isInteger(Number(age))||+age<1||+age>120)return 'Age must be a whole number from 1 to 120.';
 if(!Number.isInteger(Number(severity))||+severity<1||+severity>10)return 'Severity must be a whole number from 1 to 10.';
 return '';
}
