# Token Reduction & DOM Preprocessing Architecture

## Why Token Optimization Matters in Web Automation
Modern ATS job application pages (Lever, Ashby, Greenhouse, Workday) ship heavy JavaScript bundles with:
- Inline SVG icon definitions
- Base64 embedded fonts and tracking pixels
- Cookie consent banners, modal overlays, analytics scripts
- Marketing headers and footer link matrices

A typical raw page contains **30,000 to 200,000 HTML characters (~7,500 to 50,000 tokens)**. Passing raw HTML to an LLM on every page inspection is slow, expensive, and dilutes model attention.

---

## Token Pruning Strategy

| Pipeline Stage | Action Taken | Token Impact |
|---|---|---|
| **1. Tag Pruning** | Strips `<script>`, `<style>`, `<svg>`, `<noscript>`, `<iframe>`, `<header>`, `<footer>`, `<nav>`, `<canvas>`. | 📉 **~70% Reduction** |
| **2. Attribute Stripping** | Removes styling classes, telemetry IDs, inline styles, base64 strings. | 📉 **~15% Reduction** |
| **3. Interactive Tree Extraction** | Evaluates only active `input`, `select`, `textarea`, `[role="checkbox"]`, `[role="radio"]` elements and their immediate question headings. | 📉 **~10% Reduction** |
| **Total Net Result** | Compresses 20,000+ raw tokens down to **< 500 clean JSON tokens** | 🚀 **97.7% Net Savings** |

---

## Example Compressed Tree

```json
{
  "url": "https://jobs.ashbyhq.com/example/role-id/application",
  "title": "Software Engineer @ Example",
  "fields": [
    {"id": "_systemfield_name", "type": "text", "label": "Name", "required": true},
    {"id": "_systemfield_email", "type": "email", "label": "Email", "required": true},
    {"id": "02dad4e7-cb13-4aa4-9a27-2ab0e8b11f59", "type": "text", "label": "LinkedIn Url"},
    {"id": "_systemfield_resume", "type": "file", "label": "Resume"},
    {"id": "", "type": "checkbox", "label": "Are you currently legally authorized to work in the job location?"},
    {"id": "", "type": "checkbox", "label": "Will you require a work visa or sponsorship for work authorization now or in the future?"},
    {"id": "", "type": "checkbox", "label": "Can you commit to a hybrid work environment that involves working in the office 2 days per week?"}
  ]
}
```
