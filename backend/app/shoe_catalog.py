"""Running shoe brands and their model lines (owner request 2026-10-04): the shoe form
offers them as suggestions and a typed or recognised model is matched to its line, so
the same shoe is always written the same way.

A line is (name, category, carbon plate, drop mm | None). The version number is not
part of the line ("Clifton" covers Clifton 9 and 10) because drop and stack change
between versions (Clifton 9 has 5 mm, Clifton 10 8 mm), so a drop is given only where
the whole line keeps it (zero-drop brands and lines). Categories follow the app's seven:
daily | cushioned | stability | racing | minimal | trail | track. The list is not
exhaustive; any other brand or model can still be typed in.
"""
import re

D, CU, ST, R, MI, T, TR = "daily", "cushioned", "stability", "racing", "minimal", "trail", "track"

CATALOG: dict[str, list[tuple]] = {
    "Nike": [
        ("Pegasus", D, False, None), ("Pegasus Plus", D, False, None), ("Pegasus Premium", CU, False, None),
        ("Vomero", CU, False, None), ("Vomero Plus", CU, False, None), ("Vomero Premium", CU, False, None),
        ("Invincible", CU, False, None), ("Structure", ST, False, None), ("Winflo", D, False, None),
        ("Revolution", D, False, None), ("Downshifter", D, False, None), ("Journey Run", D, False, None),
        ("Interact Run", D, False, None), ("Infinity Run", ST, False, None), ("Free Run", MI, False, None),
        ("Zoom Fly", R, True, None), ("Vaporfly", R, True, None), ("Alphafly", R, True, None),
        ("Streakfly", R, False, None), ("Pegasus Trail", T, False, None), ("Kiger", T, False, None),
        ("Wildhorse", T, False, None), ("Zegama", T, False, None), ("Ultrafly", T, True, None),
        ("Juniper Trail", T, False, None), ("Dragonfly", TR, False, None), ("Maxfly", TR, False, None),
        ("Victory", TR, False, None), ("Rival", TR, False, None),
    ],
    "adidas": [
        ("Adizero Adios Pro", R, True, None), ("Adizero Adios Pro Evo", R, True, None), ("Adizero Pro", R, True, None),
        ("Adizero Prime X", R, True, None), ("Adizero Adios", R, False, None), ("Adizero Takumi Sen", R, False, None),
        ("Adizero Boston", D, False, None), ("Adizero Evo SL", D, False, None), ("Adizero SL", D, False, None),
        ("Supernova", D, False, None), ("Supernova Rise", D, False, None), ("Supernova Prima", D, False, None),
        ("Supernova Solution", ST, False, None), ("Ultraboost", D, False, None), ("Adistar", CU, False, None),
        ("Solarglide", D, False, None), ("Duramo", D, False, None), ("Duramo SL", D, False, None),
        ("Response", D, False, None), ("Galaxy", D, False, None), ("Runfalcon", D, False, None),
        ("Terrex Agravic", T, False, None), ("Terrex Agravic Speed", T, False, None), ("Terrex Speed Ultra", T, False, None),
        ("Terrex Soulstride", T, False, None), ("Tracefinder", T, False, None),
        ("Adizero Avanti", TR, False, None), ("Adizero Ambition", TR, False, None), ("Adizero Prime SP", TR, False, None),
    ],
    "ASICS": [
        ("Gel-Nimbus", CU, False, None), ("Gel-Kayano", ST, False, None), ("GT-2000", ST, False, None),
        ("GT-1000", ST, False, None), ("GT-4000", ST, False, None), ("Gel-Cumulus", D, False, None),
        ("Novablast", D, False, None), ("Superblast", D, False, None), ("Megablast", D, False, None),
        ("Gel-Excite", D, False, None), ("Gel-Pulse", D, False, None), ("Gel-Contend", D, False, None),
        ("Dynablast", D, False, None), ("EvoRide", D, False, None), ("Magic Speed", R, True, None),
        ("Metaspeed Sky", R, True, None), ("Metaspeed Edge", R, True, None), ("Metaspeed Ray", R, False, None),
        ("Hyper Speed", R, False, None), ("Gel-Trabuco", T, False, None), ("Trabuco Max", T, False, None),
        ("Fuji Lite", T, False, None), ("Fujispeed", T, True, None), ("Gel-Sonoma", T, False, None),
        ("Gel-Venture", T, False, None), ("Hyper MD", TR, False, None), ("Hyper LD", TR, False, None),
        ("Metasprint", TR, False, None),
    ],
    "Brooks": [
        ("Ghost", D, False, None), ("Ghost Max", CU, False, None), ("Glycerin", CU, False, None),
        ("Glycerin GTS", ST, False, None), ("Glycerin Max", CU, False, None), ("Adrenaline GTS", ST, False, None),
        ("Launch", D, False, None), ("Launch GTS", ST, False, None), ("Hyperion", R, False, None),
        ("Hyperion Max", D, False, None), ("Hyperion Elite", R, True, None), ("Levitate", D, False, None),
        ("Revel", D, False, None), ("Trace", D, False, None), ("Ariel GTS", ST, False, None),
        ("Beast GTS", ST, False, None), ("Caldera", T, False, None), ("Cascadia", T, False, None),
        ("Catamount", T, False, None), ("Divide", T, False, None),
    ],
    "HOKA": [
        ("Clifton", D, False, None), ("Bondi", CU, False, None), ("Mach", D, False, None), ("Mach X", D, False, None),
        ("Rincon", D, False, None), ("Arahi", ST, False, None), ("Gaviota", ST, False, None), ("Skyflow", D, False, None),
        ("Skyward X", CU, True, None), ("Kawana", D, False, None), ("Transport", D, False, None),
        ("Rocket X", R, True, None), ("Cielo X1", R, True, None), ("Cielo Road", R, False, None),
        ("Carbon X", R, True, None), ("Speedgoat", T, False, None), ("Challenger", T, False, None),
        ("Torrent", T, False, None), ("Tecton X", T, True, None), ("Mafate", T, False, None), ("Zinal", T, False, None),
        ("Stinson", T, False, None), ("Crescendo", TR, False, None),
    ],
    "Saucony": [
        ("Ride", D, False, None), ("Guide", ST, False, None), ("Triumph", CU, False, None), ("Hurricane", ST, False, None),
        ("Tempus", ST, False, None), ("Kinvara", D, False, None), ("Axon", D, False, None), ("Freedom", D, False, None),
        ("Echelon", D, False, None), ("Endorphin Speed", D, False, None), ("Endorphin Shift", D, False, None),
        ("Endorphin Pro", R, True, None), ("Endorphin Elite", R, True, None), ("Peregrine", T, False, None),
        ("Xodus", T, False, None), ("Endorphin Edge", T, True, None), ("Blaze TR", T, False, None),
        ("Excursion TR", T, False, None), ("Endorphin Cheetah", TR, False, None), ("Kilkenny", TR, False, None),
    ],
    "New Balance": [
        ("Fresh Foam X 1080", CU, False, None), ("Fresh Foam X 880", D, False, None), ("Fresh Foam X 860", ST, False, None),
        ("Fresh Foam X More", CU, False, None), ("Fresh Foam X Vongo", ST, False, None), ("Fresh Foam Arishi", D, False, None),
        ("FuelCell Rebel", D, False, None), ("FuelCell Propel", D, False, None),
        ("FuelCell SuperComp Trainer", D, True, None), ("FuelCell SuperComp Elite", R, True, None),
        ("FuelCell SuperComp Pacer", R, True, None), ("Ellipse", D, False, None),
        ("Fresh Foam X Hierro", T, False, None), ("Fresh Foam X More Trail", T, False, None),
        ("FuelCell Summit Unknown", T, False, None), ("FuelCell MD-X", TR, False, None), ("XC Seven", TR, False, None),
    ],
    "On": [
        ("Cloudmonster", CU, False, None), ("Cloudmonster Hyper", CU, False, None), ("Cloudsurfer", D, False, None),
        ("Cloudflow", D, False, None), ("Cloudflyer", ST, False, None), ("Cloudrunner", ST, False, None),
        ("Cloudeclipse", CU, False, None), ("Cloudstratus", CU, False, None), ("Cloudswift", D, False, None),
        ("Cloudgo", D, False, None), ("Cloudboom Echo", R, True, None), ("Cloudboom Strike", R, True, None),
        ("Cloudultra", T, False, None), ("Cloudvista", T, False, None), ("Cloudventure", T, False, None),
        ("Cloudsurfer Trail", T, False, None), ("Cloudspike", TR, False, None),
    ],
    "PUMA": [
        ("Deviate Nitro", D, True, None), ("Deviate Nitro Elite", R, True, None), ("Fast-R Nitro Elite", R, True, None),
        ("Fast-FWD Nitro Elite", R, True, None), ("Velocity Nitro", D, False, None), ("Magnify Nitro", CU, False, None),
        ("MagMax Nitro", CU, False, None), ("ForeverRun Nitro", ST, False, None), ("Liberate Nitro", D, False, None),
        ("Electrify Nitro", D, False, None), ("Voyage Nitro", T, False, None), ("Fast-Trac Nitro", T, False, None),
        ("evoSPEED", TR, False, None),
    ],
    "Mizuno": [
        ("Wave Rider", D, False, None), ("Wave Inspire", ST, False, None), ("Wave Sky", CU, False, None),
        ("Wave Horizon", ST, False, None), ("Wave Skyrise", D, False, None), ("Neo Vista", D, False, None),
        ("Neo Zen", D, False, None), ("Wave Rebellion Pro", R, False, None), ("Wave Rebellion Flash", D, False, None),
        ("Wave Daichi", T, False, None), ("Wave Mujin", T, False, None), ("Wave Ibuki", T, False, None),
    ],
    "Altra": [
        ("Escalante", D, False, 0.0), ("Torin", CU, False, 0.0), ("Paradigm", ST, False, 0.0), ("Provision", ST, False, 0.0),
        ("Rivera", D, False, 0.0), ("Via Olympus", CU, False, 0.0), ("Vanish Carbon", R, True, 0.0),
        ("Experience Flow", D, False, 4.0), ("Experience Form", ST, False, 4.0), ("Experience Wild", T, False, 4.0),
        ("Lone Peak", T, False, 0.0), ("Timp", T, False, 0.0), ("Olympus", T, False, 0.0), ("Mont Blanc", T, False, 0.0),
        ("Superior", T, False, 0.0), ("Outroad", T, False, 0.0),
    ],
    "Topo Athletic": [
        ("Phantom", CU, False, None), ("Ultrafly", ST, False, None), ("Cyclone", D, False, None), ("Specter", D, False, None),
        ("Atmos", CU, False, None), ("Magnifly", D, False, None), ("Fli-Lyte", D, False, None), ("ST", MI, False, None),
        ("Ultraventure", T, False, None), ("MTN Racer", T, False, None), ("Terraventure", T, False, None),
        ("Pursuit", T, False, None), ("Runventure", T, False, None),
    ],
    "Salomon": [
        ("Speedcross", T, False, None), ("Sense Ride", T, False, None), ("S/Lab Genesis", T, False, None),
        ("S/Lab Ultra", T, False, None), ("S/Lab Pulsar", T, False, None), ("Ultra Glide", T, False, None),
        ("Thundercross", T, False, None), ("Genesis", T, False, None), ("Pulsar Trail", T, False, None),
        ("XA Pro 3D", T, False, None), ("Glide Max TR", T, False, None), ("Aero Glide", D, False, None),
        ("Aero Blaze", D, False, None), ("Aero Volt", D, False, None), ("DRX Bliss", CU, False, None),
        ("S/Lab Phantasm", R, True, None),
    ],
    "inov-8": [
        ("Trailfly", T, False, None), ("Trailtalon", T, False, None), ("Mudtalon", T, False, None),
        ("X-Talon", T, False, None), ("Roclite", T, False, None), ("Terraultra", T, False, None),
        ("Parkclaw", T, False, None), ("Roadfly", D, False, None),
    ],
    "La Sportiva": [
        ("Bushido", T, False, None), ("Akasha", T, False, None), ("Jackal", T, False, None), ("Prodigio", T, False, None),
        ("Mutant", T, False, None), ("Cyklon", T, False, None), ("Karacal", T, False, None), ("Kaptiva", T, False, None),
        ("Lycan", T, False, None),
    ],
    "Merrell": [
        ("Agility Peak", T, False, None), ("MTL Long Sky", T, False, None), ("Nova", T, False, None),
        ("Antora", T, False, None), ("Trail Glove", MI, False, 0.0), ("Vapor Glove", MI, False, 0.0),
    ],
    "Scarpa": [("Spin", T, False, None), ("Ribelle Run", T, False, None), ("Golden Gate", T, False, None)],
    "Dynafit": [("Ultra", T, False, None), ("Alpine", T, False, None), ("Feline", T, False, None), ("Sky DNA", T, False, None)],
    "Scott": [
        ("Kinabalu", T, False, None), ("Supertrac", T, False, None), ("Ultra Carbon RC", T, True, None),
        ("Speed Carbon RC", R, True, None), ("Pursuit", D, False, None),
    ],
    "The North Face": [("Vectiv Enduris", T, False, None), ("Vectiv Infinite", T, False, None), ("Vectiv Pro", T, True, None),
                       ("Vectiv Sky", T, True, None)],
    "Under Armour": [
        ("Velociti Elite", R, True, None), ("Infinite Elite", D, False, None), ("Infinite Pro", D, False, None),
        ("HOVR Machina", D, False, None), ("HOVR Sonic", D, False, None), ("Charged Rogue", D, False, None),
        ("Charged Pursuit", D, False, None),
    ],
    "Skechers": [
        ("GOrun Razor", D, False, None), ("GOrun Ride", D, False, None), ("Max Cushioning", CU, False, None),
        ("GOrun Speed Beast", R, True, None), ("GOrun Speed Freek", R, True, None),
    ],
    "Reebok": [("Floatride Energy", D, False, None), ("Floatride Run Fast", R, False, None)],
    "Kiprun": [
        ("KD900X", R, True, None), ("KD900", D, False, None), ("KS900", CU, False, None), ("KD500", D, False, None),
        ("KS500", CU, False, None), ("MT Cushion", T, False, None), ("Race Light", T, False, None),
    ],
    "Kalenji": [("Jogflow", D, False, None), ("Run Support", ST, False, None)],
    "Craft": [("CTM Ultra", CU, False, None), ("Nordlite Ultra", T, False, None), ("Endurance Trail", T, False, None)],
    "Norda": [("001", T, False, None), ("002", T, False, None)],
    "VJ": [("Spark", T, False, None), ("Ultra", T, False, None), ("Maxx", T, False, None), ("Irock", T, False, None)],
    "Icebug": [("Pytho", T, False, None)],
    "Arc'teryx": [("Norvan LD", T, False, None), ("Sylan", T, False, None)],
    "Karhu": [("Fusion", D, False, None), ("Ikoni", D, False, None), ("Synchron", ST, False, None), ("Mestari", T, False, None)],
    "Diadora": [("Gara Carbon", R, True, None), ("Equipe Atomo", D, False, None), ("Mythos Blushield", D, False, None)],
    "361°": [("Flame", R, True, None), ("Centauri", D, False, None), ("Kairos", D, False, None)],
    "Li-Ning": [("Feidian", R, True, None), ("Red Rabbit", D, False, None), ("Chitu", D, False, None)],
    "Anta": [("C202", R, True, None)],
    "Xtep": [("160X", R, True, None)],
    "Newton": [("Gravity", D, False, None), ("Distance", D, False, None), ("Motion", ST, False, None), ("Fate", D, False, None)],
    "Vivobarefoot": [("Primus Lite", MI, False, 0.0), ("Primus Trail", MI, False, 0.0), ("Motus Strength", MI, False, 0.0),
                     ("Hydra ESC", MI, False, 0.0)],
    "Xero Shoes": [("HFS", MI, False, 0.0), ("Speed Force", MI, False, 0.0), ("Mesa Trail", MI, False, 0.0),
                   ("TerraFlex", MI, False, 0.0)],
    "Tracksmith": [("Eliot Runner", D, False, None)],
    "Veja": [("Condor", D, False, None)],
    "Allbirds": [("Tree Dasher", D, False, None)],
    "Kailas": [("Fuga", T, False, None)],
    "Joma": [],
    "Hylo": [],
    "Speedland": [],
}

