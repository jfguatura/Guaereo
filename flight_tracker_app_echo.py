# -*- coding: utf-8 -*-
"""
Flight-Tracker App — Echo
Estimativa de tempo de voo teórico e rastreamento em tempo real de aeronaves.

Correções aplicadas nesta versão:
  1. Mapa sem refresh desnecessário — reconstruído apenas quando origem/destino/posição mudam
  2. Cadeia de APIs ampliada: airplanes.live (primária) → ADSB.lol → OpenSky (fallback)
  3. NameError em vel_custom corrigido — variável inicializada antes do bloco condicional
  4. Campo 'subida_descida' removido do catálogo de aeronaves (era declarado mas nunca usado)
  5. Heurística de fase de voo corrigida para voos curtos (sem cruzeiro)
  6. ZoneInfo com fallback para UTC quando timezone do destino é inválida
"""

# ========================
# Importação de Bibliotecas
# ========================
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from airportsdata import load
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium

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
# Parâmetros das Aeronaves
# CORREÇÃO 4: campo 'subida_descida' removido — era declarado mas nunca utilizado
# ========================

REDUTOR = 0.9

aeronaves = {
    'VC-1 (Airbus A319)': {
        'altitude_cruzeiro_ft': 35000,
        'vel_subida_kmh':   500 * REDUTOR,
        'vel_cruzeiro_kmh': 840 * REDUTOR,
        'vel_descida_kmh':  600 * REDUTOR,
        'razao_subida_fpm': 2000,
        'razao_descida_fpm': 1800,
    },
    'VC-2 (Embraer 190)': {
        'altitude_cruzeiro_ft': 37000,
        'vel_subida_kmh':   480 * REDUTOR,
        'vel_cruzeiro_kmh': 820 * REDUTOR,
        'vel_descida_kmh':  580 * REDUTOR,
        'razao_subida_fpm': 2200,
        'razao_descida_fpm': 1800,
    },
    'KC-30 (Airbus A330)': {
        'altitude_cruzeiro_ft': 41000,
        'vel_subida_kmh':   550 * REDUTOR,
        'vel_cruzeiro_kmh': 880 * REDUTOR,
        'vel_descida_kmh':  650 * REDUTOR,
        'razao_subida_fpm': 2000,
        'razao_descida_fpm': 2000,
    },
}

# ========================
# Funções de Cálculo
# ========================

def calcular_distancia(lat1, lon1, lat2, lon2):
    """Calcula distância geográfica entre dois pontos em km."""
    return geodesic((lat1, lon1), (lat2, lon2)).kilometers


