# Visa DATASPRINT 2026 - Krakow
https://visadatasprint.com/#home

> Megapolis VISA to zaawansowana analitycznie platforma cyfrowa stworzona w celu wspierania procesów strategicznych, planistycznych i inwestycyjnych w jednostkach samorządu terytorialnego, która – wykorzystując realne, anonimizowane dane transakcyjne systemu Visa oraz szczegółową geometrię kodów pocztowych – redefiniuje podejście do tworzenia polityk rozwoju miast, gmin, powiatów i województw

## Dopasowania gmin (demo)

Uruchom `streamlit run streamlit_app.py`. Domyślnie otwiera się widok
**Statystyki gmin**; u góry można przełączyć na **Wzmocnienie** lub
**Uzupełnienie**, a następnie wybrać gminę i zasięg.
Mapa oraz lista pokazują pięć najlepszych dopasowań. Oceny kategorii i ranking
są syntetycznymi mockami; rzeczywiste jest tylko położenie z GeoJSON.

## 🚀 Local Setup

We use a standard Python virtual environment (`venv`) to keep project dependencies isolated.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/artkowal/visa-datasprint-2026-krakow.git
   cd visa-datasprint-2026-krakow
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   ```
   *(Ubuntu users: if you get an `ensurepip` error, run `sudo apt install python3.12-venv` first, remove the broken `.venv` folder, and try again).*


3. **Activate the environment:**
   * **Ubuntu / macOS:**
     ```bash
     source .venv/bin/activate
     ```
   * **Windows:**
     ```cmd
     .venv\Scripts\activate
     ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Verify Installation:**
   To confirm everything is set up correctly, run:
   ```bash
   pip list
   ```
   You should see `duckdb`, `pandas`, `polars`, and `pyarrow` in the output list.

6. **Run**

   ```shell
   streamlit run streamlit_app.py
   ```