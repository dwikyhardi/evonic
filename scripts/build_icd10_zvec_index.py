"""
Build the zvec vector index for icd10_search2.

Reads:  data/icd10_who_2010_codes.txt   (default, --source who)
        data/icd10cm_order_2025.txt     (--source cm)
Writes: data/icd10_zvec/

Usage:
    python3 scripts/build_icd10_zvec_index.py                        # full build (WHO 2010)
    python3 scripts/build_icd10_zvec_index.py --source cm            # full build (ICD-10-CM 2025)
    python3 scripts/build_icd10_zvec_index.py --source cm --limit 20 # smoke-test
    python3 scripts/build_icd10_zvec_index.py --rebuild              # force full rebuild
"""

import argparse
import os
import re
import shutil
import sys
import time

import requests
import zvec

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHO_DATA_FILE   = os.path.join(PROJECT_ROOT, 'data', 'icd10_who_2010_codes.txt')
CM_DATA_FILE    = os.path.join(PROJECT_ROOT, 'data', 'icd10cm_order_2025.txt')
INDEX_PATH      = os.path.join(PROJECT_ROOT, 'data', 'icd10_zvec')
OLLAMA_URL     = os.getenv('OLLAMA_BASE_URL', 'http://192.168.1.7:11434')
EMBED_MODEL    = os.getenv('OLLAMA_EMBED_MODEL', 'bge-m3:567m-fp16')
EMBED_DIMS     = 1024
BATCH_SIZE     = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_data_file(path: str) -> list[tuple[str, str]]:
    """Parse WHO 2010 semicolon-delimited format."""
    entries = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.split(';')
            if len(parts) < 9:
                continue
            raw_code = parts[5].strip()
            # Normalise: strip ICD dagger/asterisk markers and trailing punctuation
            code = re.sub(r'[^A-Z0-9.]', '', raw_code.upper())
            code = code.rstrip('.')
            desc = parts[8].strip()
            if code and desc and re.match(r'^[A-Z]\d{2}', code):
                entries.append((code, desc))
    return entries


def parse_cm_file(path: str) -> list[tuple[str, str]]:
    """Parse ICD-10-CM fixed-width order file (e.g. icd10cm_order_2025.txt).

    Format per line: SSSSS CCCCCCC B LLLL...LLLL SSSS...SSSS
      cols 0-4:  sequence number
      col  5:    space
      cols 6-12: code (7 chars, right-padded with spaces)
      col  13:   space
      col  14:   billable flag (1 = valid billing code, 0 = header)
      col  15:   space
      cols 16-75: long description (60 chars, right-padded)
      cols 76+:  short description
    Only billable codes (flag == '1') are included.
    """
    entries = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if len(line) < 77:
                continue
            billable = line[14]
            if billable != '1':
                continue
            code = line[6:13].strip()
            long_desc = line[16:76].strip()
            if code and long_desc and re.match(r'^[A-Z]\d', code):
                entries.append((code, long_desc))
    return entries


_LLM_URL = os.getenv('LLM_BASE_URL', 'http://192.168.1.7:8080/v1')
ENRICH_BATCH = 10   # entries per LLM call for synonym enrichment


def _expand_hyphens(text: str) -> str:
    """For any hyphenated term in text, append the split version.
    e.g. 'community-acquired pneumonia' → 'community-acquired pneumonia, community acquired pneumonia'
    """
    if '-' not in text:
        return text
    split_version = text.replace('-', ' ')
    if split_version != text:
        return f'{text}, {split_version}'
    return text


