import { Fragment, useEffect, useRef, useState } from "react"
import {
  createBrowserRouter,
  Link,
  Outlet,
  RouterProvider,
  useLocation,
  useNavigate,
  useParams,
} from "react-router"
import MuscleAnatomy from "@/components/MuscleAnatomy"

const runnerTabs = [
  ["today", "Přehled"],
  ["post", "Po tréninku"],
  ["mechanics", "Mechanika"],
  ["load", "Zátěž"],
  ["program", "Program"],
  ["messages", "Zprávy"],
]
const roles = [
  ["runner", "Běžec", "Monitoring zátěže a běžecké mechaniky."],
  ["physio", "Fyzioterapeut", "Triage a souvislosti v datech pacientů."],
  ["employer", "Zaměstnavatel", "Anonymní přehled běžecké kohorty."],
  ["partner", "Partner", "Doporučení, konverze a provize."],
]

function useDynamicReveal() {
  useEffect(() => {
    let timer: number | undefined
    const revealLatest = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        const panels =
          document.querySelectorAll<HTMLElement>("[data-auto-reveal]")
        panels
          .item(panels.length - 1)
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" })
      }, 100)
    }
    const observer = new MutationObserver(revealLatest)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => {
      window.clearTimeout(timer)
      observer.disconnect()
    }
  }, [])
}

