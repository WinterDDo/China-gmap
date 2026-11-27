"""Pure parsing helpers for official statistical bulletins (统计公报).

Nothing here touches the network or the cache: sources pass in text and get back
plain dicts, so every function can be unit-tested on saved snippets.

  places    – match a place name as written by a publisher ("延边州", "海南州", "吉林市") to its 6-digit code
  htmltext  – HTML → plain text (block elements become line breaks), element and link extraction
  bulletin  – bulletin text → fields ({value, unit, quote}), with validation flags
  records   – the per-(code, year) record format shared by every bulletin source, merging and coverage
"""
