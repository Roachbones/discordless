import html
import re


class TextNode:
    def __init__(self, text: str):
        self.text: str = text

    def render(self) -> str:
        return html.escape(self.text)


class HtmlNode:
    def __init__(self, code: str):
        self.code: str = code

    def render(self) -> str:
        return self.code


class Rule:
    def __init__(self, pattern: str):
        self.pattern: re.Pattern = re.compile(pattern, re.S)

    def parse(self, match: re.Match) -> str:
        raise NotImplemented()


class CodeBlockRule(Rule):
    def __init__(self):
        super().__init__(r"\`\`\`(.+?)\`\`\`")

    def parse(self, match: re.Match) -> str:
        content = match.group(1)
        return f"<pre><code>{html.escape(content)}</code></pre>"


class InlineCodeBlockRule(Rule):
    def __init__(self):
        super().__init__(r"\`([^`]+?)\`(?!\`)")

    def parse(self, match: re.Match) -> str:
        content = match.group(1)
        return f"<code>{html.escape(content)}</code>"


class TextStylingRule(Rule):
    def __init__(self, patter: str, start: str, end: str):
        super().__init__(patter)
        self.start: str = start
        self.end: str = end

    def parse(self, match: re.Match) -> str:
        content = discord_markdown_to_html(match.group(1))
        return f"{self.start}{content}{self.end}"

class HeaderRule(Rule):
    def __init__(self, level: int):
        super().__init__(f"(?<!#){"#"*level}([^\n#]+)")
        self.level = level

    def parse(self, match: re.Match) -> str:
        content = discord_markdown_to_html(match.group(1))
        return f"<h{self.level}>{content}</h{self.level}>"

class ListRule(Rule):
    def __init__(self):
        super().__init__(r"- ([\S^\n]*?)\n")

    def parse(self, match: re.Match) -> str:
        content = discord_markdown_to_html(match.group(1))
        return f"<ul style=\"margin:0\"><li>{content}</li></ul>"

RULES: list[Rule] = [
    CodeBlockRule(),
    InlineCodeBlockRule(),
    ListRule(),
    HeaderRule(1),
    HeaderRule(2),
    HeaderRule(3),
    HeaderRule(4),
    HeaderRule(5),
    HeaderRule(6),
    # TODO: rewrite to allow reliable nesting
    TextStylingRule(r"__\*\*\*([^_\*]+?)\*\*\*__", "<span style=\"text-decoration: underline;\"><b><i>","</i></b></span>"),
    TextStylingRule(r"__\*\*([^_\*]+?)\*\*__", "<span style=\"text-decoration: underline;\"><b>","</b></span>"),
    TextStylingRule(r"__\*([^_\*]+?)\*__", "<span style=\"text-decoration: underline;\"><i>","</i></span>"),
    TextStylingRule(r"(?<!_)_([^_]+?)_(?!_)", "<i>","</i>"),
    TextStylingRule(r"~~([^~]+?)~~", "<s>","</s>"),
    TextStylingRule(r"(?<!\*)\*([^\*]+?)\*(?!\*)", "<i>","</i>"),
    TextStylingRule(r"(?<!\*)\*\*([^\*]+?)\*\*(?!\*)", "<b>","</b>"),
    TextStylingRule(r"__([^_]+?)__", "<span style=\"text-decoration: underline;\">","</span>"),
    TextStylingRule(r"\*\*\*([^\*]+?)\*\*\*", "<b><i>","</i></b>"),
]


def parse_rule(current_ast: list[HtmlNode | TextNode], rule: Rule):
    new_ast = []
    for node in current_ast:
        # if it isn't a text node, we don't have to parse it
        if not isinstance(node, TextNode):
            new_ast.append(node)
            continue
        # it is a text node, parse it
        text_start = 0
        while True:
            match = rule.pattern.search(node.text, text_start)
            if match is None:
                break
            # finish text node before rule starts
            text_end = match.start()
            if text_end - text_start > 0:
                token_text = node.text[text_start:text_end]
                new_ast.append(TextNode(token_text))
            # the rule itself
            new_ast.append(HtmlNode(rule.parse(match)))
            # the rest that remains: update start, continue in loop
            text_start = match.end()
        # there might be text remaining at the end
        if len(node.text) - text_start > 0:
            token_text = node.text[text_start:]
            new_ast.append(TextNode(token_text))
    return new_ast


def discord_markdown_to_html(markdown: str) -> str:
    ast = [TextNode(markdown)]
    for rule in RULES:
        ast = parse_rule(ast, rule)
    return "".join((node.render() for node in ast))


if __name__ == "__main__":
    print(discord_markdown_to_html("""
    test<> ```\nddd<> ``` ``` `test` 
    _italic_ 
    *italic* 
    **bold** 
    __underline__ 
    ***bold italics***
    __*underline italics*__
    __**underline bold**__
    __***underline bold italics***__
    ~~Strikethrough~~
    #a
    ##a
    ###a
    ####a
    #####a
    ######a
    
    fake lists
    -
    -asd
    good lists
    - asd
    - fgh
    """))
