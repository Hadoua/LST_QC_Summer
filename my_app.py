import streamlit as st
import rioxarray
import geopandas as gpd
import leafmap.foliumap as leafmap
import folium
import os
import numpy as np
from shapely.geometry import box
from branca.element import Element
import matplotlib.colors as mcolors
from shapely import wkt

st.set_page_config(layout="wide", page_title="Thermal Analysis Quebec") # centered / wide

st.markdown("""
    <style>
        .block-container {
            /* Padding: Haut(0) | Droite(2rem) | Bas(0) | Gauche(2rem) */
            padding: 0rem 2rem 0rem 2rem; 
            max-width: 1300px;
        }
    </style>
""", unsafe_allow_html=True)

MAPBOX_TOKEN = st.secrets["MAPBOX_TOKEN"]
ID_GAUCHE = "guts3644.1jaipybb"
ID_DROITE = "guts3644.4u4wzcjc"

@st.cache_resource
def load_data():
    try:
        gdf = gpd.read_file("vdq-quartier.geojson")
        img_avant = rioxarray.open_rasterio("temp_avant.tif").squeeze() if os.path.exists("temp_avant.tif") else None
        img_apres = rioxarray.open_rasterio("temp_apres.tif").squeeze() if os.path.exists("temp_apres.tif") else None
        return gdf, img_avant, img_apres
    except Exception as e:
        st.error(f"Erreur : {e}")
        return None, None, None

@st.cache_data
def get_mask_geojson(wkt_str):
    """
    Génère un masque géométrique inversé (le monde entier MOINS le quartier sélectionné).

    En mode "Swipe Map", nous utilisons des tuiles Mapbox (XYZ tiles) qui sont des images 
    statiques qu'on ne peut découper. Je veux superposer un polygone semi-transparent qui couvre 
    toute la Terre SAUF la zone d'intérêt et donc avoir un effet visuel "focus" 
    """
    
    quartier_geom = wkt.loads(wkt_str) # text to geometry
    world_box = box(-180, -90, 180, 90)
    mask_geom = world_box.difference(quartier_geom) # world - quatier selectionné
    return gpd.GeoSeries([mask_geom]).set_crs("EPSG:4326")


@st.cache_data
def process_evolution_layer(choix_q):
    """
    Valeurs de LST avant et après en classes
    """
    
    target_geom = gdf[gdf['NOM'] == choix_q] if choix_q != "Quebec City (Overview)" else gdf
    
    img1_clip = img_avant.rio.clip(target_geom.geometry, target_geom.crs, drop=True)
    img2_clip = img_apres.rio.clip(target_geom.geometry, target_geom.crs, drop=True)
    
    delta = img2_clip - img1_clip # delta, > 0 il fait plus chaud, < 0 plus froid
    delta_web = delta.rio.reproject("EPSG:3857") # pour les pixels

    # Classe 0 : inf à -6°C | Classe 1 : -6°C à -4°C | Classe 2 : -4°C à -2°C | Classe 3 : -2°C à -1°C | Classe 4 : -1°C à +1°C | Classe 5 : +1°C à +2°C 
    # Classe 6 : +2°C à +4°C | Classe 7 : +4°C à +6°C | Classe 8 : sup à +6°C
    bins = [-6, -4, -2, -1, 1, 2, 4, 6]
    colors_hex = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#ffffff", "#fdae61", "#f46d43", "#d73027", "#a50026"]
    
    delta_np = delta_web.values
    classified = np.digitize(np.nan_to_num(delta_np, nan=np.nan), bins).astype(float)
    
    rgba_evo = np.zeros((classified.shape[0], classified.shape[1], 4))
    for i, color in enumerate(colors_hex):
        if i == 4: continue # on ne fait rien 
        mask = (classified == i) & (~np.isnan(delta_np))
        rgba_evo[mask, :3] = mcolors.to_rgb(color)
        rgba_evo[mask, 3] = 0.8 #transparence 20%

    delta_4326 = delta.rio.reproject("EPSG:4326") # pour les coins
    bounds = [[float(delta_4326.rio.bounds()[1]), float(delta_4326.rio.bounds()[0])], 
              [float(delta_4326.rio.bounds()[3]), float(delta_4326.rio.bounds()[2])]]
        
    return rgba_evo, bounds

gdf, img_avant, img_apres = load_data()
if gdf is None: st.stop()

st.write("Choose display mode")

mode_selection = st.radio(
    "# Choose display mode:", 
    ["Swipe Map", "Evolution"], 
    horizontal=True,
    label_visibility="collapsed"
)


st.write("Drag the slider to compare and use the filter to zoom to areas of interest")

# [image, selectbox, Espace, image, selectbox, Espace, image, Toggle]
cols = st.columns([1.3, 4, 0.2, 1.3, 4, 0.2, 1.3, 3], vertical_alignment="center")

with cols[0]: st.image("https://img.icons8.com/ios/50/ffffff/map-marker.png", width=50) 
with cols[1]:
    quartiers = ["Quebec City (Overview)"] + sorted(gdf['NOM'].unique())
    choix_q = st.selectbox("Zone", quartiers, label_visibility="collapsed", key="q_select")

with cols[3]: st.image("https://img.icons8.com/ios/50/ffffff/layers.png", width=50) 
with cols[4]:
    basemaps = ["SATELLITE", "Google Maps", "CartoDB.DarkMatter"]
    choix_fond = st.selectbox("Fond de carte", basemaps, label_visibility="collapsed", index=1)

with cols[6]: st.image("https://img.icons8.com/ios/50/ffffff/polygon.png", width=50) 
with cols[7]: 
    show_limits = st.toggle("Limites", value=True)

st.divider()

