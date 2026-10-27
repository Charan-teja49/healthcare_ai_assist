import i18next from 'i18next';
import hindi from '../locales/hi.json';
export const languageMetadata = {en:{name:'English',ready:true},hi:{name:'हिन्दी',ready:true},mr:{name:'मराठी',ready:false},ta:{name:'தமிழ்',ready:false}};
const english=Object.fromEntries(Object.keys(hindi).map(key=>[key,key]));
i18next.init({lng:globalThis.localStorage?.getItem('medi-language')||'en',fallbackLng:'en',supportedLngs:['en','hi','mr','ta'],keySeparator:false,nsSeparator:false,initImmediate:false,interpolation:{escapeValue:false},resources:{en:{translation:english},hi:{translation:hindi},mr:{translation:{}},ta:{translation:{}}}});
export function t(text){return typeof text==='string'?i18next.t(text,{defaultValue:text}):text;}
export async function setUiLanguage(language){await i18next.changeLanguage(language);globalThis.localStorage?.setItem('medi-language',language);if(globalThis.document)document.documentElement.lang=language;}
export default i18next;

export function referenceLabel(text){return text.replace('illustrative adult example',t('illustrative adult example')).replace('printed report',t('printed report')).replace('printed range needs review',t('printed range needs review'));}