def calcular_perfil_de_voo(
    distancia_total_km: float,
    tipo_aeronave: str = None,
    vel_custom: float = None,
    altitude_cruzeiro_ft: int = None,
    vel_subida_kmh: float = None,
    vel_cruzeiro_kmh: float = None,
    vel_descida_kmh: float = None,
    razao_subida_fpm: int = None,
    razao_descida_fpm: int = None,
):
    """
    Calcula o perfil de voo considerando parâmetros específicos da aeronave.

    CORREÇÃO 5: trata corretamente voos curtos onde a soma das fases de subida
    e descida ultrapassa a distância total (sem fase de cruzeiro real).
    Retorna dict com subida, cruzeiro, descida, tempo_total_h e altitude_cruzeiro_ft.
    """
    # Obter parâmetros conforme o tipo de aeronave
    if tipo_aeronave in aeronaves:
        param = aeronaves[tipo_aeronave]
        altitude_cruzeiro_ft = param['altitude_cruzeiro_ft']
        vel_subida_kmh       = param['vel_subida_kmh']
        vel_cruzeiro_kmh     = param['vel_cruzeiro_kmh']
        vel_descida_kmh      = param['vel_descida_kmh']
        razao_subida_fpm     = param['razao_subida_fpm']
        razao_descida_fpm    = param['razao_descida_fpm']
    elif tipo_aeronave == 'Custom':
        if None in [vel_custom, altitude_cruzeiro_ft, razao_subida_fpm, razao_descida_fpm]:
            raise ValueError("Para aeronave Custom, todos os parâmetros devem ser fornecidos.")
        vel_subida_kmh   = vel_custom
        vel_cruzeiro_kmh = vel_custom
        vel_descida_kmh  = vel_custom
    else:
        raise ValueError("Tipo de aeronave não especificado corretamente.")

    # Tempos de subida e descida (em horas)
    tempo_subida_h  = (altitude_cruzeiro_ft / razao_subida_fpm) / 60
    tempo_descida_h = (altitude_cruzeiro_ft / razao_descida_fpm) / 60

    # Distâncias percorridas nas fases extremas
    d_subida_km  = vel_subida_kmh  * tempo_subida_h
    d_descida_km = vel_descida_kmh * tempo_descida_h

    # CORREÇÃO 5: voo curto — subida e descida somadas superam a distância total
    d_fases_extremas = d_subida_km + d_descida_km
    if distancia_total_km <= d_fases_extremas:
        # Sem fase de cruzeiro: distribui proporcionalmente
        proporcao = distancia_total_km / d_fases_extremas
        d_subida_km   = d_subida_km  * proporcao
        d_descida_km  = d_descida_km * proporcao
        tempo_subida_h  = d_subida_km  / vel_subida_kmh  if vel_subida_kmh  > 0 else 0
        tempo_descida_h = d_descida_km / vel_descida_kmh if vel_descida_kmh > 0 else 0
        d_cruzeiro_km = 0.0
        t_cruzeiro_h  = 0.0
    else:
        d_cruzeiro_km = distancia_total_km - d_fases_extremas
        t_cruzeiro_h  = d_cruzeiro_km / vel_cruzeiro_kmh if vel_cruzeiro_kmh > 0 else 0

    tempo_total_h = tempo_subida_h + t_cruzeiro_h + tempo_descida_h

    return {
        "subida":   {"dist_km": d_subida_km,   "tempo_h": tempo_subida_h},
        "cruzeiro": {"dist_km": d_cruzeiro_km,  "tempo_h": t_cruzeiro_h},
        "descida":  {"dist_km": d_descida_km,   "tempo_h": tempo_descida_h},
        "tempo_total_h":      tempo_total_h,
        "altitude_cruzeiro_ft": altitude_cruzeiro_ft,
    }


# ========================
# Funções de Rastreamento
# ========================

def consultar_airplanes_live(icao24: str) -> dict | None:
    """
    Fonte primária: airplanes.live — gratuita, sem chave, 1 req/s.
    Endpoint: https://api.airplanes.live/v2/hex/{icao24}
    Retorna dict com latitude, longitude, velocity (km/h) e altitude_ft, ou None.
    """
    url = f"https://api.airplanes.live/v2/hex/{icao24.lower()}"
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        ac_list = data.get("ac", [])
        if not ac_list:
            return None
        ac = ac_list[0]
        lat = ac.get("lat")
        lon = ac.get("lon")
        gs  = ac.get("gs")          # ground speed em knots
        alt = ac.get("alt_baro")    # altitude barométrica em ft (pode ser "ground")
        if lat is None or lon is None:
            return None
        altitude_ft = None
        if isinstance(alt, (int, float)):
            altitude_ft = float(alt)
        return {
            "latitude":   float(lat),
            "longitude":  float(lon),
            "velocity":   float(gs) * 1.852 if gs is not None else None,  # knots → km/h
            "altitude_ft": altitude_ft,
            "fonte":      "airplanes.live",
        }
    except Exception:
        return None


