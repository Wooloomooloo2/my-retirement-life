# My Retirement Life

> **Plan your retirement with confidence — wherever you are in the world.**

My Retirement Life is a free, open-source, locally-run retirement planning application for Windows and Linux. It helps you build a complete picture of your financial future, model the impact of life decisions, and find out when — and how comfortably — you can retire.

Unlike cloud-based tools, your data never leaves your machine.

---

## Why this exists

Most retirement planning tools are built for a single country, a single currency, and a single pension system. They don't help the person with a UK state pension, a US 401(k), a Spanish property, and savings in three currencies.

My Retirement Life is built from the ground up to handle the real complexity of modern financial lives — multi-currency assets, international pension systems, property, investments, and the life events that change everything.

---

## What it does

- **Full financial picture** — cash savings, investments, pensions (state and private), property, other assets, and future windfalls — in any currency
- **Income planning** — current income, expected trajectory, working years remaining
- **Budget modelling** — mandatory and discretionary spending, loans, inflation adjustments
- **Life events** — model the financial impact of children leaving home, university fees, buying or selling property, moving abroad, caring for family, early retirement, and more
- **Retirement projections** — visual burndown charts showing your cash position year by year through retirement
- **Confidence scoring** — a clear indicator of how likely your retirement plan is to succeed given your assumptions
- **International asset support** — UK state pension, private pensions, US Social Security, 401(k), ISAs, SIPPs, and more
- **Multi-currency** — input assets and income in any currency; view projections in your chosen base currency

---

## Who it's for

- People approaching retirement who want a clear, honest picture of where they stand
- FIRE (Financial Independence, Retire Early) planners who need to stress-test their numbers
- Anyone with a financially complex life — multiple countries, currencies, or asset types
- People who want their financial data to stay private and on their own machine

---

## Status

🚧 **Early development** — MVP in progress. See the [MVP outline](docs/requirements/mvp.md) for what's being built first.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python + FastAPI |
| Data store | Oxigraph (RDF triple store) |
| Frontend | HTMX + Tailwind CSS + DaisyUI |
| Packaging | PyInstaller (Windows) + AppImage (Linux) |

See [docs/adr/](docs/adr/) for the full architecture decision records.

---

## Running locally (development)

### Prerequisites
- Python 3.13+
- Git

### Setup

```bash
git clone https://github.com/Wooloomooloo2/my-retirement-life.git
cd my-retirement-life
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

The app will start and open in your default browser at `http://127.0.0.1:8000`.

---

## Documentation

- [Architecture Decision Records](docs/adr/) — why the stack was chosen
- [MVP Outline](docs/requirements/mvp.md) — what's being built first
- [User Stories](docs/requirements/user-stories.md) — functional requirements
- [Ontology](docs/ontology/) — data model design

---

## Contributing

Contributions are welcome. Please open an issue before submitting a pull request so we can discuss the approach first.

---

## Licence

MIT — free to use, modify, and distribute.
