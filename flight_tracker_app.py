# -*- coding: utf-8 -*-
"""
Flight-Tracker App
Estimativa de tempo de voo teórico e rastreamento em tempo real de aeronaves.
"""

# ========================
# Importação de Bibliotecas
# ========================
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from airportsdata import load
from math import radians, sin, cos, sqrt, atan2
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
from opensky_api import OpenSkyApi

# ========================
# Configuração do App
# ========================
st.set_page_config(page_title="Flight-Tracker", layout="wide")
st.title("✈️ Flight-Tracker")
st.markdown("Estimativa de tempo de voo teórico e rastreamento em tempo real de aeronaves.")

# ========================
# Carregar dados dos aeroportos
# ========================
airports = load('ICAO')
df_airports = pd.DataFrame(airports).T.dropna(subset=['lat', 'lon'])

# ========================
# Funções de Cálculo
# ========================

def calcular_distancia(lat1, lon1, lat2, lon2):
    return geodesic((lat1, lon1), (lat2, lon2)).kilometers
    """Calcula distância geográfica entre dois pontos."""
    R = 6371  # raio da Terra em km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def calcular_perfil_de_voo(
    distancia_total_km: float,
    tipo_aeronave: str = None,
    vel_custom: float = None,
    altitude_cruzeiro_ft: int = None,
    vel_subida_kmh: float = None,
    vel_cruzeiro_kmh: float = None,
    vel_descida_kmh: float = None,
    razao_subida_fpm: int = None,
    razao_descida_fpm: int = None
):
    """
    Calcula o perfil de voo considerando parâmetros específicos da aeronave.
    """
    # Obter parâmetros da aeronave
    if tipo_aeronave in aeronaves:
        param = aeronaves[tipo_aeronave]
        altitude_cruzeiro_ft = param['altitude_cruzeiro_ft']
        vel_subida_kmh = param['vel_subida_kmh']
        vel_cruzeiro_kmh = param['vel_cruzeiro_kmh']
        vel_descida_kmh = param['vel_descida_kmh']
        razao_subida_fpm = param['razao_subida_fpm']
        razao_descida_fpm = param['razao_descida_fpm']
    elif tipo_aeronave == 'Custom':
        if None in [vel_custom, altitude_cruzeiro_ft, razao_subida_fpm, razao_descida_fpm]:
            raise ValueError("Para aeronave custom, todos os parâmetros devem ser fornecidos")
        vel_subida_kmh = vel_custom
        vel_cruzeiro_kmh = vel_custom
        vel_descida_kmh = vel_custom
    else:
        raise ValueError("Tipo de aeronave não especificado corretamente")

    # Cálculos do perfil de voo
    tempo_subida_min = altitude_cruzeiro_ft / razao_subida_fpm
    tempo_descida_min = altitude_cruzeiro_ft / razao_descida_fpm

    tempo_subida_h = tempo_subida_min / 60
    tempo_descida_h = tempo_descida_min / 60

    d_subida_km = vel_subida_kmh * tempo_subida_h
    d_descida_km = vel_descida_kmh * tempo_descida_h

    d_cruzeiro_km = max(0, distancia_total_km - d_subida_km - d_descida_km)
    t_cruzeiro_h = d_cruzeiro_km / vel_cruzeiro_kmh if d_cruzeiro_km > 0 else 0

    tempo_total_h = tempo_subida_h + t_cruzeiro_h + tempo_descida_h

    return {
        "subida": {"dist_km": d_subida_km, "tempo_h": tempo_subida_h},
        "cruzeiro": {"dist_km": d_cruzeiro_km, "tempo_h": t_cruzeiro_h},
        "descida": {"dist_km": d_descida_km, "tempo_h": tempo_descida_h},
        "tempo_total_h": tempo_total_h,
        "altitude_cruzeiro_ft": altitude_cruzeiro_ft
    }

# ========================
# Parâmetros das Aeronaves (Atualizado)
# ========================
aeronaves = {
    'VC-1 (Airbus A319)': {
        'altitude_cruzeiro_ft': 35000,
        'vel_subida_kmh': 500,
        'vel_cruzeiro_kmh': 840,
        'vel_descida_kmh': 600,
        'razao_subida_fpm': 2000,
        'razao_descida_fpm': 1800,
        'subida_descida': 314
    },
    'VC-2 (Embraer 190)': {
        'altitude_cruzeiro_ft': 37000,
        'vel_subida_kmh': 480,
        'vel_cruzeiro_kmh': 820,
        'vel_descida_kmh': 580,
        'razao_subida_fpm': 2200,
        'razao_descida_fpm': 1800,
        'subida_descida': 268
    },
    'KC-30 (Airbus A330)': {
        'altitude_cruzeiro_ft': 41000,
        'vel_subida_kmh': 550,
        'vel_cruzeiro_kmh': 880,
        'vel_descida_kmh': 650,
        'razao_subida_fpm': 2000,
        'razao_descida_fpm': 2000,
        'subida_descida': 362
    }
}

