import re
import pdfplumber
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Moj Tjedni Shopping", page_icon="🛒", layout="wide"
)


# --- SPAJANJE NA POSTojeći SUPABASE ---
@st.cache_resource
def init_supabase():
  url = st.secrets["supabase"]["url"]
  key = st.secrets["supabase"]["key"]
  return create_client(url, key)


supabase = init_supabase()


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
                "trgovina": trgovina_naziv,
                "artikl": naziv_artikla,
                "nova_cijena": nova_cijena,
                "stara_cijena": stara_cijena,
                "stranica": page_num,
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

if st.sidebar.button("Obradi i Spremi u Supabase"):
  if uploaded_pdf is not None:
    izvuceni_podaci = obradi_pdf_katalog(uploaded_pdf, trgovina_select)
    if izvuceni_podaci:
      # Spremanje u Supabase bazu
      supabase.table("katalog_artikli").insert(izvuceni_podaci).execute()
      st.sidebar.success(
          f"Uspješno spremljeno {len(izvuceni_podaci)} artikala u bazu!"
      )
      st.rerun()
    else:
      st.sidebar.warning(
          "Nije pronađen tekst/cijene. Ako je PDF skenirana slika, potreban je"
          " OCR čitač."
      )
  else:
    st.sidebar.error("Molimo odaberite PDF datoteku.")

if st.sidebar.button("🗑️ Očisti sve kataloge (Novi tjedan)"):
  supabase.table("katalog_artikli").delete().neq("id", 0).execute()
  st.sidebar.info("Baza kataloga je ispražnjena.")
  st.rerun()


# --- GLAVNI EKRAN APLIKACIJE ---
st.title("🛒 Moj Tjedni Popis i Usporedba Cijena (Cloud)")

tab1, tab2, tab3 = st.tabs([
    "📝 Slaganje Popisa (Pon-Sri)",
    "📊 Pregled i Sortiranje po Trgovinama",
    "🔍 Pretraživanje svih Kataloga",
])

# --- DOHVAĆANJE PODATAKA IZ BAZE ---
response_popis = (
    supabase.table("shopping_popis").select("*").order("id").execute()
)
popis_data = response_popis.data if response_popis.data else []

response_katalog = (
    supabase.table("katalog_artikli").select("*").order("id").execute()
)
katalog_data = response_katalog.data if response_katalog.data else []


# --- TAB 1: SLAGANJE POPISA (TO-DO LISTA) ---
with tab1:
  st.subheader("Dodaj artikl na popis za kupovinu")
  col1, col2 = st.columns([3, 1])

  with col1:
    novi_artikl = st.text_input(
        "Unesi naziv artikla (npr. mlijeko, kava, sir):", key="unos_artikla"
    )
  with col2:
    st.write("##")
    if st.button("Dodaj na popis") and novi_artikl:
      supabase.table("shopping_popis").insert({
          "naziv": novi_artikl.strip().lower(),
          "kupljeno": False,
      }).execute()
      st.rerun()

  if popis_data:
    st.markdown("### 📋 Tvoj To-Do Popis za kupovinu (Spremljeno u oblaku):")

    for item in popis_data:
      idx = item["id"]
      c1, c2, c3 = st.columns([0.5, 3.5, 1])

      kupljeno_status = c1.checkbox(
          "",
          value=item["kupljeno"],
          key=f"check_{idx}",
          label_visibility="collapsed",
      )
      if kupljeno_status != item["kupljeno"]:
        supabase.table("shopping_popis").update(
            {"kupljeno": kupljeno_status}
        ).eq("id", idx).execute()
        st.rerun()

      naziv_tekst = item["naziv"].capitalize()
      if kupljeno_status:
        c2.markdown(f"~~{naziv_tekst}~~")
      else:
        c2.markdown(f"**{naziv_tekst}**")

      if c3.button("Ukloni", key=f"del_{idx}"):
        supabase.table("shopping_popis").delete().eq("id", idx).execute()
        st.rerun()

    st.markdown("---")
    if st.button("🧹 Ukloni sve kupljene stavke s popisa"):
      supabase.table("shopping_popis").delete().eq("kupljeno", True).execute()
      st.rerun()


# --- TAB 2: AKCIJA SRIDA (SORTIRANJE PO TRGOVINAMA) ---
with tab2:
  st.subheader("🛍️ Najbolje cijene po trgovinama za tvoj popis")

  if not popis_data:
    st.info("Popis za kupovinu je prazan. Dodajte artikle u prvom tabu.")
  elif not katalog_data:
    st.warning("Nema učitanih kataloga u bazi. Učitajte PDF kataloge sa strane.")
  else:
    df_baza = pd.DataFrame(katalog_data)

    pronadjeni_artikli = []
    for item in popis_data:
      trazeni_item = item["naziv"]
      rezultat = df_baza[
          df_baza["artikl"].str.contains(trazeni_item, case=False, na=False)
      ].copy()
      rezultat["Traženo"] = trazeni_item.capitalize()
      rezultat["Kupljeno"] = item["kupljeno"]
      pronadjeni_artikli.append(rezultat)

    if pronadjeni_artikli:
      df_rezultati = pd.concat(pronadjeni_artikli, ignore_index=True)

      if not df_rezultati.empty:
        df_prikaz = df_rezultati[[
            "Traženo",
            "trgovina",
            "artikl",
            "nova_cijena",
            "stara_cijena",
            "stranica",
        ]].sort_values(by=["Traženo", "nova_cijena"])
        df_prikaz.columns = [
            "Traženo",
            "Trgovina",
            "Artikl",
            "Nova Cijena (€)",
            "Stara Cijena (€)",
            "Stranica",
        ]

        st.dataframe(df_prikaz, use_container_width=True)

        st.markdown("---")
        st.markdown("### 🏆 Preporučeni raspored kupovine (Srijeda)")

        trgovine = df_rezultati["trgovina"].unique()
        for trg in trgovine:
          st.write(f"#### 🏪 {trg}")
          podaci_trg = df_rezultati[df_rezultati["trgovina"] == trg]
          for _, row in podaci_trg.iterrows():
            stara = (
                f"~~{row['stara_cijena']} €~~ ➔ "
                if pd.notnull(row["stara_cijena"])
                else ""
            )
            status_ikona = "✅ " if row["Kupljeno"] else "⬜ "
            st.write(
                f"- {status_ikona}**{row['Traženo']}** ({row['artikl']}):"
                f" {stara}**{row['nova_cijena']} €** (Str. {row['stranica']})"
            )
      else:
        st.warning(
            "Niti jedan artikl s vašeg popisa nije pronađen u učitanim"
            " katalozima."
        )

# --- TAB 3: PRETRAŽIVANJE SVEGA ---
with tab3:
  st.subheader("🔍 Pretraži sve akcijske artikle iz kataloga")
  if katalog_data:
    df_sve = pd.DataFrame(katalog_data)
    search_query = st.text_input("Pretraži po nazivu u svim katalozima:")
    if search_query:
      df_sve = df_sve[
          df_sve["artikl"].str.contains(search_query, case=False, na=False)
      ]
    st.dataframe(df_sve, use_container_width=True)
  else:
    st.info("Nema učitanih kataloga u bazi.")
