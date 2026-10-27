import test from 'node:test';
import assert from 'node:assert/strict';
import {readApiResponse} from './http.js';

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json'}});
}

test('successful login JSON is returned without changing credentials or user data', async () => {
  const data = {token: 'fictional-test-token', user: {id: 1, role: 'patient', consent: true}};
  assert.deepEqual(await readApiResponse(jsonResponse(data)), data);
});

test('successful list responses are supported', async () => {
  const data = [{id: 2, status: 'booked'}];
  assert.deepEqual(await readApiResponse(jsonResponse(data)), data);
});

test('plain proxy failures explain how to start the backend', async () => {
  for (const status of [500, 502, 503, 504]) {
    const response = new Response('Internal server error', {status});
    await assert.rejects(readApiResponse(response), error => {
      assert.equal(error.status, status);
      assert.match(error.message, /backend is unavailable/i);
      assert.match(error.message, /start\.ps1/);
      assert.match(error.message, /backend-errors\.log/);
      return true;
    });
  }
});

test('empty proxy failures also produce the actionable backend message', async () => {
  await assert.rejects(readApiResponse(new Response('', {status: 502})), error => {
    assert.equal(error.status, 502);
    assert.match(error.message, /backend is unavailable/i);
    return true;
  });
});

test('proxy JSON without an API detail is treated as unavailable', async () => {
  await assert.rejects(readApiResponse(jsonResponse({message: 'Bad gateway'}, 502)), error => {
    assert.equal(error.status, 502);
    assert.match(error.message, /backend is unavailable/i);
    return true;
  });
});

test('401 credentials remain distinct from connection and session errors', async () => {
  await assert.rejects(readApiResponse(jsonResponse({detail: 'Incorrect email or password'}, 401)), error => {
    assert.equal(error.status, 401);
    assert.equal(error.message, 'Incorrect email or password');
    assert.doesNotMatch(error.message, /session expired|backend is unavailable/i);
    return true;
  });
});

test('403 consent errors retain the API explanation', async () => {
  await assert.rejects(readApiResponse(jsonResponse({detail: 'Consent is required to process health data'}, 403)), error => {
    assert.equal(error.status, 403);
    assert.equal(error.message, 'Consent is required to process health data');
    return true;
  });
});

test('422 validation errors identify each affected field', async () => {
  const data = {detail: [
    {loc: ['body', 'email'], msg: 'Invalid email'},
    {loc: ['body', 'password'], msg: 'Password is required'},
  ]};
  await assert.rejects(readApiResponse(jsonResponse(data, 422)), error => {
    assert.equal(error.status, 422);
    assert.match(error.message, /email: Invalid email/);
    assert.match(error.message, /password: Password is required/);
    return true;
  });
});

test('structured 503 setup errors are preserved rather than called an offline backend', async () => {
  await assert.rejects(readApiResponse(jsonResponse({detail: 'Image OCR needs Tesseract'}, 503)), error => {
    assert.equal(error.status, 503);
    assert.equal(error.message, 'Image OCR needs Tesseract');
    return true;
  });
});

test('HTML masquerading as a successful API reply is rejected clearly', async () => {
  await assert.rejects(readApiResponse(new Response('<html>Frontend page</html>', {status: 200})), error => {
    assert.equal(error.status, 200);
    assert.match(error.message, /unreadable response/i);
    return true;
  });
});

test('empty, null, and primitive successful replies violate the API JSON contract', async () => {
  for (const response of [new Response('', {status: 200}), jsonResponse(null), jsonResponse('not an API object')]) {
    await assert.rejects(readApiResponse(response), error => {
      assert.equal(error.status, 200);
      assert.match(error.message, /unreadable|invalid JSON/i);
      return true;
    });
  }
});