# ========================
# Funções de Rastreamento
# ========================
def consultar_adsb_lol(icao24):
    """Consulta fallback na API ADSB.lol"""
    url = f"https://api.adsb.lol/v2/icao/{icao24.lower()}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("total", 0) > 0 and "ac" in data:
            ac = data["ac"][0]
            return {
                "latitude": ac.get("lat"),
                "longitude": ac.get("lon"),
                "velocity": ac.get("gs") * 1.852 if ac.get("gs") else None,  # knots → km/h
                "timestamp": datetime.utcnow(),
            }
        else:
            return None
    except:
        return None

# ========================
# Sidebar — Entrada de Dados (Atualizado)
# ========================
with st.sidebar:
    st.header("✈️ Dados do Voo")

    # Seleção da aeronave
    tipo_aeronave = st.selectbox(
        "Selecione a aeronave",
        options=list(aeronaves.keys()) + ['Custom']
    )

    if tipo_aeronave == 'Custom':
        vel_custom = st.number_input("Velocidade média (km/h)", min_value=100.0, max_value=1200.0, value=850.0)
        altitude_custom = st.number_input("Altitude de cruzeiro (ft)", min_value=10000, max_value=50000, value=35000)
        razao_subida_custom = st.number_input("Razão de subida (ft/min)", min_value=500, max_value=3000, value=2000)
        razao_descida_custom = st.number_input("Razão de descida (ft/min)", min_value=500, max_value=3000, value=1800)

    st.markdown("### 🚩 Selecione os aeroportos")

    # Escolha do método de seleção
    modo_selecao = st.radio(
        "Modo de seleção dos aeroportos:",
        ["Por código ICAO", "Por país e cidade"]
    )

    if modo_selecao == "Por código ICAO":
        origem = st.text_input("Código ICAO do aeroporto de origem", value="SBGR").upper()
        destino = st.text_input("Código ICAO do aeroporto de destino", value="SBRJ").upper()

    else:
        # Preparar dataframe
        df_ap = df_airports.copy()
        df_ap['country'] = df_ap['country'].fillna('Desconhecido')
        df_ap['city'] = df_ap['city'].fillna('Desconhecido')

        # Selecione a origem
        st.subheader("🛫 Origem")
        pais_origem = st.selectbox("País de origem", sorted(df_ap['country'].unique()))
        cidades_origem = sorted(df_ap[df_ap['country'] == pais_origem]['city'].unique())
        cidade_origem = st.selectbox("Cidade de origem", cidades_origem)

        opcoes_origem = df_ap[
            (df_ap['country'] == pais_origem) & (df_ap['city'] == cidade_origem)
        ]
        origem = st.selectbox(
            "Aeroporto de origem",
            opcoes_origem.index.map(lambda x: f"{x} — {opcoes_origem.loc[x]['name']}")
        ).split(' — ')[0]

        # Selecione o destino
        st.subheader("🛬 Destino")
        pais_destino = st.selectbox("País de destino", sorted(df_ap['country'].unique()))
        cidades_destino = sorted(df_ap[df_ap['country'] == pais_destino]['city'].unique())
        cidade_destino = st.selectbox("Cidade de destino", cidades_destino)

        opcoes_destino = df_ap[
            (df_ap['country'] == pais_destino) & (df_ap['city'] == cidade_destino)
        ]
        destino = st.selectbox(
            "Aeroporto de destino",
            opcoes_destino.index.map(lambda x: f"{x} — {opcoes_destino.loc[x]['name']}")
        ).split(' — ')[0]

    # Inserção do horário de partida
    partida_str = st.text_input(
        "Horário de partida (HH:MM) — Fuso de Brasília",
        value="10:00"
    )

    st.markdown("---")

    # Opção de rastrear em tempo real
    rastrear = st.checkbox("🔎 Ativar rastreamento em tempo real (ICAO24)")
    if rastrear:
        icao24 = st.text_input("Código ICAO24 da aeronave", value="e49102").lower()

    st.markdown("---")