def consultar_adsb_lol(icao24: str) -> dict | None:
    """
    Fonte secundária: ADSB.lol — gratuita, open-source, sem chave obrigatória.
    Retorna dict com latitude, longitude, velocity (km/h) e altitude_ft, ou None.
    """
    url = f"https://api.adsb.lol/v2/icao/{icao24.lower()}"
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        if data.get("total", 0) == 0 or "ac" not in data:
            return None
        ac = data["ac"][0]
        lat = ac.get("lat")
        lon = ac.get("lon")
        gs  = ac.get("gs")
        alt = ac.get("alt_baro")
        if lat is None or lon is None:
            return None
        altitude_ft = None
        if isinstance(alt, (int, float)):
            altitude_ft = float(alt)
        return {
            "latitude":   float(lat),
            "longitude":  float(lon),
            "velocity":   float(gs) * 1.852 if gs is not None else None,  # knots → km/h
            "altitude_ft": altitude_ft,
            "fonte":      "ADSB.lol",
        }
    except Exception:
        return None


def consultar_opensky_rest(icao24: str, username=None, password=None) -> dict | None:
    """
    Fonte terciária (fallback): OpenSky Network REST.
    Frequentemente instável; mantido como último recurso.
    Retorna dict com latitude, longitude, velocity (km/h) e altitude_ft, ou None.
    """
    url = "https://opensky-network.org/api/states/all"
    params = {"icao24": icao24.lower()}
    try:
        resp = requests.get(
            url,
            params=params,
            timeout=10,
            auth=(username, password) if username and password else None,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("states"):
            return None
        state = data["states"][0]
        longitude    = state[5]
        latitude     = state[6]
        baro_alt_m   = state[7]   # metros
        velocity_ms  = state[9]   # m/s
        if latitude is None or longitude is None or velocity_ms is None:
            return None
        return {
            "latitude":   float(latitude),
            "longitude":  float(longitude),
            "velocity":   float(velocity_ms) * 3.6,                                    # m/s → km/h
            "altitude_ft": float(baro_alt_m) * 3.28084 if baro_alt_m is not None else None,
            "fonte":      "OpenSky",
        }
    except Exception:
        return None


def consultar_aeronave(icao24: str) -> dict | None:
    """
    Orquestra as três fontes em cascata:
      1. airplanes.live  (primária — mais confiável e estável)
      2. ADSB.lol        (secundária — open-source)
      3. OpenSky REST    (terciária — instável, último recurso)
    Retorna o primeiro resultado válido ou None se todas falharem.
    """
    for consultor in [consultar_airplanes_live, consultar_adsb_lol, consultar_opensky_rest]:
        resultado = consultor(icao24)
        if resultado and resultado.get("latitude") and resultado.get("longitude"):
            return resultado
    return None


# ========================
# Utilitário de fuso horário
# CORREÇÃO 6: ZoneInfo com fallback para UTC quando timezone do destino é inválida
# ========================

def timezone_segura(tz_str: str) -> ZoneInfo:
    """Retorna ZoneInfo para tz_str, com fallback para UTC se inválida."""
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError, Exception):
        return ZoneInfo("UTC")


