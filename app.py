import re
import pdfplumber
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Moj Tjedni Shopping", page_icon="🛒", layout="wide"
)

# Inicijalizacija radne memorije u aplikaciji (Session State)
if "katalozi_baza" not in st.session_state:
    st.session_state["katalozi_baza"] = []

# Popis sada čuva rječnik (naziv artikla + status je li kupljen: True/False)
if "popis_za_kupovinu" not in st.session_state:
    st.session_state["popis_za_kupovinu"] = []


# --- FUNKCIJA ZA PARSIRANJE PDF-a ---
def obradi_pdf_katalog(pdf_file, trgovina_naziv):
    proizvodi = []
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            linije = text.split("\n")
            for linija in linije:
                cijene = re.findall(
                    r"(\d+[\.,]\d{2})\s*(?:€|EUR)", linija, re.IGNORECASE
                )

                if cijene:
                    naziv_artikla = re.sub(
                        r"(\d+[\.,]\d{2})\s*(?:€|EUR)", "", linija
                    ).strip()
                    stara_cijena = None
                    nova_cijena = float(cijene[-1].replace(",", "."))

                    if len(cijene) > 1:
                        stara_cijena = float(cijene[0].replace(",", "."))

                    if len(naziv_artikla) > 2:
                        proizvodi.append({
                            "Trgovina": trgovina_naziv,
                            "Artikl": naziv_artikla,
                            "Nova Cijena (€)": nova_cijena,
                            "Stara Cijena (€)": stara_cijena,
                            "Stranica": page_num,
                        })
    return proizvodi


# --- BOČNA TRAKA (SIDEBAR) - NEDJELJNI UPLOAD ---
st.sidebar.header("📅 Nedjeljni Upload Kataloga")
trgovina_select = st.sidebar.selectbox(
    "Odaberi trgovinu:",
    ["Plodine", "Kaufland", "Lidl", "Konzum", "Interspar", "Eurospin"],
)
uploaded_pdf = st.sidebar.file_uploader(
    f"Učitaj PDF katalog za {trgovina_select}", type=["pdf"]
)

if st.sidebar.button("Obradi i Spremi Katalog"):
    if uploaded_pdf is not None:
        izvuceni_podaci = obradi_pdf_katalog(uploaded_pdf, trgovina_select)
        if izvuceni_podaci:
            st.session_state["katalozi_baza"].extend(izvuceni_podaci)
            st.sidebar.success(
                f"Uspješno učitano {len(izvuceni_podaci)} artikala iz kataloga"
                f" {trgovina_select}!"
            )
        else:
            st.sidebar.warning(
                "Nije pronađen tekst/cijene. Ako je PDF skenirana slika, potreban"
                " je OCR čitač."
            )
    else:
        st.sidebar.error("Molimo odaberite PDF datoteku.")

if st.sidebar.button("🗑️ Očisti sve kataloge (Novi tjedan)"):
    st.session_state["katalozi_baza"] = []
    st.sidebar.info("Baza kataloga je prazna.")


# --- GLAVNI EKRAN APLIKACIJE ---
st.title("🛒 Moj Tjedni Popis i Usporedba Cijena")

tab1, tab2, tab3 = st.tabs([
    "📝 Slaganje Popisa (Pon-Sri)",
    "📊 Pregled i Sortiranje po Trgovinama",
    "🔍 Pretraživanje svih Kataloga",
])

