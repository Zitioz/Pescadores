import streamlit as st
from supabase import create_client, Client
import pandas as pd
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Inteligencia Territorial", page_icon="🗺️", layout="wide")

# Inicializar Supabase
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- 2. FUNCIONES DE AUTH (Tu lógica original simplificada) ---
def mostrar_login():
    st.markdown("## 🔐 Acceso a Plataforma")
    email = st.text_input("Correo Electrónico")
    password = st.text_input("Contraseña", type="password")
    
    if st.button("Iniciar Sesión"):
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state["user"] = res.user
            st.session_state["access_token"] = res.session.access_token
            st.success("Bienvenido!")
            st.rerun()
        except Exception as e:
            st.error(f"Error de acceso: {e}")

def cerrar_sesion():
    supabase.auth.sign_out()
    st.session_state.pop("user", None)
    st.rerun()

# --- 3. FUNCIONES DE DATOS ---

def cargar_excel_ssr(file):
    """Procesa el Excel de SSR específico que subiste"""
    try:
        # Leemos el excel
        df = pd.read_excel(file)
        
        # Mapeo de columnas basado en tu archivo BD_SSR
        # Ajusta estos nombres si cambian en el Excel final
        col_map = {
            'NOMBRE_OFICIAL_SISTEMA': 'nombre_oficial',
            'REGIÓN': 'region',
            'COMUNA': 'comuna',
            'COORD_GEOGRÁFICAS_LATITUD_SIRGAS_CHILE': 'latitud',
            'COORD_GEOGRÁFICAS_LONGITUD_SIRGAS_CHILE': 'longitud',
            'N°_ARRANQUES': 'arranques',
            'RUT': 'rut',
            'CLASIFICACIÓN_ART_106_D50': 'clasificacion'
        }
        
        # Verificar que existan las columnas críticas
        if not all(col in df.columns for col in col_map.keys()):
            st.error("El archivo no tiene las columnas esperadas del formato SSR Oficial.")
            st.write("Columnas encontradas:", df.columns.tolist())
            return None

        records_to_insert = []
        
        progress_bar = st.progress(0)
        total_rows = len(df)
        
        for idx, row in df.iterrows():
            # Limpieza de coordenadas (Manejo de errores si vienen vacías o con comas)
            try:
                lat = float(str(row['COORD_GEOGRÁFICAS_LATITUD_SIRGAS_CHILE']).replace(',', '.'))
                lon = float(str(row['COORD_GEOGRÁFICAS_LONGITUD_SIRGAS_CHILE']).replace(',', '.'))
                
                # Crear diccionario de detalles (JSONB)
                detalles = {
                    "arranques": row.get('N°_ARRANQUES'),
                    "rut": row.get('RUT'),
                    "clasificacion": row.get('CLASIFICACIÓN_ART_106_D50'),
                    "beneficiarios": row.get('BENEFICIARIOS_ESTIMADOS', 0)
                }

                record = {
                    "nombre_oficial": row['NOMBRE_OFICIAL_SISTEMA'],
                    "tipo_punto": "SSR", # Etiqueta fija para esta carga
                    "region": row['REGIÓN'],
                    "comuna": row['COMUNA'],
                    "latitud": lat,
                    "longitud": lon,
                    "detalles": detalles,
                    "usuario_creador": st.session_state["user"].email
                }
                records_to_insert.append(record)
                
            except Exception as e:
                # Si falla una fila (ej: sin coordenadas), la saltamos pero podrías loguearla
                continue
            
            if idx % 100 == 0:
                progress_bar.progress(idx / total_rows)

        # Insertar en lotes a Supabase
        if records_to_insert:
            # Supabase a veces limita el tamaño del insert, hacemos lotes de 100
            batch_size = 100
            for i in range(0, len(records_to_insert), batch_size):
                batch = records_to_insert[i:i + batch_size]
                supabase.table("puntos_territoriales").insert(batch).execute()
            
            progress_bar.progress(100)
            return len(records_to_insert)
        return 0

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
        return None

