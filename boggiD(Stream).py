import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import re

# ⭐️ 수정 1: HOST_URL을 금고(secrets)에서 찾지 않고 직접 적어줍니다.
app_key = st.secrets["APP_KEY"]
app_secret = st.secrets["APP_SECRET"]
host_url = "https://api.kiwoom.com" 

# 1. 인증 및 데이터 수집 함수
@st.cache_data(ttl=3600)
def get_access_token():
    url = f"{host_url}/oauth2/token"
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    data = {"grant_type": "client_credentials", "appkey": app_key, "secretkey": app_secret}
    return requests.post(url, headers=headers, json=data).json().get('token')

@st.cache_data(ttl=86400) 
def get_broker_list(token):
    url = f"{host_url}/api/dostk/stkinfo"
    headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": "ka10102", "authorization": f"Bearer {token}"}
    res = requests.post(url, headers=headers, json={})
    return res.json()

def get_daily_chart(token, stock_code, target_date):
    url = f"{host_url}/api/dostk/chart"
    headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": "ka10081", "authorization": f"Bearer {token}"}
    data = {"stk_cd": stock_code, "qry_tp": "1", "upd_stkpc_tp": "1", "base_dt": target_date}
    return requests.post(url, headers=headers, json=data, timeout=10).json()

def get_daily_broker_data(token, stock_code, start_dt, end_dt, broker_code):
    url = f"{host_url}/api/dostk/mrkcond"
    headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": "ka10078", "authorization": f"Bearer {token}"}
    data = {"mmcm_cd": broker_code, "stk_cd": stock_code, "strt_dt": start_dt, "end_dt": end_dt} 
    return requests.post(url, headers=headers, json=data, timeout=10).json()

def get_investor_data_ka10059(token, stock_code, target_date, trde_tp):
    url = f"{host_url}/api/dostk/stkinfo"
    headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": "ka10059", "authorization": f"Bearer {token}"}
    data = {"dt": target_date, "stk_cd": stock_code, "amt_qty_tp": "2", "trde_tp": trde_tp, "unit_tp": "1"}
    return requests.post(url, headers=headers, json=data, timeout=10).json()

investor_mapping = {
    "개인투자자": "ind_invsr", "기관계": "orgn", "외국인투자자": "frgnr_invsr",
    "금융투자": "fnnc_invt", "보험": "insrnc", "투신": "invtrt", "은행": "bank",
    "연기금등": "penfnd_etc", "사모펀드": "samo_fund", "국가": "natn",
    "기타법인": "etc_corp", "기타금융": "etc_fnnc", "내외국인": "natfor"
}

# ----------------------------------------------------
# 2. 메인 실행부
# ----------------------------------------------------
st.set_page_config(page_title="수급 마스터 v9.7", layout="wide")
st.title("📊 주체별 수급 분석 (클라우드 완벽 패치)")

auth_token = get_access_token()

with st.sidebar:
    st.header("⚙️ 설정")
    stock_number = st.text_input("종목코드", value="005930")
    selected_date = st.date_input("기준 날짜", datetime.now())
    target_date_str = selected_date.strftime('%Y%m%d')
    
    if auth_token:
        broker_data_raw = get_broker_list(auth_token)
        broker_dict = {}
        if "list" in broker_data_raw:
            for item in broker_data_raw["list"]: 
                broker_dict[f"{item['name']}({item['code']})"] = item["code"]
        else:
            st.error("🚨 창구 목록을 불러오지 못했습니다. 아래 메시지를 확인하세요.")
            st.json(broker_data_raw)

        broker_names = sorted(list(broker_dict.keys())) if broker_dict else ["데이터없음"]
        def_brk_idx = next((i for i, n in enumerate(broker_names) if "키움증권" in n), 0) if broker_dict else 0
        selected_broker_name = st.selectbox("🔎 창구 선택 (3층)", broker_names, index=def_brk_idx)
        target_broker_code = broker_dict.get(selected_broker_name, "")
        
        investor_names = sorted(list(investor_mapping.keys()))
        def_inv_idx = next((i for i, n in enumerate(investor_names) if "기관계" == n), 0)
        selected_investor_name = st.selectbox("🔎 투자자 선택 (4층)", investor_names, index=def_inv_idx)
        target_investor_field = investor_mapping[selected_investor_name]

