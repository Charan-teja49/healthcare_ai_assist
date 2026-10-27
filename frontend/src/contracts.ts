export type Scenario = 'normal_rest'|'arrhythmia_episode'|'low_spo2'|'fever'|'fall'|'leads_off';
export type Urgency = 'SELF_CARE'|'CONSULT_SOON'|'URGENT'|'EMERGENCY';
export interface ReviewCase {id:number;source:string;urgency:Urgency;status:string}
interface PacketBase {device_id:string;event_id:string;timestamp:number;source:'device'|'simulator';signal:boolean}
export type SensorPacket =
 | (PacketBase & {kind:'vitals';hr:number;spo2:number;temperature:number})
 | (PacketBase & {kind:'ecg';sample_rate:250|360;samples:number[]})
 | (PacketBase & {kind:'event';event:'fall'|'leads_off'|'restored';fall_detected?:boolean});
export interface DemoReplay {scenario:Scenario;synthetic:true;compressed_seconds:number;packet_count:number;final:SensorPacket;fall_detected:boolean;new_cases:ReviewCase[];related_cases:ReviewCase[]}
export type Api = <T>(path:string,options?:RequestInit)=>Promise<T>;
