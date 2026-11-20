# Shamela research tools for Claude

Search the classical Arabic library (al-Maktaba al-Shamela, 8,587 books) from inside Claude:

- **by meaning**, when you do not know the author's wording;
- **by words standing near each other**, for one-line remarks, formulas and proof-texts;
- **read a page and check a quote** from your own copy of the books, with the editors' footnotes kept apart;
- **a notebook of checked findings**, so a passage is never hunted twice;
- **your own library** for books that Shamela does not have (typed text or OCR from scans);
- **an optional third library**: a large extra corpus that you supply yourself, indexed without the works Shamela already has.

Search results are candidates, not quotes. The tools are built so that the wording is always checked on the page before it is cited.

> **Status, 20 Nov 2026.** This is the first clean copy of a working private setup. It runs every day on the author's server.
> It has been installed into an empty folder and started there (see *What has been tested*), but not yet on a second machine.
> Licence: GPL-3.0 (see `LICENSE`).

## What is inside

| Folder | What it is |
|---|---|
| `search/` | The search service (`service.py`, local only, port 8791) and what it uses: the search code, the page store, the chapter paths, the notebook, the author labels, the page reader of the third library. `pages/ingest.py` copies every Shamela book to your machine. |
| `connector/` | The MCP server that Claude connects to (16 tools), and the scripts that add your own books to the library. |
| `build/` | The scripts that build the search index on Modal (GPU), the small index for your own library, the index for the optional third library, and the OCR job. |
| `ops/` | A nightly backup, a watch on disk and services with phone alerts, and the service files. |

## What you need

- A Linux machine that stays on. Tested on Ubuntu 22.04, ARM64, Python 3.10.
- Disk: about 45 GB (search index 12 GB, page copy 18 GB, and room to work). Memory: the search uses 1 to 5 GB.
- Only if you build the search index yourself: a [Modal](https://modal.com) account. The full build took about 8 US dollars of GPU
  time in November 2026.
- An HTTPS address in front of the connector (any reverse proxy), so Claude can reach it.
- A Claude plan that allows custom connectors.

## Install

1. `./install.sh` puts the code in `~/semsearch`, `~/library/maktaba` and `~/backups`, makes two Python environments and writes the
   service files. It creates `/etc/maktaba.env` with a new secret token. It starts nothing.
2. **Get the search index** into `~/semsearch/data`, one of two ways:
   - *Ready-made.* If this project's Releases page offers the index, download it (12 GB, every piece is checked):
     `cd ~/semsearch && venv/bin/python get_index.py https://github.com/<owner>/<repo>/releases/download/<tag> data`
   - *Build it yourself* with the four scripts in `build/shamela-index/` (A fetch, B embed, C index, D prepare the server files),
     then `modal volume get shamela-sem /serve ...`. Each script says at its top what it reads and writes.
3. **Copy the pages**: `cd ~/semsearch/pages && ../venv/bin/python ingest.py run`. Free, about an hour and a half, 18 GB. It can be
   stopped and started again.
4. **Start**: `sudo systemctl enable --now shamela-sem maktaba`, then check `curl http://127.0.0.1:8791/health`.
5. **Connect Claude**: point your HTTPS address at port 8790 and add `https://<your address>/<token>/mcp` as a connector.
   The token is in `/etc/maktaba.env`. Anyone who has the link can use the tools, so keep it private.
6. Optional: your own rules (`connector/profile.example.md`), author labels (`search/labels.example.json`), and the backup and
   watch (`ops/`, described at the top of `backup.py` and `health.py`).

## The tools Claude gets

| Tool | What it does |
|---|---|
| `search_digest` | Start here: one call runs both searches in every scope you name and returns one line per book. About ten times less for the chat to read. |
| `semantic_search` | Search Shamela by meaning. Scope it to books, an author or a category. |
| `nearby_words` | Find passages where given Arabic words stand near each other. Copies of the same passage are shown once. |
| `semantic_books` | Which books the search covers, with the exact author names. |
| `shamela_read_page`, `shamela_check_quote`, `shamela_contents` | Read a page, check a quote letter for letter, list a book's headings. |
| `findings_search`, `findings_add` | The notebook of passages already checked on the page. |
| `list_books`, `search`, `get_page`, `get_links`, `get_page_image` | Your own library: books, keyword search, pages, and the scan of a page. |
| `kutub_read_page`, `check_quote` | Read a page of the third library. Check a quote letter for letter in your own library or in the third one. |

`search_digest`, `semantic_search`, `nearby_words` and `semantic_books` take `library`: `"shamela"` (the default), `"maktaba"` (your own
books) or `"kutub"` (the third library). A library that is not installed answers with a clear message, and the other tools keep working.

Every Shamela result carries the book, author, death year, volume and page, the chapter it sits in, and a note when the author is
on your label list.

## The optional third library ("kutub")

A third library can stand beside Shamela and your own books: a large extra corpus that you supply yourself as ONE SQLite file.
This repository holds no such file and no tool to fetch one. The code only expects this shape:

- `books(slug, title, title_arabic, author, author_slug, year, status, ...)`: one row per work. `status` is `done` when the text is
  complete, `author` is written in Latin letters, `year` is the author's death year (AH).
- `pages(slug, idx, volume, page_no, text)`: one row per page.

Put the file at `~/kutub/index.sqlite3` (or name it in `KUTUB_DB`). It is opened read-only and never written. Then, from nothing:

1. `~/kutub/catalog.py` finds the works that Shamela already has **by title** (with the author and the death year as a check).
2. `~/semsearch/kutub/kt_build.py` builds a keyword index of the rest. No GPU.
3. `~/kutub/overlap_check.py` finds the works whose **text** is in Shamela under another title: five runs of eight words from each
   book, searched as exact phrases.
4. `kt_build.py --skip-twins` builds the index again without those. Restart the search service; `/health` then lists the library.
5. Optional, for meaning-search: `kt_modal.py` embeds the passages on Modal and `kt_modal.py assemble` writes the vectors.
   `KT_LIMIT=2` embeds two shards only, as a trial.

On the author's server (20 Nov 2026) a corpus of 10,256 complete works came down to 2,751 that Shamela does not have (2.3 million
passages). Step 2 took 15 minutes and step 4 six.