# --- TAB 1: SLAGANJE POPISA (TO-DO LISTA) ---
with tab1:
    st.subheader("Dodaj artikl na popis za kupovinu")
    col1, col2 = st.columns([3, 1])

    with col1:
        novi_artikl = st.text_input(
            "Unesi naziv artikla (npr. mlijeko, kava, sir):",
            key="unos_artikla",
        )
    with col2:
        st.write("##")
        if st.button("Dodaj na popis") and novi_artikl:
            # Spremamo kao rječnik: naziv i status (kupljeno: False)
            st.session_state["popis_za_kupovinu"].append({
                "naziv": novi_artikl.strip().lower(),
                "kupljeno": False,
            })
            st.rerun()

    if st.session_state["popis_za_kupovinu"]:
        st.markdown("### 📋 Tvoj To-Do Popis za kupovinu:")
        st.info(
            "Označite kvačicom kupljene artikle dok kupujete ili kliknite"
            " 'Ukloni' za brisanje s liste."
        )

        for idx, item in enumerate(st.session_state["popis_za_kupovinu"]):
            c1, c2, c3 = st.columns([0.5, 3.5, 1])

            # Interaktivna kvačica za status kupljeno/nije kupljeno
            kupljeno_status = c1.checkbox(
                "",
                value=item["kupljeno"],
                key=f"check_{idx}",
                label_visibility="collapsed",
            )
            if kupljeno_status != item["kupljeno"]:
                st.session_state["popis_za_kupovinu"][idx][
                    "kupljeno"
                ] = kupljeno_status
                st.rerun()

            # Prikaz naziva (ako je kupljeno, tekst postaje prekrižen)
            naziv_tekst = item["naziv"].capitalize()
            if kupljeno_status:
                c2.markdown(f"~~{naziv_tekst}~~")
            else:
                c2.markdown(f"**{naziv_tekst}**")

            # Gumb za potpuno brisanje artikla s popisa
            if c3.button("Ukloni", key=f"del_{idx}"):
                st.session_state["popis_za_kupovinu"].pop(idx)
                st.rerun()

        st.markdown("---")
        if st.button("🧹 Ukloni sve kupljene stavke s popisa"):
            st.session_state["popis_za_kupovinu"] = [
                item
                for item in st.session_state["popis_za_kupovinu"]
                if not item["kupljeno"]
            ]
            st.rerun()

# --- TAB 2: AKCIJA SRIDA (SORTIRANJE PO TRGOVINAMA) ---
with tab2:
    st.subheader("🛍️ Najbolje cijene po trgovinama za tvoj popis")

    if not st.session_state["popis_za_kupovinu"]:
        st.info("Popis za kupovinu je prazan. Dodajte artikle u prvom tabu.")
    elif not st.session_state["katalozi_baza"]:
        st.warning(
            "Nema učitanih kataloga. Učitajte PDF kataloge s lijeve strane."
        )
    else:
        df_baza = pd.DataFrame(st.session_state["katalozi_baza"])

        pronadjeni_artikli = []
        for item in st.session_state["popis_za_kupovinu"]:
            trazeni_item = item["naziv"]
            rezultat = df_baza[
                df_baza["Artikl"].str.contains(trazeni_item, case=False, na=False)
            ].copy()
            rezultat["Traženo"] = trazeni_item.capitalize()
            rezultat["Kupljeno"] = item["kupljeno"]
            pronadjeni_artikli.append(rezultat)

        if pronadjeni_artikli:
            df_rezultati = pd.concat(pronadjeni_artikli, ignore_index=True)

            if not df_rezultati.empty:
                # Prikaz tablice
                df_prikaz = df_rezultati[[
                    "Traženo",
                    "Trgovina",
                    "Artikl",
                    "Nova Cijena (€)",
                    "Stara Cijena (€)",
                    "Stranica",
                ]].sort_values(by=["Traženo", "Nova Cijena (€)"])

                st.dataframe(df_prikaz, use_container_width=True)

                st.markdown("---")
                st.markdown("### 🏆 Preporučeni raspored kupovine (Srijeda)")

                trgovine = df_rezultati["Trgovina"].unique()
                for trg in trgovine:
                    st.write(f"#### 🏪 {trg}")
                    podaci_trg = df_rezultati[df_rezultati["Trgovina"] == trg]
                    for _, row in podaci_trg.iterrows():
                        stara = (
                            f"~~{row['Stara Cijena (€)']} €~~ ➔ "
                            if pd.notnull(row["Stara Cijena (€)"])
                            else ""
                        )
                        status_ikona = "✅ " if row["Kupljeno"] else "⬜ "
                        st.write(
                            f"- {status_ikona}**{row['Traženo']}**"
                            f" ({row['Artikl']}): {stara}**{row['Nova Cijena"
                            f" (€)']} €** (Str. {row['Stranica']})"
                        )
            else:
                st.warning(
                    "Niti jedan artikl s vašeg popisa nije pronađen u učitanim"
                    " katalozima."
                )

# --- TAB 3: PRETRAŽIVANJE SVEGA ---
with tab3:
    st.subheader("🔍 Pretraži sve akcijske artikle iz kataloga")
    if st.session_state["katalozi_baza"]:
        df_sve = pd.DataFrame(st.session_state["katalozi_baza"])
        search_query = st.text_input("Pretraži po nazivu u svim katalozima:")
        if search_query:
            df_sve = df_sve[
                df_sve["Artikl"].str.contains(search_query, case=False, na=False)
            ]
        st.dataframe(df_sve, use_container_width=True)
    else:
        st.info("Nema učitanih kataloga.")