import io
import json
import zipfile
import gdown
import google.generativeai as genai
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Pametni Tjedni Popis", page_icon="🛒", layout="wide"
)


# --- SPAJANJE NA SUPABASE ---
@st.cache_resource
def init_supabase():
  url = st.secrets["supabase"]["url"]
  key = st.secrets["supabase"]["key"]
  return create_client(url, key)


supabase = init_supabase()


# --- FUNKCIJA ZA ANALIZU SLIKE IZ ZIP-a ---
def obradi_sliku_bytes(image_bytes, trgovina_naziv, filename):
  genai.configure(api_key=st.secrets["gemini"]["api_key"])
  model = genai.GenerativeModel("gemini-2.5-flash")

  prompt = (
      f"Analiziraj ovu sliku kataloga trgovine {trgovina_naziv}. Pronađi sve"
      " artikle, njihove nazive i nove/akcijske cijene u EUR. Vrati isključivo"
      " u JSON formatu kao lista objekata s ključevima: 'artikl' (naziv"
      " proizvoda), 'nova_cijena' (broj u eurima, npr 1.59), 'stara_cijena'"
      " (broj ili null ako nema stare cijene)."
  )

  try:
    mime_type = (
        "image/png" if filename.lower().endswith(".png") else "image/jpeg"
    )
    image_part = {"mime_type": mime_type, "data": image_bytes}
    response = model.generate_content([prompt, image_part])

    tekst_odgovora = (
        response.text.replace("```json", "").replace("```", "").strip()
    )
    artikli_lista = json.loads(tekst_odgovora)

    proizvodi = []
    for item in artikli_lista:
      proizvodi.append({
          "trgovina": trgovina_naziv,
          "artikl": item.get("artikl"),
          "nova_cijena": float(item.get("nova_cijena", 0)),
          "stara_cijena": (
              float(item.get("stara_cijena"))
              if item.get("stara_cijena")
              else None
          ),
      })
    return proizvodi
  except Exception as e:
    return []


# --- BOČNA TRAKA (SIDEBAR) - GOOGLE DRIVE LINK ---
st.sidebar.header("📅 Uvoz ZIP Arhive s Google Drive-a")
trgovina_select = st.sidebar.selectbox(
    "Odaberi trgovinu:",
    ["Plodine", "Kaufland", "Lidl", "Konzum", "Interspar", "Eurospin"],
)

gdrive_link = st.sidebar.text_input(
    "Zalijepi Google Drive link ZIP arhive:"
)

