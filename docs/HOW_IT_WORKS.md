# How the AI Visibility Auditor works, in plain terms

This is your guide for explaining the tool to an interviewer, a client, or anyone else. Each section starts with the one-sentence version, then goes deeper if you need it.

---

## The 30-second version

> "More and more people ask ChatGPT or Claude what product to buy instead of Googling it. I built a tool that measures how often an AI recommends a brand, how high up, and where competitors are winning instead. It asks several AIs the questions real buyers ask, pulls out which brands they named and in what order, and scores every brand from 0 to 100. The AI is only used to *read* answers. The scoring is plain math that gives the same answer every time, and there's a safety check that throws out anything the AI claims that isn't actually in the text."

---

## The problem it solves

Search used to mean Google, and businesses measured "where do we rank?" Now buyers ask an AI assistant: *"What's the best software for a small cleaning company?"* The AI names three or four products. If yours isn't one of them, you lost that buyer and never knew they existed.

Companies like Broadcastwell sell exactly this measurement ("AI search visibility"). This tool is a working, small-scale version of that idea.

---

## The five stages

Think of it like an assembly line. Each station does one job and hands its output to the next.

### 1. Setup: what are we auditing? (`config.py`)

A small settings file lists:
- **the brand** we care about (the "target"), e.g. GreenPrint
- **its competitors**, e.g. Jobber, Housecall Pro
- **other spellings** of each name ("HousecallPro" = "Housecall Pro")
- **their websites**, to spot when an AI points to a brand's site
- **the buyer questions** to ask

**How to say it:** "You tell it who you are, who you compete with, and what your customers ask."

### 2. Ask: question every AI (`engines.py`)

The tool sends every question to every AI it's configured for (Claude, ChatGPT, Gemini) and saves each answer to disk.

Why save them? Two reasons. **Cost:** re-running the report doesn't pay for the same answers twice. **Proof:** you can always show the exact answer behind a score.

Each AI is plugged in the same way, so adding a fourth one is one small block of code.

**How to say it:** "It asks every AI every question and keeps the receipts."

### 3. Translate: turn answers into facts (`extract.py`)

An AI answer is a paragraph of text. A score needs facts. This stage pulls out:
- which tracked brands were named, **in what order** (named first = rank 1)
- whether the answer **linked to a brand's website**
- *(optional)* whether each brand was **recommended, just mentioned, or warned against**
- *(optional)* **other products** the AI named that you aren't tracking yet

It does this in two layers:

**Layer 1, text matching (no AI).** Searches the answer for each brand's names and websites. Simple, fast, and gives the same result every time. This layer decides who was mentioned and in what order.

**Layer 2, AI reading (Claude, optional).** Text matching can't tell *"Jobber is great"* from *"avoid Jobber."* So Claude reads each answer and labels the tone for each brand, and lists any other products it noticed.

**The guard, "AI that checks AI."** AIs sometimes state things that aren't true. So the AI's labels are only accepted for brands that Layer 1 actually found in the text. If Claude says "GreenPrint was recommended" and the word GreenPrint isn't in the answer, that claim is thrown out and counted in the report.

**How to say it:** "Plain text matching finds the facts. AI adds nuance like tone. And there's a check so the AI can describe the answer but can't make anything up about it."

### 4. Judge: score every brand (`score.py`)

Pure math, no AI. For each brand, across all answers:

| Measure | Plain meaning | Weight |
|---|---|---|
| Mention rate | How often it's named at all | 35% |
| Top-3 rate | How often it's in the first three named | 25% |
| First rate | How often it's named first | 20% |
| Citation rate | How often its website is referenced | 10% |
| Share of voice | Its slice of all brand mentions | 10% |

Those combine into one **visibility score from 0 to 100**. The weights live in one place in the code, so changing them is a visible, deliberate decision.

It also produces:
- **a score per AI** ("Claude mentions us, Gemini doesn't")
- **gaps**: every answer where a competitor was named and you weren't. This is the most useful part, because each gap is a specific question you should create content to win.

**How to say it:** "The score is simple, fixed math, so it's repeatable and defensible. Nobody can argue the AI made the number up."

### 5. Show: the report (`report.py`)

Writes a web page report plus spreadsheet files. The page answers, in order:
1. How visible are we? (the big score)
2. How do we compare? (leaderboard)
3. Where are we losing? (gaps)
4. Who else is the AI recommending? (untracked products)
5. Show me the evidence. (every raw answer, expandable)

---

## The canary tests (`tests/`)

A canary test locks in a known-correct result. For example: on the bundled sample data, Housecall Pro must score 71.9 and GreenPrint 11.4. If anyone changes the matching or the math and those numbers move, the test fails immediately, before a wrong score reaches a client.

It's the same discipline as the Command Center's canary baselines.

**How to say it:** "Every change is checked against known answers, so the scores can't quietly drift."

---

## Honest limitations (say these before someone else does)

- **API vs. app:** it asks the AI models directly. The consumer apps sometimes search the web live, so a real customer might see a slightly different answer.
- **AIs vary:** the same question can get a different answer tomorrow. More questions and repeated runs give steadier numbers. Saving answers makes any single run reproducible.
- **Echoed names:** if the question names a brand ("alternatives to Jobber"), the answer usually repeats it, which counts as a mention.
- **Sample data is fake:** the bundled demo answers are hand-written examples to show the report working. A live run with API keys produces the real thing.

---

## Likely interview questions, with answers

**"Why not let the AI score it?"**
Because an AI's judgment isn't repeatable or auditable. Same answer in, different score out. I use AI where it's good (reading messy text) and plain code where trust matters (the numbers).

**"How do you stop the AI from hallucinating?"**
The guard. The AI can only label brands that text matching already found in the answer. Anything else is discarded and counted.

**"What would you build next?"**
Run each question several times and average the results to smooth out randomness. Track scores over time to show trends. Add engines with live web search. Schedule it weekly and alert when a score drops.

**"How long did it take and how did you build it?"**
I architected it, directed the build with Claude, and verified it with tests. The design rule, "the model translates, the scripts judge," comes from my audit engine for local businesses.

**"Why Python?"**
It's the standard for data and automation work, it runs anywhere, and this tool needs nothing beyond Python's built-in libraries.