# ========================
# Sidebar — Entrada de Dados
# CORREÇÃO 3: vel_custom inicializado como None antes de qualquer bloco condicional
# ========================
with st.sidebar:
    st.header("✈️ Dados do Voo")

    # Seleção da aeronave
    tipo_aeronave = st.selectbox(
        "Selecione a aeronave",
        options=list(aeronaves.keys()) + ['Custom'],
    )

    # CORREÇÃO 3: variáveis Custom inicializadas com None — evita NameError
    vel_custom          = None
    altitude_custom     = None
    razao_subida_custom = None
    razao_descida_custom = None

    if tipo_aeronave == 'Custom':
        vel_custom           = st.number_input("Velocidade média (km/h)",       min_value=100.0,  max_value=1200.0, value=850.0)
        altitude_custom      = st.number_input("Altitude de cruzeiro (ft)",     min_value=10000,  max_value=50000,  value=35000)
        razao_subida_custom  = st.number_input("Razão de subida (ft/min)",      min_value=500,    max_value=3000,   value=2000)
        razao_descida_custom = st.number_input("Razão de descida (ft/min)",     min_value=500,    max_value=3000,   value=1800)

    st.markdown("### 🚩 Selecione os aeroportos")

    modo_selecao = st.radio(
        "Modo de seleção dos aeroportos:",
        ["Por código ICAO", "Por país e cidade"],
    )

    if modo_selecao == "Por código ICAO":
        origem  = st.text_input("Código ICAO do aeroporto de origem",  value="SBGR").upper()
        destino = st.text_input("Código ICAO do aeroporto de destino", value="SBRJ").upper()
    else:
        df_ap = df_airports.copy()
        df_ap['country'] = df_ap['country'].fillna('Desconhecido')
        df_ap['city']    = df_ap['city'].fillna('Desconhecido')

        st.subheader("🛫 Origem")
        pais_origem    = st.selectbox("País de origem",   sorted(df_ap['country'].unique()))
        cidades_origem = sorted(df_ap[df_ap['country'] == pais_origem]['city'].unique())
        cidade_origem  = st.selectbox("Cidade de origem", cidades_origem)
        opcoes_origem  = df_ap[(df_ap['country'] == pais_origem) & (df_ap['city'] == cidade_origem)]
        origem = st.selectbox(
            "Aeroporto de origem",
            opcoes_origem.index.map(lambda x: f"{x} — {opcoes_origem.loc[x]['name']}"),
        ).split(' — ')[0]

        st.subheader("🛬 Destino")
        pais_destino    = st.selectbox("País de destino",   sorted(df_ap['country'].unique()))
        cidades_destino = sorted(df_ap[df_ap['country'] == pais_destino]['city'].unique())
        cidade_destino  = st.selectbox("Cidade de destino", cidades_destino)
        opcoes_destino  = df_ap[(df_ap['country'] == pais_destino) & (df_ap['city'] == cidade_destino)]
        destino = st.selectbox(
            "Aeroporto de destino",
            opcoes_destino.index.map(lambda x: f"{x} — {opcoes_destino.loc[x]['name']}"),
        ).split(' — ')[0]

    partida_str = st.text_input(
        "Horário de partida (HH:MM) — Fuso de Brasília",
        value="10:00",
    )

    st.markdown("---")

    rastrear = st.checkbox("🔎 Ativar rastreamento em tempo real (ICAO24)")
    icao24   = ""
    if rastrear:
        icao24 = st.text_input("Código ICAO24 da aeronave", value="e49102").lower()

    st.markdown("---")


# ========================
# Validação e cálculo da estimativa teórica
# ========================

def obter_info_aeroporto(cod):
    return airports.get(cod)

origem_info  = obter_info_aeroporto(origem)
destino_info = obter_info_aeroporto(destino)

if not origem_info or not destino_info:
    st.error("Código ICAO de origem ou destino inválido.")
    st.stop()

lat1, lon1 = origem_info['lat'], origem_info['lon']
lat2, lon2 = destino_info['lat'], destino_info['lon']
distancia  = calcular_distancia(lat1, lon1, lat2, lon2)

if tipo_aeronave in aeronaves:
    perfil = calcular_perfil_de_voo(
        distancia_total_km=distancia,
        tipo_aeronave=tipo_aeronave,
    )
else:
    # CORREÇÃO 3: vel_custom e demais sempre definidos acima; sem risco de NameError
    perfil = calcular_perfil_de_voo(
        distancia_total_km=distancia,
        tipo_aeronave='Custom',
        vel_custom=vel_custom,
        altitude_cruzeiro_ft=altitude_custom,
        razao_subida_fpm=razao_subida_custom,
        razao_descida_fpm=razao_descida_custom,
    )

tempo_teorico    = perfil['tempo_total_h']
altitude_cruzeiro = perfil['altitude_cruzeiro_ft']

horas           = int(tempo_teorico)
minutos         = int((tempo_teorico - horas) * 60)
tempo_formatado = f"{horas}h {minutos}min"

try:
    fuso_brasilia = ZoneInfo("America/Sao_Paulo")
    agora         = datetime.now(fuso_brasilia)
    partida_h, partida_m = map(int, partida_str.split(":"))
    partida         = agora.replace(hour=partida_h, minute=partida_m, second=0, microsecond=0)
    chegada_teorica = partida + timedelta(hours=tempo_teorico)
