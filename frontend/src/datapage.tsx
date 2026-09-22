import { useEffect, useRef, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, Chip, Field, Label, Metric, useAsync, useToast } from "@/ui"
import { fmtD } from "@/lib"

type Result = { ok?: boolean; loading?: boolean; error?: string; activities?: number; addedDaily?: number; meta?: any; source?: string; mfa?: boolean; mfaToken?: string }

export function DataView() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const integ = boot?.integration
  const acts = boot?.activities || []
  const [source, setSource] = useState<"garmin" | "garminlive" | "apple">("garmin")
  const [res, setRes] = useState<Result | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const afile = useRef<HTMLInputElement>(null)
  const [email, setEmail] = useState("")
  const [pw, setPw] = useState("")
  const [code, setCode] = useState("")
  const [appleTok, setAppleTok] = useState<{ token: string; url: string; last_used_at?: string } | null>(null)
  const [remember, setRemember] = useState(true)
  const [gStatus, setGStatus] = useState<any | null>(null)
  const toast = useToast()
  const loadGStatus = () => api.garminStatus().then(setGStatus).catch(() => setGStatus(null))
  useEffect(() => { loadGStatus() }, [rid])

  // Absolute webhook URL from the live origin (robust behind a TLS proxy).
  const pushUrl = `${location.origin}/api/integrations/apple/push`
  const copy = (s: string) => { navigator.clipboard?.writeText(s); toast({ title: "Zkopírováno" }) }
  useEffect(() => {
    if (source === "apple" && !appleTok) api.applePushToken().then(setAppleTok).catch(() => {})
  }, [source, appleTok])
  const rotateAppleTok = async () => {
    try { setAppleTok(await api.applePushTokenRotate()); toast({ title: "Token obnoven" }) } catch { /* ignore */ }
  }

  const upload = async (f: File | undefined, kind: "garmin" | "apple") => {
    if (!f) return
    setRes({ loading: true, source: kind })
    try {
      const r = kind === "garmin" ? await api.garminIngest(f, false) : await api.appleIngest(f)
      setRes({ ok: true, source: kind, activities: r.activities, meta: r.meta })
      toast({ title: `${r.activities} aktivit`, msg: "Import hotový" })
      refresh()
    } catch (e: any) {
      setRes({ ok: false, source: kind, error: e?.message || "Import selhal." })
    }
  }
  const garminLogin = async () => {
    if (!email || !pw) return toast({ title: "Zadejte e-mail i heslo" })
    setRes({ loading: true, source: "garminlive" })
    try {
      const r = await api.garminConnect(email, pw, remember)
      if (r.mfa_required) { setRes({ source: "garminlive", mfa: true, mfaToken: r.mfa_token }); toast({ title: "Zadejte ověřovací kód" }) }
      else { setRes({ ok: true, source: "garminlive", activities: r.added_activities, addedDaily: r.added_daily, meta: r.meta }); toast({ title: `${r.added_activities} nových běhů z Garminu` }); setPw(""); loadGStatus(); refresh() }
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Stažení selhalo." }) }
  }
  const garminMfa = async () => {
    if (!code) return
    setRes({ loading: true, source: "garminlive" })
    try {
      const r = await api.garminMfa(res!.mfaToken!, code, remember)
      setRes({ ok: true, source: "garminlive", activities: r.added_activities, addedDaily: r.added_daily, meta: r.meta })
      toast({ title: `${r.added_activities} nových běhů z Garminu` }); setPw(""); setCode(""); loadGStatus(); refresh()
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Ověření selhalo." }) }
  }
  const garminSyncNow = async () => {
    setRes({ loading: true, source: "garminlive" })
    try {
      const r: any = await api.garminSync()
      setRes({ ok: true, source: "garminlive", activities: r.added_activities, addedDaily: r.added_daily, meta: r.meta })
      toast({ title: r.added_activities || r.added_daily ? `Staženo: ${r.added_activities} běhů, ${r.added_daily} dní` : "Máte aktuální data" })
      if (r.status) setGStatus(r.status); else loadGStatus()
      refresh()
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Synchronizace selhala." }); loadGStatus() }
  }
  const garminStreamsNow = async () => {
    setRes({ loading: true, source: "garminlive" })
    try {
      const r: any = await api.garminStreams()
      setRes({ ok: true, source: "garminlive" })
      toast({ title: r.stored ? `Detailní data: ${r.stored} běhů (trať a sklon)` : "Detailní data jsou aktuální" })
      refresh()
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Načtení detailních dat selhalo." }) }
  }
  const garminTerrainNow = async () => {
    setRes({ loading: true, source: "garminlive" })
    try {
      const r: any = await api.garminTerrain()
      setRes({ ok: true, source: "garminlive" })
      const s = r.surface || {}
      const cls = { paved: "zpevněný", compact: "šotolina", soft: "měkký", unknown: "neznámý" }[s.surfaceClass as string] || s.surfaceClass
      toast({ title: `Povrch trasy: ${cls}${s.onTrail ? " · terén" : ""}${s.forest ? " · les" : ""}`, msg: `zdroj ${String(s.source).toUpperCase()} · pokrytí ${Math.round((s.coverage || 0) * 100)} %` })
      refresh()
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Určení povrchu selhalo." }) }
  }
  const garminToggleAuto = async (enabled: boolean) => {
    try { setGStatus(await api.garminAutoSync(enabled)); toast({ title: enabled ? "Ranní synchronizace zapnuta" : "Ranní synchronizace vypnuta" }) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se změnit nastavení" }) }
  }
  const garminDisconnect = async () => {
    try { setGStatus(await api.garminDisconnect()); toast({ title: "Garmin odpojen — uložený token smazán" }) }
    catch (e: any) { toast({ title: e?.message || "Odpojení selhalo" }) }
  }

  const R = res?.source === source ? res : null

  const engineMode: "v1" | "v2" = boot?.assessment?.engineMode || boot?.runner?.engine_mode || "v1"
  const [engBusy, setEngBusy] = useState(false)
  const switchEngine = async (mode: "v1" | "v2") => {
    if (mode === engineMode || engBusy) return
    setEngBusy(true)
    try {
      await api.setEngine(rid, mode)
      toast({ title: mode === "v2" ? "Zapnut Citlivý engine" : "Zapnut Standardní engine" })
      await refresh()
    } catch (e: any) {
      toast({ title: e?.message || "Přepnutí se nezdařilo" })
    } finally {
      setEngBusy(false)
    }
  }
  const engines: [("v1" | "v2"), string, string][] = [
    ["v1", "Standardní", "Vyhlazený průměr napříč běhy."],
    ["v2", "Citlivý", "Zachytí i malé změny mechaniky dřív."],
  ]
  const [btBusy, setBtBusy] = useState(false)
  const downloadBacktest = async () => {
    setBtBusy(true)
    try {
      const res = await fetch(`/api/runners/${rid}/backtest.xlsx`, { credentials: "include" })
      if (!res.ok) throw new Error("Backtest se nepodařilo vytvořit")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "dosslap_backtest.xlsx"
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
      toast({ title: "Backtest stažen", msg: "Excel: Souhrn · Týdně · Denně (v1 vs v2)" })
    } catch (e: any) {
      toast({ title: e?.message || "Backtest se nepodařilo vytvořit" })
    } finally {
      setBtBusy(false)
    }
  }
  const [dtBusy, setDtBusy] = useState(false)
  const downloadDetailed = async () => {
    setDtBusy(true)
    try {
      const res = await fetch(`/api/runners/${rid}/backtest-detailed.xlsx`, { credentials: "include" })
      if (!res.ok) throw new Error("Detailní backtest se nepodařilo vytvořit")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "dosslap_backtest_detailed.xlsx"
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
      toast({ title: "Detailní backtest stažen", msg: "Rozpad skóre po signálech + drivery + legenda" })
    } catch (e: any) {
      toast({ title: e?.message || "Detailní backtest se nepodařilo vytvořit" })
    } finally {
      setDtBusy(false)
    }
  }
  const [expBusy, setExpBusy] = useState(false)
  const downloadData = async () => {
    setExpBusy(true)
    try {
      const res = await fetch(`/api/runners/${rid}/export.json`, { credentials: "include" })
      if (!res.ok) throw new Error("Export se nepodařilo vytvořit")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "dosslap_data.json"
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
      toast({ title: "Data stažena", msg: "JSON bez tokenů/hesel — můžeš ho sdílet" })
    } catch (e: any) {
      toast({ title: e?.message || "Export se nepodařilo vytvořit" })
    } finally {
      setExpBusy(false)
    }
  }

  return (
    <>
      <div className="mb-6"><Label>Data a připojení</Label><h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">{integ?.status === "connected" ? "Zdroj připojen" : "Zatím nepřipojeno"}</h1></div>
      <div className="grid gap-4 md:grid-cols-3">
        <Metric warm label="Aktivit v účtu" value={`${acts.length}`} caption={acts.length ? `${fmtD(acts.at(-1)?.started_at)} → ${fmtD(acts[0]?.started_at)}` : "zatím bez importu"} />
        <Metric label="Stav" value={integ?.status === "connected" ? "připojeno" : "nepřipojeno"} caption={integ?.provider ? `zdroj ${integ.provider}` : "—"} />
        <Metric label="Profil" value={(me?.name || "").split(" ")[0]} caption="běžec / pacient" />
      </div>

      <Card className="mt-4">
        <div className="flex items-center justify-between gap-2">
          <Label>Engine hodnocení mechaniky</Label>
          <span className="rounded-full bg-[#c7ff54]/15 px-2.5 py-1 text-[10px] font-bold text-[#c7ff54]">{engineMode === "v2" ? "Citlivý" : "Standardní"}</span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {engines.map(([id, name, desc]) => {
            const on = engineMode === id
            return (
              <button
                key={id}
                onClick={() => switchEngine(id)}
                disabled={engBusy}
                className={`rounded-2xl border p-4 text-left transition disabled:opacity-60 ${on ? "border-[#c7ff54] bg-[#c7ff54]/10" : "border-white/12 bg-white/[.03] hover:border-white/25"}`}
              >
                <span className="flex items-center gap-2">
                  <i className={`size-2.5 rounded-full ${on ? "bg-[#c7ff54]" : "bg-white/25"}`} />
                  <b className="text-sm text-[#f1f8f1]">{name}{id === "v2" ? " · beta" : ""}</b>
                </span>
                <p className="mt-1.5 text-xs leading-4 text-[#a9c2b9]">{desc}</p>
              </button>
            )
          })}
        </div>
        <p className="mt-3 text-[11px] leading-4 text-[#71837b]">
          Citlivý engine počítá odchylku proti tvé vlastní typické chybě a váží čerstvé běhy víc, takže pozvolný drift zachytí dřív než průměrový Standardní. Experimentální — zatím nevalidované na reálných datech.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
          <button onClick={downloadBacktest} disabled={btBusy} className="rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313] disabled:opacity-60">{btBusy ? "Připravuji…" : "⬇ Backtest (v1 vs v2)"}</button>
          <button onClick={downloadDetailed} disabled={dtBusy} className="rounded-full border border-[#c7ff54]/40 px-4 py-2 text-xs font-bold text-[#c7ff54] disabled:opacity-60">{dtBusy ? "Připravuji…" : "⬇ Detailní backtest"}</button>
          <button onClick={downloadData} disabled={expBusy} className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-[#a9c2b9] disabled:opacity-60">{expBusy ? "Připravuji…" : "⬇ Moje data (JSON)"}</button>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-[#71837b]">Backtest = souhrn v1 vs v2. Detailní = rozpad skóre po jednotlivých signálech + drivery + legenda vzorců. Data = kompletní JSON <b>bez tokenů a hesel</b>.</p>
      </Card>

      <Card className="mt-4">
        <div className="flex flex-wrap gap-2">
          {([["garmin", "Garmin – soubor"], ["garminlive", "Garmin – přihlášení"], ["apple", "Apple Health"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setSource(k)} className={`rounded-full px-4 py-2 text-xs font-bold ${source === k ? "bg-[#c7ff54] text-[#071313]" : "border border-white/15 text-[#a9c2b9]"}`}>{l}</button>
          ))}
        </div>

        <div className="mt-6">
          {source === "garmin" && (
            <>
              <h2 className="font-serif text-2xl">Nahrát export z Garmin Connect</h2>
              <p className="mt-2 text-sm text-[#64736e]">Garmin Connect → Účet → Export Your Data. Přijde ZIP e-mailem — nahrajte ho celý, nebo jen <span className="font-mono">summarizedActivities.json</span>.</p>
              <input ref={file} type="file" accept=".zip,.json" className="hidden" onChange={(e) => upload(e.target.files?.[0], "garmin")} />
              <button onClick={() => file.current?.click()} className="mt-4 w-full rounded-2xl border-2 border-dashed border-[#9cbcb5] p-8 text-sm font-bold text-[#c7ff54]">↑ Vybrat ZIP nebo JSON</button>
            </>
          )}
          {source === "garminlive" && (
            <>
              {gStatus?.connected && (
                <div className="mb-5 rounded-2xl border border-[#c7ff54]/30 bg-[#c7ff54]/[.06] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#8fae52]">Garmin připojen</p>
                      <p className="mt-1 text-sm text-[#e6efdc]">Ranní synchronizace {gStatus.auto_sync ? <b className="text-[#c7ff54]">zapnutá</b> : <b>vypnutá</b>} · poslední: {gStatus.last_sync_at ? fmtD(gStatus.last_sync_at) : "—"}</p>
                      {gStatus.last_error && <p className="mt-1 text-xs text-[#e77a59]">{gStatus.last_error}</p>}
                      <p className="mt-1 text-[11px] text-[#7f938a]">Uložen je jen přístupový <b>token</b> (šifrovaný{gStatus.encrypted ? "" : " – bez klíče v této instanci"}), ne heslo. Token lze zrušit i v účtu Garmin.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button onClick={garminSyncNow} disabled={R?.loading} className="rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313] disabled:opacity-60">{R?.loading ? "Synchronizuji…" : "⟳ Synchronizovat teď"}</button>
                      <button onClick={garminStreamsNow} disabled={R?.loading} title="Stáhne trať, výškový profil a mechaniku po sekundách pro nedávné běhy — zapne terénní zátěž" className="rounded-full border border-[#6ce6d3]/40 px-4 py-2 text-xs font-bold text-[#6ce6d3] disabled:opacity-60">⛰ Detailní data</button>
                      <button onClick={garminTerrainNow} disabled={R?.loading} title="Z GPS trati nejnovějšího běhu určí povrch a terén (OpenStreetMap, v ČR ZABAGED)" className="rounded-full border border-[#6ce6d3]/40 px-4 py-2 text-xs font-bold text-[#6ce6d3] disabled:opacity-60">🗺 Povrch trasy</button>
                      <button onClick={() => garminToggleAuto(!gStatus.auto_sync)} className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-[#a9c2b9]">{gStatus.auto_sync ? "Vypnout ranní sync" : "Zapnout ranní sync"}</button>
                      <button onClick={garminDisconnect} className="rounded-full border border-[#e77a59]/40 px-4 py-2 text-xs font-bold text-[#e77a59]">Odpojit</button>
                    </div>
                  </div>
                </div>
              )}
              <h2 className="font-serif text-2xl">{gStatus?.connected ? "Znovu připojit Garmin Connect" : "Stáhnout data přímo z Garmin Connect"}</h2>
              <p className="mt-2 text-sm text-[#64736e]">Přihlaste se svým účtem — data se stáhnou rovnou. <b>Heslo se nikam neukládá</b> a použije se jen pro toto přihlášení. Účty s dvoufázovým ověřením zadají kód níže.</p>
              {!R?.mfa ? (
                <>
                  <Field label="E-mail Garmin Connect"><input value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="vas@email.cz" /></Field>
                  <Field label="Heslo"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="••••••••" /></Field>
                  <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-sm text-[#a9c2b9]">
                    <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="mt-0.5 size-4 accent-[#c7ff54]" />
                    <span>Zůstat připojený a <b>stahovat data automaticky každé ráno</b> (a tlačítkem „Synchronizovat" na Dnes). Uloží se jen přístupový token, ne heslo.</span>
                  </label>
                  <button onClick={garminLogin} disabled={R?.loading} className="mt-4 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">{R?.loading ? "Stahuji…" : "Stáhnout data z Garminu"}</button>
                </>
              ) : (
                <>
                  <Field label="Ověřovací kód (dvoufázové ověření)" hint="z aplikace / SMS / e-mailu"><input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="123456" /></Field>
                  <button onClick={garminMfa} disabled={R?.loading} className="mt-4 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">Ověřit a stáhnout</button>
                </>
              )}
            </>
          )}
          {source === "apple" && (
            <>
              <h2 className="font-serif text-2xl">Apple Health — automatické připojení</h2>
              <p className="mt-2 text-sm text-[#64736e]">Apple nemá cloud API (data jsou v telefonu), takže je posílá váš iPhone. Nainstalujte <b>Health Auto Export</b> (App Store) → <b>Automations → REST API</b>, formát <b>JSON</b>, a vyplňte:</p>
              <div className="mt-4 space-y-3">
                <div>
                  <Label>URL (POST)</Label>
                  <div className="mt-1 flex gap-2">
                    <input readOnly value={pushUrl} className="w-full rounded-xl border px-3 py-2.5 font-mono text-[11px]" />
                    <button onClick={() => copy(pushUrl)} className="shrink-0 rounded-xl border border-white/15 px-3 text-xs font-bold text-[#a9c2b9]">Kopírovat</button>
                  </div>
                </div>
                <div>
                  <Label>Hlavička (Header)</Label>
                  <div className="mt-1 flex gap-2">
                    <input readOnly value={appleTok ? `Authorization: Bearer ${appleTok.token}` : "…"} className="w-full rounded-xl border px-3 py-2.5 font-mono text-[11px]" />
                    <button onClick={() => appleTok && copy(`Authorization: Bearer ${appleTok.token}`)} className="shrink-0 rounded-xl border border-white/15 px-3 text-xs font-bold text-[#a9c2b9]">Kopírovat</button>
                  </div>
                </div>
                <p className="text-xs text-[#71837b]">Vyberte metriky (HRV, klidový tep, spánek, kroky) i cvičení (běhy). {appleTok?.last_used_at ? `Naposledy přijato ${fmtD(appleTok.last_used_at)}.` : "Zatím bez příjmu — po prvním odeslání z telefonu se tu objeví běhy."}</p>
                <button onClick={rotateAppleTok} className="text-xs font-bold text-[#e77a59]">Obnovit token (zneplatní starý)</button>
              </div>
              <div className="mt-6 border-t border-white/10 pt-4">
                <p className="text-sm text-[#64736e]">Nechcete tu aplikaci? Nahrajte ruční export: iPhone → Zdraví → profil → Exportovat všechna data (<span className="font-mono">export.zip</span>).</p>
                <input ref={afile} type="file" accept=".zip,.xml" className="hidden" onChange={(e) => upload(e.target.files?.[0], "apple")} />
                <button onClick={() => afile.current?.click()} className="mt-3 w-full rounded-2xl border-2 border-dashed border-[#9cbcb5] p-6 text-sm font-bold text-[#c7ff54]">↑ Vybrat ZIP nebo XML</button>
              </div>
            </>
          )}

          {R && (
            <div className="mt-5 border-t border-white/10 pt-4">
              {R.loading && <p className="text-sm text-[#71837b]">Zpracovávám…</p>}
              {R.error && <p className="text-sm font-bold text-[#e77a59]">{R.error}</p>}
              {R.ok && (
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone="ok">{R.activities} {R.source === "garminlive" ? "nových běhů" : "aktivit"}</Chip>
                  {R.addedDaily != null && <Chip>+{R.addedDaily} dní metrik</Chip>}
                  {R.meta?.first_run && <Chip>{fmtD(R.meta.first_run)} → {fmtD(R.meta.last_run)}</Chip>}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <Label>Kdo přistupoval k vašim datům</Label>
          <p className="mt-1 text-xs text-[#71837b]">Transparentnost podle GDPR — zaznamenává se přístup fyzioterapeuta, ne váš vlastní.</p>
          {(boot?.access_log || []).length ? (
            <div className="mt-3 divide-y divide-white/10">{(boot.access_log as any[]).map((x) => (
              <div key={x.id} className="flex items-center justify-between py-2 text-sm"><span><b>{x.physio_name || "Fyzioterapeut"}</b><em className="block text-xs not-italic text-[#71837b]">{fmtD(x.date)} · {x.access_count}× {x.action === "read" ? "čtení" : "zápis"}</em></span><Chip tone={x.action === "read" ? "muted" : "watch"}>{x.action === "read" ? "čtení" : "zápis"}</Chip></div>
            ))}</div>
          ) : <p className="mt-3 text-sm text-[#71837b]">Zatím k vašim datům nikdo nepřistupoval.</p>}
        </Card>
        <Card>
          <Label>Historie zařízení</Label>
          {(boot?.device_history || []).length ? (
            <div className="mt-3 divide-y divide-white/10">{(boot.device_history as any[]).slice().reverse().map((h, i) => (
              <div key={i} className="py-2 text-sm"><b>{h.device}</b><em className="block text-xs not-italic text-[#71837b]">{i === 0 ? "aktuální" : "starší"} · od {fmtD(h.recorded_at)}</em></div>
            ))}</div>
          ) : <p className="mt-3 text-sm text-[#71837b]">Zatím bez záznamu.</p>}
        </Card>
      </div>
    </>
  )
}