Know this before you rely on it:

- The corpus records no school or sect for its authors. Every result says so. The labels cover only the authors on your own list.
- Most of the text is machine-read. Editors' notes are not split from the author's words, and there are no chapter paths.
- "The same work" was decided by machine: by title, then by content. No person read the 1,975 pairs that were left out. An
  abridgement that copies its source word for word can look like a twin.

## What was measured (November 2026)

Real questions were searched in each of the four madhhabs, and readers marked every result page as direct, possible or a
different matter.

- Nearby-words, best matches first: 576 of 994 result pages were directly on the matter (58%; eleven questions).
- Meaning-search, 25 results a scope: 416 of 1,000 (ten questions).
- The two together, 25 results each, reached at least three different books with a direct passage in 38 of 40 scopes
  (ten questions, four madhhabs). Nearby-words alone reached that in 33.
- `search_digest` against the two full lists (ten questions, 40 scopes): the full lists cost 80 calls and 1.71 million characters
  and gave a direct passage in 40 scopes, from three or more books in 38. The digest with 10 books a scope: 10 calls, 124,000
  characters, 40 and 34. With 20 books: 219,000 characters, 40 and 38.
- Tried and found to give no gain: chapter names added to the passages, a root-level keyword field, hadith chains stripped
  before embedding, full-size vectors instead of the short ones.
- A meaning-search over the whole library with no scope rarely lands on the right page. Scope it.

## What is not in this repository

No books, no page scans, no notebook contents, no personal rules and no text of the third library. The search index is too big for the repository itself;
it is offered, if at all, as pieces on the Releases page (step 2). You fetch the page texts yourself (step 3).

## What has been tested

- Daily use on the author's server (Ubuntu 22.04, ARM64).
- `install.sh --no-systemd` into an empty folder on that server (1.3 GB for the two Python environments). From that folder the
  search service started against an existing index and answered a nearby-words search, a meaning-search, a page read and the
  notebook. The connector started, listed its tools and passed a search through.
- That test found two faults, both fixed here: the default `torch` pulls several GB of GPU libraries (the installer now takes the
  CPU build), and version 2 of the `mcp` package breaks the connector (pinned below 2).
- Known gap: with an empty library the five own-library tools (`list_books`, `search`, `get_page`, `get_links`, `get_page_image`)
  answer with an error until a first book is added. The Shamela tools do not depend on it.
- The index download (`get_index.py`, with `build/release/make_index_parts.sh` on the publishing side) was tried on a small index
  cut into five pieces and served locally: the unpacked copy was identical, and a damaged piece was refused. Not yet tried against
  GitHub itself.
- The third library (20 Nov 2026, on the author's server): `search/tests/kutub_test.py`, 21 of 21 tests against the running service.
  They cover: a request with `library` unset answers as before; nearby-words, the digest, a page read and the quote check in the
  third library; the digest and the quote check in the own library; the labels; clear refusals of options a library does not have.
- Meaning-search for the third library (20 Nov 2026): 2,296,918 passages embedded on Modal with `kt_modal.py`, 281 shards on two
  A10G GPUs, 38 minutes, 1.72 US dollars. A trial of two shards ran first. 49 passages picked at random each matched their own
  vector, and a whole passage searched by meaning brought its own page back in the top 3 for 8 of 8.
- Not yet tested: the Modal build scripts on another account, the service files on a second machine, and anything on Windows or macOS.

## Sources and thanks

- Texts: the dataset `AuthenticIlm/Shamela4_Full_DB` on Hugging Face, from al-Maktaba al-Shamela.
- Search model: `Omartificial-Intelligence-Space/Arabic-Triplet-Matryoshka-V2`.
- OCR: Kraken with the OpenITI Arabic model.

## Licence

GPL-3.0, see `LICENSE`. The books, the search index and the search model are not part of this repository and keep their own terms.