function Mark() {
  return (
    <span className="grid size-9 place-items-center rounded-xl bg-[#235e59] font-serif text-lg font-bold text-[#f8f7f1]">
      d
    </span>
  )
}
function Topbar() {
  const [profileOpen, setProfileOpen] = useState(false)
  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-[#dfe2da]/80 bg-[#f9f7f1]/95 backdrop-blur">
      <div className="mx-auto flex h-[68px] max-w-[1180px] items-center justify-between px-5">
        <Link
          to="/app/today"
          className="flex items-center gap-2.5 text-lg font-bold tracking-[-.04em]"
        >
          <Mark />
          došlap
        </Link>
        <nav className="hidden items-center gap-6 text-xs font-bold text-[#58716b] md:flex">
          <Link to="/app/today">Můj přehled</Link>
          <Link to="/data">Data a připojení</Link>
          <Link to="/role/physio">Pro odborníky</Link>
        </nav>
        <div className="relative flex items-center gap-2">
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="grid size-9 place-items-center rounded-full bg-[#dcece7] text-[10px] font-bold text-black"
            aria-expanded={profileOpen}
            aria-label="Otevřít profil"
          >
            AK
          </button>
          {profileOpen && (
            <div
              data-auto-reveal
              className="absolute right-0 top-12 w-72 origin-top animate-[careReveal_.28s_ease-out] rounded-2xl border border-white/10 bg-[#102724] p-4 text-[#f1f8f1] shadow-2xl"
            >
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-full bg-[#c7ff54] text-xs font-bold text-[#071313]">
                  AK
                </span>
                <div>
                  <b>Adéla Kučerová</b>
                  <p className="text-[10px] text-[#91b7a9]">běžecký profil</p>
                </div>
              </div>
              <div className="mt-4 border-t border-white/10 pt-3 text-xs text-[#a9c2b9]">
                <p>Garmin připojen</p>
                <p className="mt-1">Cíl: Birell 10K Praha</p>
              </div>
              <Link
                to="/profile"
                onClick={() => setProfileOpen(false)}
                className="mt-4 block rounded-full bg-[#c7ff54] px-3 py-2 text-center text-xs font-bold text-[#071313]"
              >
                Otevřít celý profil
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
function Layout() {
  return (
    <div className="motion-shell min-h-screen bg-[#e7e9e1] text-[#193431]">
      <Topbar />
      <main className="mx-auto min-h-screen max-w-[1180px] bg-[#f9f7f1] px-5 pb-24 pt-24 md:rounded-b-[28px] md:px-9">
        <Outlet />
      </main>
      <AtlasBubble />
      <AtlasNav />
    </div>
  )
}
function Label({ children }: { children: string }) {
  return (
    <p className="font-mono text-[10px] font-medium uppercase tracking-[.16em] text-[#a8c7bd]">
      {children}
    </p>
  )
}
function Card({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`group rounded-[24px] border border-[#dfe2da] bg-white p-5 transition duration-200 hover:-translate-y-0.5 hover:border-[#235e59]/45 hover:shadow-[0_14px_34px_rgb(15_40_36_/_0.12)] ${className}`}
    >
      {children}
    </section>
  )
}
function Metric({
  label,
  value,
  caption,
  warm = false,
}: {
  label: string
  value: string
  caption: string
  warm?: boolean
}) {
  return (
    <Card className={warm ? "border-0 bg-[#235e59] text-[#f8f7f1]" : ""}>
      <Label>{label}</Label>
      <p
        className={`mt-4 font-serif text-4xl tracking-[-.07em] ${
          warm ? "text-white" : ""
        }`}
      >
        {value}
      </p>
      <p
        className={`mt-2 text-xs ${warm ? "text-[#c9dfd8]" : "text-[#6b7b76]"}`}
      >
        {caption}
      </p>
    </Card>
  )
}
function Chart() {
  return (
    <div className="mt-5 flex h-28 items-end gap-1.5 border-b border-[#dae2dd] pb-1">
      {[36, 42, 38, 55, 48, 58, 51, 66, 60, 73, 65, 78].map((h, i) => (
        <i
          key={i}
          style={{ height: `${h}%` }}
          className={`flex-1 rounded-sm ${
            i > 9 ? "bg-[#cf6542]" : "bg-[#b5d3ca]"
          }`}
        />
      ))}
    </div>
  )
}
function NumberedChart() {
  const volume = [18, 21, 19, 26, 24, 28, 25, 31, 29, 34, 32, 35]
  return (
    <div className="mt-7 flex h-32 items-end gap-1.5 border-b border-[#dae2dd] pb-1">
      {volume.map((km, i) => (
        <div key={i} className="relative flex h-full flex-1 items-end">
          <span className="absolute -top-0 left-1/2 -translate-x-1/2 text-[9px] font-bold text-[#9bb3aa]">
            {km}
          </span>
          <i
            style={{ height: `${km * 2}%` }}
            className={`block min-h-1 w-full self-end rounded-t-sm ${
              i > 9 ? "bg-[#cf6542]" : "bg-[#b5d3ca]"
            }`}
          />
        </div>
      ))}
    </div>
  )
}
function RecoveryRanges() {
  const rows = [
    ["Spánek", "7,7 h", "7,0–8,5 h", 58, "#c7ff54"],
    ["HRV", "54 ms", "49–63 ms", 42, "#6ce6d3"],
    ["Klidový tep", "49", "45–52", 55, "#c7ff54"],
  ]
  return (
    <div className="mt-4 space-y-3">
      {rows.map(([name, today, range, pos, color]) => (
        <div
          key={name as string}
          className="grid grid-cols-[72px_1fr_auto] items-center gap-2 text-[10px]"
        >
          <span className="text-[#91b7a9]">{name}</span>
          <div className="relative h-2 rounded-full bg-[#29413b]">
            <i className="absolute left-[18%] right-[16%] top-0 h-full rounded-full bg-[#47756a]" />
            <b
              style={{ left: `${pos}%`, backgroundColor: color as string }}
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[#102724]"
            />
          </div>
          <span className="text-right text-[#d9ebe4]">
            <b>{today}</b>
            <small className="ml-1 text-[#91b7a9]">{range}</small>
          </span>
        </div>
      ))}
    </div>
  )
}
function VolumeGrowth() {
  return (
    <div className="min-w-40 rounded-2xl border border-[#e77a59]/35 bg-[#3c2922] px-3 py-2.5 text-[#ffc1ab]">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[8px] uppercase tracking-[.12em]">
          Tento týden
        </span>
        <b className="text-lg leading-none">+19 %</b>
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-[#e77a59]/20 pt-2 text-[9px]">
        <span>nyní +5,7 km</span>
        <span className="text-[#f6d69a]">zdravě +1,5 km</span>
      </div>
    </div>
  )
}

function SevenDayVolume() {
  const values = [4.2, 5.1, 3.8, 6.4, 4.9, 5.7, 4.7]
  const points = values
    .map((value, index) => `${16 + index * 38},${77 - value * 8}`)
    .join(" ")
  const limit = values.map((_, index) => `${16 + index * 38},30`).join(" ")
  return (
    <Card className="border-0 bg-[#102724] text-[#f1f8f1]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Label>Posledních 7 dní</Label>
          <strong className="mt-2 block font-serif text-3xl">34,8 km</strong>
        </div>
        <span className="rounded-full bg-[#c7ff54]/12 px-2.5 py-1 font-mono text-[9px] text-[#c7ff54]">
          akutní objem
        </span>
      </div>
      <div className="mt-4">
        <svg
          viewBox="0 0 244 92"
          className="h-28 w-full overflow-visible"
          aria-label="Denní objem za posledních sedm dní a zdravý limit růstu"
        >
          <line
            x1="12"
            y1="78"
            x2="240"
            y2="78"
            stroke="currentColor"
            strokeOpacity=".14"
          />
          <polyline
            points={limit}
            fill="none"
            stroke="#c7ff54"
            strokeWidth="1.5"
            strokeOpacity=".42"
            strokeDasharray="4 4"
          />
          <polyline
            points={points}
            fill="none"
            stroke="#6ce6d3"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {values.map((value, index) => (
            <g key={index}>
              <circle
                cx={16 + index * 38}
                cy={77 - value * 8}
                r="3.5"
                fill="#6ce6d3"
              />
              <text
                x={16 + index * 38}
                y={70 - value * 8}
                textAnchor="middle"
                fill="#d9ebe4"
                fontSize="8"
                fontWeight="700"
              >
                {value.toFixed(1).replace(".", ",")}
              </text>
              <text
                x={16 + index * 38}
                y="90"
                textAnchor="middle"
                fill="#91b7a9"
                fontSize="7"
              >
                {["Po", "Út", "St", "Čt", "Pá", "So", "Dnes"][index]}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[10px] text-[#9bb3aa]">
        <i className="h-px w-5 bg-[#6ce6d3]" /> skutečný objem{" "}
        <i className="ml-2 h-px w-5 border-t border-dashed border-[#c7ff54]/50" />{" "}
        zdravý limit +5 %
      </div>
    </Card>
  )
}

function TwentyEightDayVolume() {
  const values = [
    2.6, 3.4, 3.1, 4.2, 2.8, 3.9, 4.1, 3.2, 4.4, 3.8, 4.7, 3.5, 4.1, 5.0, 3.7,
    4.4, 4.8, 3.9, 5.2, 4.5, 5.1, 4.2, 4.9, 5.6, 4.6, 5.3, 5.8, 5.1,
  ]
  const points = values
    .map((value, index) => `${8 + index * 8.25},${76 - value * 8}`)
    .join(" ")
  const baseline = values.map((_, index) => `${8 + index * 8.25},36`).join(" ")
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <Label>Posledních 28 dní</Label>
          <strong className="mt-2 block font-serif text-3xl">116 km</strong>
        </div>
        <span className="text-right text-[10px] leading-4 text-[#71837b]">
          kumulativní limit
          <br />
          <b className="text-[#c7ff54]">120,6 km</b>
        </span>
      </div>
      <svg
        viewBox="0 0 240 88"
        className="mt-4 h-28 w-full overflow-visible"
        aria-label="Objem za posledních 28 dní a kumulativní zdravý limit"
      >
        <line
          x1="6"
          y1="78"
          x2="236"
          y2="78"
          stroke="currentColor"
          strokeOpacity=".12"
        />
        <polyline
          points={baseline}
          fill="none"
          stroke="#c7ff54"
          strokeWidth="1.5"
          strokeOpacity=".4"
          strokeDasharray="4 4"
        />
        <polyline
          points={points}
          fill="none"
          stroke="#235e59"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="231" cy={76 - values[27] * 8} r="3.5" fill="#e77a59" />
        <text x="8" y="88" fill="#71837b" fontSize="7">
          28 dní zpět
        </text>
        <text x="205" y="88" fill="#71837b" fontSize="7">
          dnes
        </text>
      </svg>
      <div className="mt-1 flex items-center gap-2 text-[10px] text-[#71837b]">
        <i className="h-px w-5 bg-[#235e59]" /> denní objem{" "}
        <i className="ml-2 h-px w-5 border-t border-dashed border-[#c7ff54]/50" />{" "}
        kumulativní limit +5 %
      </div>
    </Card>
  )
}

function BaselineBoxplot() {
  return (
    <Card>
      <Label>EWMA vůči baseline</Label>
      <strong className="mt-2 block font-serif text-3xl">1,34</strong>
      <p className="mt-1 text-[10px] text-[#71837b]">
        mírně nad obvyklým rozsahem
      </p>
      <div className="mt-7">
        <div className="relative h-7">
          <i className="absolute left-[12%] right-[11%] top-1/2 h-px -translate-y-1/2 bg-[#9bb3aa]" />
          <i className="absolute left-[26%] right-[28%] top-1/2 h-4 -translate-y-1/2 rounded-sm bg-[#6ce6d3]/35" />
          <i className="absolute left-1/2 top-1/2 h-6 w-px -translate-y-1/2 bg-[#235e59]" />
          <i className="absolute left-[75%] top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#e77a59] ring-4 ring-[#e77a59]/15" />
        </div>
        <div className="flex justify-between text-[9px] text-[#71837b]">
          <span>0,75</span>
          <span>baseline 1,00</span>
          <span>1,50</span>
        </div>
      </div>
    </Card>
  )
}

function TrainingBalance() {
  return (
    <Card>
      <Label>Tréninková bilance</Label>
      <strong className="mt-2 block font-serif text-3xl">−8</strong>
      <p className="mt-1 text-[10px] text-[#71837b]">
        střední únava stále použitelný prostor pro pohyb
      </p>
      <div className="mt-6">
        <div className="relative h-3 rounded-full bg-[#edf0e9]">
          <i className="absolute left-1/2 top-0 h-full w-px bg-[#91b7a9]" />
          <i className="absolute left-[30%] top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#e77a59] ring-4 ring-[#e77a59]/15" />
        </div>
        <div className="mt-2 flex justify-between text-[9px] text-[#71837b]">
          <span>více únavy</span>
          <span>rovnováha</span>
          <span>více svěžesti</span>
        </div>
      </div>
    </Card>
  )
}

function LoadRecoveryRanges() {
  const rows = [
    ["HRV", "54 ms", "49  63 ms", 42, "#6ce6d3"],
    ["Klidový tep", "49", "45  52", 55, "#c7ff54"],
    ["Spánek", "7,7 h", "7,0  8,5 h", 58, "#6ce6d3"],
  ]
  return (
    <div className="mt-5 space-y-5">
      {rows.map(([name, value, range, position, color]) => (
        <div
          key={name as string}
          className="grid grid-cols-[84px_1fr] gap-x-4 gap-y-2 text-xs"
        >
          <span className="font-semibold">{name}</span>
          <span className="text-right font-serif text-lg leading-none">
            {value}
          </span>
          <div className="col-span-2 relative h-2 rounded-full bg-[#edf0e9]">
            <i className="absolute left-[18%] right-[16%] top-0 h-full rounded-full bg-[#6ce6d3]/25" />
            <b
              style={{ left: `${position}%`, backgroundColor: color as string }}
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[#102724]"
            />
          </div>
          <span className="col-span-2 text-[10px] text-[#71837b]">
            Váš obvyklý rozsah: {range}
          </span>
        </div>
      ))}
    </div>
  )
}

function Today() {
  const [open, setOpen] = useState(false)
  const [feeling, setFeeling] = useState<number | null>(null)
  return (
    <>
      <div className="flex items-end justify-between">
        <div>
          <Label>Úterý 18. srpna</Label>
          <h1 className="mt-1 font-serif text-4xl leading-none tracking-[-.06em] md:text-5xl">
            Dobré ráno, Adélo.
          </h1>
        </div>
        <span className="text-2xl">☼</span>
      </div>
      <div className="mt-7 grid gap-4 lg:grid-cols-[1.4fr_.8fr]">
        <section className="relative overflow-hidden rounded-[24px] bg-[#235e59] p-6 text-[#f8f7f1]">
          <i className="absolute -right-10 -top-10 size-36 rounded-full border-[22px] border-[#559188]/40" />
          <Label>Dnešní doporučení</Label>
          <h2 className="relative mt-5 font-serif text-3xl leading-[.95] tracking-[-.05em]">
            Lehký běh
            <br />
            je v pořádku.
          </h2>
          <p className="relative mt-3 max-w-md text-sm leading-6 text-[#cbe1db]">
            Tělo drží rytmus. Dnes zůstaň v konverzačním tempu, do 45 minut.
          </p>
          <div className="relative mt-6 flex gap-8 border-t border-[#579087] pt-4 text-xs">
            <span>
              <b className="block font-mono text-[9px] uppercase text-[#b7d6cd]">
                Intenzita
              </b>
              nízká
            </span>
            <span>
              <b className="block font-mono text-[9px] uppercase text-[#b7d6cd]">
                Objem
              </b>
              do 45 min
            </span>
          </div>
        </section>
        <Card>
          <div className="flex justify-between">
            <Label>Připravenost</Label>
            <span className="text-[#235e59]">i</span>
          </div>
          <div className="mt-4 flex items-end gap-3">
            <strong className="font-serif text-5xl tracking-[-.08em]">
              78
            </strong>
            <span className="mb-1 rounded-full bg-[#e3f0e8] px-2 py-1 text-[10px] font-bold text-[#247252]">
              +6 tento týden
            </span>
          </div>
          <div className="mt-5 h-2 overflow-hidden rounded-full bg-[#edf0e9]">
            <i className="block h-full w-[78%] rounded-full bg-[#75ac8a]" />
          </div>
          <p className="mt-3 text-xs leading-5 text-[#687872]">
            Spánek a HRV jsou blízko vašeho normálu.
          </p>
        </Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_.8fr]">
        <Card>
          <div className="flex justify-between">
            <div>
              <Label>Zátěž 12 týdnů</Label>
              <h2 className="mt-1 font-serif text-2xl tracking-[-.05em]">
                V obvyklém pásmu
              </h2>
            </div>
            <span className="h-fit rounded-full bg-[#fff0df] px-2 py-1 text-[10px] font-bold text-[#a45431]">
              mírně ↑
            </span>
          </div>
          <Chart />
          <p className="mt-3 text-xs text-[#657872]">
            Akutní / chronická zátěž{" "}
            <b className="float-right text-[#193431]">1,34</b>
          </p>
        </Card>
        <Card className="bg-[#edf0e9]">
          <Label>Mechanika</Label>
          <div className="mt-3 flex gap-4">
            <div className="grid size-16 place-items-center rounded-full border-[7px] border-[#f6d69a] border-r-[#e47d51] font-serif text-xl">
              1
            </div>
            <div>
              <h2 className="font-serif text-xl tracking-[-.04em]">
                Jemný drift
              </h2>
              <p className="mt-1 text-xs leading-5 text-[#64736e]">
                Vertikální poměr je výš než obvykle.
              </p>
            </div>
          </div>
          <button className="mt-4 text-xs font-bold text-[#235e59] underline decoration-[#91b8b0] underline-offset-4">
            Zobrazit souvislost
          </button>
        </Card>
      </div>
      <p className="mx-auto mt-8 max-w-2xl text-center text-[10px] leading-4 text-[#89938f]">
        Došlap podporuje rozhodování odborníka. Není zdravotnický prostředek a
        nestanovuje diagnózu ani léčbu.
      </p>
      <button
        onClick={() => setOpen(true)}
        className={`fixed bottom-[5.25rem] right-5 z-50 flex items-center gap-2 rounded-full bg-[#e47d51] px-4 py-3 text-sm font-bold text-white shadow-lg transition ${
          open ? "scale-75 opacity-0" : ""
        }`}
      >
        <span className="grid size-6 place-items-center rounded-full bg-white/20">
          ♡
        </span>
        Check-in
      </button>
      {open && (
        <Checkin
          feeling={feeling}
          setFeeling={setFeeling}
          close={() => setOpen(false)}
        />
      )}
    </>
  )
}
function Checkin({
  feeling,
  setFeeling,
  close,
}: {
  feeling: number | null
  setFeeling: (n: number) => void
  close: () => void
}) {
  return (
    <div
      data-auto-reveal
      className="fixed inset-x-0 bottom-[4.3rem] z-[60] mx-auto h-[66dvh] max-w-[480px] overflow-hidden rounded-t-[30px] bg-[#f9f7f1] shadow-[0_-14px_45px_rgba(25,52,49,.2)] md:bottom-5 md:right-5 md:left-auto md:rounded-[30px]"
    >
      <div className="grid h-full grid-rows-[1.6fr_1fr]">
        <div className="p-5">
          <div className="flex justify-between">
            <div>
              <Label>Denní check-in</Label>
              <h2 className="mt-1 font-serif text-3xl tracking-[-.05em]">
                Jak se dnes cítí tělo?
              </h2>
            </div>
            <button
              onClick={close}
              className="grid size-9 place-items-center rounded-full border border-[#d8ddd5] bg-white text-lg"
            >
              ×
            </button>
          </div>
          <p className="mt-2 text-xs leading-5 text-[#64736e]">
            Jeden rychlý signál pro přesnější doporučení dnešního pohybu.
          </p>
          <div className="mt-5 grid grid-cols-5 gap-2">
            {["☹", "◔", "○", "◡", "☀"].map((f, i) => (
              <button
                onClick={() => setFeeling(i)}
                key={f}
                className={`aspect-square rounded-2xl border text-xl ${
                  feeling === i
                    ? "border-[#e47d51] bg-[#fff0e8]"
                    : "border-[#dfe2da] bg-white"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <button
            onClick={close}
            disabled={feeling === null}
            className="mt-5 w-full rounded-full bg-[#235e59] py-3 text-sm font-bold text-white disabled:bg-[#b5c1bc]"
          >
            Uložit dnešní check-in
          </button>
        </div>
        <div className="border-t border-[#dce0d8] bg-[#edf0e9] p-5">
          <Label>Dnešní kontext</Label>
          <div className="mt-3 grid grid-cols-3 divide-x divide-[#d2dbd5]">
            <p className="font-serif text-2xl">
              78
              <span className="block font-sans text-[10px] text-[#687671]">
                připravenost
              </span>
            </p>
            <p className="pl-3 font-serif text-2xl">
              7:42
              <span className="block font-sans text-[10px] text-[#687671]">
                spánek
              </span>
            </p>
            <p className="pl-3 font-serif text-2xl">
              1,34
              <span className="block font-sans text-[10px] text-[#687671]">
                zátěž
              </span>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
function GenericRunner() {
  const { tab } = useParams()
  const current = runnerTabs.find((x) => x[0] === tab)?.[1] || "Přehled"
  return (
    <>
      <Label>{current}</Label>
      <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
        {tab === "mechanics"
          ? "Jak se mění váš běh"
          : tab === "load"
            ? "Kolik toho unesete"
            : tab === "post"
              ? "Hodnocení po tréninku"
              : tab === "program"
                ? "Váš pohybový program"
                : "Zprávy a péče"}
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-[#64736e]">
        Přehled je postavený na vašich vlastních datech a vysvětluje jen
        souvislosti, které pro vás dávají smysl.
      </p>
      <div className="mt-7 grid gap-4 md:grid-cols-3">
        <Metric
          label="Aktuální hodnota"
          value={tab === "load" ? "34,8 km" : "86 %"}
          caption="v osobním rozsahu"
          warm
        />
        <Metric label="Baseline" value="vysoká" caption="spolehlivost 86 %" />
        <Metric label="Poslední běh" value="8,2 km" caption="včera   lehce" />
      </div>
      <Card className="mt-4">
        <Label>Vývoj v čase</Label>
        <Chart />
        <p className="mt-4 text-sm leading-6 text-[#64736e]">
          Jednotlivé signály můžete rozkliknout, abyste viděli konkrétní čísla,
          evidenci i jejich limity.
        </p>
      </Card>
    </>
  )
}
function Quadrant() {
  return (
    <div className="group relative">
      <div className="mt-4 grid grid-cols-2 overflow-hidden rounded-xl border border-[#d5ded8] text-[10px]">
        <span className="bg-[#e2f0e8] p-3 text-[#163c32]">stabilní</span>
        <span className="relative bg-[#fff0df] p-3 font-bold text-[#7c431f]">
          driftuje
          <i className="atlas-point absolute right-2 top-2 size-2.5 rounded-full bg-[#e47d51] ring-2 ring-[#fff0df]" />
          <small className="mt-1 block font-normal text-[#a45431]">
            vy jste zde
          </small>
        </span>
        <span className="bg-[#edf0e9] p-3">odlehčit</span>
        <span className="bg-[#f8e9e4] p-3 font-bold text-[#ad5434]">
          objednat fyzio
        </span>
      </div>
      <div className="pointer-events-none absolute right-0 top-full z-20 mt-2 w-72 translate-y-1 rounded-2xl bg-[#193431] p-4 text-xs leading-5 text-[#e4eee9] opacity-0 shadow-xl transition group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100">
        <b className="block font-serif text-lg text-white">Tichý drift</b>
        Mechanika se změnila oproti vašemu normálu, aniž by objem narostl. To je
        vhodný moment pro včasnou konzultaci ne diagnóza.
      </div>
    </div>
  )
}
function PeriodControl({
  label,
  offset,
  setOffset,
  daily = false,
}: {
  label: string
  offset: number
  setOffset: (value: number) => void
  daily?: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => setOffset(offset - 1)}
        className="grid size-7 place-items-center rounded-full border border-white/15 text-xs"
      >
        ←
      </button>
      <span className="min-w-28 text-center font-mono text-[9px] uppercase tracking-[.12em] text-[#91b7a9]">
        {offset === 0 ? label : daily ? offset === -1 ? "včera" : `${Math.abs(offset)} dny zpět` : `${Math.abs(offset)}. týden zpět`}
      </span>
      <button
        disabled={offset === 0}
        onClick={() => setOffset(offset + 1)}
        className="grid size-7 place-items-center rounded-full border border-white/15 text-xs disabled:opacity-30"
      >
        →
      </button>
    </div>
  )
}
function TodayV2() {
  const [open, setOpen] = useState(false)
  const [feeling, setFeeling] = useState<number | null>(null)
  const [week, setWeek] = useState(0)
  const [recoveryWeek, setRecoveryWeek] = useState(0)
  return (
    <>
      <div className="flex items-end justify-between">
        <div>
          <Label>Úterý 18. srpna</Label>
          <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
            Dobré ráno, Adélo.
          </h1>
        </div>
      </div>
      <div className="mt-7 grid gap-4 lg:grid-cols-[1.45fr_.8fr]">
        <section className="rounded-[24px] border border-white/10 bg-[#0c201d] p-6 text-[#f1f8f1]">
          <Label>Energie pro dnešek</Label>
          <div className="mt-3 flex items-end justify-between">
            <b className="text-4xl">
              78{" "}
              <small className="text-sm font-normal text-[#9bb3aa]">
                / 100
              </small>
            </b>
          </div>
          <div className="relative mt-4 h-7 rounded-md border border-[#c7ff54]/35 bg-[#071313] p-1">
            <i className="absolute inset-y-1 left-1 w-[72%] rounded-sm bg-[#c7ff54]/45" />
            <i className="absolute inset-y-1 left-[72%] w-[6%] rounded-r-sm border-l border-[#071313] bg-[#c7ff54] shadow-[0_0_18px_rgb(199_255_84_/_0.45)]" />
            <span className="absolute left-[75%] top-[-1.45rem] -translate-x-1/2 text-sm text-[#c7ff54]">
              ☾
            </span>
            <i className="absolute inset-y-1 left-1/4 w-px bg-[#071313]/50" />
            <i className="absolute inset-y-1 left-1/2 w-px bg-[#071313]/50" />
            <i className="absolute inset-y-1 left-3/4 w-px bg-[#071313]/50" />
            <i className="absolute -right-1.5 top-1/2 h-3 w-1.5 -translate-y-1/2 rounded-r-sm bg-[#c7ff54]/50" />
          </div>
          <div className="mt-2 flex justify-between text-[9px] text-[#71837b]">
            <span>nízká</span>
            <span>vyvážená</span>
            <span>plná</span>
          </div>
          <div className="mt-5 grid gap-2 border-t border-white/10 pt-4 text-xs">
            <div className="flex items-center gap-3">
              <span className="grid size-6 place-items-center rounded-full bg-[#6ce6d3]/15 text-[#6ce6d3]">
                ☾
              </span>
              <span>
                <b>Spánek dobil rezervu</b>
                <small className="ml-2 text-[#91b7a9]">+6 bodů přes noc</small>
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="grid size-6 place-items-center rounded-full bg-[#c7ff54]/15 text-[#c7ff54]">
                ↗
              </span>
              <span>
                <b>Lehký běh je vhodný</b>
                <small className="ml-2 text-[#91b7a9]">do 45 minut</small>
              </span>
            </div>
          </div>
        </section>
        <Card>
          <PeriodControl
            label="dnes"
            offset={recoveryWeek}
            setOffset={setRecoveryWeek}
            daily
          />
          <RecoveryRanges />
        </Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.45fr_.8fr]">
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Label>Zátěž 12 týdnů</Label>
              <h2 className="mt-1 font-serif text-2xl">V obvyklém pásmu</h2>
            </div>
            <PeriodControl
              label="tento týden"
              offset={week}
              setOffset={setWeek}
            />
          </div>
          <NumberedChart />
          <div className="mt-3 grid grid-cols-3 text-xs text-[#657872]">
            <span>
              Akutní <b className="block text-[#193431]">34,8 km</b>
            </span>
            <span>
              Chronická <b className="block text-[#193431]">29,1 km</b>
            </span>
            <span>
              Monotónnost <b className="block text-[#193431]">1,82</b>
            </span>
          </div>
        </Card>
        <Card className="bg-[#edf0e9]">
          <div className="flex items-center justify-between gap-3">
            <Label>Mechanika</Label>
            <PeriodControl
              label="tento týden"
              offset={week}
              setOffset={setWeek}
            />
          </div>
          <div className="mt-3 flex gap-4">
            <div className="grid size-16 place-items-center rounded-full border-[7px] border-[#f6d69a] border-r-[#e47d51] font-serif text-xl">
              60
            </div>
            <div>
              <h2 className="font-serif text-xl">Jemný drift</h2>
              <p className="mt-1 text-xs text-[#64736e]">
                Vertikální poměr +3,2 % proti baseline.
              </p>
            </div>
          </div>
          <Quadrant />
          <p className="mt-3 text-[10px] text-[#6e817a]">
            Podržte nebo najeďte pro vysvětlení kvadrantu.
          </p>
          <div className="mt-5 border-t border-white/10 pt-4">
            <div className="flex items-center justify-between"><Label>Trend signálů po týdnech</Label><span className="text-[9px] text-[#71837b]">6 týdnů</span></div>
            <svg viewBox="0 0 260 72" className="mt-3 h-20 w-full overflow-visible" aria-label="Šestitýdenní trend mechanických signálů"><path d="M8 51 L56 46 L104 48 L152 37 L200 40 L252 24" fill="none" stroke="#e77a59" strokeWidth="2.5" strokeLinecap="round"/><path d="M8 35 L56 33 L104 36 L152 31 L200 33 L252 30" fill="none" stroke="#6ce6d3" strokeWidth="2" strokeDasharray="4 4"/>{[51,46,48,37,40,24].map((y,index)=><g key={index}><circle cx={8+index*48.8} cy={y} r="3" fill="#e77a59"/><text x={8+index*48.8} y="70" textAnchor="middle" fill="#71837b" fontSize="8">T{index+1}</text></g>)}</svg>
            <div className="flex gap-4 text-[9px] text-[#71837b]"><span><i className="mr-1 inline-block size-2 rounded-full bg-[#e77a59]"/>drift</span><span><i className="mr-1 inline-block h-px w-3 align-middle border-t border-dashed border-[#6ce6d3]"/>obvyklý rozsah</span></div>
          </div>
        </Card>
      </div>
    </>
  )
}
function MechanicsMetric({
  label,
  value,
  baseline,
  delta,
  position,
  active,
  onSelect,
  weeks = [],
}: {
  label: string
  value: string
  baseline: string
  delta: string
  position: number
  active: boolean
  onSelect: () => void
  weeks?: number[]
}) {
  const hasWeeks = weeks.length > 0
  const wkMinV = hasWeeks ? Math.min(...weeks) : 0
  const wkMaxV = hasWeeks ? Math.max(...weeks) : 1
  const wkPad = (wkMaxV - wkMinV) * 0.35 || 1
  const wkLo = wkMinV - wkPad
  const wkHi = wkMaxV + wkPad
  const wkFmt = (v: number) =>
    label === "Vertikální poměr"
      ? v.toFixed(1).replace(".", ",")
      : String(Math.round(v))
  const wkY = (v: number) => 72 - ((v - wkLo) / (wkHi - wkLo)) * 54
  // Map bar centers to the same horizontal fractions as the trend chart below
  // (viewBox -28..274, points at x = 14 + i*35) so the two charts align.
  const wkX = (index: number) => ((42 + index * 35) / 302) * 220
  return (
    <button
      onClick={onSelect}
      className="group w-full p-4 text-left"
    >
      <div className="flex items-start justify-between gap-3">
        <Label>{label}</Label>
        <span
          className={`rounded-full px-2 py-1 text-[9px] font-bold ${
            delta.includes("+")
              ? "bg-[#e77a59]/15 text-[#ffc1ab]"
              : "bg-[#c7ff54]/10 text-[#c7ff54]"
          }`}
        >
          {delta}
        </span>
      </div>
      <strong className="mt-4 block font-serif text-3xl tracking-[-.05em] text-[#f1f8f1]">
        {value}
      </strong>
      <div className="mt-4">
        <div className="relative h-2 rounded-full bg-[#071313]">
          <i className="absolute left-[20%] right-[18%] top-0 h-full rounded-full bg-[#6ce6d3]/25" />
          <i className="absolute left-1/2 top-[-3px] h-3.5 w-px bg-[#91b7a9]" />
          <i
            style={{ left: `${position}%` }}
            className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#e77a59] ring-4 ring-[#e77a59]/15"
          />
        </div>
        <p className="mt-2 text-[10px] text-[#9bb3aa]">
          váš obvyklý střed: {baseline}
        </p>
      </div>
      {hasWeeks && (
        <div className="mt-4 border-t border-white/5 pt-3">
          <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">
            Průměr 8 týdnů zpět
          </p>
          <svg
            viewBox="0 0 220 96"
            className="mt-2 h-24 w-full overflow-visible"
            aria-label={`Týdenní průměry metriky ${label}`}
          >
            {/* Y axis */}
            <line x1="22" y1="10" x2="22" y2="74" stroke="#6ce6d3" strokeOpacity=".3" />
            {[wkMaxV, wkMinV].map((tick, tickIndex) => (
              <g key={tickIndex}>
                <line
                  x1="19"
                  y1={wkY(tick)}
                  x2="22"
                  y2={wkY(tick)}
                  stroke="#6ce6d3"
                  strokeOpacity=".35"
                />
                <text
                  x="17"
                  y={wkY(tick) + 2.5}
                  textAnchor="end"
                  fill="#71837b"
                  fontSize="6.5"
                >
                  {wkFmt(tick)}
                </text>
              </g>
            ))}
            {weeks.map((weekValue, index) => {
              const latest = index === weeks.length - 1
              const barW = 9
              const cx = wkX(index)
              const y = wkY(weekValue)
              return (
                <g key={index}>
                  <text
                    x={cx}
                    y={y - 4}
                    textAnchor="middle"
                    fill={latest ? "#ffc1ab" : "#9bb3aa"}
                    fontSize="6"
                    fontWeight={latest ? "bold" : "normal"}
                  >
                    {wkFmt(weekValue)}
                  </text>
                  <rect
                    x={cx - barW / 2}
                    y={y}
                    width={barW}
                    height={Math.max(72 - y, 1)}
                    rx="2"
                    fill={latest ? "#e77a59" : "#6ce6d3"}
                    fillOpacity={latest ? 1 : 0.45}
                  />
                  <text
                    x={cx}
                    y="86"
                    textAnchor="middle"
                    fill={latest ? "#ffc1ab" : "#71837b"}
                    fontSize="6.5"
                  >
                    {latest ? "nyní" : `−${weeks.length - index}`}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>
      )}
    </button>
  )
}

type TerrainRun = {
  date: string
  dist: string
  pace: string
  vr: string
  gct: string
  cad: string
  weight: number
}

type Terrain = {
  name: string
  value: string
  position: number
  confidence: string
  runs: TerrainRun[]
}

const TERRAINS: Terrain[] = [
  {
    name: "Rovina",
    value: "7,9 %",
    position: 78,
    confidence: "vysoká",
    runs: [
      { date: "29. 8.", dist: "12,4 km", pace: "5:18", vr: "7,8 %", gct: "248 ms", cad: "174 spm", weight: 34 },
      { date: "25. 8.", dist: "9,1 km", pace: "5:02", vr: "7,9 %", gct: "246 ms", cad: "175 spm", weight: 28 },
      { date: "21. 8.", dist: "6,2 km", pace: "5:31", vr: "8,0 %", gct: "251 ms", cad: "173 spm", weight: 22 },
      { date: "18. 8.", dist: "14,0 km", pace: "5:24", vr: "7,9 %", gct: "247 ms", cad: "174 spm", weight: 16 },
    ],
  },
  {
    name: "Mírné stoupání",
    value: "8,0 %",
    position: 61,
    confidence: "střední",
    runs: [
      { date: "27. 8.", dist: "8,0 km", pace: "4:41", vr: "8,1 %", gct: "236 ms", cad: "178 spm", weight: 45 },
      { date: "23. 8.", dist: "18,6 km", pace: "5:34", vr: "7,9 %", gct: "251 ms", cad: "173 spm", weight: 32 },
      { date: "16. 8.", dist: "10,3 km", pace: "5:12", vr: "8,0 %", gct: "243 ms", cad: "175 spm", weight: 23 },
    ],
  },
  {
    name: "Trail",
    value: "nedostatek dat",
    position: 0,
    confidence: "málo dat",
    runs: [],
  },
]

function TerrainProfiles() {
  const [open, setOpen] = useState<string | null>(null)

  return (
    <Card className="mt-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <Label>Profily terénu</Label>
          <h2 className="mt-2 font-serif text-2xl">Kde se změna ukazuje</h2>
        </div>
        <span className="text-[10px] text-[#71837b]">8 srovnatelných běhů</span>
      </div>
      <div className="mt-6 space-y-3">
        {TERRAINS.map((t) => {
          const isOpen = open === t.name
          const hasRuns = t.runs.length > 0
          return (
            <div
              key={t.name}
              className={`rounded-2xl border transition ${
                isOpen
                  ? "border-[#6ce6d3]/45 bg-[#0f2621]"
                  : "border-transparent"
              }`}
            >
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : hasRuns ? t.name : null)}
                aria-expanded={isOpen}
                disabled={!hasRuns}
                className={`grid w-full grid-cols-[96px_1fr_auto_14px] items-center gap-3 rounded-2xl px-2 py-2 text-left text-xs ${
                  hasRuns ? "hover:bg-[#102724]" : "cursor-default opacity-70"
                }`}
              >
                <span className="font-semibold">{t.name}</span>
                <div className="relative h-2 rounded-full bg-[#edf0e9]">
                  <i className="absolute left-[25%] right-[28%] top-0 h-full rounded-full bg-[#6ce6d3]/25" />
                  {t.position > 0 && (
                    <i
                      style={{ left: `${t.position}%` }}
                      className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#e77a59] ring-4 ring-[#e77a59]/15"
                    />
                  )}
                </div>
                <span className="text-right">
                  <b className="block text-[#f1f8f1]">{t.value}</b>
                  <small className="text-[9px] text-[#71837b]">
                    {t.confidence}
                  </small>
                </span>
                <i
                  aria-hidden
                  className={`justify-self-end text-[9px] text-[#6ce6d3] transition-transform ${
                    hasRuns ? "" : "opacity-0"
                  } ${isOpen ? "rotate-180" : ""}`}
                >
                  ▾
                </i>
              </button>

              {isOpen && hasRuns && (
                <section
                  data-auto-reveal=""
                  className="origin-top animate-[careReveal_.28s_ease-out] px-2 pb-3"
                >
                  <p className="mb-2 mt-1 text-[10px] uppercase tracking-[0.14em] text-[#71837b]">
                    {t.runs.length} běhů ve výpočtu · váženo podle vzdálenosti
                  </p>
                  <ul className="space-y-1.5">
                    {t.runs.map((r) => (
                      <li
                        key={r.date}
                        className="rounded-xl bg-[#102724] px-3 py-2"
                      >
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-semibold text-[#f1f8f1]">
                            {r.date} · {r.dist}
                          </span>
                          <span className="text-[#6ce6d3]">
                            podíl {r.weight} %
                          </span>
                        </div>
                        <div className="mt-1.5 h-1 rounded-full bg-[#071313]">
                          <i
                            style={{ width: `${r.weight}%` }}
                            className="block h-full rounded-full bg-[#6ce6d3]/60"
                          />
                        </div>
                        <dl className="mt-2 grid grid-cols-4 gap-2 text-[9px] text-[#9bb3aa]">
                          {[
                            ["Tempo", r.pace],
                            ["Vert. poměr", r.vr],
                            ["Kontakt", r.gct],
                            ["Kadence", r.cad],
                          ].map(([k, v]) => (
                            <div key={k}>
                              <dt className="uppercase tracking-[0.1em]">{k}</dt>
                              <dd className="mt-0.5 font-mono text-[10px] text-[#f1f8f1]">
                                {v}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function RunHistory() {
  const [open, setOpen] = useState(false)
  const [openRun, setOpenRun] = useState<number | null>(null)
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }, 120)
    return () => window.clearTimeout(timer)
  }, [open])

  const runs = [
    {
      date: "29. 8.",
      type: "Vytrvalostní",
      dist: "12,4 km",
      pace: "5:18 /km",
      hr: "148 tep",
      vr: "7,8 %",
      gct: "248 ms",
      cad: "174 spm",
      stride: "1,18 m",
      power: "268 W",
      osc: "8,4 cm",
      balance: "49,6 / 50,4 %",
    },
    {
      date: "27. 8.",
      type: "Tempo",
      dist: "8,0 km",
      pace: "4:41 /km",
      hr: "162 tep",
      vr: "8,1 %",
      gct: "236 ms",
      cad: "178 spm",
      stride: "1,29 m",
      power: "301 W",
      osc: "8,9 cm",
      balance: "49,1 / 50,9 %",
    },
    {
      date: "25. 8.",
      type: "Regenerační",
      dist: "6,2 km",
      pace: "6:02 /km",
      hr: "132 tep",
      vr: "7,5 %",
      gct: "255 ms",
      cad: "172 spm",
      stride: "1,08 m",
      power: "241 W",
      osc: "8,1 cm",
      balance: "50,0 / 50,0 %",
    },
    {
      date: "23. 8.",
      type: "Dlouhý běh",
      dist: "18,6 km",
      pace: "5:34 /km",
      hr: "151 tep",
      vr: "7,9 %",
      gct: "251 ms",
      cad: "173 spm",
      stride: "1,15 m",
      power: "259 W",
      osc: "8,6 cm",
      balance: "49,4 / 50,6 %",
    },
    {
      date: "21. 8.",
      type: "Intervaly",
      dist: "9,3 km",
      pace: "4:12 /km",
      hr: "168 tep",
      vr: "8,3 %",
      gct: "229 ms",
      cad: "181 spm",
      stride: "1,34 m",
      power: "318 W",
      osc: "9,2 cm",
      balance: "48,8 / 51,2 %",
    },
  ]

  return (
    <>
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="mt-4 flex w-full items-center justify-between gap-4 rounded-[24px] border border-white/10 bg-[#102724] px-5 py-4 text-left text-[#f1f8f1] transition hover:border-[#6ce6d3]/40 hover:shadow-[0_14px_34px_rgb(0_0_0_/_0.25)]"
      >
        <span>
          <span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
            Historie běhů
          </span>
          <span className="mt-1 block font-serif text-xl">
            Všechny běhy z Garminu
          </span>
        </span>
        <span
          className={`grid size-8 shrink-0 place-items-center rounded-full border border-white/15 text-sm transition-transform ${
            open ? "rotate-180" : ""
          }`}
        >
          ⌄
        </span>
      </button>

      {open && (
        <section
          data-auto-reveal
          ref={ref}
          className="mt-3 origin-top animate-[careReveal_.28s_ease-out] overflow-hidden rounded-[24px] border border-[#6ce6d3]/25 bg-[#0c201d] p-4 text-[#f1f8f1] shadow-[0_18px_35px_rgb(0_0_0_/_0.2)] md:p-5"
        >
          <div className="flex items-end justify-between gap-4">
            <div>
              <Label>Klíčové metriky</Label>
              <h2 className="mt-2 font-serif text-2xl">
                Klepněte na běh pro detail
              </h2>
            </div>
            <span className="text-[10px] text-[#71837b]">{runs.length} běhů</span>
          </div>

          <div className="mt-4 grid grid-cols-[auto_1fr_auto_auto] gap-x-3 border-b border-white/10 pb-2 font-mono text-[9px] uppercase tracking-[.12em] text-[#71837b]">
            <span>Datum</span>
            <span>Typ</span>
            <span className="text-right">Vzdálenost</span>
            <span className="text-right">Tempo</span>
          </div>

          <div className="divide-y divide-white/5">
            {runs.map((run, index) => {
              const expanded = openRun === index
              return (
                <div key={index}>
                  <button
                    onClick={() =>
                      setOpenRun((value) => (value === index ? null : index))
                    }
                    aria-expanded={expanded}
                    className={`grid w-full grid-cols-[auto_1fr_auto_auto] items-center gap-x-3 py-3 text-left text-xs transition ${
                      expanded ? "text-[#f1f8f1]" : "text-[#c5d9d1]"
                    } hover:text-[#f1f8f1]`}
                  >
                    <span className="font-semibold">{run.date}</span>
                    <span className="flex items-center gap-2">
                      {run.type}
                      <i
                        className={`text-[9px] text-[#6ce6d3] transition-transform ${
                          expanded ? "rotate-180" : ""
                        }`}
                      >
                        ⌄
                      </i>
                    </span>
                    <b className="text-right">{run.dist}</b>
                    <span className="text-right text-[#9bb3aa]">{run.pace}</span>
                  </button>

                  {expanded && (
                    <div
                      data-auto-reveal
                      className="origin-top animate-[careReveal_.24s_ease-out] pb-4"
                    >
                      <div className="rounded-2xl bg-[#071313] p-4">
                        <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">
                          Mechanika z Garminu
                        </p>
                        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                          {[
                            ["Srdeční tep", run.hr],
                            ["Vertikální poměr", run.vr],
                            ["Kontakt se zemí", run.gct],
                            ["Kadence", run.cad],
                            ["Délka kroku", run.stride],
                            ["Běžecký výkon", run.power],
                            ["Vert. oscilace", run.osc],
                            ["Balanc L/P", run.balance],
                          ].map(([metricLabel, metricValue]) => (
                            <div
                              key={metricLabel}
                              className="rounded-xl border border-white/5 bg-[#0c201d] p-3"
                            >
                              <p className="text-[9px] text-[#71837b]">
                                {metricLabel}
                              </p>
                              <b className="mt-1 block text-sm text-[#f1f8f1]">
                                {metricValue}
                              </b>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}
    </>
  )
}

function MechanicsTrend({
  metric,
  embedded = false,
}: {
  metric: string
  embedded?: boolean
}) {
  const trend =
    metric === "Vertikální poměr"
      ? [7.3, 7.4, 7.5, 7.4, 7.6, 7.7, 7.5, 7.8]
      : metric === "Kontakt se zemí"
        ? [239, 243, 241, 244, 246, 242, 247, 248]
        : [176, 175, 175, 174, 174, 176, 173, 174]
  const min = Math.min(...trend) - (metric === "Kontakt se zemí" ? 3 : 0.25)
  const max = Math.max(...trend) + (metric === "Kontakt se zemí" ? 3 : 0.25)
  // Taller vertical plot area so the trend line has more amplitude.
  const PLOT_BOTTOM = 104
  const PLOT_SPAN = 92
  const fmt = (value: number) =>
    metric === "Vertikální poměr"
      ? value.toFixed(1).replace(".", ",")
      : String(Math.round(value))
  const yFor = (value: number) =>
    PLOT_BOTTOM - ((value - min) / (max - min)) * PLOT_SPAN
  const points = trend
    .map((value, index) => `${14 + index * 35},${yFor(value)}`)
    .join(" ")
  const baselineValue =
    metric === "Kontakt se zemí" ? 242 : metric === "Kadence" ? 175 : 7.5
  const baselineY = yFor(baselineValue)
  const Wrapper = embedded ? "div" : Card
  const wrapperClass = embedded
    ? "border-t border-white/10 px-4 pb-4 pt-4"
    : "mt-4 overflow-hidden"
  return (
    <Wrapper className={wrapperClass}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <Label>Vývoj za 8 srovnatelných běhů</Label>
          <h2
            className={`mt-2 font-serif text-2xl ${
              embedded ? "text-[#f1f8f1]" : ""
            }`}
          >
            {metric}
          </h2>
        </div>
        <span className="rounded-full bg-[#e77a59]/15 px-3 py-1.5 text-[10px] font-bold text-[#ffc1ab]">
          dnes mimo střed
        </span>
      </div>
      <svg
        viewBox="-28 0 302 124"
        preserveAspectRatio="xMidYMid meet"
        className="mt-5 w-full aspect-[302/124] overflow-hidden"
        aria-label={`Vývoj metriky ${metric} za osm běhů`}
      >
        {/* Y axis */}
        <line x1="6" y1="8" x2="6" y2={PLOT_BOTTOM + 2} stroke="#6ce6d3" strokeOpacity=".3" />
        {[max, baselineValue, min].map((tickValue, tickIndex) => {
          const y = yFor(tickValue)
          return (
            <g key={tickIndex}>
              <line x1="3" y1={y} x2="6" y2={y} stroke="#6ce6d3" strokeOpacity=".35" />
              <text
                x="0"
                y={y + 2.5}
                textAnchor="end"
                fill="#91b7a9"
                fontSize="6.5"
              >
                {fmt(tickValue)}
              </text>
            </g>
          )
        })}
        <rect
          x="10"
          y={baselineY - 12}
          width="254"
          height="24"
          rx="5"
          fill="#6ce6d3"
          fillOpacity=".12"
        />
        <line
          x1="10"
          y1={baselineY}
          x2="264"
          y2={baselineY}
          stroke="#6ce6d3"
          strokeOpacity=".58"
          strokeDasharray="4 4"
        />
        <polyline
          points={points}
          fill="none"
          stroke="#f1f8f1"
          strokeOpacity=".9"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {trend.map((value, index) => {
          const y = yFor(value)
          const last = index === trend.length - 1
          return (
            <g key={index}>
              <text
                x={14 + index * 35}
                y={y - 6}
                textAnchor="middle"
                fill={last ? "#ffc1ab" : "#c5d9d1"}
                fontSize="6.5"
                fontWeight={last ? "bold" : "normal"}
              >
                {fmt(value)}
              </text>
              <circle
                cx={14 + index * 35}
                cy={y}
                r={last ? 4.5 : 3}
                fill={last ? "#e77a59" : "#f1f8f1"}
              />
              <text
                x={14 + index * 35}
                y={PLOT_BOTTOM + 14}
                textAnchor="middle"
                fill="#91b7a9"
                fontSize="7"
              >
                {index === 7 ? "Dnes" : `−${7 - index}`}
              </text>
            </g>
          )
        })}
      </svg>
      <div className="flex gap-5 text-[10px] text-[#9bb3aa]">
        <span>
          <i className="mr-2 inline-block size-2 rounded-full bg-[#e77a59]" />
          dnešní hodnota
        </span>
        <span>
          <i className="mr-2 inline-block h-px w-4 align-middle border-t border-dashed border-[#6ce6d3]" />
          váš obvyklý rozsah
        </span>
      </div>
    </Wrapper>
  )
}

const carePhysios = [
  {
    name: "Mgr. Jana Havlíčková",
    initials: "JH",
    clinic: "Fyzio Holešovice",
    focus: "běh, lýtko a Achillova šlacha",
    detail:
      "Pracuje s návratem k běhu po přetížení. Konzultace navazuje na vaše běžecká data.",
    next: "dnes 17:30",
  },
  {
    name: "Bc. Tomáš Vacek",
    initials: "TV",
    clinic: "RunLab Karlín",
    focus: "technika a návrat po zranění",
    detail: "Zaměřuje se na došlap, kadenci a postupné budování objemu.",
    next: "zítra 16:00",
  },
  {
    name: "Mgr. Lucie Malá",
    initials: "LM",
    clinic: "Pohyb 360",
    focus: "koleno, kyčel a stabilita",
    detail: "Vhodná volba, pokud chcete propojit běh s kompenzací a silou.",
    next: "čtvrtek 18:15",
  },
]

function PhysioPicker({
  current,
  close,
  reserve,
}: {
  current: string
  close: () => void
  reserve: (name: string) => void
}) {
  const pickerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      pickerRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      })
    }, 120)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <section
      data-auto-reveal
      ref={pickerRef}
      className="mt-3 origin-top animate-[careReveal_.28s_ease-out] overflow-hidden rounded-[24px] border border-[#6ce6d3]/30 bg-[#0c201d] p-4 text-[#f1f8f1] shadow-[0_18px_35px_rgb(0_0_0_/_0.2)] md:p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <Label>Výběr fyzioterapeuta</Label>
          <h2 className="mt-2 font-serif text-3xl">Kdo vám bude sedět?</h2>
          <p className="mt-2 max-w-lg text-sm leading-6 text-[#a9c2b9]">
            Vyberte odborníka podle zaměření. Změna se projeví až po potvrzení
            termínu.
          </p>
        </div>
        <button
          onClick={close}
          className="grid size-9 place-items-center rounded-full border border-white/15 text-lg"
        >
          ×
        </button>
      </div>
      <div className="mt-6 grid gap-3">
        {carePhysios.map((person) => (
          <article
            key={person.name}
            className={`rounded-2xl border p-4 ${
              person.name === current
                ? "border-[#6ce6d3]/50 bg-[#17382f]"
                : "border-white/10 bg-[#0c201d]"
            }`}
          >
            <div className="flex gap-3">
              <span className="grid size-11 shrink-0 place-items-center rounded-full bg-[#c7ff54] text-xs font-bold text-[#071313]">
                {person.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b>{person.name}</b>
                  {person.name === current && (
                    <span className="rounded-full bg-[#6ce6d3]/15 px-2 py-1 text-[9px] font-bold text-[#6ce6d3]">
                      současná péče
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-[#91b7a9]">
                  {person.clinic} {person.focus}
                </p>
                <p className="mt-3 text-xs leading-5 text-[#a9c2b9]">
                  {person.detail}
                </p>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <span className="text-[10px] text-[#c7ff54]">
                    Nejbližší volno: {person.next}
                  </span>
                  <button
                    onClick={() => reserve(person.name)}
                    className="rounded-full bg-[#c7ff54] px-3 py-2 text-[10px] font-bold text-[#071313]"
                  >
                    Změnit a rezervovat
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

function RunnerDetails() {
  const { tab } = useParams()
  const [book, setBook] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [physioName, setPhysioName] = useState(carePhysios[0].name)
  const [message, setMessage] = useState("")
  const [activeMetric, setActiveMetric] = useState("Vertikální poměr")
  const titles: Record<string, string> = {
    post: "Hodnocení po tréninku",
    mechanics: "Jak se mění váš běh",
    load: "Kolik toho unesete a jak se z toho dostáváte",
    program: "Návrat do rytmu",
    messages: "Zprávy a péče",
  }
  const t = tab || ""
  const physio =
    carePhysios.find((person) => person.name === physioName) || carePhysios[0]
  const mechanicsMetrics: {
    label: string
    value: string
    baseline: string
    delta: string
    position: number
    weeks: number[]
  }[] = [
    {
      label: "Vertikální poměr",
      value: "7,8 %",
      baseline: "7,5 %",
      delta: "+0,3 p. b.",
      position: 75,
      weeks: [7.2, 7.3, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8],
    },
    {
      label: "Kontakt se zemí",
      value: "248 ms",
      baseline: "242 ms",
      delta: "+6 ms",
      position: 72,
      weeks: [240, 242, 241, 243, 245, 245, 247, 248],
    },
    {
      label: "Kadence",
      value: "174 spm",
      baseline: "175 spm",
      delta: "stabilní",
      position: 48,
      weeks: [176, 175, 175, 175, 174, 174, 174, 174],
    },
  ]
  if (t === "mechanics")
    return (
      <>
        <Label>Mechanika</Label>
        <h1 className="mt-1 font-serif text-4xl">{titles[t]}</h1>
        <p className="mt-3 text-sm text-[#64736e]">
          Vždy proti vašim běhům ve srovnatelném tempu a terénu.
        </p>
        <section className="mt-6 overflow-hidden rounded-[28px] border border-[#6ce6d3]/20 bg-[#102724] p-5 md:p-7">
          <div className="grid gap-7 lg:grid-cols-[.82fr_1.18fr] lg:items-center">
            <div>
              <Label>Signál pohybu</Label>
              <h2 className="mt-2 font-serif text-3xl leading-tight text-[#f1f8f1]">
                Jemný drift na rovině
              </h2>
              <p className="mt-3 max-w-sm text-sm leading-6 text-[#a9c2b9]">
                Při stejném tempu se krok mírně prodlužuje a kontakt se zemí
                narůstá. Není to alarm, ale dobrý okamžik ubrat tlak.
              </p>
              <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#e77a59]/12 px-3 py-2 text-[10px] font-bold text-[#ffc1ab]">
                <i className="size-2 rounded-full bg-[#e77a59]" />
                vyšší než váš obvyklý střed
              </div>
            </div>
            <div className="relative w-full">
              <MuscleAnatomy />
            </div>
          </div>
        </section>
        <div className="mt-4 space-y-4">
          {mechanicsMetrics.map((m) => {
            const isOpen = activeMetric === m.label
            return (
              <div
                key={m.label}
                data-auto-reveal={isOpen ? "" : undefined}
                className={`overflow-hidden rounded-[22px] border transition ${
                  isOpen
                    ? "border-[#6ce6d3]/60 bg-[#17382f] shadow-[0_0_0_1px_rgb(108_230_211_/_0.12)]"
                    : "border-white/10 bg-[#0c201d] hover:border-[#6ce6d3]/30"
                }`}
              >
                <MechanicsMetric
                  label={m.label}
                  value={m.value}
                  baseline={m.baseline}
                  delta={m.delta}
                  position={m.position}
                  weeks={m.weeks}
                  active={isOpen}
                  onSelect={() =>
                    setActiveMetric(isOpen ? "" : m.label)
                  }
                />
                {isOpen && (
                  <div className="origin-top animate-[careReveal_.28s_ease-out]">
                    <MechanicsTrend metric={m.label} embedded />
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <TerrainProfiles />
        <RunHistory />
      </>
    )
  if (t === "load")
    return (
      <>
        <Label>Zátěž</Label>
        <h1 className="mt-1 font-serif text-4xl">{titles[t]}</h1>
        <div className="mt-6 grid gap-4 md:grid-cols-4">
          <SevenDayVolume />
          <TwentyEightDayVolume />
          <BaselineBoxplot />
          <TrainingBalance />
        </div>
        <Card className="mt-4">
          <Label>Regenerace 14 dní</Label>
          <p className="mt-2 text-xs leading-5 text-[#71837b]">
            Dnešní hodnoty jsou zasazené do vašeho vlastního 14denního rozsahu.
          </p>
          <LoadRecoveryRanges />
        </Card>
      </>
    )
  if (t === "program")
    return (
      <>
        <Label>Program od fyzioterapeutky</Label>
        <h1 className="mt-1 font-serif text-4xl">{titles[t]}</h1>
        <p className="mt-3 text-sm text-[#64736e]">
          Vede Mgr. Jana Havlíčková 63 % splněno tento týden.
        </p>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {[
            ["Výpon na jedné noze", "3 × 12   3× týdně", "24 / 36 opakování"],
            ["Dřep s oporou", "3 × 8   2× týdně", "16 / 16 opakování"],
            ["Boční prkno", "3 × 30 s   3× týdně", "2 / 3 série"],
            ["Mobilita kotníku", "5 min   denně", "4 / 7 dní"],
          ].map((x) => (
            <Card key={x[0]}>
              <div className="flex justify-between">
                <div>
                  <Label>Cvik</Label>
                  <h2 className="mt-1 font-serif text-xl">{x[0]}</h2>
                </div>
                <span className="grid size-7 place-items-center rounded-full border border-[#a9bdb6] text-[#235e59]">
                  ✓
                </span>
              </div>
              <p className="mt-3 text-sm">{x[1]}</p>
              <p className="mt-1 text-xs text-[#71837b]">{x[2]}</p>
            </Card>
          ))}
        </div>
        <Card className="mt-4">
          <Label>Změna v programu</Label>
          <p className="mt-2 text-sm leading-6 text-[#64736e]">
            12. srpna snížena dávka výponů z 4×12 na 3×12 po hlášení ztuhlosti
            lýtka.
          </p>
        </Card>
      </>
    )
  if (t === "messages")
    return (
      <>
        <Label>Péče a komunikace</Label>
        <h1 className="mt-1 font-serif text-4xl">{titles[t]}</h1>
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
          <Card>
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-full bg-[#dcece7] font-bold text-[#235e59]">
                {physio.initials}
              </span>
              <div>
                <b>{physio.name}</b>
                <p className="text-xs text-[#71837b]">
                  Fyzioterapeutka {physio.clinic}
                </p>
              </div>
            </div>
            <div className="mt-5 space-y-3 text-sm">
              <p className="max-w-[80%] rounded-2xl rounded-tl-sm bg-[#edf0e9] p-3">
                Jak se vám šly výpony po posledním běhu?
              </p>
              <p className="ml-auto max-w-[80%] rounded-2xl rounded-tr-sm bg-[#dcece7] p-3 text-black">
                Lýtko je druhý den ráno trochu tužší, ale bez bolesti.
              </p>
            </div>
            <div className="mt-5 flex gap-2">
              <input
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                className="min-w-0 flex-1 rounded-full border border-[#d9dfda] px-4 text-sm"
                placeholder={`Napsat ${physio.name.split(" ")[1]}…`}
              />
              <button
                onClick={() => setMessage("")}
                className="rounded-full bg-[#235e59] px-4 text-xs font-bold text-white"
              >
                Odeslat
              </button>
            </div>
          </Card>
          <Card>
            <Label>Fyzioterapie</Label>
            <h2 className="mt-1 font-serif text-2xl">Péče podle vás</h2>
            <div className="mt-4 flex items-center gap-3 rounded-2xl bg-[#17382f] p-3">
              <span className="grid size-9 place-items-center rounded-full bg-[#c7ff54] text-[10px] font-bold text-[#071313]">
                {physio.initials}
              </span>
              <div>
                <b className="block text-sm">{physio.name}</b>
                <span className="text-[10px] text-[#9bb3aa]">
                  {physio.focus}
                </span>
              </div>
            </div>
            <p className="mt-4 text-xs leading-5 text-[#71837b]">
              Příští rezervace: čtvrtek 20. srpna 17:30. Změnu odborníka
              potvrdíte až výběrem nového termínu.
            </p>
            <button
              onClick={() => setPickerOpen(true)}
              className="mt-5 w-full rounded-full border border-[#6ce6d3]/35 bg-[#17382f] py-2.5 text-xs font-bold text-white"
            >
              Změnit fyzioterapeuta
            </button>
            <button
              onClick={() => setBook(true)}
              className="mt-2 w-full rounded-full bg-[#e6f0ec] py-2.5 text-xs font-bold text-black"
            >
              Vybrat další termín
            </button>
            {pickerOpen && (
              <PhysioPicker
                current={physioName}
                close={() => setPickerOpen(false)}
                reserve={(name) => {
                  setPhysioName(name)
                  setPickerOpen(false)
                  setBook(true)
                }}
              />
            )}
          </Card>
        </div>
        {book && <Booking therapist={physio} close={() => setBook(false)} />}
      </>
    )
  return (
    <>
      <Label>Po tréninku</Label>
      <h1 className="mt-1 font-serif text-4xl">{titles[t]}</h1>
      <Card className="mt-6">
        <Label>Včerejší běh 8,2 km</Label>
        <h2 className="mt-1 font-serif text-2xl">Jak se tělo cítilo?</h2>
        <div className="mt-5 grid grid-cols-5 gap-2">
          {["žádná bolest", "mírná", "střední", "vyšší", "stop"].map((x, i) => (
            <button
              key={x}
              className="rounded-xl border border-[#dfe2da] p-3 text-[10px] hover:border-[#e47d51]"
            >
              {i}/4
              <br />
              <span className="text-[#71837b]">{x}</span>
            </button>
          ))}
        </div>
        <textarea
          className="mt-5 min-h-24 w-full rounded-xl border border-[#dfe2da] p-3 text-sm"
          placeholder="Poznámka k běhu (nepovinné)"
        />
        <button className="mt-4 rounded-full bg-[#235e59] px-5 py-3 text-sm font-bold text-white">
          Uložit hodnocení
        </button>
      </Card>
    </>
  )
}
function Booking({
  close,
  therapist,
}: {
  close: () => void
  therapist: typeof carePhysios[number]
}) {
  const [day, setDay] = useState("Út 18")
  const [slot, setSlot] = useState<string | null>(null)
  const days = ["Po 17", "Út 18", "St 19", "Čt 20", "Pá 21"]
  const availability = {
    "Po 17": ["09:00", "10:00", "11:00", "13:30", "14:30"],
    "Út 18": ["09:00", "10:00", "11:00", "13:30", "14:30"],
    "St 19": ["09:00", "10:00", "11:00", "13:30", "14:30"],
    "Čt 20": ["09:00", "10:00", "11:00", "13:30", "14:30"],
    "Pá 21": ["09:00", "10:00", "11:00", "13:30", "14:30"],
  } as Record<string, string[]>
  const booked =
    day === "Út 18"
      ? ["09:00", "11:00", "13:30"]
      : day === "Čt 20"
        ? ["10:00", "14:30"]
        : ["10:00", "13:30"]
  return (
    <div
      data-auto-reveal
      className="fixed inset-0 z-[80] grid place-items-end bg-[#071313]/75 p-3 backdrop-blur-sm md:place-items-center"
    >
      <div className="w-full max-w-2xl rounded-[30px] border border-white/10 bg-[#102724] p-5 text-[#f1f8f1] shadow-2xl md:p-7">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Label>Rezervace péče</Label>
            <h2 className="mt-2 font-serif text-3xl">
              Vyberte čas s {therapist.name.split(" ").slice(1).join(" ")}
            </h2>
            <p className="mt-2 text-xs text-[#9bb3aa]">
              45 minut {therapist.clinic}
            </p>
          </div>
          <button
            onClick={close}
            className="grid size-9 place-items-center rounded-full border border-white/15"
          >
            ×
          </button>
        </div>
        <div className="mt-6 grid grid-cols-5 gap-1.5">
          {days.map((d) => (
            <button
              key={d}
              onClick={() => setDay(d)}
              className={`rounded-xl px-1 py-2 text-[10px] font-bold ${
                day === d
                  ? "bg-[#c7ff54] text-[#071313]"
                  : "bg-[#071313] text-[#9bb3aa]"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
        <div className="mt-6 rounded-2xl border border-white/10 bg-[#071313] p-4">
          <div className="flex items-center justify-between">
            <b className="text-sm">{day}. srpna</b>
            <span className="text-[10px] text-[#9bb3aa]">časová osa dne</span>
          </div>
          <div className="mt-4 grid grid-cols-[42px_1fr] gap-x-3 text-xs">
            {availability[day].map((time, index) => {
              const isBooked = booked.includes(time)
              return (
                <Fragment key={`slot-${time}`}>
                  <span
                    key={`${time}-label`}
                    className="pt-2 text-right font-mono text-[10px] text-[#71837b]"
                  >
                    {time}
                  </span>
                  <button
                    key={time}
                    disabled={isBooked}
                    onClick={() => setSlot(time)}
                    className={`relative min-h-10 rounded-lg border px-3 text-left text-[11px] transition ${
                      isBooked
                        ? "cursor-not-allowed border-white/5 bg-white/[.035] text-[#64736e]"
                        : slot === time
                          ? "border-[#c7ff54] bg-[#c7ff54]/15 text-[#f1f8f1]"
                          : "border-[#6ce6d3]/25 bg-[#102724] text-[#d9ebe4] hover:border-[#6ce6d3]"
                    }`}
                  >
                    <span className="font-semibold">
                      {isBooked ? "obsazeno" : "volný termín"}
                    </span>
                    {!isBooked && (
                      <i className="absolute right-3 top-1/2 size-2 -translate-y-1/2 rounded-full bg-[#6ce6d3]" />
                    )}
                  </button>
                </Fragment>
              )
            })}
          </div>
          <div className="mt-4 flex gap-4 text-[10px] text-[#9bb3aa]">
            <span>
              <i className="mr-2 inline-block size-2 rounded-sm bg-[#102724] ring-1 ring-[#6ce6d3]/40" />
              volno
            </span>
            <span>
              <i className="mr-2 inline-block size-2 rounded-sm bg-white/10" />
              obsazeno
            </span>
            <span>
              <i className="mr-2 inline-block size-2 rounded-full bg-[#c7ff54]" />
              vybraný termín
            </span>
          </div>
        </div>
        <button
          disabled={!slot}
          onClick={close}
          className="mt-5 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-35"
        >
          {slot ? `Potvrdit ${day} v ${slot}` : "Vyberte volný termín"}
        </button>
      </div>
    </div>
  )
}
function RunnerPage() {
  const { tab } = useParams()
  return tab === "today" ? <TodayV2 /> : <RunnerDetails />
}
function DataPage() {
  const [source, setSource] = useState("Garmin")
  return (
    <>
      <Label>Data a připojení</Label>
      <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
        Zatím nepřipojeno.
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-[#64736e]">
        Připojte hodinky a sledujte zátěž, regeneraci i mechaniku ve vlastním
        kontextu.
      </p>
      <div className="mt-7 grid gap-4 md:grid-cols-3">
        <Metric
          label="Aktivit v účtu"
          value="0"
          caption="zatím bez importu"
          warm
        />
        <Metric label="Stav" value=" " caption="čeká na připojení" />
        <Metric label="Profil" value="Adéla" caption="běžec / pacient" />
      </div>
      <Card className="mt-4">
        <div className="flex gap-2">
          <button
            onClick={() => setSource("Garmin")}
            className={`rounded-full px-4 py-2 text-xs font-bold ${
              source === "Garmin" ? "bg-[#235e59] text-white" : "bg-[#edf0e9]"
            }`}
          >
            Garmin Connect
          </button>
          <button
            onClick={() => setSource("Apple")}
            className={`rounded-full px-4 py-2 text-xs font-bold ${
              source === "Apple" ? "bg-[#235e59] text-white" : "bg-[#edf0e9]"
            }`}
          >
            Apple Health
          </button>
        </div>
        <div className="mt-7 grid gap-8 md:grid-cols-[1.4fr_.8fr]">
          <div>
            <h2 className="font-serif text-2xl tracking-[-.04em]">
              Nahrát export z {source}
            </h2>
            <p className="mt-2 text-sm leading-6 text-[#64736e]">
              Nahrajte export ve formátu ZIP, XML nebo JSON. Data se zpracují a
              uloží pouze k vašemu účtu.
            </p>
            <button className="mt-5 w-full rounded-2xl border-2 border-dashed border-[#9cbcb5] bg-[#f2f8f5] p-9 text-sm font-bold text-[#235e59]">
              ↑ Vybrat soubor k nahrání
              <span className="mt-1 block text-xs font-normal text-[#69817a]">
                ZIP, XML nebo JSON
              </span>
            </button>
          </div>
          <div className="rounded-2xl bg-[#edf0e9] p-5">
            <Label>Co se odemkne</Label>
            <ul className="mt-4 space-y-3 text-sm leading-5 text-[#64736e]">
              <li>
                <b className="text-[#193431]">Běhy</b> zátěž, tempo a trasa
              </li>
              <li>
                <b className="text-[#193431]">Regenerace</b> HRV, tep a spánek
              </li>
              <li>
                <b className="text-[#193431]">Mechanika</b> pokud ji zařízení
                měří
              </li>
            </ul>
          </div>
        </div>
      </Card>
    </>
  )
}
function RolePage() {
  const { role = "physio" } = useParams()
  const title =
    role === "physio"
      ? "Fronta triáže"
      : role === "employer"
        ? "Firemní kohorta"
        : "Partnerský přehled"
  const cards =
    role === "physio"
      ? [
          ["Adéla Kučerová", "Tichý drift   vysoká spolehlivost"],
          ["Petra Bláhová", "Zátěž nad osobním pásmem"],
        ]
      : role === "employer"
        ? [
            ["Ochrana soukromí", "V kohortě je 6 zapojených lidí"],
            ["Další krok", "Pro zobrazení agregátů je potřeba 8 lidí"],
          ]
        : [
            ["Aktivní doporučení", "12 návštěvníků za posledních 30 dní"],
            ["Konverze", "4 založené účty"],
          ]
  return (
    <>
      <Label>{roles.find((x) => x[0] === role)?.[1] || "Přehled"}</Label>
      <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">{title}</h1>
      <p className="mt-3 text-sm text-[#64736e]">
        {role === "physio"
          ? "Případy čekající na odborné posouzení."
          : "Citlivé údaje jsou chráněné a agregované."}
      </p>
      <div className="mt-7 grid gap-4 md:grid-cols-2">
        {cards.map(([a, b]) => (
          <Card key={a}>
            <Label>{role === "physio" ? "Čeká na vás" : "Přehled"}</Label>
            <h2 className="mt-2 font-serif text-2xl">{a}</h2>
            <p className="mt-2 text-sm text-[#64736e]">{b}</p>
            <button className="mt-5 text-xs font-bold text-[#235e59] underline underline-offset-4">
              Otevřít →
            </button>
          </Card>
        ))}
      </div>
    </>
  )
}
function Home() {
  return (
    <div className="-mx-5 -mt-24 min-h-screen bg-[#f9f7f1] text-[#193431]">
      <section className="bg-[#235e59] px-5 pb-24 pt-6 text-[#f8f7f1] md:px-10">
        <div className="mx-auto max-w-[1180px]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold">
              <Mark />
              došlap
            </div>
            <Link
              to="/auth"
              className="rounded-full border border-white/25 px-4 py-2 text-sm font-bold"
            >
              Přihlásit se
            </Link>
          </div>
          <div className="mt-20 max-w-2xl">
            <Label>Běžet dál, rozumět dřív</Label>
            <h1 className="mt-4 font-serif text-5xl leading-[.95] tracking-[-.06em] md:text-6xl">
              Změny ve vaší zátěži a mechanice vidíte včas.
            </h1>
            <p className="mt-5 text-base leading-7 text-[#cbe1db]">
              Data z hodinek a pohybová mechanika ve vztahu k vašemu vlastnímu
              normálu. Ne diagnóza kontext pro vás a vašeho odborníka.
            </p>
          </div>
        </div>
      </section>
      <section className="relative mx-auto -mt-12 max-w-[1180px] px-5 pb-16 md:px-10">
        <div className="grid gap-3 md:grid-cols-4">
          {roles.map(([id, name, desc]) => (
            <Link
              key={id}
              to={`/auth?role=${id}`}
              className="rounded-[22px] border border-[#dfe2da] bg-white p-5 shadow-sm transition hover:-translate-y-1"
            >
              <span className="grid size-9 place-items-center rounded-xl bg-[#dcece7] text-[#235e59]">
                {id === "runner" ? "⌁" : "◌"}
              </span>
              <Label>{name}</Label>
              <h2 className="mt-1 font-serif text-2xl">{name}</h2>
              <p className="mt-2 min-h-12 text-xs leading-5 text-[#64736e]">
                {desc}
              </p>
              <span className="mt-4 block text-xs font-bold text-[#235e59]">
                Přihlásit se →
              </span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
function Auth() {
  const nav = useNavigate()
  const [role, setRole] = useState("runner")
  return (
    <div className="motion-shell min-h-screen bg-[#e7e9e1] p-5 md:grid md:grid-cols-2 md:gap-8 md:p-8">
      <aside className="hidden rounded-[30px] bg-[#235e59] p-10 text-white md:flex md:flex-col">
        <div className="flex items-center gap-2 font-bold">
          <Mark />
          došlap
        </div>
        <div className="my-auto">
          <Label>Bezpečný přístup</Label>
          <h1 className="mt-4 max-w-md font-serif text-5xl leading-[.95]">
            Zranění se ohlásí v datech dřív než v noze.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-6 text-[#cbe1db]">
            Čtyři různé dveře pro čtyři role. Každý vidí jen ta data, ke kterým
            má oprávněný přístup.
          </p>
        </div>
      </aside>
      <section className="mx-auto flex w-full max-w-md flex-col justify-center py-8">
        <Link
          to="/"
          className="mb-10 flex items-center gap-2 font-bold md:hidden"
        >
          <Mark />
          došlap
        </Link>
        <Label>Přístup do platformy</Label>
        <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
          Kdo se přihlašuje?
        </h1>
        <div className="mt-6 grid grid-cols-2 gap-3">
          {roles.map(([id, name]) => (
            <button
              onClick={() => setRole(id)}
              key={id}
              className={`rounded-2xl border p-4 text-left ${
                role === id
                  ? "border-[#235e59] bg-[#eff7f4]"
                  : "border-[#dfe2da] bg-white"
              }`}
            >
              <span className="text-[#235e59]">◌</span>
              <b className="mt-2 block text-sm">{name}</b>
            </button>
          ))}
        </div>
        <Card className="mt-5">
          <p className="font-serif text-xl">
            Přihlásit se {roles.find((x) => x[0] === role)?.[1]}
          </p>
          <input
            className="mt-5 w-full rounded-xl border border-[#d9dfda] px-3 py-3 text-sm"
            placeholder="E-mail"
            defaultValue={role === "runner" ? "adela@demo.cz" : ""}
          />
          <input
            type="password"
            className="mt-3 w-full rounded-xl border border-[#d9dfda] px-3 py-3 text-sm"
            defaultValue="demo1234"
          />
          <button
            onClick={() =>
              nav(role === "runner" ? "/app/today" : `/role/${role}`)
            }
            className="mt-5 w-full rounded-full bg-[#235e59] py-3 text-sm font-bold text-white"
          >
            Přihlásit se
          </button>
        </Card>
      </section>
    </div>
  )
}
function MotionAtlas() {
  const [active, setActive] = useState("Dnes")
  return (
    <div className="min-h-screen overflow-hidden bg-[#071313] text-[#f1f8f1]">
      <header className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 md:px-10">
        <Link
          to="/"
          className="flex items-center gap-2 font-semibold tracking-tight"
        >
          <span className="grid size-8 place-items-center rounded-lg bg-[#c7ff54] font-serif text-lg text-[#071313]">
            d
          </span>
          došlap
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden font-mono text-[10px] uppercase tracking-[.18em] text-[#83a298] md:block">
            Živé signály
          </span>
          <button className="grid size-9 place-items-center rounded-full border border-white/15 text-[#c7ff54]">
            ◦
          </button>
          <span className="grid size-9 place-items-center rounded-full bg-[#17352f] text-[10px] font-bold">
            AK
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 pb-28 md:px-10">
        <div className="flex gap-5 overflow-x-auto border-b border-white/10 pb-4 text-xs font-bold text-[#7f9e95]">
          {["Dnes", "Zátěž", "Pohyb", "Péče"].map((x) => (
            <button
              onClick={() => setActive(x)}
              key={x}
              className={`shrink-0 ${active === x ? "text-[#c7ff54]" : ""}`}
            >
              {x}
            </button>
          ))}
        </div>
        <div className="mt-8 grid gap-5 lg:grid-cols-[1.05fr_.95fr]">
          <section className="relative min-h-[420px] overflow-hidden rounded-[32px] border border-white/10 bg-[#0c201d] p-6 md:p-9">
            <div className="atlas-orbit absolute -right-28 -top-28 size-[420px] rounded-full border border-[#c7ff54]/20" />
            <div className="atlas-orbit absolute -right-14 -top-14 size-[300px] rounded-full border border-[#6ce6d3]/25" />
            <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
              Úterý 18. srpna 07:42
            </p>
            <h1 className="relative mt-5 max-w-md text-4xl font-semibold leading-[.96] tracking-[-.06em] md:text-6xl">
              Tělo je v pohybu.
              <br />
              <em className="font-serif font-normal text-[#c7ff54]">
                Dnes s rezervou.
              </em>
            </h1>
            <p className="relative mt-5 max-w-sm text-sm leading-6 text-[#aac3b9]">
              Obnova drží krok se zátěží. Lehký běh do 45 minut je dobrá volba.
            </p>
            <div className="relative mt-10 flex items-center gap-5">
              <div className="grid size-16 place-items-center rounded-full bg-[#c7ff54] text-xl text-[#071313]">
                ↗
              </div>
              <div>
                <b className="block text-sm">78 / 100</b>
                <span className="text-xs text-[#9bb3aa]">
                  připravenost roste
                </span>
              </div>
            </div>
            <div className="absolute bottom-6 left-6 flex gap-2">
              <span className="rounded-full border border-[#c7ff54]/25 bg-[#c7ff54]/10 px-3 py-1.5 text-[10px] font-bold text-[#c7ff54]">
                lehká intenzita
              </span>
              <span className="rounded-full border border-white/10 px-3 py-1.5 text-[10px] text-[#b7cdc5]">
                do 45 min
              </span>
            </div>
          </section>
          <section className="relative rounded-[32px] border border-white/10 bg-[#102724] p-6 md:p-8">
            <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
              Mapa pohybu
            </p>
            <h2 className="mt-2 text-2xl tracking-[-.04em]">
              Jemná změna rytmu
            </h2>
            <div className="relative mx-auto mt-3 h-64 max-w-sm">
              <div className="atlas-pulse absolute left-1/2 top-1/2 size-44 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#e77a59]/30" />
              <div className="atlas-pulse absolute left-1/2 top-1/2 size-32 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#e77a59]/40" />
              <svg
                className="absolute inset-0 h-full w-full"
                viewBox="0 0 160 220"
                fill="none"
                aria-label="Běžecká mechanika"
              >
                <circle
                  cx="80"
                  cy="28"
                  r="15"
                  stroke="#bdebdc"
                  strokeWidth="2"
                />
                <path
                  d="M80 44 L77 103 L55 142 M77 103 L103 139 M69 66 L45 96 M84 67 L113 91 M55 142 L43 193 M103 139 L119 191"
                  stroke="#bdebdc"
                  strokeWidth="4"
                  strokeLinecap="round"
                />
                <circle cx="102" cy="139" r="9" fill="#e77a59" />
                <circle
                  cx="103"
                  cy="139"
                  r="17"
                  stroke="#e77a59"
                  strokeOpacity=".45"
                />
              </svg>
              <span className="absolute right-0 top-[55%] rounded-full bg-[#e77a59] px-3 py-1 text-[10px] font-bold text-[#151515]">
                +3,2 % vert. poměr
              </span>
            </div>
            <div className="grid grid-cols-3 border-t border-white/10 pt-4 text-center">
              <p>
                <b className="block text-lg text-[#c7ff54]">7,8%</b>
                <span className="text-[10px] text-[#8ba59d]">vert. poměr</span>
              </p>
              <p>
                <b className="block text-lg">248 ms</b>
                <span className="text-[10px] text-[#8ba59d]">kontakt</span>
              </p>
              <p>
                <b className="block text-lg">174</b>
                <span className="text-[10px] text-[#8ba59d]">kadence</span>
              </p>
            </div>
          </section>
        </div>
        <div className="mt-5 grid gap-5 md:grid-cols-[1.1fr_.9fr]">
          <section className="rounded-[28px] border border-white/10 bg-[#0c201d] p-6">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
                  Zátěž 12 týdnů
                </p>
                <h2 className="mt-2 text-xl">V obvyklém pásmu</h2>
              </div>
              <span className="rounded-full bg-[#e77a59]/15 px-3 py-1 text-[10px] font-bold text-[#ffc1ab]">
                4,2 km nad doporučeným +5 %
              </span>
            </div>
            <div className="mt-9 flex h-24 items-end gap-1">
              {[24, 32, 40, 35, 48, 44, 58, 49, 62, 55, 70, 65, 76, 70].map(
                (h, i) => (
                  <i
                    key={i}
                    style={{ height: `${h}%` }}
                    className={`flex-1 rounded-sm ${
                      i > 10 ? "bg-[#c7ff54]" : "bg-[#28564d]"
                    }`}
                  />
                ),
              )}
            </div>
            <div className="mt-4 flex justify-between text-xs text-[#9bb3aa]">
              <span>Akutní 34,8 km</span>
              <span>Chronická 29,1 km</span>
              <span>TSB −8</span>
            </div>
          </section>
          <section className="rounded-[28px] bg-[#c7ff54] p-6 text-[#071313]">
            <p className="font-mono text-[10px] uppercase tracking-[.15em] text-[#35602a]">
              Mechanika
            </p>
            <h2 className="mt-2 max-w-sm text-2xl leading-tight tracking-[-.04em]">
              Jemný drift, který stojí za pozornost.
            </h2>
            <div className="mt-6 flex items-center justify-between border-t border-[#071313]/15 pt-4">
              <div>
                <b className="text-sm">Jana H. fyzio</b>
                <p className="mt-1 text-xs text-[#31562b]">
                  Čtvrtek 17:30 Fyzio Holešovice
                </p>
              </div>
              <Link
                to="/app/messages"
                className="rounded-full bg-[#071313] px-3 py-2 text-xs font-bold text-[#c7ff54]"
              >
                Otevřít péči →
              </Link>
            </div>
          </section>
        </div>
      </main>
      <nav className="fixed inset-x-0 bottom-0 flex border-t border-white/10 bg-[#071313]/95 px-4 pb-[max(.8rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:hidden">
        {[
          ["⌂", "Dnes"],
          ["⌁", "Zátěž"],
          ["◌", "Pohyb"],
          ["◔", "Péče"],
        ].map(([i, t]) => (
          <button
            key={t}
            onClick={() => setActive(t)}
            className={`flex flex-1 flex-col items-center gap-1 text-[10px] ${
              active === t ? "text-[#c7ff54]" : "text-[#80968e]"
            }`}
          >
            <span className="text-lg">{i}</span>
            {t}
          </button>
        ))}
      </nav>
    </div>
  )
}
function ProfilePage() {
  return (
    <>
      <Label>Váš profil</Label>
      <h1 className="mt-1 font-serif text-4xl">Adéla Kučerová</h1>
      <Card className="mt-6 max-w-xl">
        <Label>Nastavení běžce</Label>
        <p className="mt-3 text-sm text-[#64736e]">
          Garmin cíl: Birell 10K Praha 15. září
        </p>
        <button className="mt-5 rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313]">
          Upravit profil
        </button>
      </Card>
    </>
  )
}
function MotionAtlas2() {
  const [notice, setNotice] = useState(false)
  const [pain, setPain] = useState(false)
  const nav = [
    ["/app/today", "⌂", "Dnes"],
    ["/app/load", "⌁", "Zátěž"],
    ["/app/mechanics", "◌", "Pohyb"],
    ["/app/messages", "◔", "Péče"],
  ]
  return (
    <div className="min-h-screen overflow-hidden bg-[#071313] text-[#f1f8f1]">
      <header className="fixed inset-x-0 top-0 z-40 border-b border-white/10 bg-[#071313]/92 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 md:px-10">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <span className="grid size-8 place-items-center rounded-lg bg-[#c7ff54] font-serif text-lg text-[#071313]">
              d
            </span>
            došlap
          </Link>
          <div className="relative flex items-center gap-3">
            <button
              onClick={() => setNotice(!notice)}
              className="grid size-9 place-items-center rounded-full border border-white/15 text-[#c7ff54]"
              aria-label="Otevřít upozornění"
            >
              ◦
            </button>
            <Link
              to="/profile"
              className="grid size-9 place-items-center rounded-full bg-[#17352f] text-[10px] font-bold"
              aria-label="Otevřít profil"
            >
              AK
            </Link>
            {notice && (
              <div
                data-auto-reveal
                className="absolute right-11 top-11 w-72 rounded-2xl border border-white/10 bg-[#102724] p-4 text-xs shadow-2xl"
              >
                <b className="text-[#c7ff54]">1 nové upozornění</b>
                <p className="mt-2 leading-5 text-[#adc7bc]">
                  Mechanika na rovině se drží nad vaším vlastním rozsahem už 3
                  běhy.
                </p>
                <Link
                  to="/app/mechanics"
                  className="mt-3 block font-bold text-[#c7ff54]"
                >
                  Prohlédnout pohyb →
                </Link>
              </div>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 pb-28 pt-8 md:px-10">
        <div className="grid gap-5 lg:grid-cols-[1.05fr_.95fr]">
          <section className="relative min-h-[410px] overflow-hidden rounded-[32px] border border-white/10 bg-[#0c201d] p-6 md:p-9">
            <i className="atlas-orbit absolute -right-28 -top-28 size-[420px] rounded-full border border-[#c7ff54]/20" />
            <i className="atlas-orbit absolute -right-14 -top-14 size-[300px] rounded-full border border-[#6ce6d3]/25" />
            <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
              Úterý 18. srpna 07:42
            </p>
            <h1 className="relative mt-5 text-4xl font-semibold leading-[.96] tracking-[-.06em] md:text-6xl">
              Tělo je v pohybu.
              <br />
              <em className="font-serif font-normal text-[#c7ff54]">
                Dnes s rezervou.
              </em>
            </h1>
            <div className="relative mt-10 max-w-sm">
              <div className="flex items-end justify-between">
                <div>
                  <span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
                    Energie pro dnešek
                  </span>
                  <b className="mt-1 block text-2xl text-[#f1f8f1]">
                    78{" "}
                    <small className="text-sm font-normal text-[#9bb3aa]">
                      / 100
                    </small>
                  </b>
                </div>
              </div>
              <div className="relative mt-3 h-7 rounded-md border border-[#c7ff54]/35 bg-[#071313] p-1">
                <i className="absolute inset-y-1 left-1 w-[72%] rounded-sm bg-[#c7ff54]/45" />
                <i className="absolute inset-y-1 left-[72%] w-[6%] rounded-r-sm border-l border-[#071313] bg-[#c7ff54] shadow-[0_0_18px_rgb(199_255_84_/_0.45)]" />
                <span className="absolute left-[75%] top-[-1.45rem] -translate-x-1/2 text-sm text-[#c7ff54]">
                  ☾
                </span>
                <i className="absolute inset-y-1 left-1/4 w-px bg-[#071313]/50" />
                <i className="absolute inset-y-1 left-1/2 w-px bg-[#071313]/50" />
                <i className="absolute inset-y-1 left-3/4 w-px bg-[#071313]/50" />
                <i className="absolute -right-1.5 top-1/2 h-3 w-1.5 -translate-y-1/2 rounded-r-sm bg-[#c7ff54]/50" />
              </div>
              <div className="mt-2 flex justify-between text-[9px] text-[#71837b]">
                <span>nízká</span>
                <span>vyvážená</span>
                <span>plná</span>
              </div>
              <div className="mt-5 grid gap-2 border-t border-white/10 pt-4 text-xs">
                <div className="flex items-center gap-3">
                  <span className="grid size-6 place-items-center rounded-full bg-[#6ce6d3]/15 text-[#6ce6d3]">
                    ☾
                  </span>
                  <span className="text-[#d9ebe4]">
                    <b>Spánek dobil rezervu</b>
                    <small className="ml-2 text-[#91b7a9]">
                      +6 bodů přes noc
                    </small>
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="grid size-6 place-items-center rounded-full bg-[#c7ff54]/15 text-[#c7ff54]">
                    ↗
                  </span>
                  <span className="text-[#d9ebe4]">
                    <b>Lehký běh je vhodný</b>
                    <small className="ml-2 text-[#91b7a9]">do 45 minut</small>
                  </span>
                </div>
              </div>
            </div>
          </section>
          <section className="relative rounded-[32px] border border-white/10 bg-[#102724] p-6 md:p-8">
            <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
              Připravenost
            </p>
            <h2 className="mt-2 text-2xl">Tělo drží dobrý rytmus</h2>
            <div
              onMouseEnter={() => setPain(true)}
              onMouseLeave={() => setPain(false)}
              onClick={() => setPain(!pain)}
              className="relative mx-auto mt-3 h-44 max-w-sm cursor-help"
            >
              <i className="atlas-pulse absolute left-1/2 top-[55%] size-32 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#e77a59]/40" />
              <svg
                className="absolute inset-0 h-full w-full"
                viewBox="0 0 180 250"
                fill="none"
                aria-label="Vizuální mapa připravenosti"
              >
                <circle
                  cx="91"
                  cy="28"
                  r="18"
                  stroke="#d6f4e8"
                  strokeWidth="2.5"
                />
                <path
                  d="M76 51C70 65 70 86 75 105L60 139C57 152 62 165 70 170L59 218M104 52C113 68 113 86 107 105L121 138C126 151 122 163 113 170L127 218M75 63L48 91M107 63L135 83M77 104C84 111 98 111 106 104M70 169C81 177 102 177 113 169"
                  stroke="#d6f4e8"
                  strokeWidth="5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M59 218L45 237M127 218L140 234"
                  stroke="#d6f4e8"
                  strokeWidth="5"
                  strokeLinecap="round"
                />
                <ellipse cx="119" cy="140" rx="11" ry="14" fill="#e77a59" />
                <circle
                  cx="119"
                  cy="140"
                  r="23"
                  stroke="#e77a59"
                  strokeOpacity=".35"
                />
              </svg>
              {pain && (
                <div className="absolute right-0 top-1/2 z-20 w-52 rounded-2xl border border-[#e77a59]/30 bg-[#182b27] p-3 text-[11px] leading-5 shadow-xl">
                  <b className="text-[#ffc1ab]">Mechanika v kontextu</b>
                  <p className="mt-1 text-[#d5e5dd]">
                    Pravé lýtko 3× za 14 dní
                  </p>
                  <p className="text-[#9bb3aa]">
                    Achillova šlacha 2× za 14 dní
                  </p>
                  <p className="text-[#9bb3aa]">Bolest průměrně 2/10</p>
                </div>
              )}
            </div>
            <div className="grid grid-cols-3 border-t border-white/10 pt-4 text-center">
              <p>
                <b className="block text-lg text-[#c7ff54]">7,8%</b>
                <span className="text-[10px] text-[#8ba59d]">pohyb</span>
              </p>
              <p>
                <b className="block text-lg">248 ms</b>
                <span className="text-[10px] text-[#8ba59d]">regenerace</span>
              </p>
              <p>
                <b className="block text-lg">174</b>
                <span className="text-[10px] text-[#8ba59d]">spánek</span>
              </p>
            </div>
          </section>
        </div>
        <div className="mt-5 grid gap-5 md:grid-cols-[1.1fr_.9fr]">
          <section className="rounded-[28px] border border-white/10 bg-[#0c201d] p-6">
            <div className="flex justify-between">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#91b7a9]">
                  Tok zátěže 12 týdnů
                </p>
                <h2 className="mt-2 text-xl">Tělo zpracovává objem</h2>
              </div>
              <span className="rounded-full bg-[#e77a59]/15 px-3 py-1 text-[10px] font-bold text-[#ffc1ab]">
                4,2 km nad doporučeným +5 %
              </span>
            </div>
            <div className="mt-9 flex h-28 items-end gap-1">
              {[14, 18, 23, 20, 27, 25, 31, 29, 34, 32, 38, 36, 42, 39].map(
                (km, i) => (
                  <div key={i} className="relative flex flex-1 items-end">
                    <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[9px] text-[#9bb3aa]">
                      {km}
                    </span>
                    <i
                      style={{ height: `${km * 2}%` }}
                      className={`w-full rounded-sm ${
                        i > 10 ? "bg-[#c7ff54]" : "bg-[#28564d]"
                      }`}
                    />
                  </div>
                ),
              )}
            </div>
            <div className="mt-4 flex justify-between text-xs text-[#9bb3aa]">
              <span>km / týden</span>
              <span>Akutní 34,8 km</span>
              <span>Chronická 29,1 km</span>
            </div>
          </section>
          <section className="rounded-[28px] bg-[#c7ff54] p-6 text-[#071313]">
            <p className="font-mono text-[10px] uppercase tracking-[.15em] text-[#35602a]">
              Péče v kontextu
            </p>
            <h2 className="mt-2 text-2xl">
              Když se rytmus změní, máte komu napsat.
            </h2>
            <Link
              to="/app/messages"
              className="mt-7 inline-block rounded-full bg-[#071313] px-4 py-2.5 text-xs font-bold text-[#c7ff54]"
            >
              Otevřít péči →
            </Link>
          </section>
        </div>
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-50 flex border-t border-white/10 bg-[#071313]/95 px-4 pb-[max(.8rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:hidden">
        {nav.map(([to, i, label]) => (
          <Link
            key={to}
            to={to}
            className="flex flex-1 flex-col items-center gap-1 text-[10px] text-[#c7ff54]"
          >
            <span className="text-lg">{i}</span>
            {label}
          </Link>
        ))}
      </nav>
    </div>
  )
}
function AtlasBubble() {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const dragRef = useRef<{
    startX: number
    startY: number
    offX: number
    offY: number
    w: number
    h: number
    moved: boolean
  } | null>(null)
  const [score, setScore] = useState<number | null>(null)
  const [pain, setPain] = useState(0)
  const [soreness, setSoreness] = useState(1)
  const [fatigue, setFatigue] = useState(2)
  const [note, setNote] = useState("")
  const { tab } = useParams()
  const bodySignals: [string, number, (value: number) => void, string][] = [
    ["Bolest", pain, setPain, "žádná"],
    ["Svalová ztuhlost", soreness, setSoreness, "lehká"],
    ["Únava", fatigue, setFatigue, "mírná"],
  ]
  return (
    <>
      {!open && (
        <button
          onPointerDown={(event) => {
            const target = event.currentTarget
            target.setPointerCapture(event.pointerId)
            const rect = target.getBoundingClientRect()
            dragRef.current = {
              startX: event.clientX,
              startY: event.clientY,
              offX: event.clientX - rect.left,
              offY: event.clientY - rect.top,
              w: rect.width,
              h: rect.height,
              moved: false,
            }
          }}
          onPointerMove={(event) => {
            const drag = dragRef.current
            if (!drag) return
            if (
              Math.abs(event.clientX - drag.startX) +
                Math.abs(event.clientY - drag.startY) >
              6
            ) {
              drag.moved = true
            }
            if (drag.moved) {
              const x = Math.min(
                Math.max(8, event.clientX - drag.offX),
                window.innerWidth - drag.w - 8,
              )
              const y = Math.min(
                Math.max(8, event.clientY - drag.offY),
                window.innerHeight - drag.h - 8,
              )
              setPos({ x, y })
            }
          }}
          onPointerUp={() => {
            const drag = dragRef.current
            dragRef.current = null
            if (drag && !drag.moved) setOpen(true)
          }}
          style={
            pos
              ? { left: pos.x, top: pos.y, right: "auto", bottom: "auto" }
              : undefined
          }
          className="fixed bottom-[5.4rem] right-5 z-[60] flex touch-none cursor-grab items-center gap-2 rounded-full bg-[#c7ff54] px-4 py-3 text-sm font-bold text-[#071313] shadow-[0_12px_32px_rgba(0,0,0,.35)] active:cursor-grabbing"
        >
          <span className="grid size-6 place-items-center rounded-full bg-[#071313]/10">
            ♡
          </span>
          Check-in
        </button>
      )}
      {open && (
        <div
          data-auto-reveal
          className="fixed inset-x-0 bottom-[4.4rem] z-[70] mx-auto max-h-[calc(100dvh-5rem)] max-w-[480px] overflow-y-auto rounded-t-[28px] border border-white/10 bg-[#102724] p-5 text-[#f1f8f1] shadow-2xl md:bottom-7 md:right-7 md:left-auto md:rounded-[28px]"
        >
          <div className="flex justify-between">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
                Denní check-in
              </p>
              <h2 className="mt-1 text-2xl">Jak se dnes cítí tělo?</h2>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="grid size-9 place-items-center rounded-full border border-white/15"
            >
              ×
            </button>
          </div>
          <p className="mt-5 font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
            Nálada
          </p>
          <div className="mt-2 grid grid-cols-5 gap-2">
            {[
              ["😣", "těžká"],
              ["😕", "nejistá"],
              ["😐", "neutrální"],
              ["🙂", "dobrá"],
              ["😄", "skvělá"],
            ].map(([face, label], index) => (
              <button
                onClick={() => setScore(index)}
                key={face}
                aria-label={`Nálada: ${label}`}
                className={`flex aspect-square flex-col items-center justify-center rounded-2xl border text-xl ${
                  score === index
                    ? "border-[#c7ff54] bg-[#c7ff54]/15"
                    : "border-white/10 bg-[#071313]"
                }`}
              >
                {face}
                <span className="mt-1 text-[8px] text-[#91b7a9]">{label}</span>
              </button>
            ))}
          </div>
          <div className="mt-6 space-y-5 rounded-2xl bg-[#071313] p-4">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
                Tělesné pocity
              </p>
              <span className="text-[9px] text-[#71837b]">0 nic 10 silné</span>
            </div>
            {bodySignals.map(([label, value, setValue, low]) => (
              <div key={label}>
                <div className="mb-2 flex justify-between text-xs">
                  <span>{label}</span>
                  <b className="text-[#c7ff54]">{value}/10</b>
                </div>
                <input
                  aria-label={label}
                  type="range"
                  min="0"
                  max="10"
                  value={value}
                  onChange={(event) => setValue(Number(event.target.value))}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-[#29413b] accent-[#c7ff54]"
                />
                <div className="mt-1 flex justify-between text-[9px] text-[#71837b]">
                  <span>{low}</span>
                  <span>silné</span>
                </div>
              </div>
            ))}
          </div>
          <label className="mt-5 block">
            <span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
              Poznámka
            </span>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Co by měl váš fyzioterapeut vědět?"
              className="mt-2 min-h-20 w-full rounded-xl border border-white/10 bg-[#071313] p-3 text-sm text-[#f1f8f1] placeholder:text-[#71837b]"
            />
          </label>
          <div className="mt-5 grid grid-cols-3 gap-2 rounded-2xl bg-[#071313] p-3 text-center">
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">78</b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">
                připravenost
              </span>
              <div className="relative mt-3 h-4 rounded-sm border border-[#c7ff54]/35 bg-[#071313] p-[2px]">
                <i className="block h-full w-[78%] rounded-[2px] bg-[#c7ff54]" />
                <i className="absolute inset-y-[2px] left-1/2 w-px bg-[#071313]/45" />
                <i className="absolute inset-y-[2px] left-3/4 w-px bg-[#071313]/45" />
                <i className="absolute -right-1 top-1/2 h-2 w-1 -translate-y-1/2 rounded-r-sm bg-[#c7ff54]/50" />
              </div>
              <span className="mt-1 block text-[8px] text-[#c7ff54]">
                +6 bodů od včerejšího rána
              </span>
            </div>
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">7:42</b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">
                spánek
              </span>
              <div className="relative mt-3 h-4">
                <i className="absolute left-[7%] right-[7%] top-1/2 h-px -translate-y-1/2 bg-[#71837b]" />
                <i className="absolute left-[24%] right-[22%] top-1/2 h-2 -translate-y-1/2 rounded-sm bg-[#6ce6d3]/25" />
                <i className="absolute left-[49%] top-1/2 h-3 -translate-y-1/2 border-l border-dashed border-[#91b7a9]" />
                <i className="absolute left-[65%] top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#6ce6d3] ring-2 ring-[#071313]" />
              </div>
              <div className="mt-1 flex justify-between text-[7px] text-[#71837b]">
                <span>min 6:58</span>
                <span>med 7:31</span>
                <span>max 8:12</span>
              </div>
            </div>
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">1,34</b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">
                EWMA
              </span>
              <div className="relative mt-3 h-4">
                <i className="absolute left-[7%] right-[7%] top-1/2 h-px -translate-y-1/2 bg-[#71837b]" />
                <i className="absolute left-[28%] right-[25%] top-1/2 h-2 -translate-y-1/2 rounded-sm bg-[#6ce6d3]/25" />
                <i className="absolute left-[50%] top-1/2 h-3 -translate-y-1/2 border-l border-dashed border-[#91b7a9]" />
                <i className="absolute left-[78%] top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#e77a59] ring-2 ring-[#071313]" />
              </div>
              <div className="mt-1 flex justify-between text-[7px] text-[#71837b]">
                <span>min 0,94</span>
                <span>med 1,12</span>
                <span>max 1,34</span>
              </div>
            </div>
          </div>
          <button
            onClick={() => setOpen(false)}
            disabled={score === null}
            className="mt-5 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-40"
          >
            Uložit check-in
          </button>
        </div>
      )}
    </>
  )
}
function AtlasNav() {
  const { pathname } = useLocation()
  const links = [
    ["/app/today", "⌂", "Dnes"],
    ["/app/load", "⌁", "Zátěž"],
    ["/app/mechanics", "◌", "Pohyb"],
    ["/app/messages", "◔", "Péče"],
  ]
  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 flex border-t border-white/10 bg-[#071313]/95 px-4 pb-[max(.8rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:hidden">
      {links.map(([to, icon, label]) => (
        <Link
          key={to}
          to={to}
          className={`flex flex-1 flex-col items-center gap-1 text-[10px] ${
            pathname === to ? "text-[#c7ff54]" : "text-[#80968e]"
          }`}
        >
          <span className="text-lg">{icon}</span>
          {label}
        </Link>
      ))}
    </nav>
  )
}
function MotionAtlas3() {
  return (
    <>
      <MotionAtlas2 />
      <AtlasBubble />
    </>
  )
}
function DefaultToday() {
  return (
    <div className="motion-shell min-h-screen bg-[#e7e9e1] text-[#193431]">
      <Topbar />
      <main className="mx-auto min-h-screen max-w-[1180px] bg-[#f9f7f1] px-5 pb-24 pt-24 md:rounded-b-[28px] md:px-9">
        <TodayV2 />
      </main>
      <AtlasBubble />
      <AtlasNav />
    </div>
  )
}
const router = createBrowserRouter([
  { path: "/", Component: DefaultToday },
  { path: "/auth", Component: Auth },
  {
    Component: Layout,
    children: [
      { path: "/app/:tab", Component: RunnerPage },
      { path: "/data", Component: DataPage },
      { path: "/profile", Component: ProfilePage },
      { path: "/role/:role", Component: RolePage },
    ],
  },
])
export default function App() {
  useDynamicReveal()
  return <RouterProvider router={router} />
}
