import streamlit as st
from supabase import create_client, Client
import pandas as pd
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Inteligencia Territorial", page_icon="🗺️", layout="wide")

# Inicializar Supabase
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- 2. FUNCIONES DE AUTH ---
def mostrar_login():
    st.markdown("## 🔐 Acceso a Plataforma")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        email = st.text_input("Correo Electrónico")
        password = st.text_input("Contraseña", type="password")
        
        if st.button("Iniciar Sesión", use_container_width=True):
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
    st.cache_data.clear() # Limpiamos caché
    st.rerun()

# --- 3. FUNCIONES DE DATOS ---

def cargar_excel_ssr(file):
    """Procesa el Excel de SSR específico que subiste"""
    try:
        df = pd.read_excel(file)
        
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
        
        if not all(col in df.columns for col in col_map.keys()):
            st.error("El archivo no tiene las columnas esperadas del formato SSR Oficial.")
            return None

        records_to_insert = []
        progress_bar = st.progress(0)
        total_rows = len(df)
        
        for idx, row in df.iterrows():
            try:
                lat = float(str(row['COORD_GEOGRÁFICAS_LATITUD_SIRGAS_CHILE']).replace(',', '.'))
                lon = float(str(row['COORD_GEOGRÁFICAS_LONGITUD_SIRGAS_CHILE']).replace(',', '.'))
                
                detalles = {
                    "arranques": row.get('N°_ARRANQUES'),
                    "rut": row.get('RUT'),
                    "clasificacion": row.get('CLASIFICACIÓN_ART_106_D50'),
                    "beneficiarios": row.get('BENEFICIARIOS_ESTIMADOS', 0)
                }

                record = {
                    "nombre_oficial": row['NOMBRE_OFICIAL_SISTEMA'],
                    "tipo_punto": "SSR",
                    "region": row['REGIÓN'],
                    "comuna": row['COMUNA'],
                    "latitud": lat,
                    "longitud": lon,
                    "detalles": detalles,
                    "usuario_creador": st.session_state["user"].email
                }
                records_to_insert.append(record)
                
            except Exception as e:
                continue
            
            if idx % 100 == 0:
                progress_bar.progress(idx / total_rows)

        if records_to_insert:
            batch_size = 100
            for i in range(0, len(records_to_insert), batch_size):
                batch = records_to_insert[i:i + batch_size]
                supabase.table("puntos_territoriales").insert(batch).execute()
            
            progress_bar.progress(100)
            
            # Limpiamos caché forzosamente
            st.cache_data.clear()
            return len(records_to_insert)
        return 0

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
        return None

# --- SOLUCIÓN ROBUSTA: PAGINACIÓN ---
@st.cache_data(ttl=3600)
def obtener_puntos_cache():
    all_rows = []
    start = 0
    batch_size = 1000  # Pedimos de 1000 en 1000
    
    while True:
        # Consultamos el rango actual
        response = supabase.table("puntos_territoriales").select("*").range(start, start + batch_size - 1).execute()
        rows = response.data
        
        if not rows:
            break
            
        all_rows.extend(rows)
        
        if len(rows) < batch_size:
            break
            
        start += batch_size
        
    df = pd.DataFrame(all_rows)
    
    # Pre-procesamiento: Extraer columnas clave del JSON 'detalles' para facilitar filtrado
    if not df.empty and 'detalles' in df.columns:
        df['arranques'] = df['detalles'].apply(lambda x: x.get('arranques') if x else 0)
        df['clasificacion'] = df['detalles'].apply(lambda x: x.get('clasificacion') if x else 'S/I')
        df['beneficiarios'] = df['detalles'].apply(lambda x: x.get('beneficiarios') if x else 0)
        df['rut'] = df['detalles'].apply(lambda x: x.get('rut') if x else '')
    
    return df

# --- 4. INTERFAZ PRINCIPAL ---

