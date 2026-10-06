"""Read src/templates/*.md: the report's shape, kept out of Python."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from src.utils.paths import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "src" / "templates"
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


class TemplateError(RuntimeError):
    """The template is missing or malformed."""


@dataclass(frozen=True)
class Template:
    name: str
    body: str

    def placeholders(self) -> tuple[str, ...]:
        seen: list[str] = []
        for name in _PLACEHOLDER.findall(self.body):
            if name not in seen:
                seen.append(name)
        return tuple(seen)

    def render(self, values: dict[str, str]) -> str:
        """An unfilled placeholder is an error, not a blank."""

        missing = [name for name in self.placeholders() if name not in values]
        if missing:
            raise TemplateError(f"{self.name}: nothing to fill {missing} with")
        unused = [name for name in values if name not in self.placeholders()]
        if unused:
            raise TemplateError(f"{self.name}: values {unused} have no placeholder")
        rendered = _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), self.body)
        return re.sub(r"\n{3,}", "\n\n", rendered).strip() + "\n"


@lru_cache(maxsize=4)
def get_template(name: str = "cashflow-report") -> Template:
    path = TEMPLATE_DIR / f"{name}.md"
    if not path.is_file():
        raise TemplateError(f"no template at {path}")
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return Template(name=name, body=text.strip() + "\n")
