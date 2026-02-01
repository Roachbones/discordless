import datetime
import html
import re
import unittest
from typing import Callable


class Rule:
    def __init__(self, pattern: str):
        self.pattern: re.Pattern = re.compile(pattern, re.S)

    def parse(self, match: re.Match) -> str:
        raise NotImplemented()


class WrapContent(Rule):
    def __init__(self, regexp: str, formatter: Callable[[str], str], recursive: bool = True):
        super().__init__(regexp)
        self.formatter: Callable[[str], str] = formatter
        self.recursive: bool = recursive

    def parse(self, match: re.Match) -> str:
        if self.recursive:
            content = discord_markdown_to_html(match.group(1))
        else:
            content = html.escape(match.group(1))
        return self.formatter(content)

class MaskedLinkRule(Rule):
    def __init__(self):
        super().__init__(r"\[(.*?)\]\((https?://[a-z0-9.\-]*[a-z0-9][^\s]*)\)")

    def parse(self, match: re.Match) -> str:
        content = match.group(1)
        url = match.group(2)
        if content.isspace() or content == "":
            return html.escape(match.group(0))
        else:
            return f"<a href=\"{url}\">{html.escape(content)}</a>"

class UrlRule(Rule):
    def __init__(self):
        super().__init__(r"<?(https?://[a-z0-9.\-]*[a-z0-9][^\s>]*)>?")

    def parse(self, match: re.Match) -> str:
        content = match.group(1)
        return f"<a href=\"{content}\">{html.escape(content)}</a>"

class EmojiRule(Rule):
    def __init__(self):
        # example: <:dogekek:621141522756224000>
        super().__init__(r"<a?:([^:]+):(\d+)>")

    def parse(self, match: re.Match) -> str:
        name = match.group(1)
        id = match.group(2)
        return f"<img alt=\"{html.escape(name)}\" />"

class TimeWidgetRule(Rule):
    def __init__(self):
        # example: <t:1715154814:R>
        super().__init__(r"<t:(\d+):(\w+)>")

    def parse(self, match: re.Match) -> str:
        timestamp = int(match.group(1))
        dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        time_kind_modifier = match.group(2)

        if time_kind_modifier == "t":
            timestr = dt.strftime("%H:%M")
        else:
            timestr = dt.strftime("%A, %-d %B %Y at %H:%M")

        return html.escape(timestr)

class UserPingRule(Rule):
    def __init__(self):
        # example: <@373600851529540096>
        super().__init__(r"<@!?(\d+)>")

    def parse(self, match: re.Match) -> str:
        user_id: str = match.group(1)
        return f"@user_{user_id}"

class RolePingRule(Rule):
    def __init__(self):
        # example: <@&373600854529740096>
        super().__init__(r"<@&(\d+)>")

    def parse(self, match: re.Match) -> str:
        role_id: str = match.group(1)
        return f"@role_{role_id}"

class ChannelLinkRule(Rule):
    def __init__(self):
        # example: <#1009193884015919217>
        super().__init__(r"<#(\d+)>")

    def parse(self, match: re.Match) -> str:
        channel_id: str = match.group(1)
        return f"#channel_{channel_id}"

