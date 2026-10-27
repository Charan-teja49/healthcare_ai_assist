// Educational acquisition firmware. Real measurements require calibration and testing.
#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <MAX30105.h>
#include <spo2_algorithm.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <sys/time.h>
#include "pins.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif
#ifndef MEDIASSIST_SIMULATOR
#define MEDIASSIST_SIMULATOR 1
#endif

WiFiClient network;
PubSubClient mqtt(network);
MAX30105 pulse;
Adafruit_MPU6050 motion;
Adafruit_SSD1306 display(128,64,&Wire,-1);
OneWire oneWire(TEMPERATURE_PIN);
DallasTemperature temperatureSensor(&oneWire);
bool pulseReady=false,motionReady=false,displayReady=false;
bool pulseValid=false,temperatureValid=false;
bool lastLeadsOff=true;
float heartRate=0,oxygen=0,temperatureC=0,accelerationG=1;
uint32_t ir[100],red[100],opticalCount=0;
uint32_t bootId,sequence=0,lastVitals=0,lastMotion=0,lastTemp=0,lastScreen=0,lastConnect=0,lastOptical=0,alarmUntil=0,fallUntil=0,lastFallPacket=0;
bool fallActive=false;
struct ECGFrame { float samples[ECG_FRAME_SAMPLES]; double timestamp; uint32_t sequence; };
QueueHandle_t ecgQueue;
uint32_t droppedFrames=0;

