"""HTML → core blocks, with a report of everything that did not come through.

Content written elsewhere arrives as HTML; a page or an entry here is a list of
core blocks (ADR-027). `convert_html` is a pure function: a string in, blocks
and a loss report out. It writes nothing and reads only the block contracts,
so an import can call it for every document and a dry run costs nothing.

The blocks are valid input for the page and entry services as they are —
every one is checked against its schema before it is returned, and heading
anchors are unique. What the contracts cannot hold is never dropped in
silence: each difference between the input and the output is one `HtmlLoss`
(`docs/architecture/site-html-import.md` lists the kinds):

- `lost` — content is gone: an element removed with what it held, a link
  whose address the contract refuses (the words stay), an image with no media
  asset to point at;
- `changed` — everything is still there, said differently: an underline
  written as bold, an `h1` written as `h2`, merged table cells written out;
- `split` — one thing became several because of a limit: a text over 160
  nodes, a list over 40 items, a table over 120 rows.

Two counts close the report. Every text node of the input is either placed in
a block or named in a loss, and the characters read must equal the characters
written; a difference is itself reported (`text_dropped`, `text_mismatch`),
so a gap in this converter shows up as a loss rather than as missing words.

Decisions (plan PB2, 2026-10-07):

- A table is its own block, `core.table`; rich text is cut around it.
- `<u>` has no counterpart: rich text marks are bold, italic and a link, and
  an underline on the web reads as a link. What it meant is kept (rules set
  on a real corpus, plan PB2c, 2026-10-08). An underline on a part of a text
  is emphasis and becomes bold. A short paragraph underlined from end to end
  (`LABEL_MAX_LENGTH`) names what follows it and becomes a sub-heading one
  level under the heading it stands below.
- Words are never left out because of the markup around them. Words written
  in a list outside its items become an item, words in a table outside its
  cells a paragraph before the table, and an opening tag that lost its `>`
  and swallowed the words after it (`<b<Word:</b>`) is read as the tag it
  was. What cannot be read as words is named as lost.
- A run of `div.question_answer` becomes one `core.faq` when every answer is
  plain paragraphs within the block's limits. A group with a link, a list, a
  table or an image in an answer stays text (a heading and its paragraphs):
  an FAQ answer is a plain string, and words or an address would be lost.
- A link is kept as written when the contract accepts it (`/path`, `https://`,
  `mailto:`, `tel:`, `#anchor` of a heading in the same document). `http://`
  is written as `https://`. `rewrite_link` lets the caller map legacy
  addresses first; the converter never guesses a target.
- An image needs a media asset: `image_assets` maps `src` to an asset id the
  caller uploaded. `HtmlConversion.images` lists every `src` seen, so a first
  pass tells the import what to upload.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Final

from saas_core.content_protocol.transliteration import slug_from_title

from .block_contracts import site_block_contracts

LOST: Final = "lost"
CHANGED: Final = "changed"
SPLIT: Final = "split"
SEVERITIES: Final = (LOST, CHANGED, SPLIT)

# The versions whose shape this module writes; a test holds them against the
# manifest, so a new block version asks for a look here.
RICH_TEXT_VERSION: Final = 4
TABLE_VERSION: Final = 1
FAQ_VERSION: Final = 3
SEPARATOR_VERSION: Final = 1

# The contracts' limits (`packages/contracts/site-blocks`).
_MAX_NODES = 160
_MAX_RUNS = 64
_MAX_RUN_TEXT = 4000
_MAX_HEADING = 200
_MAX_LIST_ITEMS = 40
_MAX_SUBLIST_ITEMS = 20
_MAX_QUOTE_SOURCE = 200
_MAX_CAPTION = 300
_MAX_ALT = 200
_MAX_TABLE_ROWS = 120
_MAX_TABLE_COLUMNS = 12
_MAX_FAQ_ITEMS = 30
_MAX_FAQ_QUESTION = 200
_MAX_FAQ_ANSWER = 2000
_MAX_FAQ_TITLE = 120
_MAX_HREF = 500

# A paragraph underlined from end to end is a label for what follows — a
# sub-heading — when it is no longer than this. On the corpus the rule was set
# on (3,672 such paragraphs in five languages) the longest had 81 characters.
LABEL_MAX_LENGTH: Final = 100

_HREF = re.compile(r"^(?:/(?!/)|https://|mailto:|tel:)")
_ANCHOR = re.compile(r"[a-z][a-z0-9-]{0,63}")
# The class a source puts on a question with its answer, unless told otherwise.
FAQ_CLASS: Final = "question_answer"
_FAQ_PLACE = "question or answer"
_SAMPLE = 80


def _tags(names: str) -> frozenset[str]:
    return frozenset(names.split())


_VOID = _tags("area base br col embed hr img input link meta param source track wbr")
# Removed with everything inside: nothing a visitor reads as the text.
_REMOVED = _tags(
    "script style template noscript iframe object embed canvas video audio svg math "
    "form input button select textarea head title meta link map area"
)
_HEADINGS = _tags("h1 h2 h3 h4 h5 h6")
_LISTS = _tags("ul ol")
# Structure an inline place (a list item, a cell, a quote) cannot keep.
_STRUCTURES = _HEADINGS | _LISTS | _tags("table blockquote pre dl hr")
# Parts of a list or a table: they end with their neighbour, not with a <p>.
_PARTS = _tags("li dt dd thead tbody tfoot tr td th caption colgroup col figcaption summary")
_BLOCKS = (
    _STRUCTURES
    | _PARTS
    | _tags("p div section article main header footer aside nav figure address details")
    | _tags("fieldset center")
)
# An open <p> ends where one of these starts (HTML's optional end tag).
_ENDS_PARAGRAPH = _BLOCKS - _PARTS
_BOLD = _tags("b strong")
_ITALIC = _tags("i em")
_UNDERLINE = _tags("u ins")
_STRUCK = _tags("s del strike")
_CODE = _tags("code kbd samp var tt")
# Wrappers that say nothing by themselves; what their attributes said is reported.
_NEUTRAL = _tags("span font a")
# `rel` values the renderer writes itself where they matter.
_REL_PLUMBING = _tags("noopener noreferrer external")
_REL_KINDS = ("sponsored", "ugc", "nofollow")
# Places whose words keep their marks; a heading, a caption and an FAQ string
# are plain.
_MARKED = frozenset({"paragraph", "list item", "quote", "table cell"})
# Tags whose words a reader sees: what an opening tag that lost its `>` may be.
_WORDED = (
    _BLOCKS | _BOLD | _ITALIC | _UNDERLINE | _STRUCK | _CODE | _NEUTRAL | _tags("sup sub")
) - _VOID
# Every tag this module has a rule for.
_NAMED = _WORDED | _VOID | _REMOVED
# What is found where the lost `>` of an opening tag stood — or a `<`, when
# words come after it and not a tag (`<li<b>Word</b>` only lacks the `>`).
_MANGLED = "/.,;:-"
_TAG_FOLLOWS = re.compile(r"</|<[a-zA-Z][a-zA-Z0-9]*(?:[ \t\n\r\f]+[a-zA-Z-]+=|[ \t\n\r\f]*/?>)")
# A document cut off inside a tag: `…</li> </`, `…</p><p`.
_UNFINISHED = re.compile(r"<[/!?a-zA-Z][^<>]*\Z")
_TAG_BEGUN = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)?[ \t\n\r\f]*")
_TAG_RUN = re.compile(r"[a-z][a-z0-9]*|[A-Z][A-Z0-9]*")
_TAG_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
_TAG_CLOSED = re.compile(r"</([a-zA-Z][a-zA-Z0-9]*)[ \t\n\r\f]*>\Z")


@dataclass(frozen=True, slots=True)
class HtmlLoss:
    """One kind of difference in one document, with how often it happened."""

    severity: str
    kind: str
    detail: str
    count: int
    #: The first affected words or value, shortened: enough to find the place.
    sample: str


@dataclass(frozen=True, slots=True)
class HtmlConversion:
    #: `{"block_type", "schema_version", "data"}`, ready for a draft.
    blocks: list[dict[str, Any]]
    losses: tuple[HtmlLoss, ...]
    #: Every `<img src>` of the document, in order: what an import uploads first.
    images: tuple[str, ...]
    #: `characters_in`, `characters_out` (visible, without whitespace) and the
    #: number of blocks by type.
    stats: dict[str, Any]

    def count(self, severity: str) -> int:
        return sum(loss.count for loss in self.losses if loss.severity == severity)


class HtmlConversionError(ValueError):
    """The converter built a block its own contract refuses: a defect here,
    never a property of the document."""


class _Text:
    __slots__ = ("used", "value")

    def __init__(self, value: str) -> None:
        self.value = value
        # Placed in a block, or named in a loss.
        self.used = False


@dataclass(slots=True)
class _Element:
    tag: str
    attrs: dict[str, str]
    children: list[_Element | _Text] = field(default_factory=list)


def _reopened(raw: str) -> tuple[str, str] | None:
    """An opening tag that ran on into the next tag because its `>` is gone
    (`<b<Word:</b>`, `<b word</b>`, `<liWord …</li>`): the tag it was, and
    what it swallowed. None when no tag a reader sees starts it."""
    body = raw[1:]
    run = _TAG_RUN.match(body)
    word = _TAG_WORD.match(body)
    closed = _TAG_CLOSED.search(raw)
    name = None
    if run is not None and run.group().lower() in _WORDED:
        # `<b word`, `<liWord`: the name ends where the word begins.
        name = run.group().lower()
    elif word is not None:
        letters = word.group().lower()
        end = closed.group(1).lower() if closed is not None else ""
        if end in _WORDED and letters.startswith(end):
            # `<bword</b>`: the tag that closes it names it.
            name = end
        else:
            # `<liword <b>`: a guess, the shortest tag the letters begin with.
            starts = (letters[:size] for size in range(1, len(letters) + 1))
            name = next((start for start in starts if start in _WORDED), None)
    if name is None:
        return None
    rest = body[len(name) :]
    if rest[:1] == "<":
        return name, rest if _TAG_FOLLOWS.match(rest) else rest[1:]
    return name, rest[1:] if rest[:1] in _MANGLED else rest


def _only_begun(fragment: str) -> bool:
    """The end of a document cut off inside a tag is the beginning of that
    tag and no words: `</`, `<p`, `</stro`, `<a href="/x`. Anything else
    (`<pAnd the last words`) is an opening tag that lost its `>` before the
    cut, with words nothing can tell from attributes."""
    if fragment[1] in "!?" or "=" in fragment:
        return True
    begun = _TAG_BEGUN.fullmatch(fragment)
    if begun is None:
        return False
    name = (begun.group(1) or "").lower()
    return any(known.startswith(name) for known in _NAMED)


class _Tree(HTMLParser):
    """The document as a tree, with HTML's optional end tags closed where a
    browser closes them (`<p>`, `<li>`, table parts)."""

    def __init__(self, outer: _Tree | None = None) -> None:
        super().__init__(convert_charrefs=True)
        # A fragment read for another tree (`mend`) builds that tree.
        self.root: _Element = outer.root if outer else _Element("#document", {})
        self.stack: list[_Element] = outer.stack if outer else [self.root]
        self.stray: Counter[str] = outer.stray if outer else Counter()
        # Comments and declarations: nothing a reader saw.
        self.skipped: Counter[str] = outer.skipped if outer else Counter()
        # Opening tags read as the tag they were, with that tag's name.
        self.mended: list[tuple[str, str]] = outer.mended if outer else []
        # Opening tags that swallowed words nothing could read.
        self.unread: list[str] = outer.unread if outer else []
        # The beginning of a tag the document was cut off in.
        self.unfinished = ""

    def read(self, html: str) -> None:
        cut = _UNFINISHED.search(html)
        if cut is not None:
            html = html[: cut.start()]
            if _only_begun(cut.group()):
                self.unfinished = cut.group()
            else:
                self.unread.append(cut.group())
        self.feed(html)
        self.close()

    def mend(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        """An opening tag without its `>` runs on to the end of the next tag,
        and a browser shows none of the words in between: `<b<Word:</b>` is a
        tag named `b<word:<`. No tag or attribute is named with a `<`, so this
        is read as the tag it was, and the words after it as words. A tag
        with real attributes (`=`) that only runs into the next tag after them
        is left as a browser reads it: nothing in it is words."""
        raw = self.get_starttag_text() or ""
        if "<" not in tag and ("=" in raw or not any("<" in name for name, _value in attrs)):
            return False
        found = _reopened(raw)
        if found is None:
            self.unread.append(raw)
            return False
        name, rest = found
        self.mended.append((name, raw))
        self.open(name, {})
        inner = _Tree(self)
        inner.feed(rest)
        inner.close()
        return True

    def _close(self, tags: frozenset[str] | set[str], stop: frozenset[str] | set[str]) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[index].tag
            if tag in tags:
                del self.stack[index:]
                return
            if tag in stop:
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.mend(tag, attrs):
            self.open(tag, {name: value or "" for name, value in attrs})

    def open(self, tag: str, attrs: dict[str, str]) -> None:
        if tag in _ENDS_PARAGRAPH:
            self._close({"p"}, {"table", "td", "th", "caption", "button", "object"})
        if tag == "li":
            self._close({"li"}, {"ul", "ol"})
        elif tag in ("dt", "dd"):
            self._close({"dt", "dd"}, {"dl"})
        elif tag in ("td", "th"):
            self._close({"td", "th"}, {"tr", "table"})
        elif tag == "tr":
            self._close({"tr"}, {"table"})
        elif tag in ("thead", "tbody", "tfoot"):
            self._close({"thead", "tbody", "tfoot", "tr"}, {"table"})
        element = _Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.mend(tag, attrs):
            return
        self.open(tag, {name: value or "" for name, value in attrs})
        if tag not in _VOID:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return
        self.stray[tag] += 1

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(_Text(data))

    def handle_comment(self, data: str) -> None:
        self.skipped["comment"] += 1

    def handle_decl(self, decl: str) -> None:
        self.skipped["declaration"] += 1

    def handle_pi(self, data: str) -> None:
        self.skipped["declaration"] += 1

    def unknown_decl(self, data: str) -> None:
        # `<![CDATA[…]]>` in HTML is a bogus comment: a browser shows none of it.
        self.skipped["declaration"] += 1


@dataclass(frozen=True, slots=True)
class _Marks:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    href: str | None = None
    rel: str | None = None

    def run(self, text: str) -> dict[str, Any]:
        run: dict[str, Any] = {"text": text}
        if self.bold:
            run["bold"] = True
        if self.italic:
            run["italic"] = True
        if self.href is not None:
            run["href"] = self.href
            if self.rel is not None:
                run["rel"] = self.rel
        if self.underline:
            run["_u"] = True
        return run


_PLAIN = _Marks()
# In a list of runs: a line break, and the edge of a block written inline.
_BREAK: Final = "break"
_EDGE: Final = "edge"
_Piece = dict[str, Any] | str


def _collapse(text: str) -> str:
    """HTML whitespace collapses; a non-breaking space is content."""
    return re.sub(r"[ \t\n\r\f]+", " ", text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _short(text: str) -> str:
    text = _collapse(text).strip()
    return text if len(text) <= _SAMPLE else f"{text[: _SAMPLE - 1]}…"


def _classes(element: _Element) -> list[str]:
    return element.attrs.get("class", "").split()


def _texts(node: _Element | _Text) -> Iterator[_Text]:
    if isinstance(node, _Text):
        yield node
        return
    for child in node.children:
        yield from _texts(child)


def _plain(node: _Element | _Text) -> str:
    """The words under a node, read without touching anything."""

    def parts(item: _Element | _Text) -> Iterator[str]:
        if isinstance(item, _Text):
            yield item.value
            return
        edge = " " if item.tag in _BLOCKS or item.tag == "br" else ""
        yield edge
        for child in item.children:
            yield from parts(child)
        yield edge

    return _collapse("".join(parts(node))).strip()


def _descendants(element: _Element) -> Iterator[_Element]:
    for child in element.children:
        if isinstance(child, _Element):
            yield child
            yield from _descendants(child)


def _declarations(style: str) -> Iterator[tuple[str, dict[str, bool]]]:
    """Each `name: value` of an inline style, and the marks it asks for
    (none for a declaration that is about anything else)."""
    for declaration in style.split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().lower(), value.strip().lower()
        if not name:
            continue
        marks: dict[str, bool] = {}
        if name == "font-weight":
            marks["bold"] = value in ("bold", "bolder") or (value.isdigit() and int(value) >= 600)
        elif name == "font-style":
            marks["italic"] = value in ("italic", "oblique")
        elif name in ("text-decoration", "text-decoration-line") and "underline" in value:
            marks["underline"] = True
        yield f"{name}: {value}", marks


def _same_marks(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("bold", "italic", "href", "rel", "_u"))


def _text_of(runs: Iterable[dict[str, Any]]) -> str:
    return "".join(run["text"] for run in runs)


class _Converter:
    def __init__(
        self,
        *,
        image_assets: Mapping[str, str],
        default_image_alt: str,
        rewrite_link: Callable[[str], str] | None,
        taken_anchors: Iterable[str],
        faq_class: str | None,
    ) -> None:
        self.image_assets = image_assets
        self.default_image_alt = default_image_alt.strip()
        self.rewrite_link = rewrite_link
        self.faq_class = faq_class
        self.anchors = set(taken_anchors)
        self.own_anchors: set[str] = set()
        # A legacy `id` of a heading → the anchor it got.
        self.fragments: dict[str, str] = {}
        self.blocks: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        # The level of the heading the text stands under, once there is one.
        self.section: int | None = None
        # A label waiting for what it labels: its runs, words and level.
        self.held: tuple[list[dict[str, Any]], str, int] | None = None
        self.pending: list[_Piece] = []
        self.figures: list[dict[str, Any]] = []
        # Inside a paragraph a picture is inline: it follows the paragraph.
        self.in_paragraph = False
        # A figure's caption, waiting for the figure's picture.
        self.caption = ""
        self.images: list[str] = []
        self.losses: dict[tuple[str, str, str], list[Any]] = {}
        self.characters_in = 0
        self.inserted = 0

    # -- the report ---------------------------------------------------------

    def note(self, severity: str, kind: str, detail: str = "", sample: str = "") -> None:
        entry = self.losses.setdefault((severity, kind, detail), [0, _short(sample)])
        entry[0] += 1

    def attributes(
        self, element: _Element, consumed: Iterable[str] = (), *, styled: bool = False
    ) -> None:
        """Whatever an element said beside its words that nothing kept. With
        `styled` the caller reads the marks of its inline `style` (`styled`),
        and only the other declarations are named."""
        known = set(consumed)
        for name, value in element.attrs.items():
            if name in known:
                continue
            if name == "class":
                for item in value.split():
                    if item != self.faq_class:
                        self.note(CHANGED, "class_dropped", f"{element.tag}.{item}")
            elif name == "style":
                for declaration, _marks in _declarations(value):
                    if not (styled and _marks):
                        self.note(
                            CHANGED,
                            "style_dropped",
                            declaration.partition(":")[0],
                            f"{element.tag}: {declaration}",
                        )
            else:
                self.note(CHANGED, "attribute_dropped", f"{element.tag}[{name}]", value)

    def styled(self, element: _Element, marks: _Marks) -> _Marks:
        """The marks an inline `style` asks for, over the ones inherited."""
        bold, italic, underline = marks.bold, marks.italic, marks.underline
        for _declaration, asked in _declarations(element.attrs.get("style", "")):
            bold = asked.get("bold", bold)
            italic = asked.get("italic", italic)
            underline = asked.get("underline", underline)
        return _Marks(bold, italic, underline, marks.href, marks.rel)

    def drop(self, element: _Element) -> None:
        for text in _texts(element):
            text.used = True
        self.note(LOST, "tag_dropped", element.tag, _plain(element) or element.tag)

    # -- inline -------------------------------------------------------------

    def link(self, element: _Element, marks: _Marks) -> _Marks:
        raw = element.attrs.get("href")
        words = _plain(element)
        if raw is None:
            self.attributes(element, styled=True)
            return marks
        self.attributes(element, ("href", "rel", "target"), styled=True)
        if "target" in element.attrs:
            self.note(CHANGED, "link_target_dropped", element.attrs["target"], words)
        href = raw.strip()
        if self.rewrite_link is not None and href:
            href = self.rewrite_link(href).strip()
        if href.startswith("http://"):
            href = f"https://{href[7:]}"
            self.note(CHANGED, "link_upgraded_to_https", "", raw)
        elif href.startswith("//"):
            href = f"https:{href}"
            self.note(CHANGED, "link_upgraded_to_https", "", raw)
        reason = None
        if not href:
            reason = "empty address"
        elif len(href) > _MAX_HREF:
            reason = f"address over {_MAX_HREF} characters"
        elif href.startswith("#"):
            # Settled once every heading is known (`fragments`).
            pass
        elif not _HREF.match(href):
            scheme = re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", href)
            reason = f"scheme {scheme.group(0)}" if scheme else "relative address"
        if reason is None and not words:
            around = any(item.tag == "img" for item in _descendants(element))
            reason = "link around an image" if around else "link without words"
        if reason is not None:
            self.note(LOST, "link_dropped", reason, f"{words} → {raw}")
            return marks
        rel = None
        kinds = element.attrs.get("rel", "").lower().split()
        for kind in _REL_KINDS:
            if kind in kinds and rel is None and not href.startswith(("#", "/")):
                rel = kind
        for token in kinds:
            if token != rel and token not in _REL_PLUMBING:
                self.note(CHANGED, "link_rel_dropped", token, f"{words} → {raw}")
        return _Marks(marks.bold, marks.italic, marks.underline, href, rel)

    def marks_of(self, element: _Element, marks: _Marks) -> _Marks:
        tag = element.tag
        if tag == "a":
            return self.styled(element, self.link(element, marks))
        if tag in _BOLD:
            marks = _Marks(True, marks.italic, marks.underline, marks.href, marks.rel)
        elif tag in _ITALIC:
            marks = _Marks(marks.bold, True, marks.underline, marks.href, marks.rel)
        elif tag in _UNDERLINE:
            marks = _Marks(marks.bold, marks.italic, True, marks.href, marks.rel)
        elif tag in _STRUCK:
            self.note(CHANGED, "strikethrough_dropped", tag, _plain(element))
        elif tag in ("sup", "sub"):
            kind = "superscript_flattened" if tag == "sup" else "subscript_flattened"
            self.note(CHANGED, kind, "", _plain(element))
        elif tag in _CODE:
            self.note(CHANGED, "code_mark_dropped", tag, _plain(element))
        elif tag not in _NEUTRAL:
            self.note(CHANGED, "tag_unwrapped", tag, _plain(element))
        self.attributes(element, styled=True)
        return self.styled(element, marks)

    def inline(self, node: _Element | _Text, marks: _Marks, out: list[_Piece], where: str) -> None:
        if isinstance(node, _Text):
            node.used = True
            self.characters_in += len(_squash(node.value))
            text = _collapse(node.value)
            if text:
                out.append(marks.run(text))
            return
        tag = node.tag
        if tag in _REMOVED:
            self.drop(node)
            return
        if tag == "br":
            self.attributes(node)
            if where == "paragraph":
                out.append(_BREAK)
            else:
                out.append(marks.run(" "))
                self.note(CHANGED, "line_break_as_space", where)
            return
        if tag == "img":
            self.image(node, where)
            return
        if tag in _BLOCKS:
            if tag in _STRUCTURES:
                self.note(CHANGED, "blocks_flattened", f"{tag} in a {where}", _plain(node))
            self.attributes(node, styled=True)
            inner = self.styled(node, marks)
            out.append(_EDGE)
            for child in node.children:
                self.inline(child, inner, out, where)
            out.append(_EDGE)
            return
        nested = self.marks_of(node, marks)
        for child in node.children:
            self.inline(child, nested, out, where)

    def finish(self, pieces: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Runs ready to store: whitespace collapsed across run boundaries,
        trimmed at both ends, neighbours with the same marks merged, text over
        the limit cut into more runs. Nothing but whitespace comes back empty."""
        out: list[dict[str, Any]] = []
        space_before = True
        for run in pieces:
            text = run["text"].lstrip(" ") if space_before else run["text"]
            if not text:
                continue
            if out and _same_marks(out[-1], run):
                out[-1]["text"] += text
            else:
                out.append({**run, "text": text})
            space_before = text.endswith(" ")
        if out:
            out[-1]["text"] = out[-1]["text"].rstrip(" ")
            if not out[-1]["text"]:
                out.pop()
        if not _text_of(out).strip():
            return []
        cut: list[dict[str, Any]] = []
        for run in out:
            text = run["text"]
            for start in range(0, len(text), _MAX_RUN_TEXT):
                cut.append({**run, "text": text[start : start + _MAX_RUN_TEXT]})
        return cut

    def joined(self, pieces: list[_Piece], where: str) -> list[dict[str, Any]]:
        """One run of text for a place that holds one: blocks written inline
        are joined with a space, and joining more than one is named."""
        parts: list[list[dict[str, Any]]] = [[]]
        for piece in pieces:
            if isinstance(piece, str):
                parts.append([])
            else:
                parts[-1].append(piece)
        filled = [runs for runs in (self.finish(part) for part in parts) if runs]
        if len(filled) > 1:
            self.note(CHANGED, "blocks_joined", f"in a {where}", _text_of(filled[1]))
        runs: list[dict[str, Any]] = []
        for index, part in enumerate(filled):
            if index:
                runs.append({"text": " "})
            runs.extend(part)
        return self.fitted(self.finish(runs), where)

    def emphasis(self, runs: list[dict[str, Any]], where: str) -> None:
        """An underline marks what matters, and the mark rich text has for
        that is bold. On a link it is how a link looks, and on bold words it
        adds nothing: there it only goes."""
        marked = [run for run in runs if run.pop("_u", False)]
        fresh = [run for run in marked if not run.get("bold") and "href" not in run]
        for run in fresh:
            run["bold"] = True
        if fresh:
            self.note(CHANGED, "underline_as_bold", f"in a {where}", fresh[0]["text"])
        elif marked:
            on = "a link" if "href" in marked[0] else "bold words"
            self.note(CHANGED, "underline_dropped", f"on {on} in a {where}", marked[0]["text"])

    def fitted(self, runs: list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
        """Underlines settled, and no more runs than one inline place holds."""
        if where in _MARKED:
            self.emphasis(runs, where)
        else:
            underlined = [run for run in runs if run.pop("_u", False)]
            if underlined:
                self.note(CHANGED, "underline_dropped", f"in a {where}", underlined[0]["text"])
        runs = self.finish(runs)
        if len(runs) <= _MAX_RUNS:
            return runs
        tail = runs[_MAX_RUNS - 1 :]
        self.note(CHANGED, "marks_dropped_over_run_limit", f"in a {where}", _text_of(tail))
        for run in tail:
            if "href" in run:
                self.note(LOST, "link_dropped", "over the run limit", run["text"])
        return [*runs[: _MAX_RUNS - 1], *self.finish([{"text": _text_of(tail)}])]

    def gather(self, element: _Element, where: str, marks: _Marks = _PLAIN) -> list[_Piece]:
        out: list[_Piece] = []
        for child in element.children:
            self.inline(child, marks, out, where)
        return out

    # -- the text flow ------------------------------------------------------

    def add_node(self, node: dict[str, Any]) -> None:
        self.release(followed=True)
        self.nodes.append(node)

    def add_block(self, block_type: str, version: int, data: dict[str, Any]) -> None:
        self.release(followed=True)
        self.flush_nodes()
        self.blocks.append({"block_type": block_type, "schema_version": version, "data": data})

    def flush_nodes(self) -> None:
        nodes, self.nodes = self.nodes, []
        while nodes:
            cut = len(nodes)
            if cut > _MAX_NODES:
                cut = _MAX_NODES
                reason = "at the node limit"
                for level in (2, 3, 4):
                    found = [
                        index
                        for index in range(1, _MAX_NODES + 1)
                        if nodes[index]["type"] == "heading" and nodes[index]["level"] == level
                    ]
                    if found:
                        cut = found[-1]
                        reason = f"before an h{level}"
                        break
                first = nodes[cut]
                words = first.get("text") or _text_of(first.get("content") or [])
                self.note(SPLIT, "rich_text_split", reason, str(words))
            self.blocks.append({
                "block_type": "core.rich_text",
                "schema_version": RICH_TEXT_VERSION,
                "data": {"content": nodes[:cut]},
            })
            nodes = nodes[cut:]

    def flush_paragraph(self) -> None:
        pieces, self.pending = self.pending, []
        figures, self.figures = self.figures, []
        lines: list[list[dict[str, Any]]] = [[]]
        for piece in pieces:
            if isinstance(piece, str):
                lines.append([])
            else:
                lines[-1].append(piece)
        filled = [runs for runs in (self.finish(line) for line in lines) if runs]
        if len(filled) > 1 and _BREAK in pieces:
            self.note(CHANGED, "line_break_as_paragraph", "", _text_of(filled[1]))
        for runs in filled:
            self.paragraph(runs)
        if figures and filled:
            self.note(CHANGED, "image_moved_after_paragraph", "", _text_of(filled[0]))
        for figure in figures:
            self.add_node(figure)

    def paragraph(self, runs: list[dict[str, Any]]) -> None:
        if not runs:
            return
        text = _text_of(runs)
        if self.is_label(runs, text):
            self.release(followed=True)
            # One level under the heading it stands below; a text without a
            # heading of its own stands under its page's or section's `h2`.
            self.held = (runs, text, min((self.section or 2) + 1, 4))
            return
        self.written(runs, text)

    def is_label(self, runs: list[dict[str, Any]], text: str) -> bool:
        """A short paragraph underlined from end to end names what follows it:
        `<u>Tools:</u>`, `<b><u>2. Tyres</u></b>`. Punctuation may stand
        outside the underline (`<u>Tools</u>:`). A sentence with its full
        stop, a link or italics is a text of its own, however short."""
        return (
            len(text) <= LABEL_MAX_LENGTH
            and not text.endswith(".")
            and any(run.get("_u") for run in runs)
            and all(
                "href" not in run
                and not run.get("italic")
                and (run.get("_u") or not any(sign.isalnum() for sign in run["text"]))
                for run in runs
            )
        )

    def release(self, *, followed: bool) -> None:
        """A label waits for what it labels. With something after it, it is a
        sub-heading; as the last words of the document it labels nothing and
        is emphasis like any other underline."""
        held, self.held = self.held, None
        if held is None:
            return
        runs, text, level = held
        if not followed:
            self.written(runs, text)
            return
        self.note(CHANGED, "underline_as_heading", f"h{level}", text)
        if len({bool(run.get("bold")) for run in runs if run.get("_u")}) > 1:
            self.note(CHANGED, "heading_marks_dropped", "bold on a part", text)
        self.nodes.append({
            "type": "heading",
            "level": level,
            "anchor": self.anchor(text),
            "text": text,
        })

    def written(self, runs: list[dict[str, Any]], text: str) -> None:
        self.emphasis(runs, "paragraph")
        runs = self.finish(runs)
        if len(runs) > _MAX_RUNS:
            self.note(SPLIT, "paragraph_split", f"over {_MAX_RUNS} runs", text)
        for start in range(0, len(runs), _MAX_RUNS):
            content = self.finish(runs[start : start + _MAX_RUNS])
            if content:
                self.add_node({"type": "paragraph", "content": content})

    def anchor(self, text: str, legacy: str | None = None) -> str:
        if legacy and _ANCHOR.fullmatch(legacy) and legacy not in self.anchors:
            chosen = legacy
        else:
            slug = re.sub(r"^[^a-z]+", "", slug_from_title(text, max_length=80))
            base = slug[:56].rstrip("-") or "section"
            chosen, suffix = base, 2
            while chosen in self.anchors:
                chosen, suffix = f"{base}-{suffix}", suffix + 1
        self.anchors.add(chosen)
        self.own_anchors.add(chosen)
        if legacy:
            self.fragments.setdefault(legacy, chosen)
        return chosen

    def flow(self, children: list[_Element | _Text], marks: _Marks = _PLAIN) -> None:
        index = 0
        while index < len(children):
            child = children[index]
            index += 1
            if isinstance(child, _Text) or self.is_inline(child):
                self.inline(child, marks, self.pending, "paragraph")
                continue
            if child.tag in _REMOVED:
                self.drop(child)
                continue
            self.flush_paragraph()
            if child.tag == "div" and self.faq_class in _classes(child):
                group = [child]
                while index < len(children):
                    following = children[index]
                    if isinstance(following, _Text) and not following.value.strip():
                        following.used = True
                    elif (
                        isinstance(following, _Element)
                        and following.tag == "div"
                        and self.faq_class in _classes(following)
                    ):
                        group.append(following)
                    else:
                        break
                    index += 1
                self.faq(group, marks)
                continue
            self.block(child, marks)
            self.flush_paragraph()

    def is_inline(self, element: _Element) -> bool:
        blocks = _BLOCKS if self.in_paragraph else _BLOCKS | {"img"}
        if element.tag in blocks or element.tag in _REMOVED:
            return False
        return not any(item.tag in blocks for item in _descendants(element))

    def block(self, element: _Element, marks: _Marks) -> None:
        tag = element.tag
        if tag in _HEADINGS:
            self.heading(element, marks)
        elif tag in _LISTS:
            self.item_list(element, marks)
        elif tag == "blockquote":
            self.quote(element, marks)
        elif tag == "hr":
            self.attributes(element)
            self.add_block("core.separator", SEPARATOR_VERSION, {"layout": "line"})
        elif tag == "table":
            self.table(element)
        elif tag == "img":
            self.image(element, "flow")
        elif tag == "figure":
            self.figure(element, marks)
        elif tag == "pre":
            self.note(CHANGED, "preformatted_flattened", "", _plain(element))
            self.attributes(element)
            self.pending.extend(self.gather(element, "paragraph", marks))
        elif tag == "dl":
            self.note(CHANGED, "definition_list_flattened", "", _plain(element))
            self.attributes(element)
            self.flow(element.children, marks)
        elif tag == "dt":
            self.attributes(element, styled=True)
            bold = _Marks(True, marks.italic, marks.underline, marks.href, marks.rel)
            self.flow(element.children, self.styled(element, bold))
        elif tag in _BLOCKS:
            # A paragraph, or a container whose blocks stand on their own.
            if tag not in ("p", "div", "section", "article", "main", "dd"):
                self.note(CHANGED, "tag_unwrapped", tag, _plain(element))
            elif (
                tag == "p"
                and not _plain(element)
                and not any(item.tag == "img" for item in _descendants(element))
            ):
                # A spacer: an empty paragraph, or one holding only `&nbsp;`.
                self.note(CHANGED, "empty_block_dropped", "p")
            self.attributes(element, styled=True)
            outer, self.in_paragraph = self.in_paragraph, self.in_paragraph or tag == "p"
            self.flow(element.children, self.styled(element, marks))
            self.flush_paragraph()
            self.in_paragraph = outer
        else:
            # An inline wrapper around blocks: its mark reaches all of them.
            self.flow(element.children, self.marks_of(element, marks))

    # -- blocks of the text -------------------------------------------------

    def heading(self, element: _Element, marks: _Marks) -> None:
        level = int(element.tag[1])
        target = 2 if level <= 2 else 3 if level == 3 else 4
        self.attributes(element, ("id",), styled=True)
        runs = self.joined(self.gather(element, "heading", self.styled(element, marks)), "heading")
        text = _text_of(runs)
        if not text:
            self.note(CHANGED, "empty_block_dropped", element.tag)
            return
        for run in runs:
            if "href" in run:
                # A heading holds no link. Where it pointed is said in full,
                # so whoever imports the text can decide what to do with it.
                self.note(LOST, "heading_link_dropped", run["href"], text)
        if any(run.get("italic") for run in runs):
            self.note(CHANGED, "heading_marks_dropped", "italic", text)
        if len({bool(run.get("bold")) for run in runs}) > 1:
            self.note(CHANGED, "heading_marks_dropped", "bold on a part", text)
        if level != target:
            self.note(CHANGED, "heading_level_changed", f"h{level} → h{target}", text)
        if len(text) > _MAX_HEADING:
            self.note(CHANGED, "heading_too_long", f"over {_MAX_HEADING} characters", text)
            self.add_node({
                "type": "paragraph",
                "content": self.finish([{"text": text, "bold": True}]),
            })
            return
        anchor = self.anchor(text, element.attrs.get("id") or None)
        self.add_node({"type": "heading", "level": target, "anchor": anchor, "text": text})
        self.section = target

    def item(self, element: _Element, marks: _Marks) -> tuple[list[dict[str, Any]], list[_Element]]:
        """A list item's own words, and the lists nested in it."""
        self.attributes(element, styled=True)
        inner = self.styled(element, marks)
        out: list[_Piece] = []
        nested: list[_Element] = []
        for child in element.children:
            if isinstance(child, _Element) and child.tag in _LISTS:
                nested.append(child)
            else:
                self.inline(child, inner, out, "list item")
        return self.joined(out, "list item"), nested

    def parts(self, element: _Element) -> Iterator[_Element]:
        """A list's items and sub-lists, in order. A list holds nothing else,
        so what is written between them comes as an item of its own, one for
        each run of it: words after a `</li>` that came too early, or an
        element that is not an item."""
        loose: list[_Element | _Text] = []

        def gathered() -> Iterator[_Element]:
            said = [node for node in loose if isinstance(node, _Element) or node.value.strip()]
            loose.clear()
            if len(said) == 1 and isinstance(said[0], _Element):
                # One element in an item's place is read as the item.
                self.note(CHANGED, "tag_unwrapped", f"{said[0].tag} in a list", _plain(said[0]))
                yield said[0]
                return
            wrapper = _Element("li", {}, said)
            words = _plain(wrapper)
            if words or any(item.tag == "img" for item in _descendants(wrapper)):
                self.note(CHANGED, "list_text_as_item", f"inside <{element.tag}>", words)
                yield wrapper

        for child in element.children:
            if isinstance(child, _Element) and (child.tag == "li" or child.tag in _LISTS):
                yield from gathered()
                yield child
            else:
                loose.append(child)
        yield from gathered()

    def flat_items(
        self, element: _Element, marks: _Marks, depth: int
    ) -> list[list[dict[str, Any]]]:
        """Every item of a nested list, any depth, as one level."""
        self.attributes(element)
        if depth > 2:
            self.note(CHANGED, "list_nesting_flattened", f"level {depth}", _plain(element))
        found: list[list[dict[str, Any]]] = []
        for child in self.parts(element):
            if child.tag in _LISTS:
                found.extend(self.flat_items(child, marks, depth + 1))
                continue
            content, nested = self.item(child, marks)
            if content:
                found.append(content)
            for deeper in nested:
                found.extend(self.flat_items(deeper, marks, depth + 1))
        return found

    def item_list(self, element: _Element, marks: _Marks) -> None:
        style = "ordered" if element.tag == "ol" else "bullet"
        for name in ("start", "reversed", "type"):
            if name in element.attrs and style == "ordered":
                self.note(CHANGED, "list_numbering_dropped", f"ol[{name}]", element.attrs[name])
        self.attributes(element, ("start", "reversed", "type") if style == "ordered" else ())
        items: list[dict[str, Any]] = []

        def nest(nested: list[_Element]) -> None:
            children = [
                {"content": content}
                for deeper in nested
                for content in self.flat_items(deeper, marks, 2)
            ]
            if not children:
                return
            if len(nested) > 1:
                self.note(CHANGED, "sublists_merged", "", _plain(nested[1]))
            if not items:
                items.extend(children)
                return
            parent = items[-1]
            kept = parent.setdefault(
                "children",
                {
                    "style": "ordered" if nested[0].tag == "ol" else "bullet",
                    "items": [],
                },
            )
            room = _MAX_SUBLIST_ITEMS - len(kept["items"])
            kept["items"].extend(children[:room])
            if len(children) > room:
                self.note(
                    CHANGED,
                    "sublist_overflow_promoted",
                    f"over {_MAX_SUBLIST_ITEMS} items",
                    _text_of(children[room]["content"]),
                )
                items.extend(children[room:])
            if not kept["items"]:
                del parent["children"]

        for child in self.parts(element):
            if child.tag in _LISTS:
                # A sub-list written beside the items, not inside one.
                nest([child])
                continue
            content, nested = self.item(child, marks)
            if not content and not nested:
                self.note(CHANGED, "empty_block_dropped", "li")
                continue
            if not content:
                # An item that only holds a sub-list still needs words.
                self.note(CHANGED, "list_item_without_text", "", _plain(child))
                self.inserted += 1
                content = [{"text": "–"}]
            items.append({"content": content})
            nest(nested)
        if not items:
            self.note(CHANGED, "empty_block_dropped", element.tag)
            return
        if len(items) > _MAX_LIST_ITEMS:
            self.note(
                SPLIT,
                "list_split",
                f"{style}, {len(items)} items",
                _text_of(items[_MAX_LIST_ITEMS]["content"]),
            )
        for start in range(0, len(items), _MAX_LIST_ITEMS):
            self.add_node({
                "type": "list",
                "style": style,
                "items": items[start : start + _MAX_LIST_ITEMS],
            })

    def quote(self, element: _Element, marks: _Marks) -> None:
        self.attributes(element, styled=True)
        inner = self.styled(element, marks)
        source = None
        out: list[_Piece] = []
        for child in element.children:
            words = "" if isinstance(child, _Text) else _plain(child)
            if (
                isinstance(child, _Element)
                and child.tag in ("cite", "footer")
                and source is None
                and 0 < len(words) <= _MAX_QUOTE_SOURCE
                and not any(item.tag == "a" for item in _descendants(child))
            ):
                # Who said it, or where: the quote's own field.
                self.attributes(child)
                for item in _descendants(child):
                    self.attributes(item)
                    self.note(CHANGED, "quote_source_marks_dropped", item.tag, words)
                for text in _texts(child):
                    text.used = True
                    self.characters_in += len(_squash(text.value))
                source = words
            else:
                self.inline(child, inner, out, "quote")
        content = self.joined(out, "quote")
        if not content:
            if source:
                self.add_node({"type": "paragraph", "content": self.finish([{"text": source}])})
            else:
                self.note(CHANGED, "empty_block_dropped", "blockquote")
            return
        node: dict[str, Any] = {"type": "quote", "content": content}
        if source:
            node["source"] = source
        self.add_node(node)

    def image(self, element: _Element, where: str) -> None:
        caption = ""
        if where in ("flow", "paragraph"):
            caption, self.caption = self.caption, ""
        src = element.attrs.get("src", "").strip()
        if src:
            self.images.append(src)
        self.attributes(element, ("src", "alt", "title"))
        alt = (
            element.attrs.get("alt", "").strip()
            or element.attrs.get("title", "").strip()
            or self.default_image_alt
        )
        asset = self.image_assets.get(src)
        reason = None
        if where not in ("flow", "paragraph"):
            reason = f"in a {where}"
        elif asset is None:
            reason = "no media asset given"
        elif not alt:
            reason = "no alternative text"
        if reason is not None:
            self.note(LOST, "image_dropped", reason, src or "img")
            if caption:
                # The picture is gone; its caption is still words to keep.
                self.add_node({"type": "paragraph", "content": self.finish([{"text": caption}])})
            return
        if len(alt) > _MAX_ALT:
            self.note(CHANGED, "image_alt_shortened", "", alt)
            alt = alt[:_MAX_ALT].rstrip()
        node: dict[str, Any] = {"type": "figure", "image": {"asset_id": asset, "alt": alt}}
        if caption:
            node["caption"] = caption
        if where == "paragraph":
            self.figures.append(node)
        else:
            self.add_node(node)

    def figure(self, element: _Element, marks: _Marks) -> None:
        self.attributes(element)
        pictures = [item for item in _descendants(element) if item.tag == "img"]
        captions = [
            item
            for item in element.children
            if isinstance(item, _Element) and item.tag == "figcaption"
        ]
        if (
            len(pictures) != 1
            or len(captions) != 1
            or len(_plain(captions[0])) > _MAX_CAPTION
            or any(item.tag == "a" for item in _descendants(captions[0]))
        ):
            # Not one picture with a plain caption that fits: the parts stand
            # on their own, the caption as a paragraph.
            self.flow(element.children, marks)
            return
        caption = captions[0]
        self.attributes(caption)
        runs = self.joined(self.gather(caption, "figure caption"), "figure caption")
        if any(run.keys() - {"text"} for run in runs):
            self.note(CHANGED, "caption_marks_dropped", "figure", _text_of(runs))
        # The picture takes it when it is written (`image`).
        self.caption = _text_of(runs)
        self.flow([child for child in element.children if child is not caption], marks)
        if self.caption:
            # The picture stood where a figure cannot (a cell, a list item).
            self.flush_paragraph()
            words, self.caption = self.caption, ""
            self.add_node({"type": "paragraph", "content": self.finish([{"text": words}])})

    # -- a table ------------------------------------------------------------

    def table(self, element: _Element) -> None:
        self.attributes(element)
        caption: list[dict[str, Any]] = []
        sections: dict[str, list[_Element]] = {"thead": [], "tbody": [], "tfoot": []}
        # What stands where a table has no cell: runs of it, each with the
        # element it stands in.
        loose: list[tuple[_Element, list[_Element | _Text]]] = []

        def outside(node: _Element | _Text, parent: _Element) -> None:
            if isinstance(node, _Text) and not node.value.strip():
                return
            if loose and loose[-1][0] is parent:
                loose[-1][1].append(node)
            else:
                loose.append((parent, [node]))

        def row_of(row: _Element, section: str) -> None:
            sections[section].append(row)
            for item in row.children:
                if not (isinstance(item, _Element) and item.tag in ("td", "th")):
                    outside(item, row)

        for child in element.children:
            if isinstance(child, _Text):
                outside(child, element)
                continue
            if child.tag == "caption":
                self.attributes(child)
                caption = self.joined(self.gather(child, "table caption"), "table caption")
            elif child.tag in ("colgroup", "col"):
                self.note(CHANGED, "table_column_widths_dropped", child.tag)
            elif child.tag in sections:
                self.attributes(child)
                for row in child.children:
                    if isinstance(row, _Element) and row.tag == "tr":
                        row_of(row, child.tag)
                    else:
                        outside(row, child)
            elif child.tag == "tr":
                row_of(child, "tbody")
            else:
                outside(child, element)
        head, foot = sections["thead"], sections["tfoot"]
        if foot:
            self.note(CHANGED, "table_footer_as_rows", "", _plain(foot[0]))
        if len(head) > 1:
            self.note(CHANGED, "table_extra_header_rows", f"{len(head) - 1}", _plain(head[1]))

        # The grid: merged cells written out, the words in the first of them.
        grid: list[list[dict[str, Any]]] = []
        headers: list[list[bool]] = []
        # Columns a cell from a row above still reaches into, and for how long.
        carried: dict[int, int] = {}
        for row in [*head, *sections["tbody"], *foot]:
            self.attributes(row)
            cells: list[dict[str, Any]] = []
            flags: list[bool] = []
            # The row's cells, then once more for the columns still carried.
            written: list[_Element | None] = [
                item
                for item in row.children
                if isinstance(item, _Element) and item.tag in ("td", "th")
            ]
            for entry in [*written, None]:
                while carried.get(len(cells), 0) > 0:
                    carried[len(cells)] -= 1
                    cells.append({})
                    flags.append(False)
                if entry is None:
                    break
                self.attributes(entry, ("colspan", "rowspan", "scope", "headers"), styled=True)
                content = self.joined(
                    self.gather(entry, "table cell", self.styled(entry, _PLAIN)), "table cell"
                )
                wide = _span(entry.attrs.get("colspan"))
                tall = _span(entry.attrs.get("rowspan"))
                if wide > 1 or tall > 1:
                    self.note(
                        CHANGED, "table_span_flattened", f"{wide}×{tall} cells", _text_of(content)
                    )
                for offset in range(wide):
                    if tall > 1:
                        carried[len(cells)] = tall - 1
                    cells.append({"content": content} if content and offset == 0 else {})
                    flags.append(entry.tag == "th" and offset == 0)
            if cells:
                grid.append(cells)
                headers.append(flags)
            else:
                self.note(CHANGED, "empty_block_dropped", "tr")

        # A browser shows what a table has no cell for in front of the table.
        for parent, strays in loose:
            words = _plain(_Element(parent.tag, {}, strays))
            if words:
                self.note(CHANGED, "table_text_as_paragraph", f"inside <{parent.tag}>", words)
            self.flow(strays)
            self.flush_paragraph()

        caption_text = _text_of(caption)
        if any(run.keys() - {"text"} for run in caption):
            self.note(CHANGED, "caption_marks_dropped", "table", caption_text)
            for run in caption:
                if "href" in run:
                    self.note(
                        LOST, "link_dropped", "in a table caption", f"{run['text']} → {run['href']}"
                    )
        if not grid:
            if caption_text:
                self.add_node({
                    "type": "paragraph",
                    "content": self.finish([{"text": caption_text}]),
                })
            else:
                self.note(CHANGED, "empty_block_dropped", "table")
            return
        width = max(len(cells) for cells in grid)
        for cells, flags in zip(grid, headers, strict=True):
            cells.extend({} for _ in range(width - len(cells)))
            flags.extend(False for _ in range(width - len(flags)))

        def names(index: int) -> bool:
            """Every cell of the row that says something is a header cell."""
            said = [flag for flag, cell in zip(headers[index], grid[index], strict=True) if cell]
            return bool(said) and all(said)

        header_row = bool(head) or (
            len(grid) > 1 and names(0) and not any(names(index) for index in range(1, len(grid)))
        )
        first_body = 1 if header_row else 0
        header_column = (
            width > 1 and len(grid) > first_body and all(flags[0] for flags in headers[first_body:])
        )
        # A header cell where the block has none: below the first row of the
        # head, or outside the first column.
        stray = sum(
            flag
            for flags in headers[max(first_body, len(head)) :]
            for column, flag in enumerate(flags)
            if not (header_column and column == 0)
        )
        if stray:
            self.note(CHANGED, "table_header_cell_as_data", "", f"{stray} cells")

        if caption_text and (len(caption_text) > _MAX_CAPTION or width > _MAX_TABLE_COLUMNS):
            if len(caption_text) > _MAX_CAPTION:
                self.note(
                    CHANGED,
                    "table_caption_as_paragraph",
                    f"over {_MAX_CAPTION} characters",
                    caption_text,
                )
            self.add_node({"type": "paragraph", "content": self.finish([{"text": caption_text}])})
            caption_text = ""
        if width > _MAX_TABLE_COLUMNS:
            # Wider than a table block holds: each row as a line of text.
            self.note(CHANGED, "table_too_wide", f"{width} columns", _plain(element))
            for index, cells in enumerate(grid):
                runs: list[dict[str, Any]] = []
                for cell in cells:
                    if "content" not in cell:
                        continue
                    if runs:
                        runs.append({"text": " – "})
                        self.inserted += 1
                    runs.extend(cell["content"])
                if header_row and index == 0:
                    runs = [{**run, "bold": True} for run in runs]
                self.paragraph(self.finish(runs))
            return

        header = (
            "both"
            if header_row and header_column
            else "row"
            if header_row
            else "column"
            if header_column
            else "none"
        )
        rows = [{"cells": cells} for cells in grid]
        lead = rows[:1] if header_row else []
        rest = rows[len(lead) :]
        step = _MAX_TABLE_ROWS - len(lead)
        parts = [rest[start : start + step] for start in range(0, len(rest), step)] or [[]]
        if len(parts) > 1:
            self.note(SPLIT, "table_split", f"{len(rows)} rows", caption_text or _plain(element))
            # The caption and the header row are written again above each part.
            self.inserted += (len(parts) - 1) * len(_squash(caption_text + _cells_text(lead)))
        for part in parts:
            data: dict[str, Any] = {"header": header, "rows": [*lead, *part]}
            if caption_text:
                data = {"caption": caption_text, **data}
            self.add_block("core.table", TABLE_VERSION, data)

    # -- questions and answers ----------------------------------------------

    def faq_misfit(self, group: list[_Element]) -> str | None:
        """Why a group cannot be an FAQ block without losing something."""
        for element in group:
            parts = [
                child
                for child in element.children
                if isinstance(child, _Element) or child.value.strip()
            ]
            if not parts or not isinstance(parts[0], _Element) or parts[0].tag not in _HEADINGS:
                return "no question heading"
            question = _plain(parts[0])
            answer = "\n\n".join(words for words in map(_plain, parts[1:]) if words)
            if not question or not answer:
                return "an empty question or answer"
            if len(question) > _MAX_FAQ_QUESTION:
                return f"a question over {_MAX_FAQ_QUESTION} characters"
            if len(answer) > _MAX_FAQ_ANSWER:
                return f"an answer over {_MAX_FAQ_ANSWER} characters"
            for index, part in enumerate(parts):
                place = "an answer" if index else "a question"
                for item in [part, *_descendants(part)] if isinstance(part, _Element) else []:
                    if item.tag == "a" and "href" in item.attrs:
                        return f"a link in {place}"
                    if item is not parts[0] and (
                        item.tag in _STRUCTURES
                        or item.tag in _REMOVED
                        or item.tag in ("img", "figure", "br")
                    ):
                        return f"<{item.tag}> in {place}"
        return None

    def faq(self, group: list[_Element], marks: _Marks) -> None:
        reason = self.faq_misfit(group)
        if reason is not None or marks.href is not None:
            self.note(CHANGED, "faq_kept_as_text", reason or "inside a link", _plain(group[0]))
            for element in group:
                self.attributes(element)
                self.flow(element.children, marks)
                self.flush_paragraph()
            return
        self.release(followed=True)
        items: list[dict[str, str]] = []
        for element in group:
            self.attributes(element)
            question = ""
            answers: list[str] = []
            for child in element.children:
                if isinstance(child, _Text) and not child.value.strip():
                    child.used = True
                    continue
                if isinstance(child, _Element):
                    self.attributes(child, styled=True)
                    pieces = self.gather(child, _FAQ_PLACE, self.styled(child, _PLAIN))
                else:
                    pieces = []
                    self.inline(child, _PLAIN, pieces, _FAQ_PLACE)
                runs = self.joined(pieces, _FAQ_PLACE)
                words = _text_of(runs)
                if not question:
                    question = words
                    continue
                if not words:
                    continue
                if any(run.get("bold") or run.get("italic") for run in runs):
                    self.note(CHANGED, "faq_marks_dropped", "", words)
                answers.append(words)
            if len(answers) > 1:
                self.note(CHANGED, "faq_paragraphs_joined", "", answers[1])
            items.append({"question": question, "answer": "\n\n".join(answers)})
        title = None
        last = self.nodes[-1] if self.nodes else None
        if (
            last is not None
            and last["type"] == "heading"
            and last["level"] == 2
            and len(last["text"]) <= _MAX_FAQ_TITLE
        ):
            # The heading right above the questions is the block's own title.
            self.nodes.pop()
            self.anchors.discard(last["anchor"])
            self.own_anchors.discard(last["anchor"])
            title = last["text"]
            self.note(CHANGED, "faq_heading_as_title", "", title)
        if len(items) > _MAX_FAQ_ITEMS:
            self.note(
                SPLIT, "faq_split", f"{len(items)} questions", items[_MAX_FAQ_ITEMS]["question"]
            )
        for start in range(0, len(items), _MAX_FAQ_ITEMS):
            data: dict[str, Any] = {"items": items[start : start + _MAX_FAQ_ITEMS]}
            if title and start == 0:
                data = {"title": title, **data}
            self.add_block("core.faq", FAQ_VERSION, data)

    # -- the end ------------------------------------------------------------

    def settle_fragments(self) -> None:
        """`#…` links point at a heading of this document, or go."""

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                href = value.get("href")
                if isinstance(href, str) and href.startswith("#"):
                    target = self.fragments.get(href[1:], href[1:])
                    if target not in self.own_anchors:
                        self.note(
                            LOST,
                            "link_dropped",
                            "fragment without a heading",
                            f"{value.get('text', '')} → {href}",
                        )
                        del value["href"]
                        value.pop("rel", None)
                    else:
                        value["href"] = f"#{target}"
                for item in value.values():
                    visit(item)

        for block in self.blocks:
            visit(block["data"])

    def result(self, tree: _Tree) -> HtmlConversion:
        self.flush_paragraph()
        self.release(followed=False)
        self.flush_nodes()
        self.settle_fragments()
        for tag, count in sorted(tree.stray.items()):
            for _ in range(count):
                self.note(CHANGED, "stray_end_tag", tag)
        for _ in range(tree.skipped["comment"]):
            self.note(CHANGED, "comment_dropped")
        for _ in range(tree.skipped["declaration"]):
            self.note(CHANGED, "declaration_dropped")
        for name, raw in tree.mended:
            self.note(CHANGED, "opening_tag_repaired", name, raw)
        for raw in tree.unread:
            self.note(LOST, "text_dropped", "inside a broken tag", raw)
        if tree.unfinished:
            self.note(CHANGED, "unfinished_tag_dropped", "", tree.unfinished)
        self.unplaced(tree.root)
        characters_out = len(_squash("".join(_written(self.blocks))))
        if self.characters_in + self.inserted != characters_out:
            self.note(
                LOST,
                "text_mismatch",
                "",
                f"{self.characters_in} characters read, {characters_out - self.inserted} written",
            )
        validators = site_block_contracts().validators
        for position, block in enumerate(self.blocks):
            validator = validators[block["block_type"]][block["schema_version"]]
            error = next(validator.iter_errors(block["data"]), None)
            if error is not None:
                raise HtmlConversionError(
                    f"blocks[{position}] {block['block_type']}: {error.json_path}: {error.message}"
                )
        order = {severity: index for index, severity in enumerate(SEVERITIES)}
        losses = tuple(
            HtmlLoss(severity, kind, detail, count, sample)
            for (severity, kind, detail), (count, sample) in sorted(
                self.losses.items(),
                key=lambda entry: (order[entry[0][0]], entry[0][1], entry[0][2]),
            )
        )
        return HtmlConversion(
            blocks=self.blocks,
            losses=losses,
            images=tuple(self.images),
            stats={
                "characters_in": self.characters_in,
                "characters_out": characters_out - self.inserted,
                "blocks": dict(Counter(block["block_type"] for block in self.blocks)),
            },
        )

    def unplaced(self, element: _Element) -> None:
        """Words no block took and no loss named: said here, never silently."""
        for child in element.children:
            if isinstance(child, _Element):
                self.unplaced(child)
            elif not child.used and child.value.strip():
                child.used = True
                self.note(LOST, "text_dropped", f"inside <{element.tag}>", child.value)


def _span(value: str | None) -> int:
    return max(1, min(int(value), 1000)) if value and value.strip().isdigit() else 1


def _cells_text(rows: list[dict[str, Any]]) -> str:
    return "".join(_text_of(cell.get("content", [])) for row in rows for cell in row["cells"])


def _written(blocks: list[dict[str, Any]]) -> Iterator[str]:
    """Every word the blocks hold that came from a text node of the input."""
    for block in blocks:
        data = block["data"]
        if block["block_type"] == "core.rich_text":
            for node in data["content"]:
                yield node.get("text", "")
                yield node.get("source", "")
                yield node.get("caption", "")
                yield _text_of(node.get("content", []))
                for item in node.get("items", []):
                    yield _text_of(item["content"])
                    for child in item.get("children", {}).get("items", []):
                        yield _text_of(child["content"])
        elif block["block_type"] == "core.table":
            yield data.get("caption", "")
            yield _cells_text(data["rows"])
        elif block["block_type"] == "core.faq":
            yield data.get("title", "")
            for item in data["items"]:
                yield item["question"]
                yield item["answer"]


def convert_html(
    html: str,
    *,
    image_assets: Mapping[str, str] | None = None,
    default_image_alt: str = "",
    rewrite_link: Callable[[str], str] | None = None,
    taken_anchors: Iterable[str] = (),
    faq_class: str | None = FAQ_CLASS,
) -> HtmlConversion:
    """The document as core blocks, and what the move cost (module docstring).

    `image_assets` maps an `<img src>` to the id of a media asset; an image
    without one is reported, as is one with no `alt` when `default_image_alt`
    is empty. `rewrite_link` is given every `href` before it is judged.
    `taken_anchors` are anchors the page already uses elsewhere. `faq_class`
    is the class of a `div` holding one question and its answer; None turns
    the FAQ reading off.
    """
    tree = _Tree()
    tree.read(html)
    converter = _Converter(
        image_assets=image_assets or {},
        default_image_alt=default_image_alt,
        rewrite_link=rewrite_link,
        taken_anchors=taken_anchors,
        faq_class=faq_class,
    )
    converter.flow(tree.root.children)
    return converter.result(tree)


def format_report(conversion: HtmlConversion) -> str:
    """The loss report as lines of text, for a person reading a dry run."""
    blocks = ", ".join(
        f"{block_type} ×{count}" for block_type, count in conversion.stats["blocks"].items()
    )
    lines = [
        f"blocks: {blocks or 'none'}",
        f"text: {conversion.stats['characters_in']} characters read, "
        f"{conversion.stats['characters_out']} written",
        f"images: {len(conversion.images)}",
        "losses: "
        + ", ".join(f"{conversion.count(severity)} {severity}" for severity in SEVERITIES),
    ]
    for loss in conversion.losses:
        detail = f" ({loss.detail})" if loss.detail else ""
        sample = f" — „{loss.sample}”" if loss.sample else ""
        lines.append(f"  {loss.severity:8}{loss.kind}{detail} ×{loss.count}{sample}")
    return "\n".join(lines)