if auth_token and len(stock_number) == 6 and target_broker_code:
    with st.spinner("데이터 요청 중..."):
        daily_res = get_daily_chart(auth_token, stock_number, target_date_str)
        daily_list = daily_res.get('stk_dt_pole_chart_qry', [])

        if daily_list:
            df = pd.DataFrame(daily_list)
            
            def clean_val(v):
                if pd.isna(v) or v == '': return 0
                s = str(v).replace(',', '').strip()
                match = re.search(r'-?\d+', s)
                return int(match.group()) if match else 0

            # ⭐️ 수정 2: 파이썬 최신 버전 문법에 맞게 r'(\d{8})' 로 변경하여 경고 메시지 제거
            df['key'] = df['dt'].astype(str).str.extract(r'(\d{8})')[0]
            df = df.sort_values('key').tail(100).reset_index(drop=True)
            
            df['open'] = df['open_pric'].apply(clean_val)
            df['high'] = df['high_pric'].apply(clean_val)
            df['low'] = df['low_pric'].apply(clean_val)
            df['close'] = df['cur_prc'].apply(clean_val)
            df['volume'] = df['trde_qty'].apply(clean_val) 

            for ma, d in zip(['MA5','MA20','MA60'], [5,20,60]):
                df[ma] = df['close'].rolling(window=d).mean()

            broker_res = get_daily_broker_data(auth_token, stock_number, df['key'].min(), df['key'].max(), target_broker_code)
            res_buy = get_investor_data_ka10059(auth_token, stock_number, target_date_str, "1")
            res_sell = get_investor_data_ka10059(auth_token, stock_number, target_date_str, "2")
            
            buy_list = res_buy.get('stk_invsr_orgn', [])
            sell_list = res_sell.get('stk_invsr_orgn', [])

            df['Brk_Buy'] = 0; df['Brk_Sell'] = 0; df['Brk_Net'] = 0
            broker_items = broker_res.get('sec_stk_trde_trend', [])
            if broker_items:
                df_b = pd.DataFrame(broker_items)
                
                # ⭐️ 수정 2: 여기도 동일하게 r 추가
                df_b['key'] = df_b['dt'].astype(str).str.extract(r'(\d{8})')[0]
                
                df_b['buy_n'] = df_b['buy_qty'].apply(clean_val)
                df_b['sell_n'] = df_b['sell_qty'].apply(clean_val)
                df_b['net_n'] = df_b['netprps_qty'].apply(clean_val)
                g_b = df_b.groupby('key').agg({'buy_n':'sum', 'sell_n':'sum', 'net_n':'sum'})
                df['Brk_Buy'] = df['key'].map(g_b['buy_n']).fillna(0).abs()
                df['Brk_Sell'] = df['key'].map(g_b['sell_n']).fillna(0).abs()
                df['Brk_Net'] = df['key'].map(g_b['net_n']).fillna(0)

            df['Inv_Buy'] = 0; df['Inv_Sell'] = 0; df['Inv_Net'] = 0
            if buy_list and sell_list:
                df_buy = pd.DataFrame(buy_list).set_index('dt')
                df_sell = pd.DataFrame(sell_list).set_index('dt')
                def get_investor_sum(src_df, field):
                    num_df = src_df.applymap(clean_val)
                    if field == 'orgn':
                        subs = ["fnnc_invt", "insrnc", "invtrt", "etc_fnnc", "bank", "penfnd_etc", "samo_fund", "natn"]
                        sums = num_df[subs].sum(axis=1)
                        orgns = num_df['orgn']
                        return pd.Series([max(s, o) for s, o in zip(sums, orgns)], index=src_df.index)
                    return num_df[field]
                df['Inv_Buy'] = df['key'].map(get_investor_sum(df_buy, target_investor_field)).fillna(0).abs()
                df['Inv_Sell'] = df['key'].map(get_investor_sum(df_sell, target_investor_field)).fillna(0).abs()
                df['Inv_Net'] = df['Inv_Buy'] - df['Inv_Sell']

            df['Brk_Cum'] = df['Brk_Net'].cumsum(); df['Inv_Cum'] = df['Inv_Net'].cumsum()

            x_labels = df['key'].apply(lambda x: f"{x[2:4]}/{x[4:6]}/{x[6:]}")

            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.3, 0.1, 0.3, 0.3],
                subplot_titles=("가격 및 이동평균선", "전체 거래량", f"{selected_broker_name} 수급 활동", f"{selected_investor_name} 수급 활동"),
                specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": True}]])
            
            fig.add_trace(go.Candlestick(x=x_labels, open=df['open'], high=df['high'], low=df['low'], close=df['close'], increasing_line_color='#ff4d4d', increasing_fillcolor='#ff4d4d', decreasing_line_color='#0066ff', decreasing_fillcolor='#0066ff', name="가격"), row=1, col=1)
            for ma, color in zip(['MA5', 'MA20', 'MA60'], ['#ff4d4d', '#0066ff', '#00cc44']):
                fig.add_trace(go.Scatter(x=x_labels, y=df[ma], line=dict(color=color, width=1.2), name=ma), row=1, col=1)
            
            v_colors = ['#ff4d4d' if c >= o else '#0066ff' for c, o in zip(df['close'], df['open'])]
            fig.add_trace(go.Bar(x=x_labels, y=df['volume'], marker_color=v_colors, name="거래량", opacity=0.8), row=2, col=1)
            
            def add_layer(fig, row, buy, sell, cum, name):
                fig.add_trace(go.Bar(x=x_labels, y=buy, marker_color='#ff4d4d', opacity=0.7, name=f"{name}매수"), row=row, col=1, secondary_y=False)
                fig.add_trace(go.Bar(x=x_labels, y=-sell, marker_color='#0066ff', opacity=0.7, name=f"{name}매도"), row=row, col=1, secondary_y=False)
                fig.add_trace(go.Scatter(x=x_labels, y=cum, line=dict(color='black', width=2), name=f"{name}누적"), row=row, col=1, secondary_y=True)

            add_layer(fig, 3, df['Brk_Buy'], df['Brk_Sell'], df['Brk_Cum'], "창구")
            add_layer(fig, 4, df['Inv_Buy'], df['Inv_Sell'], df['Inv_Cum'], f"{selected_investor_name}")

            fig.update_xaxes(type='category', tickangle=-45, nticks=20, showgrid=True)
            fig.update_layout(height=1100, template='plotly_white', barmode='relative', xaxis_rangeslider_visible=False, showlegend=False)
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            # 일봉 데이터를 아예 못 받았을 때의 메시지 출력
            st.error("🚨 서버에서 차트 데이터를 주지 않았습니다. 아래의 거절 사유를 확인해 주세요.")
            st.json(daily_res)