is_focus = choix_q != "Quebec City (Overview)"

if is_focus:
    target = gdf[gdf['NOM'] == choix_q]
    centroid = target.geometry.centroid.iloc[0]
    center = [centroid.y, centroid.x]
    zoom = 13
    mask_geojson = get_mask_geojson(target.geometry.iloc[0].wkt)
else:
    target = gdf
    global_centroid = gdf.geometry.union_all().centroid
    center = [global_centroid.y, global_centroid.x]
    zoom = 11
    mask_geojson = None

m = leafmap.Map(
    center=center,
    zoom=zoom, 
    draw_control=False, measure_control=False, fullscreen_control=False, layers_control=False,
)
m.add_basemap(choix_fond) 

if mode_selection == "Swipe Map":
    url_left = f"https://api.mapbox.com/v4/{ID_GAUCHE}/{{z}}/{{x}}/{{y}}.png?access_token={MAPBOX_TOKEN}"
    url_right = f"https://api.mapbox.com/v4/{ID_DROITE}/{{z}}/{{x}}/{{y}}.png?access_token={MAPBOX_TOKEN}"
    
    style_lbl = "font-size: 25px; font-weight: 900; color: white; text-shadow: 2px 2px 4px #000000;"
    
    m.split_map(
        left_layer=url_left, right_layer=url_right,
        left_label=f'<span style="{style_lbl}">2013-2019</span>', 
        right_label=f'<span style="{style_lbl}">2020-2025</span>'
    )
    
    val_min = 7.0
    val_max = 53.7

    legend_swipe_html = f"""
    <div style="position: fixed; top: 50px; right: 50px; width: 250px; z-index: 9999; background-color: rgba(38, 39, 48, 0.95); border: 1px solid #444; border-radius: 8px; padding: 10px; color: white; font-family: sans-serif;">
        <div style="font-size: 13px; font-weight: bold; text-align: center; margin-bottom: 8px;">Land Surface Temperature (&deg;C)</div>
        <div style="width: 100%; height: 18px; border-radius: 4px; border: 1px solid #666; margin-bottom: 4px; background: linear-gradient(to right, #313695, #74add1, #e0f3f8, #fee090, #f46d43, #a50026);"></div>
        <div style="display: flex; justify-content: space-between; font-size: 12px; color: #fff; font-weight: bold;">
            <span>{val_min}&deg;C</span>
            <span>{val_max}&deg;C</span>
        </div>
    </div>
    """
    m.get_root().html.add_child(Element(legend_swipe_html))
    
else:
    try:
        rgba_evo, bounds = process_evolution_layer(choix_q)  
        folium.raster_layers.ImageOverlay(image=rgba_evo, bounds=bounds, name='Evolution').add_to(m)

        colors_hex = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#ffffff", "#fdae61", "#f46d43", "#d73027", "#a50026"]
        segments_html = ""
        for i, c in enumerate(colors_hex):
            if i == 4:
                segments_html += f'''<div style="width: 11.11%; height: 100%; float: left; background-image: linear-gradient(45deg, #808080 25%, transparent 25%), linear-gradient(-45deg, #808080 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #808080 75%), linear-gradient(-45deg, transparent 75%, #808080 75%); background-size: 10px 10px; background-color: #444;"></div>'''
            else:
                segments_html += f'<div style="width: 11.11%; height: 100%; float: left; background-color: {c};"></div>'

        legend_html = f"""
        <div style="position: fixed; bottom: 50px; left: 50px; width: 300px; z-index: 9999; background-color: rgba(38, 39, 48, 0.95); border: 1px solid #444; border-radius: 8px; padding: 10px; color: white; font-family: sans-serif;">
            <div style="font-size: 13px; font-weight: bold; text-align: center; margin-bottom: 8px;">LST diff. : (&deg;C)</div>
            <div style="width: 100%; height: 18px; border-radius: 4px; overflow: hidden; border: 1px solid #666; margin-bottom: 4px;">{segments_html}</div>
            <div style="position: relative; width: 100%; height: 20px; font-size: 10px; color: #ccc;">
                <span style="position: absolute; left: 11.11%; transform: translateX(-50%);">-6</span>
                <span style="position: absolute; left: 22.22%; transform: translateX(-50%);">-4</span>
                <span style="position: absolute; left: 33.33%; transform: translateX(-50%);">-2</span>
                <span style="position: absolute; left: 44.44%; transform: translateX(-50%);">-1</span>
                <span style="position: absolute; left: 50%; transform: translateX(-50%); color: #fff; font-weight: bold; top: 10px;">Stable</span>
                <span style="position: absolute; left: 55.55%; transform: translateX(-50%);">+1</span>
                <span style="position: absolute; left: 66.66%; transform: translateX(-50%);">+2</span>
                <span style="position: absolute; left: 77.77%; transform: translateX(-50%);">+4</span>
                <span style="position: absolute; left: 88.88%; transform: translateX(-50%);">+6</span>
            </div>
        </div>
        """
        m.get_root().html.add_child(Element(legend_html))

    except Exception as e:
        st.error(f"Erreur : {e}")

if show_limits:
    if is_focus and mask_geojson is not None:
        folium.GeoJson(
            mask_geojson,
            style_function=lambda x: {'fillColor': '#000000', 'color': 'black', 'weight': 4, 'dashArray': '5, 5', 'fillOpacity': 0.8, 'interactive': False},
            name="Masque Focus"
        ).add_to(m)
    else:
        folium.GeoJson(
            target.__geo_interface__, 
            style_function=lambda x: {'color': 'black', 'weight': 4, 'fillOpacity': 0, 'dashArray': '5, 5'}, 
            name="Boundaries"
        ).add_to(m)

m.to_streamlit(height=500)
