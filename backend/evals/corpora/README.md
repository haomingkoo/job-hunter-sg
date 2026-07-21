# Semantic evaluation corpora

`synthetic-v1` is the only corpus stored in git. It exercises the loader with
invented data.

Keep private corpora outside this repository and pass both locations explicitly:

```bash
python backend/semantic_corpus.py \
  --manifest /path/to/private-corpus/manifest.json \
  --corpus-dir /path/to/private-corpus
```

Each manifest has a `dataset_version` and a non-empty `cases` list. Every case
has a unique `case_id`, a `role_family`, and `resume`, `target_job`, and `labels`
objects containing a relative `ref` and lowercase SHA-256. References cannot be
absolute or escape the corpus directory. Target-job and label artifacts must be
JSON objects.

The command prints only case IDs, role families, and artifact hashes. It never
prints artifact contents or paths.
