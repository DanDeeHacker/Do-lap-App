import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, Chip, Field, Label, ListRow, Segmented, Switch, useAsync, useToast } from "@/ui"
import { ArrowRight, Copy, Database, Download, Eye, Map as MapIcon, Mountain, Pencil, Power, RefreshCw, Smartphone, Sunrise, Unplug, Upload, Watch } from "lucide-react"
import { fmtD, initials } from "@/lib"

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
      let total = 0
      let stalled = false
      // Backfill the whole window in batches; the server returns `remaining`.
      for (let i = 0; i < 80; i++) {
        const r: any = await api.garminStreams()
        total += r.stored || 0
        if (r.stalled) { stalled = true; break }
        if (r.have) toast({ title: `Detailní data: ${r.have}/${r.total} běhů`, msg: r.remaining ? `zbývá ${r.remaining}…` : "hotovo" })
        if (!r.remaining) break
      }
      setRes({ ok: true, source: "garminlive" })
      if (stalled) toast({ title: "Garmin dočasně omezuje požadavky", msg: `Staženo +${total}. Zkus to prosím za chvíli znovu — už stažené zůstává.` })
      else toast({ title: total ? `Detailní data stažena: +${total} běhů` : "Detailní data jsou aktuální" })
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

  type EngineMode = "v1" | "v2" | "v3"
  const engineMode: EngineMode = boot?.assessment?.engineMode || boot?.runner?.engine_mode || "v1"
  const [engBusy, setEngBusy] = useState(false)
  const switchEngine = async (mode: EngineMode) => {
    if (mode === engineMode || engBusy) return
    setEngBusy(true)
    try {
      await api.setEngine(rid, mode)
      toast({ title: `Zapnut ${ENGINE_NAME[mode]} engine` })
      await refresh()
    } catch (e: any) {
      toast({ title: e?.message || "Přepnutí se nezdařilo" })
    } finally {
      setEngBusy(false)
    }
  }
  const ENGINE_NAME: Record<EngineMode, string> = { v1: "Standardní", v2: "Citlivý", v3: "Kapacitní" }
  const engines: [EngineMode, string, string][] = [
    ["v1", "Standardní", "Vyhlazený průměr napříč běhy."],
    ["v2", "Citlivý", "Zachytí i malé změny mechaniky dřív."],
    ["v3", "Kapacitní", "Citlivá mechanika + zátěž proti vaší vlastní kapacitě (objem, intenzita, klesání, stoupání). Odemkne záložku Trénink s denním doporučením."],
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
      <div className="mb-6"><Label>Data a připojení</Label><h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">{integ?.status === "connected" ? "Zdroj připojen" : "Zatím nepřipojeno"}</h1></div>
      {/* One status strip (same values as the former three tiles) */}
      <div className="card grid divide-y divide-white/[.07] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="flex items-center gap-3 p-4">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-info/15 text-info"><Database className="size-4" aria-hidden /></span>
          <span className="min-w-0"><span className="t-label block !text-fg-3">Aktivit v účtu</span><b className="t-num block text-[22px] leading-tight">{acts.length}</b><span className="block truncate text-[12px] text-fg-3">{acts.length ? `${fmtD(acts.at(-1)?.started_at)} → ${fmtD(acts[0]?.started_at)}` : "zatím bez importu"}</span></span>
        </div>
        <div className="flex items-center gap-3 p-4">
          <span className={`grid size-[34px] shrink-0 place-items-center rounded-[10px] ${integ?.status === "connected" ? "bg-ok/15 text-ok" : "bg-watch/15 text-watch"}`}><Watch className="size-4" aria-hidden /></span>
          <span className="min-w-0"><span className="t-label block !text-fg-3">Stav</span><b className={`block text-[17px] font-bold leading-tight ${integ?.status === "connected" ? "text-ok" : "text-watch"}`}>{integ?.status === "connected" ? "připojeno" : "nepřipojeno"}</b><span className="block truncate text-[12px] text-fg-3">{integ?.provider ? `zdroj ${integ.provider}` : "—"}</span></span>
        </div>
        <div className="flex items-center gap-3 p-4">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-full bg-accent text-[11px] font-extrabold text-ink">{initials(me?.name)}</span>
          <span className="min-w-0"><span className="t-label block !text-fg-3">Profil</span><b className="block text-[17px] font-bold leading-tight">{(me?.name || "").split(" ")[0]}</b><span className="block truncate text-[12px] text-fg-3">běžec / pacient</span></span>
        </div>
      </div>

      <Card className="mt-4">
        <div className="flex items-center justify-between gap-2">
          <Label>Engine hodnocení</Label>
          <Chip tone="accent">{ENGINE_NAME[engineMode] || "Standardní"}</Chip>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {engines.map(([id, name, desc]) => {
            const on = engineMode === id
            return (
              <button
                key={id}
                onClick={() => switchEngine(id)}
                disabled={engBusy}
                aria-pressed={on}
                className={`rounded-[16px] border p-4 text-left transition disabled:opacity-60 ${on ? "border-accent bg-accent/[.08]" : "border-white/[.1] bg-white/[.03] hover:border-white/25"}`}
              >
                <span className="flex items-center gap-2">
                  <i className={`grid size-4 place-items-center rounded-full border-2 ${on ? "border-accent" : "border-white/30"}`}>{on && <i className="size-1.5 rounded-full bg-accent" />}</i>
                  <b className="text-sm font-bold text-fg">{name}</b>
                  {id !== "v1" && <span className="rounded-full bg-white/[.07] px-1.5 py-0.5 text-[11px] font-bold text-fg-2">beta</span>}
                </span>
                <p className="mt-1.5 text-[12px] leading-5 text-fg-2">{desc}</p>
              </button>
            )
          })}
        </div>
        <Link to="/engines" className="nest mt-3 flex items-center justify-between gap-3 px-4 py-3 text-left transition hover:border-accent/50">
          <span>
            <b className="text-sm font-bold text-fg">Porovnat enginy</b>
            <span className="block text-[12px] text-fg-2">Jaké skóre by dnes a za posledních 6 měsíců ukazoval každý engine a co do něj vstupuje.</span>
          </span>
          <ArrowRight className="size-5 shrink-0 text-accent" aria-hidden />
        </Link>
        <p className="mt-3 text-[11px] leading-4 text-fg-3">
          Citlivý engine počítá odchylku každého běhu proti tvé vlastní typické chybě a váží čerstvé běhy víc, takže změnu zachytí dřív než průměrový Standardní — nastavený tak, aby bez skutečné změny ukázal signál zhruba jen v 5 % případů. Všechny enginy přepočítávají mechaniku na tvé obvyklé tempo, takže pomalejší klusy nevypadají jako drift. Kapacitní engine navíc hodnotí zátěž proti tomu, co jsi prokazatelně zvládl(a) bez obtíží — po jednotlivých bězích i týdnech, v objemu, intenzitě (tepové zóny), klesání a stoupání — a snižuje ji podle toho, jak ses vyspal(a). Experimentální — zatím nevalidované na reálných zraněních.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[.08] pt-4">
          <Button size="sm" icon={Download} onClick={downloadBacktest} disabled={btBusy}>{btBusy ? "Připravuji…" : "Backtest (v1 vs v2)"}</Button>
          <Button size="sm" variant="outline" icon={Download} onClick={downloadDetailed} disabled={dtBusy}>{dtBusy ? "Připravuji…" : "Detailní backtest"}</Button>
          <Button size="sm" variant="outline" icon={Download} onClick={downloadData} disabled={expBusy}>{expBusy ? "Připravuji…" : "Moje data (JSON)"}</Button>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-fg-3">Backtest = souhrn v1 vs v2. Detailní = rozpad skóre po jednotlivých signálech + drivery + legenda vzorců. Data = kompletní JSON <b>bez tokenů a hesel</b>.</p>
      </Card>

      <CoachConsentCard rid={rid} />

      <Card className="mt-4">
        <Segmented ariaLabel="Zdroj dat" options={[["garmin", "Garmin – soubor"], ["garminlive", "Garmin – přihlášení"], ["apple", "Apple Health"]] as const} value={source} onChange={setSource} />

        <div className="mt-6">
          {source === "garmin" && (
            <>
              <h2 className="font-serif text-2xl">Nahrát export z Garmin Connect</h2>
              <p className="mt-2 text-sm text-fg-2">Garmin Connect → Účet → Export Your Data. Přijde ZIP e-mailem — nahrajte ho celý, nebo jen <span className="tabular-nums">summarizedActivities.json</span>.</p>
              <input ref={file} type="file" accept=".zip,.json" className="hidden" onChange={(e) => upload(e.target.files?.[0], "garmin")} />
              <button onClick={() => file.current?.click()} className="mt-4 flex w-full items-center justify-center gap-2 rounded-[16px] border-2 border-dashed border-info/50 p-8 text-sm font-bold text-accent transition hover:border-accent hover:bg-accent/[.04]"><Upload className="size-5" aria-hidden />Vybrat ZIP nebo JSON</button>
            </>
          )}
          {source === "garminlive" && (
            <>
              {gStatus?.connected && (
                <div className="nest mb-5 !border-accent/30 !bg-accent/[.05] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="t-label !text-accent">Garmin připojen</p>
                      <p className="mt-1 text-sm text-fg">Ranní synchronizace {gStatus.auto_sync ? <b className="text-accent">zapnutá</b> : <b>vypnutá</b>} · poslední: {gStatus.last_sync_at ? fmtD(gStatus.last_sync_at) : "—"}</p>
                      {gStatus.last_error && <p className="mt-1 text-xs text-alert">{gStatus.last_error}</p>}
                      <p className="mt-1 text-[11px] text-fg-2">Detailní data (trať, výškový profil, mechanika po sekundách) nových běhů se stahují automaticky s každou synchronizací; tlačítko „Detailní data“ doplní starší historii.</p>
                      <p className="mt-1 text-[11px] text-fg-3">Uložen je jen přístupový <b>token</b> (šifrovaný{gStatus.encrypted ? "" : " – bez klíče v této instanci"}), ne heslo. Token lze zrušit i v účtu Garmin.</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-white/[.08] pt-3">
                      <button onClick={garminSyncNow} disabled={R?.loading} className="btn btn-sm btn-primary"><RefreshCw className={`size-3.5 ${R?.loading ? "animate-spin" : ""}`} aria-hidden />{R?.loading ? "Synchronizuji…" : "Synchronizovat teď"}</button>
                      <button onClick={garminStreamsNow} disabled={R?.loading} title="Doplní trať, výškový profil a mechaniku po sekundách i pro STARŠÍ běhy v historii (po dávkách). Nové běhy se stahují samy s každou synchronizací." className="btn btn-sm btn-outline"><Mountain className="size-3.5" aria-hidden />Detailní data</button>
                      <button onClick={garminTerrainNow} disabled={R?.loading} title="Z GPS trati nejnovějšího běhu určí povrch a terén (OpenStreetMap, v ČR ZABAGED)" className="btn btn-sm btn-outline"><MapIcon className="size-3.5" aria-hidden />Povrch trasy</button>
                      <button onClick={() => garminToggleAuto(!gStatus.auto_sync)} className="btn btn-sm btn-secondary"><Sunrise className="size-3.5" aria-hidden />{gStatus.auto_sync ? "Vypnout ranní sync" : "Zapnout ranní sync"}</button>
                      <button onClick={garminDisconnect} className="btn btn-sm border border-alert/45 text-alert hover:bg-alert/10"><Unplug className="size-3.5" aria-hidden />Odpojit</button>
                  </div>
                </div>
              )}
              <h2 className="font-serif text-2xl">{gStatus?.connected ? "Znovu připojit Garmin Connect" : "Stáhnout data přímo z Garmin Connect"}</h2>
              <p className="mt-2 text-sm text-fg-2">Přihlaste se svým účtem — data se stáhnou rovnou. <b>Heslo se nikam neukládá</b> a použije se jen pro toto přihlášení. Účty s dvoufázovým ověřením zadají kód níže.</p>
              {!R?.mfa ? (
                <>
                  <Field label="E-mail Garmin Connect"><input value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="vas@email.cz" /></Field>
                  <Field label="Heslo"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="••••••••" /></Field>
                  <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-sm text-fg-2">
                    <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="mt-0.5 size-4 accent-accent" />
                    <span>Zůstat připojený a <b>stahovat data automaticky každé ráno</b> (a tlačítkem „Synchronizovat" na Dnes). Uloží se jen přístupový token, ne heslo.</span>
                  </label>
                  <button onClick={garminLogin} disabled={R?.loading} className="btn btn-primary mt-4 w-full py-3 text-sm">{R?.loading ? "Stahuji…" : "Stáhnout data z Garminu"}</button>
                </>
              ) : (
                <>
                  <Field label="Ověřovací kód (dvoufázové ověření)" hint="z aplikace / SMS / e-mailu"><input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="123456" /></Field>
                  <button onClick={garminMfa} disabled={R?.loading} className="btn btn-primary mt-4 w-full py-3 text-sm">Ověřit a stáhnout</button>
                </>
              )}
            </>
          )}
          {source === "apple" && (
            <>
              <h2 className="font-serif text-2xl">Apple Health — automatické připojení</h2>
              <p className="mt-2 text-sm text-fg-2">Apple nemá cloud API (data jsou v telefonu), takže je posílá váš iPhone. Nainstalujte <b>Health Auto Export</b> (App Store) → <b>Automations → REST API</b>, formát <b>JSON</b>, a vyplňte:</p>
              <div className="mt-4 space-y-3">
                <div>
                  <Label>URL (POST)</Label>
                  <div className="mt-1 flex gap-2">
                    <input readOnly value={pushUrl} className="w-full rounded-xl border px-3 py-2.5 tabular-nums text-[11px]" />
                    <button onClick={() => copy(pushUrl)} className="btn btn-sm btn-outline shrink-0 !rounded-xl"><Copy className="size-3.5" aria-hidden />Kopírovat</button>
                  </div>
                </div>
                <div>
                  <Label>Hlavička (Header)</Label>
                  <div className="mt-1 flex gap-2">
                    <input readOnly value={appleTok ? `Authorization: Bearer ${appleTok.token}` : "…"} className="w-full rounded-xl border px-3 py-2.5 tabular-nums text-[11px]" />
                    <button onClick={() => appleTok && copy(`Authorization: Bearer ${appleTok.token}`)} className="btn btn-sm btn-outline shrink-0 !rounded-xl"><Copy className="size-3.5" aria-hidden />Kopírovat</button>
                  </div>
                </div>
                <p className="text-[12px] leading-5 text-fg-3">Vyberte metriky (HRV, klidový tep, spánek, kroky) i cvičení (běhy). {appleTok?.last_used_at ? `Naposledy přijato ${fmtD(appleTok.last_used_at)}.` : "Zatím bez příjmu — po prvním odeslání z telefonu se tu objeví běhy."}</p>
                <button onClick={rotateAppleTok} className="text-[12px] font-bold text-alert underline-offset-2 hover:underline">Obnovit token (zneplatní starý)</button>
              </div>
              <div className="mt-6 border-t border-white/[.08] pt-4">
                <p className="text-sm text-fg-2">Nechcete tu aplikaci? Nahrajte ruční export: iPhone → Zdraví → profil → Exportovat všechna data (<span className="tabular-nums">export.zip</span>).</p>
                <input ref={afile} type="file" accept=".zip,.xml" className="hidden" onChange={(e) => upload(e.target.files?.[0], "apple")} />
                <button onClick={() => afile.current?.click()} className="mt-3 flex w-full items-center justify-center gap-2 rounded-[16px] border-2 border-dashed border-info/50 p-6 text-sm font-bold text-accent transition hover:border-accent hover:bg-accent/[.04]"><Upload className="size-5" aria-hidden />Vybrat ZIP nebo XML</button>
              </div>
            </>
          )}

          {R && (
            <div className="mt-5 border-t border-white/[.08] pt-4">
              {R.loading && <p className="text-sm text-fg-3">Zpracovávám…</p>}
              {R.error && <p className="text-sm font-bold text-alert">{R.error}</p>}
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
          <p className="mt-1 text-[12px] text-fg-3">Transparentnost podle GDPR — zaznamenává se přístup fyzioterapeuta, ne váš vlastní.</p>
          {(boot?.access_log || []).length ? (
            <div className="mt-2 divide-y divide-white/[.07]">{(boot.access_log as any[]).map((x) => (
              <ListRow key={x.id} icon={x.action === "read" ? Eye : Pencil} tone={x.action === "read" ? "muted" : "watch"} title={x.physio_name || "Fyzioterapeut"}
                meta={`${fmtD(x.date)} · ${x.access_count}× ${x.action === "read" ? "čtení" : "zápis"}`}
                trailing={<Chip tone={x.action === "read" ? "muted" : "watch"}>{x.action === "read" ? "čtení" : "zápis"}</Chip>} />
            ))}</div>
          ) : <p className="mt-3 text-sm text-fg-3">Zatím k vašim datům nikdo nepřistupoval.</p>}
        </Card>
        <Card>
          <Label>Historie zařízení</Label>
          {(boot?.device_history || []).length ? (
            <div className="mt-2 divide-y divide-white/[.07]">{(boot.device_history as any[]).slice().reverse().map((h, i) => (
              <ListRow key={i} icon={i === 0 ? Watch : Smartphone} tone={i === 0 ? "ok" : "muted"} title={h.device} meta={`${i === 0 ? "aktuální" : "starší"} · od ${fmtD(h.recorded_at)}`} />
            ))}</div>
          ) : <p className="mt-3 text-sm text-fg-3">Zatím bez záznamu.</p>}
        </Card>
      </div>
    </>
  )
}

// AI summaries & training commentary (backend metrics/coach_texts.py) — opt-in,
// because derived health data goes to an externally hosted model. Phase 1 only
// switches it on and shows a preview; Dnes / Trénink show the texts later.
const COACH_KIND: Record<string, string> = {
  daily_summary: "Denní shrnutí", daily_commentary: "Komentář k tréninku", weekly_summary: "Týdenní shrnutí",
}
function CoachConsentCard({ rid }: { rid: string }) {
  const toast = useToast()
  const [st, setSt] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)
  const [show, setShow] = useState<string | null>(null)
  const polls = useRef(0)
  useEffect(() => {
    let alive = true
    let timer = 0
    const load = () =>
      api.coach(rid).then((d) => {
        if (!alive) return
        setSt(d)
        // texts are written in the background (a hosted model takes a minute or more) — look again
        if (d?.pending?.length && polls.current++ < 20) timer = window.setTimeout(load, 20000)
      }).catch(() => alive && setSt(false))
    load()
    return () => { alive = false; window.clearTimeout(timer) }
  }, [rid, st?.consent])
  const toggle = async () => {
    if (!st || busy) return
    setBusy(true)
    try {
      const next = await api.setCoachConsent(rid, !st.consent)
      polls.current = 0
      setSt({ ...next, pending: next.consent ? ["daily_summary"] : [] })
      toast({ title: next.consent ? "AI shrnutí zapnuta — první texty se připravují" : "AI shrnutí vypnuta, uložené texty smazány" })
    } catch (e: any) {
      toast({ title: e?.message || "Změna se nepodařila" })
    } finally {
      setBusy(false)
    }
  }
  if (st === null) return null
  if (st === false) return <Card className="mt-4"><Label>AI shrnutí a komentáře</Label><p className="mt-2 text-sm text-fg-3">Stav se nepodařilo načíst.</p></Card>
  const texts = st.texts || {}
  const kinds = Object.keys(COACH_KIND).filter((k) => texts[k])
  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between gap-3">
        <span><Label>AI shrnutí a komentáře · beta</Label></span>
        <Switch checked={!!st.consent} onChange={() => toggle()} label="AI shrnutí a komentáře" disabled={busy} />
      </div>
      <p className="mt-2 text-sm leading-6 text-fg-2">
        Denní shrnutí vašeho stavu, komentář k dnešnímu tréninku (engine Kapacitní) a každé pondělí shrnutí uplynulého týdne.
        Píše je jazykový model jen z čísel, která spočítá aplikace. Doporučení nemění a každý text se automaticky kontroluje —
        když kontrolou neprojde, dostanete místo něj text sestavený přímo aplikací.
      </p>
      <p className="mt-2 text-[11px] leading-5 text-fg-3">
        <b className="text-fg-2">Co se odesílá:</b> jen odvozené údaje — zátěž, regenerace, bolest a její místo, dnešní doporučení.
        Žádné jméno, e-mail, město, poloha ani názvy aktivit. Zpracovává je hostovaný model u NVIDIA{st.model ? ` (${st.model})` : ""}.
        Vypnutím se uložené texty smažou.
      </p>
      {st.consent && !st.llm && (
        <p className="mt-2 text-[11px] text-watch">Model teď není nastavený — do té doby dostáváte texty sestavené aplikací.</p>
      )}
      {st.consent && (
        <div className="mt-3 border-t border-white/[.08] pt-3">
          {st.pending?.length > 0 && <p className="mb-2 text-[11px] text-fg-2">Připravuji texty… model na to potřebuje i pár minut.</p>}
          {kinds.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {kinds.map((k) => (
                <button key={k} onClick={() => setShow(show === k ? null : k)}
                  aria-pressed={show === k} className={`rounded-full px-3 py-1.5 text-[12px] font-bold transition ${show === k ? "bg-fg text-ink" : "border border-white/15 text-fg-2 hover:border-white/30"}`}>
                  {COACH_KIND[k]} · {texts[k].source === "llm" ? "AI" : "z aplikace"}
                </button>
              ))}
            </div>
          ) : !st.pending?.length && <p className="text-[11px] text-fg-3">Zatím žádné texty.</p>}
          {show && texts[show] && (
            <div className="nest mt-3 p-3">
              <p className="whitespace-pre-line text-sm leading-6 text-fg">{texts[show].text}</p>
              <p className="mt-2 text-[11px] text-fg-3">
                {texts[show].source === "llm" ? `Napsal model ${texts[show].model}` : "Sestaveno aplikací (model nebyl k dispozici nebo text neprošel kontrolou)"}
                {" · "}{new Date(texts[show].createdAt).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}
              </p>
            </div>
          )}
          <p className="mt-2 text-[11px] text-fg-3">Na záložkách Dnes a Trénink se texty objeví v další fázi; tady je zatím náhled.</p>
        </div>
      )}
    </Card>
  )
}