except Exception:
    st.error("Horário de partida inválido. Use o formato HH:MM.")
    st.stop()

# ========================
# Estimativa Teórica — exibição
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

# Detalhe do perfil em expander
with st.expander("📊 Detalhes do perfil de voo"):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Subida",  f"{perfil['subida']['dist_km']:.0f} km",
                  f"{perfil['subida']['tempo_h']*60:.0f} min")
    with col2:
        st.metric("Cruzeiro", f"{perfil['cruzeiro']['dist_km']:.0f} km",
                  f"{perfil['cruzeiro']['tempo_h']*60:.0f} min")
    with col3:
        st.metric("Descida",  f"{perfil['descida']['dist_km']:.0f} km",
                  f"{perfil['descida']['tempo_h']*60:.0f} min")


# ========================
# Rastreamento em Tempo Real
# ========================
dados_validos = False
posicao       = None
velocidade_kmh = 0.0
altitude_atual_ft = altitude_cruzeiro  # fallback

if rastrear and icao24:
    with st.spinner("🔍 Buscando dados em tempo real..."):
        resultado = consultar_aeronave(icao24)

    if resultado:
        posicao        = (resultado["latitude"], resultado["longitude"])
        velocidade_kmh = resultado["velocity"] or 0.0
        altitude_atual_ft = resultado["altitude_ft"] if resultado.get("altitude_ft") else altitude_cruzeiro
        fonte          = resultado.get("fonte", "desconhecida")
        dados_validos  = True

        distancia_restante = geodesic(posicao, (lat2, lon2)).kilometers

        # Velocidades por tipo
        if tipo_aeronave in aeronaves:
            param        = aeronaves[tipo_aeronave]
            vel_subida   = param['vel_subida_kmh']
            vel_cruzeiro = param['vel_cruzeiro_kmh']
            vel_descida  = param['vel_descida_kmh']
        else:
            vel_subida   = vel_custom
            vel_cruzeiro = vel_custom
            vel_descida  = vel_custom

        # CORREÇÃO 5: determinação de fase robusta para voos curtos
        p = aeronaves.get(tipo_aeronave, {})
        alt_cruzeiro_ref = p.get('altitude_cruzeiro_ft', altitude_cruzeiro)
        razao_sub  = p.get('razao_subida_fpm', razao_subida_custom or 2000)
        razao_desc = p.get('razao_descida_fpm', razao_descida_custom or 1800)
        d_sub_ref  = vel_subida  * (alt_cruzeiro_ref / razao_sub  / 60)
        d_desc_ref = vel_descida * (alt_cruzeiro_ref / razao_desc / 60)

        if distancia_restante <= d_desc_ref:
            fase = "descida"
        elif altitude_atual_ft < 0.85 * alt_cruzeiro_ref:
            fase = "subida"
        else:
            fase = "cruzeiro"

        # ETA adaptativo por fase
        if fase == "descida":
            tempo_h = distancia_restante / vel_descida if vel_descida > 0 else 0
        elif fase == "cruzeiro":
            tempo_h = distancia_restante / vel_cruzeiro if vel_cruzeiro > 0 else 0
        else:
            perfil_real = calcular_perfil_de_voo(
                distancia_total_km=distancia_restante,
                tipo_aeronave=tipo_aeronave,
                vel_custom=vel_custom,
                altitude_cruzeiro_ft=altitude_cruzeiro,
                razao_subida_fpm=razao_subida_custom,
                razao_descida_fpm=razao_descida_custom,
            )
            tempo_h = perfil_real['tempo_total_h']

        tempo_estimado = timedelta(hours=tempo_h)

        # CORREÇÃO 6: fuso horário do destino com fallback seguro para UTC
        tz_destino_str = destino_info.get('tz', 'UTC')
        tz_destino     = timezone_segura(tz_destino_str)

        hora_chegada_utc = datetime.utcnow().replace(tzinfo=timezone.utc) + tempo_estimado
        hora_brasilia    = hora_chegada_utc.astimezone(ZoneInfo("America/Sao_Paulo"))
        hora_destino     = hora_chegada_utc.astimezone(tz_destino)

        st.subheader("📡 Rastreamento em Tempo Real")
        st.caption(f"Fonte dos dados: **{fonte}**")
        st.markdown(f"""
- **Posição atual:** Lat {posicao[0]:.4f}, Lon {posicao[1]:.4f}
- **Altitude atual:** {altitude_atual_ft:,.0f} ft
- **Velocidade:** {velocidade_kmh:.1f} km/h
- **Distância até o destino:** {distancia_restante:.1f} km
- **Fase estimada:** {fase.title()}
- **ETA (UTC):** {hora_chegada_utc.strftime('%H:%M:%S')}
- **ETA (Brasília):** {hora_brasilia.strftime('%H:%M:%S')}
- **ETA ({tz_destino_str}):** {hora_destino.strftime('%H:%M:%S')}
- **Tempo restante:** {str(tempo_estimado).split('.')[0]}
        """)

    else:
        st.warning("⚠️ Aeronave não encontrada em nenhuma fonte. Tentando novamente em 10 segundos...")


