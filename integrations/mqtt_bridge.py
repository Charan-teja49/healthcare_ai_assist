"""Optional MQTT to authenticated shared HTTP ingestion."""
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def forward(topic,payload,token,base,device_id):
    if topic not in [f'mediassist/{device_id}/'+name for name in ('vitals','ecg','events')]:
        raise ValueError('Unexpected topic')
    data=json.loads(payload)
    data['device_id']=device_id
    data['kind']={'vitals':'vitals','ecg':'ecg','events':'event'}[topic.rsplit('/',1)[1]]
    data.setdefault('timestamp',time.time())
    data.setdefault('source','device')
    request=Request(base.rstrip('/')+'/api/devices/ingest',json.dumps(data).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
    with urlopen(request,timeout=10) as response:
        return json.load(response)

def main():
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit('Install optional MQTT support: python -m pip install -r integrations/requirements.txt')
    token=os.getenv('MEDIASSIST_PATIENT_TOKEN','')
    if not token:
        sys.exit('Set MEDIASSIST_PATIENT_TOKEN to a signed-in patient JWT first. Never place it in source files.')
    device=os.getenv('MQTT_DEVICE_ID','esp32-demo')
    base=os.getenv('MEDIASSIST_API','http://127.0.0.1:8010')
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if os.getenv('MQTT_USERNAME'):
        client.username_pw_set(os.environ['MQTT_USERNAME'],os.getenv('MQTT_PASSWORD',''))
    if os.getenv('MQTT_TLS')=='1':
        client.tls_set()
    def connected(client,userdata,flags,reason_code,properties):
        if reason_code==0:
            client.subscribe(f'mediassist/{device}/#',qos=1)
    def received(client,userdata,message):
        try:
            forward(message.topic,message.payload,token,base,device)
            print('Reading accepted by API')
        except (ValueError,HTTPError,URLError,TimeoutError):
            print('Reading rejected or API unavailable; check session, consent and payload. No patient data logged.',file=sys.stderr)
    client.on_connect=connected
    client.on_message=received
    client.connect(os.getenv('MQTT_HOST','127.0.0.1'),int(os.getenv('MQTT_PORT','1883')),60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()

if __name__=='__main__':
    main()
