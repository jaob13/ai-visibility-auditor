"""
discover.py - PLAN the audit from what the user tells us.

The user only types: business name, website, a few answers about the business,
where they are, and how far their market reaches (a radius, their state, or the
whole country). Everything else an audit needs is worked out here:

  1. READ THE WEBSITE   Fetch the homepage and pull out its title, description and
                        visible text. This grounds the AI in what the business
                        actually says about itself, not just what the user typed.

  2. FIND COMPETITORS   Two sources:
       - Google Places (optional, local scale only): real businesses of the same
         kind near the user's location, filtered by actual distance so the radius
         the user picked is respected. Facts from a map database, not AI memory.
       - Claude: proposes competitors that fit the business and the market scale.
         Used for regional/national scale, or to fill in when Places finds few.

  3. WRITE QUESTIONS    Claude writes the questions a real customer would type into
                        an AI assistant, scoped to the market (e.g. including the city
                        for a local business). Questions never name any brand, so no
                        business gets a free mention just because the question said it.

  4. GUARD THE PLAN     Plain code cleans the AI's proposal: removes the user's own
                        business from the competitor list, removes duplicates, drops any
                        question that names a tracked brand, and caps the counts.

The result is a draft plan the user reviews and edits in the app before anything
is scored. The AI proposes; the person approves.
"""

from __future__ import annotations

import html as html_lib
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

from .config import AuditConfig, Brand
from .engines import _post_json

SCALES = ("local", "state", "national")
MAX_COMPETITORS = 8
MAX_QUESTIONS = 15


@dataclass
class BusinessInput:
    """Exactly what the user typed into the form."""

    name: str
    website: str
    what_you_do: str
    customers: str = ""
    difference: str = ""
    location: str = ""            # e.g. "Charlotte, NC"
    scale: str = "local"          # local | state | national
    radius_miles: int = 25

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Business name is required.")
        if not self.what_you_do.strip():
            raise ValueError("Tell us what the business does.")
        if self.scale not in SCALES:
            raise ValueError(f"Scale must be one of {SCALES}.")
        if self.scale in ("local", "state") and not self.location.strip():
            raise ValueError("Location is required for local or state scale.")
        if self.scale == "local" and not (1 <= int(self.radius_miles) <= 100):
            raise ValueError("Radius must be between 1 and 100 miles.")


@dataclass
class Competitor:
    name: str
    domains: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source: str = "ai"            # "places" (map data) or "ai" (Claude's suggestion)
    detail: str = ""              # e.g. "4.2 mi away" or the AI's one-line reason


@dataclass
class AuditPlan:
    """A reviewable draft: what the app will compare and which questions it will ask."""

    target_name: str
    target_aliases: list[str]
    target_domains: list[str]
    category: str
    competitors: list[Competitor]
    questions: list[str]
    notes: list[str] = field(default_factory=list)   # anything the user should know

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AuditPlan":
        return AuditPlan(
            target_name=d["target_name"], target_aliases=list(d.get("target_aliases", [])),
            target_domains=list(d.get("target_domains", [])), category=d.get("category", ""),
            competitors=[Competitor(**c) for c in d.get("competitors", [])],
            questions=list(d.get("questions", [])), notes=list(d.get("notes", [])),
        )

    def to_config(self) -> AuditConfig:
        """Turn the approved plan into the AuditConfig the scoring pipeline runs on."""
        return AuditConfig(
            target=Brand(self.target_name, tuple(self.target_aliases), tuple(self.target_domains), True),
            competitors=[Brand(c.name, tuple(c.aliases), tuple(c.domains)) for c in self.competitors],
            questions=list(self.questions),
        )


# ------------------------------------------------------------- 1. website

def domain_of(url: str) -> str:
    """'https://www.Example.com/about' -> 'example.com'. Empty string if not a URL."""
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urllib.parse.urlparse(url).hostname or ""
    return host.lower().removeprefix("www.")


def page_summary(raw_html: str, limit: int = 3000) -> dict:
    """Extract title, meta description and readable text from a page's HTML."""
    title = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', raw_html, re.I | re.S)
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "title": html_lib.unescape(title.group(1).strip()) if title else "",
        "description": html_lib.unescape(desc.group(1).strip()) if desc else "",
        "text": text[:limit],
    }