def main_app():
    st.sidebar.title(f"Usuario: {st.session_state['user'].email}")
    
    if st.sidebar.button("🔄 Actualizar Datos"):
        st.cache_data.clear()
        st.rerun()

    if st.sidebar.button("Cerrar Sesión"):
        cerrar_sesion()

    tab1, tab2 = st.tabs(["🗺️ Mapa Territorial", "📂 Carga de Datos (Admin)"])

    # --- TAB 1: MAPA ---
    with tab1:
        st.title("Visor Territorial")
        
        # Cargamos datos
        df_base = obtener_puntos_cache()
        
        if not df_base.empty:
            # --- FILTROS ---
            st.markdown("### Filtros de Búsqueda")
            col1, col2, col3, col4 = st.columns(4)
            
            # 1. Filtro Región
            regiones = ["Todas"] + sorted(df_base['region'].dropna().unique().tolist())
            region_sel = col1.selectbox("Región", regiones)
            
            # Lógica cascada para Comuna
            if region_sel != "Todas":
                comunas = ["Todas"] + sorted(df_base[df_base['region'] == region_sel]['comuna'].dropna().unique().tolist())
            else:
                comunas = ["Todas"] + sorted(df_base['comuna'].dropna().unique().tolist())
            
            # 2. Filtro Comuna
            comuna_sel = col2.selectbox("Comuna", comunas)
            
            # 3. Filtro Clasificación (Nuevo)
            clasificaciones = ["Todas"] + sorted(df_base['clasificacion'].astype(str).unique().tolist())
            clasif_sel = col3.selectbox("Clasificación SSR", clasificaciones)

            # 4. Buscador por Nombre (Nuevo)
            search_txt = col4.text_input("Buscar por Nombre", "")

            # --- APLICAR FILTROS ---
            df_show = df_base.copy()
            if region_sel != "Todas":
                df_show = df_show[df_show['region'] == region_sel]
            if comuna_sel != "Todas":
                df_show = df_show[df_show['comuna'] == comuna_sel]
            if clasif_sel != "Todas":
                df_show = df_show[df_show['clasificacion'] == clasif_sel]
            if search_txt:
                df_show = df_show[df_show['nombre_oficial'].str.contains(search_txt, case=False, na=False)]
                
            # Métricas
            st.caption(f"Visualizando {len(df_show)} registros")
            
            # --- MAPA ---
            if not df_show.empty:
                avg_lat = df_show['latitud'].mean()
                avg_lon = df_show['longitud'].mean()
                
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=6 if region_sel == "Todas" else 10, tiles=None)
                
                folium.TileLayer(
                    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
                    attr='Google',
                    name='Google Hybrid',
                    overlay=False,
                    control=True
                ).add_to(m)

                marker_cluster = MarkerCluster().add_to(m)
                
                # Limitamos marcadores si son demasiados para no pegar el navegador (opcional, aquí pongo todos)
                for idx, row in df_show.iterrows():
                    detalles = row['detalles'] if row['detalles'] else {}
                    arranques = detalles.get('arranques', 'S/I')
                    tipo = row['tipo_punto']
                    
                    html_popup = f"""
                    <div style="font-family: sans-serif; min-width: 150px;">
                        <b>{row['nombre_oficial']}</b><br>
                        <hr style="margin: 5px 0;">
                        Tipo: {tipo}<br>
                        Arranques: {arranques}<br>
                        <i>{row['comuna']}</i>
                    </div>
                    """
                    
                    folium.Marker(
                        location=[row['latitud'], row['longitud']],
                        popup=html_popup,
                        tooltip=row['nombre_oficial'],
                        icon=folium.Icon(color="blue" if tipo == "SSR" else "red", icon="info-sign")
                    ).add_to(marker_cluster)
                
                st_folium(m, width="100%", height=600)
            else:
                st.warning("No hay datos con esos filtros.")

            # --- TABLA DE DATOS (NUEVA SECCIÓN) ---
            st.markdown("---")
            st.subheader("📋 Detalle de Registros")
            
            if not df_show.empty:
                # Preparamos dataframe limpio para mostrar
                df_display = df_show[[
                    'region', 'comuna', 'nombre_oficial', 'tipo_punto', 
                    'arranques', 'clasificacion', 'rut', 'beneficiarios'
                ]].copy()
                
                # Renombrar columnas para que se vean bonitas
                df_display.columns = [
                    'Región', 'Comuna', 'Nombre Oficial', 'Tipo', 
                    'Arranques', 'Clasificación', 'RUT', 'Beneficiarios'
                ]
                
                # Ordenar por defecto: Región -> Comuna
                df_display = df_display.sort_values(by=['Región', 'Comuna'])
                
                # Mostrar tabla interactiva moderna
                st.dataframe(
                    df_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Arranques": st.column_config.NumberColumn(format="%d"),
                        "Beneficiarios": st.column_config.NumberColumn(format="%d"),
                    }
                )
            else:
                st.info("No hay datos para mostrar en la tabla.")

        else:
            st.info("La base de datos está vacía. Ve a la pestaña de Carga.")

    # --- TAB 2: CARGA DE DATOS ---
    with tab2:
        st.header("Gestión de Datos")
        st.write("Sube el archivo Excel oficial de SSR para poblar la base de datos.")
        
        uploaded_file = st.file_uploader("Cargar BD_SSR_OFICIAL.xlsx", type=["xlsx"])
        
        if uploaded_file:
            if st.button("Procesar y Guardar en BD"):
                with st.spinner("Procesando archivo..."):
                    count = cargar_excel_ssr(uploaded_file)
                    if count is not None:
                        st.success(f"¡Éxito! Se han cargado {count} registros nuevos.")
                        time.sleep(2)
                        st.rerun()

# --- 5. EJECUCIÓN ---
if "user" not in st.session_state:
    mostrar_login()
else:
    main_app()