RULES: list[Rule] = [
    # structureal elements
    WrapContent(r"\`\`\`(.+?)\`\`\`", lambda content: f"<pre><code>{content}</code></pre>", recursive=False),  # code blocks
    WrapContent(r"\`([^`]+?)\`(?!\`)", lambda content: f"<code>{content}</code>", recursive=False),  # inline code
    WrapContent(r"(?:^|\n)\s*- ([^\n]*?)(?=$|\n)", lambda content: f"<ul style=\"margin:0\"><li>{content}</li></ul>"),  # lists

    EmojiRule(),
    TimeWidgetRule(),
    UserPingRule(),
    RolePingRule(),
    ChannelLinkRule(), # ensure it has higher priority than h1 so the # is parsed correctly

    WrapContent(r"#([^\n#]+)", lambda content: f"<h1>{content}</h1>"),  # h1
    WrapContent(r"##([^\n#]+)", lambda content: f"<h2>{content}</h2>"),  # h2
    WrapContent(r"###([^\n#]+)", lambda content: f"<h3>{content}</h3>"),  # h3
    WrapContent(r"####([^\n#]+)", lambda content: f"<h4>{content}</h4>"),  # h4
    WrapContent(r"#####([^\n#]+)", lambda content: f"<h5>{content}</h5>"),  # h5
    WrapContent(r"######([^\n#]+)", lambda content: f"<h6>{content}</h6>"),  # h6

    # font styles
    WrapContent(r"\*\*(.+?)\*\*(?!\*)", lambda content: f"<b>{content}</b>"),  # bold
    WrapContent(r"\*(.+?)\*", lambda content: f"<i>{content}</i>"),  # italic, important: must be after bold rule so bold isn't interpreted as italic
    WrapContent(r"__(.+?)__", lambda content: f"<span style=\"text-decoration: underline;\">{content}</span>"),  # underline
    WrapContent(r"_(.+?)_", lambda content: f"<i>{content}</i>"),  # italic using _, important: must be after underline rule so underline isn't interpreted as italic
    WrapContent(r"~~(.+?)~~", lambda content: f"<s>{content}</s>"),  # underline

    MaskedLinkRule(),
    UrlRule(),
]


def discord_markdown_to_html(markdown: str) -> str:
    result = ""
    node_start = 0
    while True:
        best_match: re.Match | None = None
        best_rule: Rule | None = None
        best_match_start: int = len(markdown)
        for rule in RULES:
            match = rule.pattern.search(markdown, node_start)
            if match:
                match_start = match.start()
                # by using strictly smaller
                if match_start < best_match_start:
                    best_match = match
                    best_rule = rule
                    best_match_start = match_start
        if not best_match:
            # no more special markdown, finish potential text node
            text_end = len(markdown)
            if text_end - node_start > 0:
                token_text = markdown[node_start:text_end]
                result += html.escape(token_text)
            break  # we are done
        else:
            # we have a match
            # finish text node until match
            text_end = best_match.start()
            if text_end - node_start > 0:
                token_text = markdown[node_start:text_end]
                result += html.escape(token_text)
            # the match itself
            result += best_rule.parse(best_match)
            node_start = best_match.end()
    return result


