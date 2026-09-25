// Typed client for the Došlap FastAPI backend — TS port of the vanilla
// core.js `api` object. All calls go through the Vite dev proxy (/api → :8000)
// with the session cookie (credentials: "include").

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = "ApiError"
  }
}

async function call<T = any>(
  method: string,
  path: string,
  body?: any,
  opts: { skipAuthRedirect?: boolean } = {},
): Promise<T> {
  const init: RequestInit = { method, credentials: "include", headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    ;(init.headers as Record<string, string>)["Content-Type"] = "application/json"
    init.body = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, "Síť neodpovídá. Zkontrolujte připojení a zkuste to znovu.")
  }
  const text = await res.text()
  let data: any = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (res.status === 401 && !opts.skipAuthRedirect) {
    if (typeof window !== "undefined" && !location.pathname.startsWith("/auth")) {
      location.href = "/auth"
    }
    throw new ApiError(401, "Nepřihlášeno")
  }
  if (!res.ok) {
    // FastAPI 422s carry `detail` as a list of field errors; surface the first
    // human message instead of letting the object render as "[object Object]".
    const d = data && data.detail
    const msg =
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d[0]?.msg || "Neplatný vstup."
          : `Chyba serveru (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

const qs = (o: Record<string, string | number | undefined>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&")

export const api = {
  // auth
  authMe: () => call("GET", "/api/auth/me", undefined, { skipAuthRedirect: true }),
  authRegister: (payload: any) => call("POST", "/api/auth/register", payload),
  authSignIn: (email: string, password: string, expectedRole?: string) =>
    call("POST", "/api/auth/session", { email, password, expected_role: expectedRole || undefined }, { skipAuthRedirect: true }),
  authLogout: () => call("POST", "/api/auth/logout"),
  getSettings: () => call("GET", "/api/auth/settings"),
  patchSettings: (patch: any) => call("PATCH", "/api/auth/settings", patch),

  // runner-scoped
  runner: (id: string) => call("GET", `/api/runners/${id}`),
  updateProfile: (id: string, patch: any) => call("PATCH", `/api/runners/${id}`, { patch }),
  assessment: (id: string) => call("GET", `/api/runners/${id}/assessment`),
  bootstrap: (id: string) => call("GET", `/api/runners/${id}/bootstrap`),
  activities: (id: string, n = 10) => call("GET", `/api/runners/${id}/activities?limit=${n}`),
  unrated: (id: string) => call("GET", `/api/runners/${id}/activities/unrated`),
  rateActivity: (rid: string, aid: number, body: any) => call("POST", `/api/runners/${rid}/activities/${aid}/rate`, body),
  daily: (id: string, n = 14) => call("GET", `/api/runners/${id}/daily?days=${n}`),
  editDaily: (rid: string, date: string, patch: any, note?: string) => call("PATCH", `/api/runners/${rid}/daily/${date}`, { patch, note }),
  checkin: (id: string, body: any) => call("POST", `/api/runners/${id}/checkins`, body),
  injuryReports: (id: string) => call("GET", `/api/runners/${id}/injury-reports`),
  reportInjury: (id: string, body: any) => call("POST", `/api/runners/${id}/injury-report`, body),
  accessLog: (id: string) => call("GET", `/api/runners/${id}/access-log`),
  mechHistory: (id: string) => call("GET", `/api/runners/${id}/mech-history`),
  quadrantHistory: (id: string) => call("GET", `/api/runners/${id}/quadrant-history`),
  runCompare: (id: string, aid: number) => call("GET", `/api/runners/${id}/run-compare/${aid}`),
  runSegmentTest: (id: string, aid: number) => call("GET", `/api/runners/${id}/run-segments/${aid}`),
  runHistory: (id: string, limit = 20) => call("GET", `/api/runners/${id}/run-history?limit=${limit}`),

  // AI summaries & training commentary (opt-in)
  coach: (rid: string) => call("GET", `/api/runners/${rid}/coach`),
  setCoachConsent: (rid: string, consent: boolean) => call("PUT", `/api/runners/${rid}/coach/consent`, { consent }),
  refreshCoach: (rid: string) => call("POST", `/api/runners/${rid}/coach/refresh`),

  // annotation mode (in-app feedback notes)
  annotations: () => call("GET", "/api/annotations"),
  createAnnotation: (body: any) => call("POST", "/api/annotations", body),
  updateAnnotation: (id: number, patch: any) => call("PATCH", `/api/annotations/${id}`, patch),
  deleteAnnotation: (id: number) => call("DELETE", `/api/annotations/${id}`),

  // engine sensitivity sandbox (Citlivostní analýza)
  engineKnobs: () => call("GET", "/api/engine/knobs"),
  engineSimulate: (inputs: any, prevQuadrant?: string | null, mode: "v1" | "v3" = "v1") =>
    call("POST", "/api/engine/simulate", { inputs, prevQuadrant, mode }),
  engineSweep: (inputs: any, knob: string, prevQuadrant?: string | null, points?: number, mode: "v1" | "v3" = "v1") =>
    call("POST", "/api/engine/sweep", { inputs, knob, prevQuadrant, points, mode }),
  engineInputs: (id: string) => call("GET", `/api/engine/inputs/${id}`),
  bookings: (id: string) => call("GET", `/api/runners/${id}/bookings`),
  program: (id: string) => call("GET", `/api/runners/${id}/program`),
  logEx: (rid: string, exId: number) => call("PATCH", `/api/runners/${rid}/exercises/${exId}/log`, {}),
  messages: (id: string) => call("GET", `/api/runners/${id}/messages`),
  send: (id: string, sender: string, body: string) => call("POST", `/api/runners/${id}/messages`, { sender, body }),

  // booking flow
  setInterest: (rid: string, interested: boolean) => call("POST", `/api/runners/${rid}/physio-interest`, { interested }),
  bookingOptions: (dow?: string, daypart?: string) => call("GET", `/api/booking/options?${qs({ dow, daypart })}`),
  requestSlot: (slotId: number, kind = "assessment") => call("POST", "/api/booking/request", { slot_id: slotId, kind }),
  cancelBooking: (rid: string, bid: number) => call("POST", `/api/runners/${rid}/bookings/${bid}/cancel`, {}),
  declinePhysio: (rid: string, pid: string) => call("POST", `/api/runners/${rid}/physios/${pid}/decline`, {}),

  // return-to-run
  rtr: (pid: number) => call("GET", `/api/rtr/${pid}`),
  logRtrSession: (pid: number, body: any) => call("POST", `/api/rtr/${pid}/session`, body),

  // conclusions (runner reads approved)
  conclusion: (cid: number) => call("GET", `/api/conclusions/${cid}`),

  // integrations / imports
  // Import endpoints keep the user on the page even on a 4xx (e.g. wrong
  // Garmin credentials) — skipAuthRedirect so an error surfaces in the card
  // instead of the global 401 handler bouncing to the login screen.
  garminIngest: (file: File, fit: boolean) => {
    const fd = new FormData()
    fd.append("file", file)
    return call("POST", `/api/integrations/garmin/import?fit=${fit ? "true" : "false"}`, fd, { skipAuthRedirect: true })
  },
  appleIngest: (file: File) => {
    const fd = new FormData()
    fd.append("file", file)
    return call("POST", "/api/integrations/apple/import", fd, { skipAuthRedirect: true })
  },
  garminConnect: (email: string, password: string, remember = false) => call("POST", "/api/integrations/garmin/connect", { email, password, remember }, { skipAuthRedirect: true }),
  // Token-based Garmin sync (no password stored): status, one-tap sync, daily-auto toggle, disconnect.
  garminStatus: () => call("GET", "/api/integrations/garmin/status", undefined, { skipAuthRedirect: true }),
  garminSync: () => call("POST", "/api/integrations/garmin/sync", {}, { skipAuthRedirect: true }),
  garminAutoSync: (enabled: boolean) => call("POST", "/api/integrations/garmin/auto-sync", { enabled }, { skipAuthRedirect: true }),
  garminDisconnect: () => call("DELETE", "/api/integrations/garmin/session", undefined, { skipAuthRedirect: true }),
  // Phase 4: fetch per-second detail streams (track, elevation, mechanics) for recent runs.
  garminStreams: () => call("POST", "/api/integrations/garmin/streams", {}, { skipAuthRedirect: true }),
  // Phase 3b: live-sample surface/trail of the newest run's GPS track (OSM / ZABAGED).
  garminTerrain: () => call("POST", "/api/integrations/garmin/terrain", {}, { skipAuthRedirect: true }),
  // Apple Health auto-sync (device push): fetch/rotate the bearer token the
  // phone (Health Auto Export / a Shortcut) posts HealthKit data with.
  applePushToken: () => call("GET", "/api/integrations/apple/push-token"),
  applePushTokenRotate: () => call("POST", "/api/integrations/apple/push-token/rotate", {}),
  garminMfa: (mfaToken: string, mfaCode: string, remember = false) => call("POST", "/api/integrations/garmin/connect/mfa", { mfa_token: mfaToken, mfa_code: mfaCode, remember }, { skipAuthRedirect: true }),
  // Switch the engine (v1 standard / v2 sensitive / v3 capacity) and recompute.
  setEngine: (rid: string, mode: "v1" | "v2" | "v3") => call("POST", `/api/runners/${rid}/engine`, { mode }),
  runSegments: (rid: string) => call("GET", `/api/runners/${rid}/run-segments`),
}

export type Me = {
  id: number
  email: string
  name: string
  role: string
  runner_id?: string
  physio_id?: string
  employer_id?: string
  partner_id?: string
  provider?: string
}
