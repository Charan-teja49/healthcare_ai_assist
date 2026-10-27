import {errorMessage} from './helpers.js';

const unavailableStatuses = new Set([500, 502, 503, 504]);
const backendUnavailable = 'The backend is unavailable. Start both MediAssist services with start.ps1, check backend-errors.log, then try again.';

function responseError(message, status) {
  const error = new Error(message);
  error.status = status;
  return error;
}

/** Read the API's JSON contract without hiding proxy, credential, or field errors. */
export async function readApiResponse(response) {
  const status = response.status;
  let data;
  try {
    data = await response.json();
  } catch {
    if (unavailableStatuses.has(status)) {
      throw responseError(backendUnavailable, status);
    }
    throw responseError(
      response.ok
        ? 'The API returned an unreadable response. Check that the frontend is connected to the MediAssist backend and try again.'
        : `The API returned an unreadable error (HTTP ${status}). Check the backend connection and try again.`,
      status,
    );
  }

  if (!response.ok) {
    const hasDetail = typeof data?.detail === 'string' && data.detail.trim().length > 0
      || Array.isArray(data?.detail) && data.detail.length > 0;
    if (unavailableStatuses.has(status) && !hasDetail) {
      throw responseError(backendUnavailable, status);
    }
    throw responseError(errorMessage(data), status);
  }

  if (data === null || typeof data !== 'object') {
    throw responseError('The API returned an invalid JSON response. Check that you are running the matching MediAssist backend.', status);
  }
  return data;
}
