from __future__ import annotations

from getmeajob.textutil import (
    html_to_text,
    norm_label,
    options_hash,
    short_hash,
    slugify,
    strip_invisible,
    truncate,
)


def test_html_to_text_double_escaped_and_lists() -> None:
    escaped = (
        "&lt;p&gt;We use &lt;strong&gt;Python&lt;/strong&gt;&amp;nbsp;daily.&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;Postgres&lt;/li&gt;&lt;li&gt;Kubernetes &amp;amp; AWS&lt;/li&gt;"
        "&lt;/ul&gt;&lt;script&gt;track()&lt;/script&gt;"
    )
    text = html_to_text(escaped)
    assert text == "We use Python daily.\n\n- Postgres\n- Kubernetes & AWS"
    plain = html_to_text("<div>Line one<br>Line   two</div><p>Next para​</p>")
    assert plain == "Line one\nLine two\n\nNext para"
    assert html_to_text("<p>" + "word " * 50 + "</p>", max_chars=20).endswith("…")
    assert html_to_text("") == ""


def test_norm_label_variants() -> None:
    expected = "first name"
    for label in ("First Name*", "first name (required)", "First  name:", "<b>First Name</b> ✱"):
        assert norm_label(label) == expected, label
    assert norm_label("Are you authorized?") == "are you authorized"
    assert norm_label("Ｆｉｒｓｔ name (optional)") == expected  # full-width letters (NFKC)


def test_strip_invisible() -> None:
    assert strip_invisible("Py​thon‍﻿ ‮ok⁩­") == "Python ok"
    assert strip_invisible("plain") == "plain"


def test_slugify_truncate_hashes() -> None:
    assert slugify("Senior Backend Engineer, Payments!") == "senior-backend-engineer-payments"
    assert slugify("Café Déjà Vu") == "cafe-deja-vu"
    assert slugify("") == "untitled"
    assert len(slugify("x" * 100, max_len=10)) == 10
    assert truncate("hello", 10) == "hello"
    assert truncate("hello world", 6) == "hello…" and len(truncate("hello world", 6)) == 6
    assert len(short_hash("abc")) == 10 and short_hash("abc", 4) == short_hash("abc")[:4]
    assert options_hash(["Yes", "No"]) == options_hash(["no", "YES"])
