from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


@dataclass
class FormFieldNode:
    """A clean, token-optimized representation of a single form field or question."""
    id: str
    name: str
    tag: str
    type: str
    label: str
    required: bool = False
    placeholder: str = ""
    options: list[str] = field(default_factory=list)
    parent_question: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type or self.tag,
            "label": self.label or self.parent_question,
        }
        if self.required:
            d["required"] = True
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.options:
            d["options"] = self.options
        return d


@dataclass
class CompressedFormTree:
    """Compressed form representation reducing HTML token footprint by 85-95%."""
    url: str
    title: str
    fields: list[FormFieldNode] = field(default_factory=list)
    raw_token_estimate: int = 0
    compressed_token_estimate: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.raw_token_estimate == 0:
            return 0.0
        return 1.0 - (self.compressed_token_estimate / self.raw_token_estimate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "fields": [f.to_dict() for f in self.fields],
            "stats": {
                "raw_token_estimate": self.raw_token_estimate,
                "compressed_token_estimate": self.compressed_token_estimate,
                "compression_ratio_pct": round(self.compression_ratio * 100, 1),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class FormDOMPreprocessor:
    """Filters noisy web pages into compact, token-efficient interactive form trees."""

    # JavaScript payload evaluated in browser to extract only active interactive controls
    JS_EXTRACTION_SCRIPT = """
    () => {
        const title = document.title || "";
        const rawLength = document.documentElement.outerHTML.length;

        // Find question blocks or containers
        const blocks = [];
        const candidateContainers = document.querySelectorAll(
            'div[class*="question"], div[class*="field"], div[class*="form-group"], form, [role="group"], [role="radiogroup"]'
        );

        // Find all interactive elements
        const elements = document.querySelectorAll('input, select, textarea, [role="combobox"], [role="checkbox"], [role="radio"]');
        const fields = [];

        for (const el of elements) {
            // Ignore hidden or non-functional elements
            if (el.type === 'hidden' || el.style.display === 'none' || el.style.visibility === 'hidden') {
                continue;
            }

            // Extract label
            let labelText = '';
            if (el.labels && el.labels.length > 0) {
                labelText = el.labels[0].innerText;
            }

            // Check enclosing container title
            let parentQuestion = '';
            const container = el.closest('div[class*="question"], div[class*="field"], div[class*="_question_"]') || el.parentElement;
            if (container) {
                const titleEl = container.querySelector('label, h2, h3, h4, [class*="title"], [class*="heading"], [class*="_label_"]');
                if (titleEl && titleEl !== el) {
                    parentQuestion = titleEl.innerText;
                }
            }

            if (!labelText && parentQuestion) {
                labelText = parentQuestion;
            }
            if (!labelText && el.placeholder) {
                labelText = el.placeholder;
            }
            if (!labelText && el.getAttribute('aria-label')) {
                labelText = el.getAttribute('aria-label');
            }

            // Extract options for selects, radio buttons, or checkboxes
            const options = [];
            if (el.tagName.toLowerCase() === 'select') {
                for (const opt of el.options) {
                    if (opt.text) options.push(opt.text.trim());
                }
            } else if (container && (el.type === 'radio' || el.type === 'checkbox')) {
                const optLabels = container.querySelectorAll('label, span[class*="label"], span[class*="option"]');
                for (const opt of optLabels) {
                    const txt = opt.innerText.trim();
                    if (txt && !options.includes(txt) && txt !== parentQuestion) {
                        options.push(txt);
                    }
                }
            }

            fields.push({
                id: el.id || '',
                name: el.name || '',
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                label: (labelText || '').trim().replace(/\\s+/g, ' '),
                parent_question: (parentQuestion || '').trim().replace(/\\s+/g, ' '),
                required: el.required || el.getAttribute('aria-required') === 'true' || Boolean(container && container.innerText.includes('*')),
                placeholder: el.placeholder || '',
                options: options.slice(0, 10) // Limit to top 10 options to save tokens
            });
        }

        return {
            title: title,
            rawLength: rawLength,
            fields: fields
        };
    }
    """

    @classmethod
    def extract_from_page(cls, page: Any) -> CompressedFormTree:
        """Extract compressed form tree directly from an active Playwright page."""
        data = page.evaluate(cls.JS_EXTRACTION_SCRIPT)
        raw_char_count = data.get("rawLength", 50000)

        # Approximate 4 characters per token
        raw_token_estimate = max(1, raw_char_count // 4)

        fields: list[FormFieldNode] = []
        seen_keys = set()

        for f in data.get("fields", []):
            field_key = (f.get("id"), f.get("name"), f.get("label"))
            if field_key in seen_keys:
                continue
            seen_keys.add(field_key)

            fields.append(FormFieldNode(
                id=f.get("id", ""),
                name=f.get("name", ""),
                tag=f.get("tag", "input"),
                type=f.get("type", "text"),
                label=f.get("label", ""),
                required=f.get("required", False),
                placeholder=f.get("placeholder", ""),
                options=f.get("options", []),
                parent_question=f.get("parent_question", ""),
            ))

        tree = CompressedFormTree(
            url=page.url,
            title=data.get("title", ""),
            fields=fields,
            raw_token_estimate=raw_token_estimate,
        )

        # Calculate compressed token footprint
        json_len = len(tree.to_json())
        tree.compressed_token_estimate = max(1, json_len // 4)

        return tree

    @classmethod
    def prune_raw_html(cls, html: str) -> str:
        """Strip non-functional HTML tags, scripts, SVG assets, and base64 images."""
        # Strip script, style, svg, noscript, header, footer, iframe
        cleaned = re.sub(r"<(script|style|svg|noscript|iframe|header|footer|nav|canvas)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Strip comments
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
        # Strip base64 data URIs
        cleaned = re.sub(r'data:[^"\';\s]+', "", cleaned)
        # Collapse whitespace
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
