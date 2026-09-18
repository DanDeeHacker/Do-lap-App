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
  const toast = useToast()

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
      const r = await api.garminConnect(email, pw)
      if (r.mfa_required) { setRes({ source: "garminlive", mfa: true, mfaToken: r.mfa_token }); toast({ title: "Zadejte ověřovací kód" }) }
      else { setRes({ ok: true, source: "garminlive", activities: r.added_activities, addedDaily: r.added_daily, meta: r.meta }); toast({ title: `${r.added_activities} nových běhů z Garminu` }); refresh() }
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Stažení selhalo." }) }
  }
  const garminMfa = async () => {
    if (!code) return
    setRes({ loading: true, source: "garminlive" })
    try {
      const r = await api.garminMfa(res!.mfaToken!, code)
      setRes({ ok: true, source: "garminlive", activities: r.added_activities, addedDaily: r.added_daily, meta: r.meta })
      toast({ title: `${r.added_activities} nových běhů z Garminu` }); refresh()
    } catch (e: any) { setRes({ ok: false, source: "garminlive", error: e?.message || "Ověření selhalo." }) }
  }

  const R = res?.source === source ? res : null

  return (
    <>
      <div className="mb-6"><Label>Data a připojení</Label><h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">{integ?.status === "connected" ? "Zdroj připojen" : "Zatím nepřipojeno"}</h1></div>
      <div className="grid gap-4 md:grid-cols-3">
        <Metric warm label="Aktivit v účtu" value={`${acts.length}`} caption={acts.length ? `${fmtD(acts.at(-1)?.started_at)} → ${fmtD(acts[0]?.started_at)}` : "zatím bez importu"} />
        <Metric label="Stav" value={integ?.status === "connected" ? "připojeno" : "nepřipojeno"} caption={integ?.provider ? `zdroj ${integ.provider}` : "—"} />
        <Metric label="Profil" value={(me?.name || "").split(" ")[0]} caption="běžec / pacient" />
      </div>

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
              <h2 className="font-serif text-2xl">Stáhnout data přímo z Garmin Connect</h2>
              <p className="mt-2 text-sm text-[#64736e]">Přihlaste se svým účtem — data se stáhnou rovnou. Údaje se použijí <b>jen pro toto stažení</b> a nikam se neukládají. Účty s dvoufázovým ověřením zadají kód níže.</p>
              {!R?.mfa ? (
                <>
                  <Field label="E-mail Garmin Connect"><input value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="vas@email.cz" /></Field>
                  <Field label="Heslo"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="••••••••" /></Field>
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