def _enrich_batch(entries: list[tuple[str, str]]) -> list[str]:
    """Ask LLM for 2-3 common clinical synonyms per entry. Returns one synonym string per entry."""
    lines = '\n'.join(f'{code}: {desc}' for code, desc in entries)
    prompt = (
        'For each ICD-10 code below, provide 3-5 clinical search terms a doctor might use to find this condition. '
        'Include: common clinical names, lay terms, acquisition/cause modifiers (e.g. community-acquired, drug-induced, hospital-acquired), abbreviations. '
        'One line per code, format exactly: CODE | term1, term2, term3\n'
        'No explanation, no extra lines.\n\n' + lines
    )
    try:
        resp = requests.post(
            f'{_LLM_URL}/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0,
                'max_tokens': len(entries) * 40,
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()['choices'][0]['message']['content'].strip()
        synonym_map: dict[str, str] = {}
        for line in text.splitlines():
            if '|' not in line:
                continue
            left, right = line.split('|', 1)
            code = left.strip().split(':')[0].strip().split()[0].strip()
            synonyms = right.strip()
            if synonyms:
                synonym_map[code] = synonyms
        return [synonym_map.get(code, '') for code, _ in entries]
    except Exception:
        return [''] * len(entries)


def _pad_with_indonesian(desc: str) -> str:
    """Translate desc to Indonesian via llama.cpp and append, to break NaN-triggering token sequences."""
    try:
        resp = requests.post(
            f'{_LLM_URL}/chat/completions',
            json={
                'model': 'default',
                'messages': [
                    {'role': 'user', 'content': f'Translate to Indonesian, 5-10 words only, no explanation:\n{desc}'}
                ],
                'temperature': 0,
                'max_tokens': 32,
            },
            timeout=15,
        )
        resp.raise_for_status()
        indonesian = resp.json()['choices'][0]['message']['content'].strip()
        if indonesian:
            return f'{desc} | {indonesian}'
    except Exception:
        pass
    return desc


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. On NaN error, retry one-by-one and zero-fill NaN entries."""
    try:
        resp = requests.post(
            f'{OLLAMA_URL}/api/embed',
            json={'model': EMBED_MODEL, 'input': texts},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()['embeddings']
    except requests.HTTPError as e:
        if e.response is not None and 'NaN' in e.response.text and len(texts) > 1:
            # NaN in batch — embed one by one, zero-fill failures
            results = []
            for text in texts:
                # Try progressively simpler representations to escape NaN
                desc_only = text.split(': ', 1)[-1]
                # Fast attempts first (no LLM), LLM translation only as last resort
                fast_candidates = [
                    text[:256],                          # original (code: desc)
                    desc_only[:256],                     # description only
                    desc_only.replace(',', '')[:256],    # strip commas (known NaN trigger)
                    desc_only[:64],                      # short truncation
                ]
                # Try fast candidates first
                embedded = False
                for candidate in fast_candidates:
                    try:
                        r = requests.post(
                            f'{OLLAMA_URL}/api/embed',
                            json={'model': EMBED_MODEL, 'input': [candidate]},
                            timeout=30,
                        )
                        r.raise_for_status()
                        results.append(r.json()['embeddings'][0])
                        embedded = True
                        break
                    except Exception:
                        continue
                if embedded:
                    continue
                # Last resort: LLM translation to Indonesian
                indonesian = _pad_with_indonesian(desc_only)
                indonesian_only = indonesian.split(' | ', 1)[-1] if ' | ' in indonesian else ''
                candidates = [c for c in [indonesian[:256], indonesian_only[:256] if indonesian_only else None] if c]
                embedded = False
                for candidate in candidates:
                    try:
                        r = requests.post(
                            f'{OLLAMA_URL}/api/embed',
                            json={'model': EMBED_MODEL, 'input': [candidate]},
                            timeout=30,
                        )
                        r.raise_for_status()
                        results.append(r.json()['embeddings'][0])
                        embedded = True
                        break
                    except Exception:
                        continue
                if not embedded:
                    print(f'\n  WARNING: NaN embedding for {text[:60]!r} — using zero vector')
                    results.append([0.0] * EMBED_DIMS)
            return results
        raise


def build_schema() -> zvec.CollectionSchema:
    return zvec.CollectionSchema(
        name='icd10',
        fields=[
            zvec.FieldSchema('code',        zvec.DataType.STRING),
            zvec.FieldSchema('description', zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema('embedding', zvec.DataType.VECTOR_FP32, EMBED_DIMS)
        ],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',  choices=['who', 'cm'], default='who', help='Source dataset (default: who)')
    parser.add_argument('--limit',   type=int, default=0,     help='Only index first N entries (0 = all)')
    parser.add_argument('--rebuild',   action='store_true',      help='Delete existing index and rebuild')
    parser.add_argument('--resume',    action='store_true',      help='Resume from last saved progress')
    parser.add_argument('--no-enrich', action='store_true',      help='Skip LLM synonym enrichment — embed descriptions as-is')
    args = parser.parse_args()

    PROGRESS_FILE = os.path.join(INDEX_PATH, '.progress')

    DATA_FILE = CM_DATA_FILE if args.source == 'cm' else WHO_DATA_FILE

    # Guard: data file
    if not os.path.isfile(DATA_FILE):
        print(f'ERROR: data file not found: {DATA_FILE}')
        sys.exit(1)

    # Guard: existing index
    if os.path.exists(INDEX_PATH):
        if args.rebuild:
            print(f'Removing existing index at {INDEX_PATH}')
            shutil.rmtree(INDEX_PATH)
        elif not args.resume:
            print(f'Index already exists at {INDEX_PATH}')
            print('Use --rebuild to force a full rebuild, or --resume to continue.')
            sys.exit(0)

    # Parse entries
    entries = parse_cm_file(DATA_FILE) if args.source == 'cm' else parse_data_file(DATA_FILE)
    if args.limit:
        entries = entries[:args.limit]
    total = len(entries)
    print(f'Loaded {total} ICD-10 entries from {DATA_FILE}')

    # Verify embedding service
    print(f'Verifying Ollama at {OLLAMA_URL} with model {EMBED_MODEL}...')
    test_emb = embed_batch(['test'])
    actual_dims = len(test_emb[0])
    if actual_dims != EMBED_DIMS:
        print(f'ERROR: expected {EMBED_DIMS} dims, got {actual_dims}')
        sys.exit(1)
    print(f'OK — embedding dims: {actual_dims}')

    # Open or create collection; determine resume offset
    resume_from = 0
    if args.resume and os.path.exists(INDEX_PATH):
        coll = zvec.open(INDEX_PATH)
        if os.path.isfile(PROGRESS_FILE):
            resume_from = int(open(PROGRESS_FILE).read().strip())
        print(f'Resuming from entry {resume_from}')
    else:
        coll = zvec.create_and_open(INDEX_PATH, build_schema())

    # Batch embed + insert
    t0 = time.time()
    inserted = resume_from
    for batch_start in range(resume_from, total, BATCH_SIZE):
        batch = entries[batch_start:batch_start + BATCH_SIZE]

        if args.no_enrich:
            # Skip LLM enrichment — embed descriptions as-is
            texts = [f'{code}: {desc}'.replace('-', ' ')[:256] for code, desc in batch]
        else:
            # Enrich each entry with LLM-generated synonyms (sub-batches of ENRICH_BATCH)
            synonyms: list[str] = []
            for i in range(0, len(batch), ENRICH_BATCH):
                synonyms.extend(_enrich_batch(batch[i:i + ENRICH_BATCH]))

            # Build embedding text: "CODE: desc | synonym1, synonym2" with hyphen expansion
            texts = []
            for (code, desc), syn in zip(batch, synonyms):
                base = f'{code}: {desc}'.replace('-', ' ')
                if syn:
                    expanded_syn = ', '.join(_expand_hyphens(s.strip()) for s in syn.split(','))
                    text = f'{base} | {expanded_syn}'[:256]
                else:
                    text = base[:256]
                texts.append(text)

        try:
            embeddings = embed_batch(texts)
        except Exception as e:
            print(f'\nERROR embedding batch at {batch_start}: {e}')
            sys.exit(1)

        for (code, desc), emb in zip(batch, embeddings):
            coll.insert(zvec.Doc(
                id=code,
                vectors={'embedding': emb},
                fields={'code': code, 'description': desc},
            ))
        inserted += len(batch)
        open(PROGRESS_FILE, 'w').write(str(inserted))

        elapsed = time.time() - t0
        rate = inserted / elapsed
        eta = (total - inserted) / rate if rate > 0 else 0
        print(f'\r  {inserted}/{total} ({inserted/total*100:.1f}%) | '
              f'{rate:.0f} entries/s | ETA {eta:.0f}s    ', end='', flush=True)

    print()

    # Optimize for faster queries
    print('Optimizing index...')
    coll.optimize()

    elapsed = time.time() - t0
    if os.path.isfile(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    print(f'Done. {inserted} entries indexed in {elapsed:.1f}s')
    print(f'Index saved to: {INDEX_PATH}')

    # Quick sanity check
    print('\nSanity check queries:')
    for query in ['acute appendicitis', 'pneumonia', 'liver abscess']:
        q_emb = embed_batch([query])[0]
        results = coll.query(zvec.VectorQuery('embedding', vector=q_emb), topk=3)
        top = results[0] if results else None
        print(f'  {query!r} → {top.id if top else "no result"}: {top.field("description") if top else ""}')


if __name__ == '__main__':
    main()
