# Use of AI — technical sections

These references identify technical sections developed with the assistance of AI. The prompts below are reconstructed summaries, as the original wording was not retained.

## AI-01 Financial source classification prompt

**Location:** `prompt/prompt_text.py`, function `generate_classification_prompt`.

**prompt:** “Help me write a prompt that classifies a news source by financial importance, sentiment, category, and relevant niches, and returns the result as structured JSON.”

## AI-02 Financial analysis prompt

**Location:** `prompt/prompt_text.py`, function `generate_analysis_prompt`.

**prompt:** “Help me create a detailed financial-analysis prompt that evaluates the effects of an article on linked assets, uses market-price context, and produces structured analysis and trading signals.”

## AI-03 RSS source ingestion

**Location:** `ingestion/rss.py`, function `ingest_rss_feed`.

**prompt:** “Show me how to ingest articles from an RSS feed asynchronously, avoid duplicate sources, save new articles in PostgreSQL, and send them through the classification workflow.”