double epochSeconds(){
 timeval now;gettimeofday(&now,nullptr);
 return now.tv_sec+now.tv_usec/1000000.0;
}
bool clockReady(){return epochSeconds()>1700000000;}
bool leadsOff(){return !MEDIASSIST_SIMULATOR&&(digitalRead(ECG_LO_PLUS)||digitalRead(ECG_LO_MINUS));}
void envelope(JsonDocument& doc,const char* kind,double timestamp=0){
 doc["kind"]=kind;doc["device_id"]=DEVICE_ID;
 doc["event_id"]=String(bootId)+"-"+String(++sequence);
 doc["timestamp"]=timestamp>0?timestamp:epochSeconds();
 doc["source"]=MEDIASSIST_SIMULATOR?"simulator":"device";
 doc["activity"]="unknown";doc["acceleration_mode"]="raw";
}
bool publish(JsonDocument& doc,const char* channel){
 if(!mqtt.connected()||!clockReady())return false;
 String output;serializeJson(doc,output);
 String topic=String("mediassist/")+DEVICE_ID+"/"+channel;
 bool accepted=mqtt.publish(topic.c_str(),output.c_str());
 if(!accepted)Serial.println("MQTT publish failed; no measurement retransmission with a new ID");
 return accepted;
}
void event(const char* name){
 JsonDocument doc;envelope(doc,"event");doc["event"]=name;
 doc["signal"]=strcmp(name,"leads_off")!=0;doc["acceleration"]["magnitude"]=accelerationG;
 publish(doc,"events");
}
void acquireECG(void*){
 TickType_t next=xTaskGetTickCount();ECGFrame frame{};size_t count=0;uint32_t sampleIndex=0,frameSequence=0;
 for(;;){
  if(leadsOff()||!clockReady()){count=0;}
  else{
   if(count==0)frame.timestamp=epochSeconds();
   if(MEDIASSIST_SIMULATOR){
    float phase=fmodf(sampleIndex/250.0f*1.2f,1.0f);
    frame.samples[count]=expf(-powf((phase-.4f)/.02f,2))-.15f*expf(-powf((phase-.44f)/.02f,2));
   }else{
    // ADC volts normalized around midscale, not a calibrated millivolt value.
    frame.samples[count]=(analogRead(ECG_ADC)-2048)/2048.0f;
   }
   sampleIndex++;count++;
   if(count==ECG_FRAME_SAMPLES){
    frame.sequence=++frameSequence;
    if(xQueueSend(ecgQueue,&frame,0)!=pdTRUE){ECGFrame discarded;xQueueReceive(ecgQueue,&discarded,0);xQueueSend(ecgQueue,&frame,0);droppedFrames++;}
    count=0;
   }
  }
  vTaskDelayUntil(&next,pdMS_TO_TICKS(1000/ECG_HZ));
 }
}
void setup(){
 Serial.begin(115200);bootId=esp_random();
 pinMode(ECG_LO_PLUS,INPUT_PULLUP);pinMode(ECG_LO_MINUS,INPUT_PULLUP);
 pinMode(BUZZER_PIN,OUTPUT);digitalWrite(BUZZER_PIN,LOW);
 analogReadResolution(12);Wire.begin(I2C_SDA,I2C_SCL);
 if(!MEDIASSIST_SIMULATOR){
  pulseReady=pulse.begin(Wire,I2C_SPEED_FAST);
  if(pulseReady)pulse.setup(60,4,2,100,411,4096); // 25 averaged samples/s, four-second algorithm window.
  motionReady=motion.begin();
  if(motionReady){motion.setAccelerometerRange(MPU6050_RANGE_8_G);motion.setFilterBandwidth(MPU6050_BAND_21_HZ);}
  temperatureSensor.begin();temperatureSensor.setWaitForConversion(false);temperatureSensor.requestTemperatures();lastTemp=millis();
 }
 displayReady=display.begin(SSD1306_SWITCHCAPVCC,0x3C);
 WiFi.mode(WIFI_STA);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
 configTime(0,0,"pool.ntp.org","time.nist.gov");
 mqtt.setServer(MQTT_HOST,MQTT_PORT);mqtt.setBufferSize(12000);mqtt.setSocketTimeout(1);
 ecgQueue=xQueueCreate(2,sizeof(ECGFrame));
 if(!ecgQueue){Serial.println("ECG queue allocation failed");return;}
 xTaskCreatePinnedToCore(acquireECG,"ECG250Hz",4096,nullptr,2,nullptr,1);
 Serial.println(MEDIASSIST_SIMULATOR?"MODE: SIMULATOR":"MODE: PHYSICAL SENSORS (uncalibrated)");
}
void loop(){
 uint32_t now=millis();
 if(WiFi.status()==WL_CONNECTED&&!mqtt.connected()&&now-lastConnect>=5000){
  lastConnect=now;String clientId=String(DEVICE_ID)+"-"+String(bootId);
  mqtt.connect(clientId.c_str(),MQTT_USERNAME,MQTT_PASSWORD);
 }
 mqtt.loop();
 if(MEDIASSIST_SIMULATOR){heartRate=72;oxygen=98;temperatureC=36.7;accelerationG=1;pulseValid=true;temperatureValid=true;}
 else{
  if(pulseReady){
   pulse.check();
   while(pulse.available()){
    ir[opticalCount]=pulse.getIR();red[opticalCount]=pulse.getRed();pulse.nextSample();opticalCount++;
    if(opticalCount==100){
     int32_t spo2,hr;int8_t spo2Valid,hrValid;
     maxim_heart_rate_and_oxygen_saturation(ir,100,red,&spo2,&spo2Valid,&hr,&hrValid);
     pulseValid=spo2Valid&&hrValid&&hr>=25&&hr<=250&&spo2>=50&&spo2<=100&&ir[99]>50000;
     if(pulseValid){heartRate=hr;oxygen=spo2;lastOptical=now;}
     opticalCount=0;
    }
   }
  }
  if(now-lastOptical>10000)pulseValid=false;
  if(now-lastTemp>=1000){
   lastTemp=now;float measured=temperatureSensor.getTempCByIndex(0);
   temperatureValid=isfinite(measured)&&measured>=30&&measured<=45;
   if(temperatureValid)temperatureC=measured;
   temperatureSensor.requestTemperatures();
  }
  if(motionReady&&now-lastMotion>=20){
   lastMotion=now;sensors_event_t a,g,t;motion.getEvent(&a,&g,&t);
   accelerationG=sqrtf(a.acceleration.x*a.acceleration.x+a.acceleration.y*a.acceleration.y+a.acceleration.z*a.acceleration.z)/9.80665f;
   if(accelerationG>3&&!fallActive){fallActive=true;fallUntil=now+10000;alarmUntil=now+200;event("fall");lastFallPacket=now;}
  }
 }
 if(fallActive){
  if((int32_t)(now-fallUntil)>=0)fallActive=false;
  else if(now-lastFallPacket>=200){lastFallPacket=now;event("fall");}
 }
 digitalWrite(BUZZER_PIN,(int32_t)(alarmUntil-now)>0?HIGH:LOW);
 bool disconnected=leadsOff();
 if(clockReady()&&mqtt.connected()&&disconnected!=lastLeadsOff){event(disconnected?"leads_off":"restored");lastLeadsOff=disconnected;}
 if(now-lastVitals>=1000){
  lastVitals=now;
  if(pulseValid&&temperatureValid){
   JsonDocument doc;envelope(doc,"vitals");doc["hr"]=heartRate;doc["spo2"]=oxygen;doc["temperature"]=temperatureC;doc["acceleration"]["magnitude"]=accelerationG;publish(doc,"vitals");
  }
 }
 ECGFrame frame;
 if(ecgQueue&&xQueueReceive(ecgQueue,&frame,0)==pdTRUE&&!disconnected){
  JsonDocument doc;envelope(doc,"ecg",frame.timestamp);
  doc["event_id"]=String(bootId)+"-ecg-"+String(frame.sequence);
  doc["sample_rate"]=ECG_HZ;
  JsonArray samples=doc["samples"].to<JsonArray>();
  for(float sample:frame.samples)samples.add(sample);
  publish(doc,"ecg");
 }
 if(displayReady&&now-lastScreen>=1000){
  lastScreen=now;display.clearDisplay();display.setTextSize(1);display.setTextColor(SSD1306_WHITE);display.setCursor(0,0);
  display.println(MEDIASSIST_SIMULATOR?"MediAssist DEMO":"MediAssist SENSORS");
  display.println(clockReady()?(mqtt.connected()?"MQTT connected":"MQTT offline"):"Waiting for NTP");
  if(pulseValid){display.print("HR ");display.println(heartRate,0);display.print("SpO2 ");display.println(oxygen,0);}else display.println("Optical: waiting");
  if(temperatureValid){display.print("Temp ");display.println(temperatureC,1);}else display.println("Temp: waiting");
  display.println(disconnected?"ECG leads off":"ECG 250Hz target");display.display();
 }
 delay(1);
}
