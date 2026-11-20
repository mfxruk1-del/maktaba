"""Search over al-Maktaba al-Shamela, offered as extra tools on the Maktaba MCP server: search_digest (one call for a whole
question), semantic_search (by meaning), nearby_words (given words standing near each other) and semantic_books (which books are covered).

The same four tools take library="maktaba" (the owner's own books) or library="kutub" (the third library); kutub_read_page and
check_quote open and check pages there.

The work is done by a separate local service (~/semsearch/service.py on 127.0.0.1:8791); this file only forwards.
Enable in server.py with:  import sem_tools; sem_tools.register(mcp)
"""
import json, os, urllib.request

SEM_URL = os.environ.get("MAKTABA_SEM_URL", "http://127.0.0.1:8791")


def _call(path, payload, timeout=150):
    req = urllib.request.Request(SEM_URL + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode("utf-8"))
        except Exception: return {"error": "Shamela search service error %s" % e.code, "results": []}
    except Exception as e:
        return {"error": "the Shamela search service is not answering (%s). It may still be loading (about a minute after a "
                         "restart) or be stopped: sudo systemctl status shamela-sem" % type(e).__name__, "results": []}


LIBRARIES = ("shamela", "maktaba", "kutub")


def register(mcp):
    @mcp.tool(structured_output=False)          # plain text only: the same text must not travel twice
    def search_digest(phrases: list[str] | None = None, queries: list[str] | None = None, scopes: list[str] | None = None,
                      books: int = 10, window: int = 8, footnotes: str = "exclude", preset: str = "auto", chars: int = 110,
                      library: str = "shamela") -> str:
        """START HERE for a question about what the Shamela books say. ONE call runs nearby_words AND semantic_search in every scope
        you name, on the server, merges the two lists and returns ONE LINE PER BOOK. Far less to read than calling the two tools
        scope by scope, and the same sources.

        Give BOTH kinds of input, written as for the two tools:
          phrases: 5 to 8 nearby-words phrases (2 to 4 distinctive Arabic words each, alternatives with "|", plus the proof-text).
          queries: 2 Arabic wordings of the question that take DIFFERENT angles (the jurists' own framing of the matter).
          scopes: where to look; each is searched separately. "four" = the fiqh books of the four madhhabs. Shortcuts: hanafi, maliki,
            shafii, hanbali, aqida, hadith, shuruh, takhrij, tafsir, usul, fatawa. Or an Arabic category name, "author:الغزالي",
            "books:21613,5423", and combinations with ";" such as "author:ابن عابدين;category:hanafi" or "aqida;before:700".
            No scopes = the whole library, classical authors only.
          books: lines per scope. 10 for a plain matter, 20 for a disputed one (see MEASURED), up to 60.
          footnotes: editors' footnotes are left out unless "include". window, preset: as in nearby_words. chars: length of the quote.

        EACH LINE: title | author (death year AH) | volume/page | tags | chapter | the words found | id shamela_id:page_id |
        also = other pages of the same book (volume/page#page_id) | same words = other books that carry the same passage (the line
        stands under the earliest author; that is not proof of who copied whom).
        Tags: N3 = nearby-words, 3 of your phrases meet on that page; M = meaning-search; N2+M = both found it; label:... = the
        author is on the owner's label list (use the page, say whose school it is); footnote = the editor's words; editor? = may be
        the editor's introduction.

        THEN open the pages worth reading with shamela_read_page(shamela_id, page_id) and check the wording before quoting. The
        lines are candidates, not quotes, and an empty scope never proves absence. To dig deeper in one scope, use nearby_words or
        semantic_search there.

        library: "shamela" (default), "maktaba" (the owner's own books) or "kutub" (2,751 works whose text was not found in
        Shamela). There: no categories; scopes are "author:..." (Kutub: Latin letters),
        "books:id1,id2", dates or none; lines end "book <id> page <n>": open with get_page / kutub_read_page.

        MEASURED 20 Nov 2026 on ten questions in 40 scopes, with the readers' marks. Two full lists of 25 (80 calls, 1.71 million
        characters): a direct passage in 40 scopes, from three or more books in 38. This tool with books=10 (10 calls, 124,000
        characters, 14 times less): 40 and 34. With books=20 (219,000 characters, 8 times less): 40 and 38."""
        if footnotes not in ("include", "exclude", "only"): return 'ERROR: footnotes must be "include", "exclude" or "only"'
        if preset not in ("auto", "classical", "all"): return 'ERROR: preset must be "auto", "classical" or "all"'
        if library not in LIBRARIES: return 'ERROR: library must be "shamela", "maktaba" or "kutub"'
        r = _call("/digest", {"phrases": [str(x) for x in (phrases or [])][:40], "queries": [str(x) for x in (queries or [])][:5], "scopes": scopes or None,
                              "library": library,
                              "books": max(1, min(int(books), 60)), "window": max(0, min(int(window), 40)), "footnotes": footnotes, "preset": preset,
                              "chars": max(40, min(int(chars), 400))}, timeout=280)
        return r.get("digest") or ("ERROR: " + str(r.get("error") or "no answer from the search service"))

    @mcp.tool()
    def semantic_search(query: str, shamela_ids: list[int] | None = None, author: str | None = None, category: str | None = None,
                        died_after: int | None = None, died_before: int | None = None, footnotes: str = "exclude",
                        mode: str = "hybrid", limit: int = 8, chars: int = 350, preset: str = "auto",
                        per_book: int | None = None, more_queries: list[str] | None = None, library: str = "shamela",
                        hide_editor_pages: bool = False, books: list[str] | None = None) -> dict:
        """Search al-Maktaba al-Shamela BY MEANING (8,587 books, 15.3 million passages of about 900 characters).

        This searches the SHAMELA corpus, not the Maktaba library. Use it when you do not know the author's wording.
        When you can guess two or three of the author's words, nearby_words is usually better; when you know the exact
        phrase, Shamela's own phrase search is better.

        HOW WELL IT WORKS (18 known passages, measured 19 Nov 2026; right page within the first 5 / first 20 results):
          one book 13 / 16  -  one author's works 9 / 16  -  one category, classical authors 6 / 9  -  whole library 1 / 2
        So ALWAYS scope to books or to an author when you can. A category is a weak fallback. An unscoped search
        shows what kind of books talk about a topic but almost never lands on the page you need. Removing the modern
        books (preset "classical") did not change that: 3 of 18 in the first 50 instead of 2.
        - Write the query in ARABIC, as a short statement or question of the idea. English queries work badly.
        - Words with two senses mislead it (asked about breaking off the prayer, قطع الصلاة, it returned pages on
          cutting a thief's hand). Check the results, then try nearby_words with the jurists' own terms.
        - It misses one-line remarks inside an unrelated discussion. Never conclude that something is absent from a
          book because this tool did not return it.

        RESULTS ARE CANDIDATES, NOT QUOTES. The text is cleaned (no diacritics, cut to `chars`). Before quoting,
        open the page with the Shamela tools using shamela_id + part/page (or shamela_page_id) and verify the wording.
        "from": "editor's footnote" means the editor's words, not the author's. part or page -1 = Shamela has no
        such number for that book.
        "chapter" = where the page sits in its book ("كتاب ... > باب ... > فصل ..."), from the book's own table of contents;
        absent when the book has none. It can be one level off in deeply nested books: the page decides.

        Args:
          query: the idea to look for, in Arabic.
          more_queries: 1 to 4 OTHER Arabic wordings of the same question. Each is searched and the lists are fused by rank.
            Use it by default: a wording can fail badly (asked with the words for "cut" and "steal", the model returned
            pages on cutting a thief's hand). Measured 19 Nov 2026 on ten questions, direct pages in the first ten results:
            171 with the first wording alone, 202 with the second alone, 204 with both fused. Describe the situation in the
            jurists' terms; avoid a verb that has two senses. Results then carry rank_in_each_wording.
          shamela_ids: limit to these Shamela book ids (the same ids the Shamela tools use, e.g. 21613 = Radd al-Muhtar).
          author: limit to authors whose name contains this Arabic text as Shamela writes it (use semantic_books to
            check the spelling; the reply lists the author names that matched).
          category: Shamela category name or part of it in Arabic (e.g. "الفقه الحنفي", "العقيدة", "شروح الحديث").
          died_after / died_before: author's death year (hijri), inclusive. Authors with no recorded death date and
            living authors are excluded when either is set.
          preset: "auto" (default) = when you give no books, no author and no dates, only CLASSICAL authors are searched
            (died in or before 1300 AH; books with no recorded death date, e.g. fatwa sites and modern encyclopedias,
            are left out). "classical" forces that filter; "all" removes it (needed to search modern books).
            The reply's scope.preset says when the filter was applied.
          per_book: how many passages one book may place before the other books get their turn (nothing is dropped,
            only re-ordered). Default: 3 for category and whole-library searches; off (0) when you name books or an
            author, because there it pushed the right page down (top 10: 13 -> 11 of 18).
          footnotes: "exclude" (default since 20 Nov 2026: main text only), "include" (main text and the modern editors'
            footnotes; a footnote result says "from": "editor's footnote") or "only".
          hide_editor_pages: a main-text result that looks like the modern editor's contents, index or bibliography page
            carries "editor_material". It is a HINT, not a verdict: of the flags looked at on 20 Nov 2026 about three in
            four were right (contents, indexes, a modern study), the rest were the first or last pages of a real book; and
            it catches only about half of the editors' pages (never an introduction in plain prose). Default False = show
            the result with the hint. True drops flagged results: use it only for a first sweep, never to argue absence.
          library: "shamela" (default) or "maktaba" = the owner's own Maktaba library (38 books that are not in Shamela, typed
            or OCR). Maktaba results name a `book` and a `page` to open with Maktaba's get_page, not Shamela ids; there
            the filters are author, died_after / died_before and `category` "typed" or "OCR", and all its books are searched
            by default. OCR text must be checked against the page scan before quoting.
            "kutub": the third library (works not found in Shamela), searched by meaning like the others.
          books: maktaba / kutub only: book ids / slugs to search in.
          mode: "hybrid" (meaning + keyword, default), "meaning" or "keyword".
          limit: number of results, 1-25 (default 8). chars: characters of each passage to return, 80-900.
        """
        if footnotes not in ("include", "exclude", "only"): return {"error": 'footnotes must be "include", "exclude" or "only"'}
        if mode not in ("hybrid", "meaning", "keyword"): return {"error": 'mode must be "hybrid", "meaning" or "keyword"'}
        if preset not in ("auto", "classical", "all"): return {"error": 'preset must be "auto", "classical" or "all"'}
        if not (query or "").strip(): return {"error": "empty query"}
        if library not in LIBRARIES: return {"error": 'library must be "shamela", "maktaba" or "kutub"'}
        return _call("/search", {"query": query, "shamela_ids": shamela_ids, "author": author, "category": category, "books": books or None,
                                 "died_after": died_after, "died_before": died_before, "footnotes": footnotes, "mode": mode, "library": library,
                                 "hide_editor_pages": bool(hide_editor_pages),
                                 "limit": max(1, min(int(limit), 25)), "chars": max(80, min(int(chars), 900)), "preset": preset,
                                 "per_book": None if per_book is None else max(0, min(int(per_book), 20)),
                                 "queries": [str(q) for q in (more_queries or []) if str(q).strip()][:4]})

    @mcp.tool()
    def nearby_words(phrases: list[str], window: int = 8, shamela_ids: list[int] | None = None, author: str | None = None,
                     category: str | None = None, died_after: int | None = None, died_before: int | None = None,
                     preset: str = "auto", footnotes: str = "exclude", sort: str = "best", per_book: int = 2,
                     limit: int = 30, chars: int = 300, group: bool = True, library: str = "shamela",
                     hide_editor_pages: bool = False, books: list[str] | None = None) -> dict:
        """Find Shamela passages where a few given Arabic words stand NEAR EACH OTHER (within `window` words, in any order).

        Use it for what meaning-search misses: one-line remarks inside another discussion, set formulas, technical terms,
        and proof-texts (a fragment of the verse or hadith that scholars cite on the matter). It is fast (well under a
        second, even on the whole library) and uses no meaning model: it finds only what you word correctly.

        HOW TO WRITE THE PHRASES
        - Each phrase is 2 to 4 distinctive words. Leave out particles (في، من، على).
        - A word can carry alternatives with "|":  "الأنبياء|الرسل أحياء قبورهم|قبور".
        - Send SEVERAL phrases in one call (they are OR-ed): 5 to 8 different guesses of how a classical author would
          word the point, plus the proof-text. Guess before you read the page, the way the jurists write, not the way
          the user asked.
        - Matching ignores diacritics, hamza forms, ى/ي, ة/ه and a leading ال، و، ف، بال، لل. It does NOT join other
          word forms: قبور and قبورهم, حاضر and يحضر are different words. Give them as alternatives.

        WHAT COMES BACK
        - results: by default the pages where MORE of your phrases meet come first, then the stronger match
          (sort="best"; "phrases_met" says how many). sort="oldest" lists by the author's death year instead: use it
          only with tight phrases and few hits, because with many hits it cuts off the later books (measured 19 Nov
          2026 on eleven questions: 576 direct pages of 994 with "best" against 483 with "oldest"; on calling "ya" to
          saints, 34 against 0). At most `per_book` pages per book before other books get a turn. "match" is the stretch of words that was found;
          in "text" it stands between the marks U+27EA and U+27EB with context around it.
        - Pages that carry THE SAME WORDS (one passage copied from book to book, or two editions of one book) are shown
          once, under the earliest author; the other pages are listed in that result's "same_words_in" with book, author,
          death year and part/page, so nothing is dropped. The earliest book here is not proof of who copied whom: check on
          the page. group=False turns this off. (Measured 19 Nov 2026 on eleven questions: 994 pages became 839 items, and
          1 group in 104 put a direct page together with a page on a different matter.)
        - "chapter": where the page sits in its book ("كتاب ... > باب ... > فصل ..."), from the book's own table of contents.
          It tells a hit inside the chapter of the matter from a passing remark elsewhere (both are worth reading). Absent
          when the book has no table of contents; it can be one level off in deeply nested books: the page decides.
        - by_book: every book with a hit (first 80, oldest first) with its number of pages. Read it as a map of who
          said it first and who repeats it.
        - total_hits / pages_with_hits / books_with_hits; "note" appears when there were more hits than were read.

        LIMITS (measured 19 Nov 2026)
        - The two known passages that meaning-search always missed (al-Bahr al-Ra'iq 5/134, Radd al-Muhtar 3/551) were
          both found this way, the second with 3 of 7 guessed wordings. That is two cases, not a proven rate.
        - An empty result NEVER shows that something is absent: it may only mean other words were used.
        - "main text" can still be the modern editor's introduction at the start of a volume. Check the page.
        - Like semantic_search, results are candidates: verify the wording on the page with the Shamela tools before
          quoting. part or page -1 = Shamela has no such number for that book.

        Args:
          phrases: list of phrases as described above.
          window: how many words apart the words may stand (default 8; 2-4 for a fixed formula, up to 40).
          shamela_ids, author, category, died_after, died_before, footnotes, library: as in semantic_search
            (footnotes are left out by default; library="maktaba" searches the owner's Maktaba library instead).
            library="kutub": the third library; books: as in semantic_search.
          preset: as in semantic_search ("auto" = classical authors only unless you name books, an author or dates).
          sort: "best" (default), "mixed", "oldest" or "relevance". "mixed" is "best" with every fifth place given to the
            oldest author not yet shown: use it when the earliest sources matter. Measured 20 Nov 2026 on eleven questions:
            570 direct pages of 994 against 576 for "best", but 95 of them from authors who died by 500 AH against 71.
          per_book: pages per book per turn (default 2, 0 = no cap).
          limit: number of results, 1-60 (default 30). chars: characters of context per result, 80-900.
          group: True (default) shows copies of one passage once; False lists every page on its own.
          hide_editor_pages: as in semantic_search (flagged results carry "editor_material"; True drops them).
        """
        if footnotes not in ("include", "exclude", "only"): return {"error": 'footnotes must be "include", "exclude" or "only"'}
        if preset not in ("auto", "classical", "all"): return {"error": 'preset must be "auto", "classical" or "all"'}
        if sort not in ("best", "mixed", "oldest", "relevance"): return {"error": 'sort must be "best", "mixed", "oldest" or "relevance"'}
        if isinstance(phrases, str): phrases = [phrases]
        if not phrases: return {"error": "give at least one phrase"}
        if library not in LIBRARIES: return {"error": 'library must be "shamela", "maktaba" or "kutub"'}
        return _call("/near", {"phrases": [str(p) for p in phrases][:40], "window": max(0, min(int(window), 40)), "books": books or None,
                               "shamela_ids": shamela_ids, "author": author, "category": category, "died_after": died_after,
                               "died_before": died_before, "preset": preset, "footnotes": footnotes, "sort": sort, "library": library,
                               "hide_editor_pages": bool(hide_editor_pages),
                               "per_book": max(0, min(int(per_book), 20)), "limit": max(1, min(int(limit), 60)),
                               "chars": max(80, min(int(chars), 900)), "group": bool(group)}, timeout=60)

    @mcp.tool()
    def semantic_books(author: str | None = None, title: str | None = None, category: str | None = None,
                       died_after: int | None = None, died_before: int | None = None, limit: int = 40, library: str = "shamela") -> dict:
        """List the Shamela books the search index covers that match the filters (largest first), with their
        shamela_id, author as Shamela writes it, death year, category and number of passages. Use it to find the right
        shamela_ids or the exact author spelling before calling semantic_search or nearby_words. Text filters are
        Arabic substrings. library="maktaba" lists the books of the owner's Maktaba library that the search covers.
        library="kutub": the Kutub works (book = slug)."""
        if library not in LIBRARIES: return {"error": 'library must be "shamela", "maktaba" or "kutub"'}
        return _call("/books", {"author": author, "title": title, "category": category, "died_after": died_after,
                                "died_before": died_before, "limit": limit, "library": library}, timeout=60)

    @mcp.tool()
    def findings_search(arabic: str | None = None, topic: str | None = None, book: str | None = None, author: str | None = None,
                        list_topics: bool = False, limit: int = 20) -> dict:
        """Look in the NOTEBOOK OF VERIFIED FINDINGS: passages from Shamela books that were already found and checked on
        the real page in an earlier conversation. LOOK HERE FIRST when the user asks about a matter: a hit costs a few
        words instead of a full search. Then search as usual for what the notebook does not hold.

        Each record gives: topic and tags, book, author and death year, part/page with the Shamela ids, who is speaking
        (author / quoted / opponent / editor) and whom he quotes, a one-line gist in English, the Arabic words, and a
        "status" line with who checked it and when.

        READ THE STATUS. Records saved through findings_add were checked on the page by Claude. The 32 records seeded on
        19 Nov 2026 were judged on the real page by a model during tests, and their Arabic is the search index's cleaned
        text (no diacritics, cut at about 600 characters): open the page with the Shamela tools before quoting them.
        Nothing here has been checked by a person unless the status says so. An empty result means only that nothing was
        saved on this yet, never that the books are silent.

        Args (all optional, all given filters must match):
          arabic: Arabic words that must all occur in the saved passage (word forms as in nearby_words).
          topic: a topic or tag exactly as saved (call with list_topics=True to see them).
          book: a Shamela book id (digits) or part of a title in Arabic. author: part of the author's name in Arabic.
          list_topics: also return the topics and tags in the notebook with their counts. limit: 1-100 (default 20).
        """
        return _call("/findings/search", {"arabic": arabic, "topic": topic, "book": book, "author": author,
                                          "list_topics": bool(list_topics), "limit": max(1, min(int(limit), 100))}, timeout=30)

    @mcp.tool()
    def findings_add(topic: str, shamela_id: int, part: int, page: int, arabic: str, speaker: str, gist: str,
                     quotes: str = "", tags: list[str] | None = None, shamela_page_id: int | None = None,
                     footnote: bool = False) -> dict:
        """Save ONE verified passage in the notebook of findings, so later conversations do not have to find it again.

        RULES
        - Save only a passage you opened with the Shamela tools IN THIS CONVERSATION and whose wording you checked on that
          page (shamela_verify_quote, or reading the page). Never save from a search result alone.
        - arabic: the passage's own words as they stand on the page, enough to carry the point (one to five sentences).
        - speaker: whose voice it is: "author" (the book's author himself), "quoted" (an earlier scholar he reports
          without refuting), "opponent" (a view he reports in order to refute it) or "editor" (a modern editor).
          quotes: whom he is quoting, when he names him.
        - gist: one plain English sentence of what the passage says. topic: the matter in a few English words; reuse an
          existing topic when there is one (findings_search with list_topics=True).
        - Tell the user each time you save a finding.
        The same page under the same topic is never saved twice (the reply then says saved: false). The book's title,
        author and death year are filled in from the index. part or page -1 = Shamela has no such number for that book.
        footnote=True when the words stand in the editor's footnote.
        """
        if speaker not in ("author", "quoted", "opponent", "editor"): return {"error": 'speaker must be "author", "quoted", "opponent" or "editor"'}
        return _call("/findings/add", {"topic": topic, "shamela_id": shamela_id, "part": part, "page": page, "arabic": arabic, "speaker": speaker,
                                       "gist": gist, "quotes": quotes, "tags": tags or [], "shamela_page_id": shamela_page_id,
                                       "footnote": bool(footnote)}, timeout=30)


    @mcp.tool()
    def shamela_read_page(shamela_id: int, page_id: int | None = None, part: int | None = None, page: int | None = None,
                          context: int = 0, around: str | None = None, chars: int = 6000) -> dict:
        """Read a page of a Shamela book FROM THE SERVER'S OWN COPY (all 8,587 books; works when the owner's PC is off).

        Use it to open a search result and read the real page before quoting: the text has its diacritics and the
        modern editor's FOOTNOTES COME SEPARATELY ("footnotes"), never mixed into the author's words ("body").
        The copy is the public dataset the search index was built from; the Shamela connector on the PC reads the
        Shamela program itself. They should agree; when both are available and a quotation matters, compare.

        Args:
          shamela_id: the book (same ids as the Shamela tools and the search results).
          page_id: the Shamela page id ("shamela_page_id" in search results). Or give part and page (the printed
            volume and page; part -1 = no volume number). Several pages can carry one printed number: the reply says so.
          context: also return this many pages before and after (0-3). Read them before recording who is speaking:
            a commentary often names the speaker, or the view it refutes, a page earlier.
          around: Arabic words; when they stand on the page, only the stretch around them is returned.
          chars: most characters of body to return for a page (default 6000; the reply says when a page was cut).
        """
        return _call("/page", {"shamela_id": shamela_id, "page_id": page_id, "part": part, "page": page, "context": context,
                               "around": around, "chars": chars}, timeout=30)

    @mcp.tool()
    def shamela_check_quote(shamela_id: int, quote: str, page_id: int | None = None, part: int | None = None,
                            page: int | None = None) -> dict:
        """Check that Arabic words really stand in a Shamela book, on the server's own copy (no PC needed).

        Give the page (page_id, or part and page) to check that page and the one before and after; give no page to look
        through the whole book. Matching ignores diacritics, punctuation and hamza / ya / ta-marbuta spelling, but the
        words must stand in the same order with nothing between them. The reply gives "found", where (body, or the
        editor's footnotes), and "words_on_the_page": the stretch exactly as the book has it, which is what to quote.
        When not found it gives the longest run of the quote's words that does stand there, so a changed or missing word
        shows up. Leave out your own ellipses: check each unbroken piece on its own.
        """
        return _call("/quote", {"shamela_id": shamela_id, "quote": quote, "page_id": page_id, "part": part, "page": page}, timeout=60)

    @mcp.tool()
    def shamela_contents(shamela_id: int, query: str | None = None, limit: int = 60) -> dict:
        """The headings of a Shamela book (its table of contents) from the server's copy, each with the page where it
        starts. query: Arabic words that must all occur in the heading (parts of words count), to find where a book
        treats a matter; without it the first `limit` headings come back in reading order. "under" names the parent
        heading where the book records one."""
        return _call("/contents", {"shamela_id": shamela_id, "query": query, "limit": limit}, timeout=30)

    @mcp.tool()
    def kutub_read_page(book: str, page: int | None = None, volume: int | None = None, printed_page: int | None = None,
                        context: int = 0, around: str | None = None, chars: int = 6000) -> dict:
        """A page of a Kutub book: book = slug, page = a result's `page` (or volume + printed_page); context, around: as in shamela_read_page."""
        return _call("/kutub/page", {"book": book, "page": page, "volume": volume, "printed_page": printed_page, "context": context,
                                     "around": around, "chars": chars}, timeout=30)

    @mcp.tool()
    def check_quote(library: str, book: str, quote: str, page: int | None = None) -> dict:
        """shamela_check_quote for library "maktaba" (book = edition id) or "kutub" (book = slug); no page = the whole book."""
        lib = (library or "").lower()
        if lib not in ("maktaba", "kutub"): return {"error": 'library must be "maktaba" or "kutub" (for a Shamela book use shamela_check_quote)'}
        return _call("/mk/quote" if lib == "maktaba" else "/kutub/quote", {"book": book, "quote": quote, "page": page}, timeout=120)