# ========================
# Processamento da Estimativa Teórica (Atualizado)
# ========================
def obter_info_aeroporto(cod):
    return airports.get(cod)

# Validação dos aeroportos
origem_info = obter_info_aeroporto(origem)
destino_info = obter_info_aeroporto(destino)

if not origem_info or not destino_info:
    st.error("Código ICAO de origem ou destino inválido.")
    st.stop()

lat1, lon1 = origem_info['lat'], origem_info['lon']
lat2, lon2 = destino_info['lat'], destino_info['lon']
distancia = calcular_distancia(lat1, lon1, lat2, lon2)

# Tempo teórico
if tipo_aeronave in aeronaves:
    perfil = calcular_perfil_de_voo(
        distancia_total_km=distancia,
        tipo_aeronave=tipo_aeronave
    )
else:
    perfil = calcular_perfil_de_voo(
        distancia_total_km=distancia,
        tipo_aeronave='Custom',
        vel_custom=vel_custom,
        altitude_cruzeiro_ft=altitude_custom,
        razao_subida_fpm=razao_subida_custom,
        razao_descida_fpm=razao_descida_custom
    )

tempo_teorico = perfil['tempo_total_h']
altitude_cruzeiro = perfil['altitude_cruzeiro_ft']

horas = int(tempo_teorico)
minutos = int((tempo_teorico - horas) * 60)
tempo_formatado = f"{horas}h {minutos}min"

# Cálculo de chegada teórica
try:
    fuso_brasilia = ZoneInfo("America/Sao_Paulo")
    agora = datetime.now(fuso_brasilia)
    partida_h, partida_m = map(int, partida_str.split(":"))
    partida = agora.replace(hour=partida_h, minute=partida_m, second=0, microsecond=0)
    chegada_teorica = partida + timedelta(hours=tempo_teorico)
except:
    st.error("Horário de partida inválido.")
    st.stop()

# ========================
# Exibir Resultado da Estimativa Teórica
# ========================
st.subheader("🧠 Estimativa Teórica")
st.markdown(f"""
- **Origem:** {origem} — {origem_info['name']} ({origem_info['city']}, {origem_info['country']})
- **Destino:** {destino} — {destino_info['name']} ({destino_info['city']}, {destino_info['country']})
- **Distância:** {distancia:.2f} km
- **Altitude de cruzeiro:** {altitude_cruzeiro:,} ft
- **Tempo estimado de voo:** {tempo_formatado}
- **Previsão de chegada (horário Brasília):** {chegada_teorica.strftime('%H:%M')}
""")

# ========================
# Rastreamento em Tempo Real (Atualizado)
# ========================
dados_validos = False
posicao = None