# ========================
# Autorefresh
# ========================
if rastrear:
    if dados_validos:
        st_autorefresh(interval=300_000, limit=None, key="refresh")   # 5 min
    else:
        st_autorefresh(interval=10_000,  limit=None, key="refresh")   # 10 s


# ========================
# Mapa Interativo
#
# Estratégia de re-render:
#   - O objeto Folium é sempre construído com os valores atuais (sem cache).
#     @st.cache_resource foi removido: com parâmetros prefixados por "_" o
#     Streamlit ignora esses args no hash, fazendo o cache nunca invalidar —
#     exatamente o bug que impedia atualização de origem, destino e posição.
#   - O controle de re-render fica por conta do parâmetro `key` do st_folium:
#       • key NÃO muda → Streamlit reutiliza o iframe (sem flicker/reload)
#       • key MUDA     → iframe substituído com o mapa atualizado
#   - A posição é arredondada em 2 casas decimais (~1 km de granularidade),
#     evitando re-renders a cada atualização mínima de GPS.
# ========================
st.subheader("🗺️ Mapa do Voo")

margin  = 1.5
min_lat = min(lat1, lat2) - margin
max_lat = max(lat1, lat2) + margin
min_lon = min(lon1, lon2) - margin
max_lon = max(lon1, lon2) + margin

if posicao and dados_validos:
    posicao_str = f"{posicao[0]:.2f}_{posicao[1]:.2f}"
else:
    posicao_str = "sem_posicao"

map_key = f"map_{origem}_{destino}_{posicao_str}"

# Construção direta — sem cache
mapa = folium.Map(
    location=[(lat1 + lat2) / 2, (lon1 + lon2) / 2],
    zoom_start=5,
    width='100%',
    height=600,
    control_scale=True,
)

folium.Marker(
    [lat1, lon1],
    popup=f"Origem: {origem}",
    icon=folium.Icon(color="green", icon="plane-departure", prefix="fa"),
).add_to(mapa)

folium.Marker(
    [lat2, lon2],
    popup=f"Destino: {destino}",
    icon=folium.Icon(color="red", icon="plane-arrival", prefix="fa"),
).add_to(mapa)

folium.PolyLine(
    locations=[[lat1, lon1], [lat2, lon2]],
    color='blue',
    weight=3,
    dash_array='5, 5',
).add_to(mapa)

if posicao and dados_validos:
    folium.Marker(
        location=posicao,
        popup=f"Aeronave {icao24.upper()}",
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
    ).add_to(mapa)
    folium.PolyLine(
        locations=[posicao, [lat2, lon2]],
        color='orange',
        weight=2,
        dash_array='10, 5',
    ).add_to(mapa)

mapa.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

st_folium(
    mapa,
    width=1000,
    height=600,
    key=map_key,
    returned_objects=[],  # desativa retorno de dados → menos overhead
)