# How the AI Visibility Auditor works, in plain terms

This is your guide for explaining the app to an interviewer, a client, or anyone else. Each section starts with the one-sentence version, then goes deeper.

---

## The 30-second version

> "More and more people ask ChatGPT or Claude what to buy, or which business to use, instead of Googling it. I built an app that measures whether AI recommends your business. You type in your business, your website, and how far your market reaches. It reads your site, finds who you actually compete with (using Google's map data for local businesses), and writes the questions your customers ask. You review that plan, it asks the AI assistants, and it scores you and every competitor from 0 to 100. Then it shows you the exact questions where a competitor got recommended and you didn't, and you can export all of it. The AI does the reading and drafting. The scoring is plain math, and there are checks so the AI can't make things up."

---

## The problem it solves

Search used to mean Google, and businesses asked "where do we rank?" Now customers ask an AI assistant: *"What's the best day spa near Charlotte?"* The AI names three or four businesses. If yours isn't one of them, you lost that customer and never knew they existed.

Companies like Broadcastwell sell this measurement ("AI search visibility"). This app is a working version of that idea that any business can run.

---

## What the user does (the four screens)

1. **Tell us about the business.** Name, website, what you do, who your customers are, what makes you different, your location, and how far your market reaches: a local radius in miles, your state, or nationwide.
2. **Review the plan.** The app shows the competitors and questions it came up with. You can fix names, add or remove competitors, and edit questions. Nothing runs until you click *Run the audit*.
3. **Watch it run.** A live log shows each step: asking each AI, reading answers, scoring.
4. **See and export the results.** A full report on screen, with downloads for the HTML report, Print/Save as PDF, CSV (for Sheets or Excel), and JSON (all the raw data).

**How to say it:** "Four screens: tell it about you, check its plan, watch it work, take the results with you."

---

## What happens behind each screen

Think of it like an assembly line. Each station does one job and hands its output to the next.

### Station 1: Plan the audit (`discover.py`)

The user typed a handful of fields. An audit needs a lot more: a competitor list, their websites, other spellings of every name, and 12 or so good questions. This station works all of that out.

- **Read the website.** It downloads the homepage and pulls out the title, description, and visible text. This grounds the AI in what the business actually says about itself, not just what was typed into the form.
- **Find real local competitors (Google Places).** For a local business with a Places key, it looks up the business on the map, searches for the same kind of business nearby, and **measures the real distance** to each one. Anything outside the chosen radius is dropped. These are facts from a map database, not AI memory.
- **Ask Claude to fill in the rest.** Claude gets everything (form answers, website text, market reach) and proposes a category ("day spa"), more competitors if needed, and the questions customers would ask. Local questions include the city.
- **Clean the plan (the first guard).** Plain code then checks Claude's proposal. It removes your own business if Claude listed it as a competitor, removes duplicates, and **throws out any question that names a business**, because "Is Hand & Stone good?" would hand Hand & Stone a free mention.

**How to say it:** "It reads your site, uses map data to find real competitors inside your radius, has Claude draft the rest, then cleans up anything that would skew the results. And you approve the plan before anything runs."

### Station 2: Ask every AI (`engines.py`)

Every question goes to every AI the user picked (Claude, ChatGPT, Gemini), and each answer is saved.

Why save them? **Cost:** running the report again doesn't pay for the same answers twice. **Proof:** you can always show the exact answer behind a score.

### Station 3: Read the answers (`extract.py`)

An answer is a paragraph. A score needs facts. Two layers handle this:

- **Text matching (no AI)** finds which businesses were named, in what order, and whether their website was cited. It gives the same result every time.
- **Claude reading (optional)** labels the tone for each business (recommended, just mentioned, or warned against) and lists other businesses the AI named that you aren't tracking.

**The second guard, "AI that checks AI":** Claude may only label businesses that text matching actually found in the answer. If Claude claims a business was mentioned and it isn't in the text, that claim is thrown out and counted in the report.

**How to say it:** "Plain matching finds the facts. AI adds nuance. And the AI can describe an answer but can't invent anything about it."

### Station 4: Score (`score.py`)

Pure math, no AI.

| Measure | Plain meaning | Weight |
|---|---|---|
| Mention rate | How often it's named at all | 35% |
| Top-3 rate | How often it's in the first three named | 25% |
| First rate | How often it's named first | 20% |
| Citation rate | How often its website is referenced | 10% |
| Share of voice | Its slice of all mentions | 10% |

These combine into a **visibility score from 0 to 100**, plus a score per AI ("Claude knows us, Gemini doesn't") and the **gaps**: every answer where a competitor was named and you weren't. Each gap is a specific question to create content for.

**How to say it:** "The score is fixed, simple math, so it's repeatable and defensible. Nobody can say the AI made the number up."

### Station 5: Report and export (`report.py`, `server.py`)

The report reads top to bottom the way an owner would ask: How visible are we? How do we compare? Where are we losing? Who else is the AI recommending? Show me the evidence. Every raw answer is included and expandable.

### How the pieces connect (`server.py`, `pipeline.py`, `web/index.html`)

- The **web page** is one file with the four screens.
- The **server** runs on your own computer. Each long step (planning, running) is a background "job," and the page checks it every second to show progress.
- The **pipeline** is a single function that runs stations 2 through 4. The web app and the command line both call it, so they can't drift apart.
- **API keys** are typed into the page, used for that request, and never saved to disk or shown in error messages.

---

## The tests (`tests/`)

22 tests run with no internet, using fake AI engines. They check that:
- known inputs produce known scores (the "canary": the sample data must score exactly 11.4),
- the guards drop what they should (self-listing, duplicates, branded questions, made-up claims),
- distance math is correct (Charlotte to Raleigh is about 130 miles),
- the whole app works end to end: plan, run, export, demo, and bad input rejected.

**How to say it:** "Every change gets checked against known answers, so results can't quietly drift."

---

## Honest limitations (say these before someone else does)

- **API vs. app:** it asks the AI models directly. The consumer apps sometimes search the web live, so a real customer might see a different answer.
- **AI competitor lists can be stale:** without a Places key, competitors come from the AI's memory. That's why the review screen exists, and why map data is used when it's available.
- **Small businesses are often invisible to AI.** A score of 0 isn't a bug. It's the finding, and it's the pitch: "AI assistants don't know you exist yet."
- **AIs vary:** the same question can get a different answer tomorrow. More questions give steadier numbers.
- **Sample report is illustrative:** the demo answers are hand-written examples, not real AI output.

---

## Likely interview questions, with answers

**"Why not let the AI score it?"**
An AI's judgment isn't repeatable or auditable. I use AI where it's strong (reading messy text, drafting plans) and plain code where trust matters (the numbers).

**"How do you stop the AI from hallucinating?"**
Two guards. At planning, code removes self-listings, duplicates, and questions that name a brand, and map data replaces AI memory for local competitors when it's available. At scoring, the AI can only label businesses that text matching found in the answer. And a person reviews the plan before anything runs.

**"Why Google Places?"**
For local businesses, the AI's memory of who's nearby is the weakest link. Map data is current, and measuring real distance means the radius the user picked actually means something.

**"What would you build next?"**
Run each question several times and average to smooth out randomness. Save audits over time to show trends. Add AI engines with live web search. Schedule audits weekly and alert when a score drops.

**"How did you build it?"**
I architected it, directed the build with Claude, and verified it with tests. The design rule, "the model translates, the scripts judge," comes from the audit engine I built for local businesses.