if st.sidebar.button("Skini i Obradi Arhivu"):
  if gdrive_link:
    try:
      with st.spinner("Preuzimam arhivu s Google Drive-a..."):
        output = "temp_katalog.zip"
        # gdown automatski skida s GDrive linka
        gdown.download(gdrive_link, output, fuzzy=True)

      ukupno_spremljeno = 0
      with zipfile.ZipFile(output, "r") as z:
        slike_u_zipu = [
            f
            for f in z.namelist()
            if f.lower().endswith((".png",].jpg", ".jpeg"))
            and not f.startswith("__MACOSX/")
        ]

        if not slike_u_zipu:
          st.sidebar.error(
              "U ZIP arhivi nisu pronađene slike (jpg/png format)."
          )
        else:
          progress_bar = st.sidebar.progress(0)
          total_files = len(slike_u_zipu)

          for i, filename in enumerate(slike_u_zipu):
            with z.open(filename) as img_file:
              img_bytes = img_file.read()
              with st.spinner(
                  f"Obrađujem sliku {i+1} od {total_files} ({filename})..."
              ):
                izvuceni_podaci = obradi_sliku_bytes(
                    img_bytes, trgovina_select, filename
                )
                if izvuceni_podaci:
                  supabase.table("katalog_artikli").insert(
                      izvuceni_podaci
                  ).execute()
                  ukupno_spremljeno += len(izvuceni_podaci)
            progress_bar.progress((i + 1) / total_files)

          st.sidebar.success(
              f"Uspješno obrađeno i spremljeno {ukupno_spremljeno} artikala iz"
              f" {total_files} slika!"
          )
    except Exception as e:
      st.sidebar.error(
          f"Greška kod preuzimanja ili obrade: {str(e)}. Provjerite link."
      )
  else:
    st.sidebar.error("Molimo unesite Google Drive link.")

if st.sidebar.button("🗑️ Očisti sve kataloge (Novi tjedan)"):
  supabase.table("katalog_artikli").delete().neq("id", 0).execute()
  st.sidebar.info("Baza kataloga je ispražnjena.")
  st.rerun()


# --- GLAVNI EKRAN APLIKACIJE ---
st.title("🛒 Pametni Tjedni Popis po Trgovinama")

tab1, tab2 = st.tabs([
    "📝 Slaganje Popisa i Trgovine",
    "🔍 Pretraživanje svih Kataloga",
])

response_popis = (
    supabase.table("shopping_popis").select("*").order("id").execute()
)
popis_data = response_popis.data if response_popis.data else []

response_katalog = (
    supabase.table("katalog_artikli").select("*").order("id").execute()
)
katalog_data = response_katalog.data if response_katalog.data else []


# --- TAB 1: SLAGANJE POPISA ---
with tab1:
  st.subheader("Dodaj artikl na popis")
  col1, col2 = st.columns([3, 1])

  with col1:
    novi_artikl = st.text_input(
        "Unesi naziv artikla (npr. tuna, mlijeko, kava):", key="unos_artikla"
    )
  with col2:
    st.write("##")
    if st.button("Dodaj na popis") and novi_artikl:
      trazeni_naziv = novi_artikl.strip().lower()
      odabrana_trgovina = "Nepoznato (Nema u katalozima)"
      pridruzena_cijena = None

      if katalog_data:
        df_baza = pd.DataFrame(katalog_data)
        rezultati = df_baza[
            df_baza["artikl"].str.contains(trazeni_naziv, case=False, na=False)
        ]

        if not rezultati.empty:
          najjeftiniji_red = rezultati.loc[
              rezultati["nova_cijena"].idxmin()
          ]
          odabrana_trgovina = najjeftiniji_red["trgovina"]
          pridruzena_cijena = najjeftiniji_red["nova_cijena"]

      supabase.table("shopping_popis").insert({
          "naziv": trazeni_naziv,
          "trgovina": odabrana_trgovina,
          "cijena": pridruzena_cijena,
          "kupljeno": False,
      }).execute()
      st.rerun()

  st.markdown("---")
  st.subheader("🛍️ Kupovina po trgovinama")

  dostupne_trgovine = [
      "Plodine",
      "Kaufland",
      "Lidl",
      "Konzum",
      "Interspar",
      "Eurospin",
      "Nepoznato (Nema u katalozima)",
  ]
  aktivna_trgovina = st.selectbox(
      "Izaberi trgovinu u kojoj se trenutno nalazite:", dostupne_trgovine
  )

  popis_za_trgovinu = [
      item for item in popis_data if item.get("trgovina") == aktivna_trgovina
  ]

  if popis_za_trgovinu:
    st.markdown(f"### Popis za: **{aktivna_trgovina}**")
    st.info(
        "Označite kvačicom kupljeni artikl – automatski se briše s popisa."
    )

    for item in popis_za_trgovinu:
      idx = item["id"]
      c1, c2, c3 = st.columns([0.5, 4, 1])

      kupljeno_status = c1.checkbox(
          "", value=False, key=f"check_{idx}", label_visibility="collapsed"
      )
      if kupljeno_status:
        supabase.table("shopping_popis").delete().eq("id", idx).execute()
        st.rerun()

      cijena_tekst = (
          f" ({item['cijena']} €)" if item.get("cijena") is not None else ""
      )
      c2.markdown(f"**{item['naziv'].capitalize()}**{cijena_tekst}")

      if c3.button("Ukloni", key=f"del_{idx}"):
        supabase.table("shopping_popis").delete().eq("id", idx).execute()
        st.rerun()
  else:
    st.info(f"Nemate artikala na popisu za trgovinu **{aktivna_trgovina}**.")

  if popis_data:
    with st.expander("Pregled cijelog popisa (sve trgovine zajedno)"):
      df_popis = pd.DataFrame(popis_data)
      st.dataframe(
          df_popis[["naziv", "trgovina", "cijena"]], use_container_width=True
      )


# --- TAB 2: PRETRAŽIVANJE SVEGA ---
with tab2:
  st.subheader("🔍 Pretraži sve artikle iz kataloga")
  if katalog_data:
    df_sve = pd.DataFrame(katalog_data)
    search_query = st.text_input("Pretraži po nazivu:")
    if search_query:
      df_sve = df_sve[
          df_sve["artikl"].str.contains(search_query, case=False, na=False)
      ]
    st.dataframe(df_sve, use_container_width=True)
  else:
    st.info("Nema učitanih kataloga u bazi.")