if rastrear:
    api = OpenSkyApi()

    with st.spinner("🔍 Buscando dados em tempo real..."):
        state = None
        try:
            states = api.get_states(icao24=icao24)
            if states and states.states:
                state = states.states[0]
                if state.latitude and state.longitude and state.velocity:
                    dados_validos = True
                    posicao = (state.latitude, state.longitude)
                    velocidade_kmh = state.velocity * 3.6
                else:
                    dados_validos = False
            else:
                dados_validos = False
        except:
            dados_validos = False

        if not dados_validos:
            fallback = consultar_adsb_lol(icao24)
            if fallback and fallback["latitude"] and fallback["longitude"] and fallback["velocity"]:
                posicao = (fallback["latitude"], fallback["longitude"])
                velocidade_kmh = fallback["velocity"]
                dados_validos = True
                st.info("✅ Dados via fallback (ADSB.lol)")
            else:
                st.warning("⚠️ Dados não encontrados. Tentando novamente em 10 segundos...")

        if dados_validos:
            distancia_restante = geodesic(posicao, (lat2, lon2)).kilometers
        
            # Obter altitude atual
            try:
                altitude_atual_ft = state.baro_altitude * 3.28084 if state and state.baro_altitude else altitude_cruzeiro
            except:
                altitude_atual_ft = altitude_cruzeiro
        
            # Obter parâmetros da aeronave
            if tipo_aeronave in aeronaves:
                param = aeronaves[tipo_aeronave]
                vel_subida = param['vel_subida_kmh']
                vel_cruzeiro = param['vel_cruzeiro_kmh']
                vel_descida = param['vel_descida_kmh']
            else:
                vel_subida = vel_custom
                vel_cruzeiro = vel_custom
                vel_descida = vel_custom
        
            # Determinar fase de voo
            if distancia_restante < 150:
                fase = "descida"
            elif altitude_atual_ft < 0.85 * altitude_cruzeiro:
                fase = "subida"
            else:
                fase = "cruzeiro"
        
            # Cálculo adaptativo
            if fase == "descida":
                tempo_h = distancia_restante / vel_descida
            elif fase == "cruzeiro":
                tempo_h = distancia_restante / vel_cruzeiro
            else:  # Subida + cruzeiro + descida (voos muito longos ainda subindo)
                perfil_real = calcular_perfil_de_voo(
                    distancia_total_km=distancia_restante,
                    tipo_aeronave=tipo_aeronave,
                    vel_custom=vel_custom if tipo_aeronave == 'Custom' else None,
                    altitude_cruzeiro_ft=altitude_cruzeiro
                )
                tempo_h = perfil_real['tempo_total_h']
        
            tempo_estimado = timedelta(hours=tempo_h)
        
            # ETA
            hora_chegada_utc = datetime.utcnow().replace(tzinfo=timezone.utc) + tempo_estimado
            hora_brasilia = hora_chegada_utc.astimezone(ZoneInfo("America/Sao_Paulo"))
            hora_destino = hora_chegada_utc.astimezone(ZoneInfo(destino_info['tz']))
        
            # Mostrar dados
            st.subheader("📡 Rastreamento em Tempo Real")
            st.markdown(f"""
            - **Posição atual:** Lat {posicao[0]:.4f}, Lon {posicao[1]:.4f}
            - **Altitude atual:** {altitude_atual_ft:,.0f} ft
            - **Velocidade:** {velocidade_kmh:.2f} km/h
            - **Distância até o destino:** {distancia_restante:.2f} km
            - **Fase estimada:** {fase.title()}
            - **ETA (UTC):** {hora_chegada_utc.strftime('%H:%M:%S')}
            - **ETA (Brasília):** {hora_brasilia.strftime('%H:%M:%S')}
            - **ETA ({destino_info['tz']}):** {hora_destino.strftime('%H:%M:%S')}
            - **Tempo restante:** {str(tempo_estimado).split('.')[0]}
            """)

# ========================
# Autorefresh — Atualização Automática
# ========================
if rastrear:
    if dados_validos:
        st_autorefresh(interval=300000, limit=None, key="refresh")  # 5 minutos
    else:
        st_autorefresh(interval=10000, limit=None, key="refresh")   # 10 segundos

# ========================
# Mapa Interativo Aprimorado
# ========================
st.subheader("🗺️ Mapa do Voo")

# Calcular o bounding box para enquadrar toda a rota
margin = 1.5  # graus de margem ao redor da rota
min_lat = min(lat1, lat2) - margin
max_lat = max(lat1, lat2) + margin
min_lon = min(lon1, lon2) - margin
max_lon = max(lon1, lon2) + margin

# Criar o mapa com dimensões maiores e zoom ajustado automaticamente
mapa = folium.Map(
    location=[(lat1 + lat2) / 2, (lon1 + lon2) / 2],
    zoom_start=5,
    width='100%',
    height=600,
    control_scale=True
)

# Adicionar marcadores e linha de rota
folium.Marker(
    [lat1, lon1], 
    popup=f"Origem: {origem}",
    icon=folium.Icon(color="green", icon="plane-departure", prefix="fa")
).add_to(mapa)

folium.Marker(
    [lat2, lon2], 
    popup=f"Destino: {destino}",
    icon=folium.Icon(color="red", icon="plane-arrival", prefix="fa")
).add_to(mapa)

folium.PolyLine(
    locations=[[lat1, lon1], [lat2, lon2]], 
    color='blue',
    weight=3,
    dash_array='5, 5'
).add_to(mapa)

# Adicionar aeronave se estiver sendo rastreada
if rastrear and dados_validos:
    folium.Marker(
        location=posicao,
        popup=f"Aeronave {icao24.upper()}",
        icon=folium.Icon(color="blue", icon="plane", prefix="fa")
    ).add_to(mapa)
    
    # Adicionar linha da posição atual até o destino
    folium.PolyLine(
        locations=[posicao, [lat2, lon2]], 
        color='orange',
        weight=2,
        dash_array='10, 5'
    ).add_to(mapa)

# Ajustar os limites do mapa para enquadrar toda a rota
mapa.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

# Usar st_folium com parâmetro key para evitar redesenho desnecessário
st_map = st_folium(
    mapa, 
    width=1000, 
    height=600,
    key=f"map_{origem}_{destino}_{icao24 if rastrear else 'no_tracking'}"
)