class TestMarkdownRendering(unittest.TestCase):
    def test_codeblocks(self):
        self.assertEqual(discord_markdown_to_html("```codeblock```"),"<pre><code>codeblock</code></pre>")
        self.assertEqual(discord_markdown_to_html("`inline`"), "<code>inline</code>")
        self.assertEqual(discord_markdown_to_html("```codeblock``` followed by `inline`"), "<pre><code>codeblock</code></pre> followed by <code>inline</code>")

    def test_no_styling_in_code(self):
        self.assertEqual(discord_markdown_to_html("`*not italic*`"), "<code>*not italic*</code>")
        self.assertEqual(discord_markdown_to_html("```*not italic*```"), "<pre><code>*not italic*</code></pre>")

    def test_text_decoration(self):
        self.assertEqual(discord_markdown_to_html("_italic_"), "<i>italic</i>")
        self.assertEqual(discord_markdown_to_html("*italic*"), "<i>italic</i>")
        self.assertEqual(discord_markdown_to_html("**bold**"), "<b>bold</b>")
        self.assertEqual(discord_markdown_to_html("__underline__"), "<span style=\"text-decoration: underline;\">underline</span>")
        self.assertEqual(discord_markdown_to_html("***bold italics***"), "<b><i>bold italics</i></b>")
        self.assertEqual(discord_markdown_to_html("__*underline italics*__"), "<span style=\"text-decoration: underline;\"><i>underline italics</i></span>")
        self.assertEqual(discord_markdown_to_html("__**underline bold**__"), "<span style=\"text-decoration: underline;\"><b>underline bold</b></span>")
        self.assertEqual(discord_markdown_to_html("__***underline bold italics***__"), "<span style=\"text-decoration: underline;\"><b><i>underline bold italics</i></b></span>")
        self.assertEqual(discord_markdown_to_html("~~Strikethrough~~"), "<s>Strikethrough</s>")

    def test_headers(self):
        self.assertEqual(discord_markdown_to_html("#a"), "<h1>a</h1>")
        self.assertEqual(discord_markdown_to_html("##a"), "<h2>a</h2>")
        self.assertEqual(discord_markdown_to_html("###a"), "<h3>a</h3>")
        self.assertEqual(discord_markdown_to_html("####a"), "<h4>a</h4>")
        self.assertEqual(discord_markdown_to_html("#####a"), "<h5>a</h5>")
        self.assertEqual(discord_markdown_to_html("######a"), "<h6>a</h6>")

    def test_fake_lists(self):
        self.assertEqual(discord_markdown_to_html("-"), "-")
        self.assertEqual(discord_markdown_to_html("-asd"), "-asd")
        self.assertEqual(discord_markdown_to_html("a - a"), "a - a")

    def test_lists(self):
        self.assertEqual(discord_markdown_to_html("- asd\n- fgh"), "<ul style=\"margin:0\"><li>asd</li></ul><ul style=\"margin:0\"><li>fgh</li></ul>")

    def test_html_escapes(self):
        self.assertEqual(discord_markdown_to_html("<>"), "&lt;&gt;")

    def test_convert_url_to_link(self):
        self.assertEqual(discord_markdown_to_html("http://example.com/test"), "<a href=\"http://example.com/test\">http://example.com/test</a>")
        self.assertEqual(discord_markdown_to_html("https://example.com/test"), "<a href=\"https://example.com/test\">https://example.com/test</a>")
        self.assertEqual(discord_markdown_to_html("<https://example.com/test>"), "<a href=\"https://example.com/test\">https://example.com/test</a>")

    def test_links(self):
        self.assertEqual(discord_markdown_to_html("[test](http://example.com)"), "<a href=\"http://example.com\">test</a>")
        self.assertEqual(discord_markdown_to_html("[test](https://example.com)"), "<a href=\"https://example.com\">test</a>")

    def test_invalid_links_stay_text(self):
        self.assertEqual(discord_markdown_to_html("[test](invalid)"), "[test](invalid)")
        self.assertEqual(discord_markdown_to_html("[ ](http://invalid)"), "[ ](http://invalid)")
        self.assertEqual(discord_markdown_to_html("[\n](http://invalid)"), "[\n](http://invalid)")
        self.assertEqual(discord_markdown_to_html("[\t](http://invalid)"), "[\t](http://invalid)")
        self.assertEqual(discord_markdown_to_html("[](http://invalid)"), "[](http://invalid)")

    def test_dicord_element(self):
        self.assertEqual(discord_markdown_to_html("<:dogekek:621141528756224000>"), "<img alt=\"dogekek\" />")
        self.assertEqual(discord_markdown_to_html("<a:HanSalute:707723880655224893>"), "<img alt=\"HanSalute\" />")

        self.assertEqual(discord_markdown_to_html("<t:1715159814:R>"), "Wednesday, 8 May 2024 at 09:16")
        self.assertEqual(discord_markdown_to_html("<t:1715159814:t>"), "09:16")

        self.assertEqual(discord_markdown_to_html("<@373600854529540096>"), "@user_373600854529540096")
        self.assertEqual(discord_markdown_to_html("<@&819559337005023272>"), "@role_819559337005023272")
        self.assertEqual(discord_markdown_to_html("<#1009193884015919215>"), "#channel_1009193884015919215")

if __name__ == "__main__":
    unittest.main()
