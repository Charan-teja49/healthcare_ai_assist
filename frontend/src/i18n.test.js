import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const hi=JSON.parse(fs.readFileSync(new URL('../locales/hi.json',import.meta.url)));
const extracted=JSON.parse(fs.readFileSync(new URL('../locales/extracted.json',import.meta.url)));
test('every extracted static interface string has a Hindi translation',()=>{assert.deepEqual(extracted.filter(k=>!hi[k]),[]);});
test('Hindi dictionary contains Devanagari text for actionable labels',()=>{for(const key of ['Sign in','Save review','Send answer','Book demo appointment','Enable health processing','Delete account and records'])assert.match(hi[key],/[\u0900-\u097f]/);});
test('technical credentials and phone examples stay unchanged',()=>{assert.equal(hi['Password: Demo@12345'],'पासवर्ड: Demo@12345');assert.equal(hi['+919876543210'],'+919876543210');});
