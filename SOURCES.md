# Sources

EA-100's task distribution is a benchmark weighting derived from large-scale
observational studies of real consumer and workplace AI usage. The full spec
(`EA-100_Everyday_AI_Benchmark.md`, § "Why these tasks were chosen") cites each
category against its source anchor; the underlying sources are:

1. OpenAI, **"How People Use ChatGPT"** (research paper, 2025) — primary anchor;
   Practical Guidance, Seeking Information, and Writing ≈ 77–78% of consumer
   ChatGPT conversations, plus the granular per-category breakdown.
   https://cdn.openai.com/pdf/a253471f-8260-40c6-a2cc-aa93fe9f142e/economic-research-chatgpt-usage-paper.pdf

2. OpenAI, **"How people are using ChatGPT"** (summary page, 2025).
   https://openai.com/index/how-people-are-using-chatgpt/

3. OpenAI **Signals** consumer data & methodology — privacy-preserving aggregate
   statistics from ~300,000 sampled consumer ChatGPT messages/month.
   https://openai.com/signals/data/

4. OpenAI Signals **data dictionary**.
   https://cdn.openai.com/signals/data-dictionary.pdf

5. Anthropic, **Economic Index: Economic primitives** (Jan 2026) — coding-heavy
   Claude usage; office/admin ≈13% of API records; used to preserve work/coding/
   administrative tasks that would otherwise be underrepresented.
   https://www.anthropic.com/research/anthropic-economic-index-january-2026-report

6. Anthropic, **Economic Index: Learning curves** (Mar 2026) — education as a
   major category; broadening into product comparison, home maintenance,
   sales/outreach workflows.
   https://www.anthropic.com/research/economic-index-march-2026-report

7. Microsoft Research, **"Working with AI: Measuring the Applicability of
   Generative AI to Occupations"** (2025) — 200k anonymized Bing Copilot
   conversations; information gathering + writing dominate work uses.
   https://www.microsoft.com/en-us/research/publication/working-with-ai-measuring-the-occupational-implications-of-generative-ai/

## How they were used

- **OpenAI (1–4)** = the main prior for the consumer task mix (information
  seeking, tutoring, editing, how-to, drafting, health, translation, etc.).
- **Anthropic (5–6)** = adjustment to keep coding, office/admin, education, and
  commercial tasks represented despite low consumer-share numbers.
- **Microsoft (7)** = corroborating evidence for boosting summarization/synthesis
  and decision-support tasks.

The final distribution is explicitly *not* presented as market share — it is a
benchmark weighting. Image-generation tasks are reduced and scored separately
because they usually measure the assistant stack/toolchain rather than the base LLM.