def fetch_website(url: str, timeout: int = 15) -> dict:
    """Download the homepage. Returns a summary dict, or {'error': ...} if the site
    can't be reached; a missing website never stops the audit."""
    if not url:
        return {"error": "no website given"}
    full = url if "://" in url else "https://" + url
    req = urllib.request.Request(full, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(400_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
        return page_summary(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"couldn't read {full}: {e}"}


# --------------------------------------------------- 2a. Google Places (local)

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance between two map points, in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _places_search(query: str, key: str, center: tuple[float, float] | None = None,
                   radius_m: float | None = None, limit: int = 15) -> list[dict]:
    payload: dict = {"textQuery": query, "pageSize": limit}
    if center and radius_m:
        payload["locationBias"] = {"circle": {"center": {"latitude": center[0], "longitude": center[1]},
                                              "radius": min(radius_m, 50_000.0)}}
    data = _post_json("https://places.googleapis.com/v1/places:searchText", payload, {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.location,places.formattedAddress",
    })
    return data.get("places", [])


def places_competitors(inp: BusinessInput, category: str, key: str, target_domain: str,
                       log=print) -> list[Competitor]:
    """Real nearby businesses of the same kind, kept only if inside the chosen radius."""
    # Find the user's own business to get a map center; fall back to the city itself.
    found = _places_search(f"{inp.name} {inp.location}", key, limit=1) or \
            _places_search(inp.location, key, limit=1)
    if not found or "location" not in found[0]:
        log("  Google Places: couldn't find the location on the map.")
        return []
    c = found[0]["location"]
    center = (c["latitude"], c["longitude"])
    radius_m = inp.radius_miles * 1609.34

    results = _places_search(f"{category} near {inp.location}", key, center, radius_m)
    target_name = inp.name.strip().lower()
    out: list[Competitor] = []
    for p in results:
        name = (p.get("displayName") or {}).get("text", "").strip()
        loc = p.get("location")
        if not name or not loc:
            continue
        dist = haversine_miles(center[0], center[1], loc["latitude"], loc["longitude"])
        dom = domain_of(p.get("websiteUri", ""))
        if dist > inp.radius_miles:                      # outside the radius: drop
            continue
        if name.lower() == target_name or (dom and dom == target_domain):
            continue                                     # that's the user's own business
        out.append(Competitor(name=name, domains=[dom] if dom else [], source="places",
                              detail=f"{dist:.1f} mi away"))
    log(f"  Google Places: {len(out)} competitors within {inp.radius_miles} miles.")
    return out


# --------------------------------------------------------- 2b + 3. Claude

PLAN_SYSTEM_PROMPT = """You plan an "AI visibility audit": measuring whether AI assistants recommend a business.
Return ONLY a JSON object:
{"category": "<short plain phrase for what the business is, e.g. 'day spa', 'field service software'>",
 "aliases": ["<other ways people write the business name>"],
 "competitors": [{"name": "<real competitor>", "website": "<domain or empty>", "reason": "<one short line>"}],
 "questions": ["<question a customer would ask an AI assistant>"]}
Rules:
- Competitors must be real businesses that compete for the SAME customers at the stated market scale.
  Local scale: businesses near the stated location. State scale: within that state. National: national players.
  Only include competitors you are confident exist. Fewer real ones beat more invented ones.
- Questions: 12 natural questions a potential customer would type, varied (best-of, comparisons of needs,
  price/value, specific services). For local or state scale include the place name in most questions.
- Questions must NOT contain the business's name or any competitor's name.
- Use the website text as the main source of truth about what the business offers."""


def ai_plan(inp: BusinessInput, site: dict, planner, wanted_competitors: int) -> dict:
    market = {"local": f"within about {inp.radius_miles} miles of {inp.location}",
              "state": f"across the state/region of {inp.location}",
              "national": "nationwide (United States)"}[inp.scale]
    site_part = (f"Website title: {site.get('title', '')}\nWebsite description: {site.get('description', '')}\n"
                 f"Website text (excerpt): {site.get('text', '')}" if "error" not in site
                 else f"(Website could not be read: {site['error']})")
    prompt = (f"Business name: {inp.name}\nWebsite: {inp.website}\nWhat they do: {inp.what_you_do}\n"
              f"Customers: {inp.customers or 'not given'}\nWhat makes them different: {inp.difference or 'not given'}\n"
              f"Location: {inp.location or 'not given'}\nMarket scale: {inp.scale}, {market}\n"
              f"Propose up to {wanted_competitors} competitors.\n\n{site_part}")
    raw = planner.ask(prompt, system=PLAN_SYSTEM_PROMPT, max_tokens=1800)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("The AI didn't return a usable plan. Try again.")
    return json.loads(raw[start:end + 1])


# ---------------------------------------------------------------- 4. guard

def _mentions_any(text: str, names: list[str]) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![\w-])" + re.escape(n.lower()) + r"(?![\w-])", low) for n in names if n)


def guard_plan(inp: BusinessInput, target_domain: str, ai: dict,
               places: list[Competitor]) -> AuditPlan:
    """Clean the proposal with plain rules. Map-data competitors come first, then AI ones."""
    notes: list[str] = []
    target_names = [inp.name.strip(), *[a.strip() for a in ai.get("aliases", []) if a.strip()]]
    target_lower = {n.lower() for n in target_names}

    competitors: list[Competitor] = []
    seen: set[str] = set()

    def add(c: Competitor) -> None:
        key = c.name.strip().lower()
        if not key or key in seen or key in target_lower:
            return
        if target_domain and target_domain in c.domains:
            return
        seen.add(key)
        competitors.append(c)

    for c in places:
        add(c)
    for c in ai.get("competitors", []):
        if len(competitors) >= MAX_COMPETITORS:
            break
        dom = domain_of(c.get("website", ""))
        add(Competitor(name=str(c.get("name", "")).strip(), domains=[dom] if dom else [],
                       source="ai", detail=str(c.get("reason", "")).strip()))
    competitors = competitors[:MAX_COMPETITORS]
    if not competitors:
        notes.append("No competitors were found. Add a few by hand before running.")
    elif any(c.source == "ai" for c in competitors):
        notes.append("AI-suggested competitors come from the model's knowledge. Check they're real and current.")

    all_names = target_names + [c.name for c in competitors]
    questions, dropped = [], 0
    for q in ai.get("questions", []):
        q = str(q).strip()
        if not q or q in questions:
            continue
        if _mentions_any(q, all_names):
            dropped += 1
            continue
        questions.append(q)
    questions = questions[:MAX_QUESTIONS]
    if dropped:
        notes.append(f"Removed {dropped} question(s) that named a brand, so no one gets a free mention.")

    return AuditPlan(
        target_name=inp.name.strip(), target_aliases=[a for a in target_names[1:] if a.lower() != inp.name.strip().lower()],
        target_domains=[target_domain] if target_domain else [],
        category=str(ai.get("category", "")).strip(), competitors=competitors,
        questions=questions, notes=notes)


# --------------------------------------------------------------- the stage

def build_plan(inp: BusinessInput, planner, places_key: str | None = None, log=print) -> AuditPlan:
    """Run steps 1-4 and return a draft plan for the user to review."""
    inp.validate()
    target_domain = domain_of(inp.website)

    log("Reading the website...")
    site = fetch_website(inp.website)
    if "error" in site:
        log(f"  {site['error']} (continuing with what you typed)")
    else:
        log(f"  Read: {site['title'] or target_domain}")

    log("Asking Claude to plan the comparison...")
    ai = ai_plan(inp, site, planner, MAX_COMPETITORS)
    category = str(ai.get("category", "")).strip() or inp.what_you_do[:60]

    places: list[Competitor] = []
    if inp.scale == "local" and places_key:
        log("Searching Google Places for nearby competitors...")
        try:
            places = places_competitors(inp, category, places_key, target_domain, log)
        except Exception as e:  # noqa: BLE001
            log(f"  Google Places failed ({e}); using AI suggestions only.")

    plan = guard_plan(inp, target_domain, ai, places)
    if "error" in site:
        plan.notes.append("The website couldn't be read, so the plan relies on your answers.")
    if inp.scale == "local" and not places_key:
        plan.notes.append("Tip: add a Google Places key to find real competitors inside your exact radius.")
    log(f"Plan ready: {len(plan.competitors)} competitors, {len(plan.questions)} questions.")
    return plan