def obtener_puntos(filtro_region=None, filtro_comuna=None):
    query = supabase.table("puntos_territoriales").select("*")
    
    if filtro_region and filtro_region != "Todas":
        query = query.eq("region", filtro_region)
    if filtro_comuna and filtro_comuna != "Todas":
        query = query.eq("comuna", filtro_comuna)
        
    response = query.execute()
    return pd.DataFrame(response.data)

# --- 4. INTERFAZ PRINCIPAL ---

def main_app():
    st.sidebar.title(f"Usuario: {st.session_state['user'].email}")
    if st.sidebar.button("Cerrar Sesión"):
        cerrar_sesion()

    # Tabs de navegación
    tab1, tab2 = st.tabs(["🗺️ Mapa Territorial", "📂 Carga de Datos (Admin)"])

    # --- TAB 1: MAPA ---
    with tab1:
        st.title("Visor Territorial")
        
        # Filtros
        col1, col2 = st.columns(2)
        
        # Obtener lista única de regiones para el filtro (cacheado idealmente)
        # Por simplicidad hacemos query ligera o hardcodeamos si son fijas
        # Aquí traeremos todo primero (cuidado si son +10.000 registros, usar limit)
        df_base = obtener_puntos() # Trae todo para calcular filtros
        
        if not df_base.empty:
            regiones = ["Todas"] + sorted(df_base['region'].dropna().unique().tolist())
            region_sel = col1.selectbox("Filtrar por Región", regiones)
            
            if region_sel != "Todas":
                comunas = ["Todas"] + sorted(df_base[df_base['region'] == region_sel]['comuna'].dropna().unique().tolist())
            else:
                comunas = ["Todas"] + sorted(df_base['comuna'].dropna().unique().tolist())
                
            comuna_sel = col2.selectbox("Filtrar por Comuna", comunas)
            
            # Filtrar Dataframe localmente para rapidez visual
            df_show = df_base.copy()
            if region_sel != "Todas":
                df_show = df_show[df_show['region'] == region_sel]
            if comuna_sel != "Todas":
                df_show = df_show[df_show['comuna'] == comuna_sel]
                
            st.caption(f"Mostrando {len(df_show)} puntos")
            
            # MAPA FOLIUM
            if not df_show.empty:
                # Centro promedio
                avg_lat = df_show['latitud'].mean()
                avg_lon = df_show['longitud'].mean()
                
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=6 if region_sel == "Todas" else 10)
                marker_cluster = MarkerCluster().add_to(m)
                
                for idx, row in df_show.iterrows():
                    # Extraer detalles del JSONB
                    detalles = row['detalles'] if row['detalles'] else {}
                    arranques = detalles.get('arranques', 'S/I')
                    tipo = row['tipo_punto']
                    
                    html_popup = f"""
                    <b>{row['nombre_oficial']}</b><br>
                    Tipo: {tipo}<br>
                    Arranques: {arranques}<br>
                    <i>{row['comuna']}</i>
                    """
                    
                    folium.Marker(
                        location=[row['latitud'], row['longitud']],
                        popup=html_popup,
                        tooltip=row['nombre_oficial'],
                        icon=folium.Icon(color="blue" if tipo == "SSR" else "green", icon="info-sign")
                    ).add_to(marker_cluster)
                
                st_folium(m, width="100%", height=600)
            else:
                st.warning("No hay datos con esos filtros.")
        else:
            st.info("La base de datos está vacía. Ve a la pestaña de Carga.")

    # --- TAB 2: CARGA DE DATOS ---
    with tab2:
        st.header("Gestión de Datos")
        st.write("Sube el archivo Excel oficial de SSR para poblar la base de datos.")
        
        uploaded_file = st.file_uploader("Cargar BD_SSR_OFICIAL.xlsx", type=["xlsx"])
        
        if uploaded_file:
            if st.button("Procesar y Guardar en BD"):
                with st.spinner("Procesando archivo... esto puede tomar unos segundos..."):
                    count = cargar_excel_ssr(uploaded_file)
                    if count is not None:
                        st.success(f"¡Éxito! Se han cargado {count} registros nuevos.")
                        time.sleep(2)
                        st.rerun()

# --- 5. EJECUCIÓN ---
import time

if "user" not in st.session_state:
    mostrar_login()
else:
    main_app()