# molitvenik

Православни молитвеник на интернету: случајна молитва, молитва по филтеру или претрагом.
Текст је препис књиге *Православни молитвеник* (Штампарија Српске патријаршије, Београд 1998).

* Сајт: https://acailic.github.io/molitvenik/
* Дизајн и разлози одлука: [`docs/superpowers/specs/2026-11-24-molitvenik-design.md`](docs/superpowers/specs/2026-11-24-molitvenik-design.md)
* Статичан сајт без корака градње: `index.html`, `style.css`, `app/`, подаци у `data/prayers.json`.

## Алатке за текст

Текст се добија из скенираних страница и проверава поређењем независних читалања (дизајн, поглавља 5 и 6).

Потребно: [uv](https://docs.astral.sh/uv/), Tesseract 5 са моделом `srp` из `tessdata_best`, Hunspell
са српским речником (LibreOffice `sr`). PDF и слике страница нису у репоу.

```sh
uv sync                                   # окружење и зависности
uv run pytest                             # тестови алатки
uv run ruff check tools tests             # линт
uv run molitvenik --help                  # кораци канала (fetch, ocr, ia-ocr, clean, assemble, check, review)
```

## Сајт

```sh
npm test                                  # тестови логике у прегледачу (node --test)
npm run check                             # синтаксна провера свих модула
python3 -m http.server                    # локални преглед: http://localhost:8000
```

Сајт нема корак градње. За локални преглед послужите фасциклу (на пример наредбом изнад), јер
прегледач не учитава модуле директно из `file://`.

## Права

Код је под MIT лиценцом (види `LICENSE`). Права на текст молитава припадају њиховим носиоцима
(издавачу и Цркви). Сајт је некомерцијалан. Ако сте приметили грешку у тексту, отворите проблем
(Issues) и наведите молитву и реч.

---

*English.* An online Orthodox prayer book in Serbian Cyrillic: a random prayer, filters and
search (typed in Cyrillic or Latin). The text is a transcription of *Православни молитвеник*
(Belgrade 1998). Static site, no build step, no dependencies. The code is MIT-licensed; the
rights to the text belong to their right holders. The `tools/` directory holds the transcription
pipeline and its verification; the design and the reasons behind every decision are in
`docs/superpowers/specs/`.
