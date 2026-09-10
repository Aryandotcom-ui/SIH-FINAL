#!/usr/bin/env bash
#
# Fetch corpus documents that are listed in ai/corpus.yaml but not yet on
# disk, then rebuild the index.
#
#   ./scripts/fetch-corpus.sh           download what is missing
#   ./scripts/fetch-corpus.sh --list    say what is missing, download nothing
#
# It downloads ONLY what data/pdfs does not already have. Seventeen of the
# documents the project needs are already in the repository, correctly tagged
# in ai/corpus.yaml and already ingested; re-fetching them would risk
# replacing a verified scan with whatever a portal serves today, for no gain.
#
# ---------------------------------------------------------------------------
# The filename is a contract
# ---------------------------------------------------------------------------
# Each output name below MUST match a `file:` key in ai/corpus.yaml. That is
# what attaches the document's jurisdiction, act_name and effective_date to
# every chunk it produces — and the jurisdiction is what the India /
# International scope filter searches on. A file downloaded under any other
# name still ingests, but on *inferred* metadata, and inference is where every
# corpus defect found so far has come from (see ai/corpus.yaml's header).
#
# ---------------------------------------------------------------------------
# Verify before you trust
# ---------------------------------------------------------------------------
# These are official portals, but portals reorganise. After a download,
# CHECK that the file is the instrument named and is the current amended
# text, then flip its `status: pending` to `status: ingested` in
# ai/corpus.yaml. A wrong or superseded text ingested under a correct
# act_name is worse than a missing one: it will be quoted at an applicant
# with a citation that looks right.

set -euo pipefail
cd "$(dirname "$0")/.."

LIST_ONLY=0
[ "${1:-}" = "--list" ] && LIST_ONLY=1

DEST=data/pdfs
mkdir -p "$DEST"

# filename|url
# Only documents ai/corpus.yaml lists as `pending`. Anything already
# `ingested` is deliberately absent from this list.
DOCS=(
  "patents-amendment-rules-2024.pdf|https://ipindia.gov.in/writereaddata/Portal/IPORule/1_83_1_Patent_Amendment_Rule_2024_Gazette_Copy.pdf"
  "designs-act-2000.pdf|https://www.indiacode.nic.in/bitstream/123456789/1993/3/A2000-16.pdf"
  "copyright-act-1957.pdf|https://www.indiacode.nic.in/bitstream/123456789/1367/1/195714.pdf"
  "trips-agreement-1994.pdf|https://www.wto.org/english/docs_e/legal_e/27-trips.pdf"
  "convention-on-biological-diversity-1992.pdf|https://www.cbd.int/doc/legal/cbd-en.pdf"
  "madrid-protocol-1989.pdf|https://www.wipo.int/wipolex/en/text/283484"
  "hague-agreement-1999.pdf|https://www.wipo.int/wipolex/en/text/285215"
  "budapest-treaty-1977.pdf|https://www.wipo.int/wipolex/en/text/283810"
  "eu-directive-2004-24-ec-thmpd.pdf|https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32004L0024"
  "fda-botanical-drug-development-guidance-2016.pdf|https://www.fda.gov/media/93113/download"
)

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$1" >&2; }

missing=()
for entry in "${DOCS[@]}"; do
  name="${entry%%|*}"
  if [ -s "$DEST/$name" ]; then
    printf '  have  %s\n' "$name"
  else
    missing+=("$entry")
    printf '  MISS  %s\n' "$name"
  fi
done

if [ "${#missing[@]}" -eq 0 ]; then
  say "Nothing missing. data/pdfs already has every document the manifest lists."
  exit 0
fi

if [ "$LIST_ONLY" = 1 ]; then
  say "${#missing[@]} document(s) missing. Re-run without --list to fetch them."
  exit 0
fi

say "Fetching ${#missing[@]} missing document(s)"
failed=0
for entry in "${missing[@]}"; do
  name="${entry%%|*}"
  url="${entry#*|}"
  tmp="$DEST/.$name.part"
  printf '  %s\n' "$name"
  if curl -fL --retry 2 --connect-timeout 20 --max-time 300 -o "$tmp" "$url" 2>/dev/null; then
    # A portal that has moved the document usually answers 200 with an HTML
    # error page. Writing that to a .pdf makes the extractor fail later with
    # a confusing error, so check the magic bytes here instead.
    if [ "$(head -c 4 "$tmp")" = "%PDF" ]; then
      mv "$tmp" "$DEST/$name"
    else
      rm -f "$tmp"
      warn "$name: the server did not return a PDF (likely a moved page). Fetch it by hand."
      failed=$((failed + 1))
    fi
  else
    rm -f "$tmp"
    warn "$name: download failed. Fetch it by hand from the URL in ai/corpus.yaml."
    failed=$((failed + 1))
  fi
done

if [ "$failed" -gt 0 ]; then
  warn "$failed document(s) could not be fetched. The rest are in $DEST."
fi

cat <<'NOTE'

  Next:
    1. Open each new file and confirm it is the instrument named, and the
       current amended text.
    2. Set its `status: pending` to `status: ingested` in ai/corpus.yaml,
       and fill in `effective_date` from the document itself.
    3. Rebuild so the new chunks are tagged and searchable:

         ./scripts/run.sh --rebuild

NOTE
