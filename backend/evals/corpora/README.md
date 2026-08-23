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

Require nonzero, schema-valid label coverage before a regression run:

```bash
python backend/scripts/check_semantic_corpus_labels.py \
  --manifest backend/evals/corpora/synthetic-v1/manifest.json \
  --corpus-dir backend/evals/corpora/synthetic-v1 \
  --minimum-labelled-cases 1 \
  --minimum-labels 2
```

This coverage gate does not score model quality. The checked-in labels describe
candidate-evidence alignment fields. A target-assessment quality regression also
requires case-aligned reference labels for specialist findings, synthesis claims,
judge disposition, and the expected evidence citations; those artifacts are not
currently checked in.

CI also runs the privacy-safe label-coverage gate:

```bash
python backend/scripts/check_semantic_corpus_labels.py \
  --manifest backend/evals/corpora/synthetic-v1/manifest.json \
  --corpus-dir backend/evals/corpora/synthetic-v1 \
  --minimum-labelled-cases 1 \
  --minimum-labels 2
```

This proves only that a non-empty, hash-pinned label contract is available. It
does not score model quality. A quality regression gate still requires
case-aligned reference outputs covering all five specialists, synthesis, and
the independent judge.