BRANDS = tuple(CATALOG)


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z]+", (s or "").lower()) if t]


def match_line(brand: str | None, model: str | None) -> tuple | None:
    """The catalog line the model starts with, whole words only, the longest one wins
    ("Mach X 2" → Mach X, "Machina" → nothing)."""
    if not brand or not model or brand not in CATALOG:
        return None
    mt = _tokens(model)
    best, best_n = None, 0
    for line in CATALOG[brand]:
        lt = _tokens(line[0])
        if lt and mt[:len(lt)] == lt and len(lt) > best_n:
            best, best_n = line, len(lt)
    return best


def canonical_model(brand: str | None, model: str | None) -> tuple[str | None, tuple | None]:
    """The model with its line written as in the catalog ("gel nimbus 26" → "Gel-Nimbus 26")."""
    line = match_line(brand, model)
    if not line:
        return model, None
    words = [w for w in re.split(r"[\s\-_/]+", model.strip()) if w]
    rest = words[len(_tokens(line[0])):] if len(words) >= len(_tokens(line[0])) else []
    return " ".join([line[0], *rest]), line


def catalog_json() -> dict:
    return {"brands": [{"name": b, "models": [{"name": n, "category": c, "carbon": cb, "drop": d}
                                              for n, c, cb, d in lines]} for b, lines in CATALOG.items()]}
