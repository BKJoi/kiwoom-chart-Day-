import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import re
import numpy as np

# 1. URL은 숨길 필요가 없으므로 직접 입력 (모의투자 또는 실투자 URL)
host_url = "https://api.kiwoom.com" # 또는 모의투자 URL

# 2. 내 진짜 키값은 Streamlit의 안전한 금고(secrets)에서 불러오기!
app_key = st.secrets["APP_KEY"]
app_secret = st.secrets["APP_SECRET"]


# ----------------------------------------------------
# 1. 인증 및 데이터 수집 함수 (User-Agent 위장 추가)
# ----------------------------------------------------
@st.cache_data(ttl=3600)
def get_access_token():
    url = f"{host_url}/oauth2/token"
    
    # 💡 [핵심] 일반 PC의 크롬 브라우저인 것처럼 위장하는 코드 추가
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    data = {"grant_type": "client_credentials", "appkey": app_key, "secretkey": app_secret}
    
    response = requests.post(url, headers=headers, json=data)
    
    try:
        res_json = response.json()
        return res_json.get('token')
    except requests.exceptions.JSONDecodeError:
        st.error("🚨 키움증권 방화벽 차단 (Request Blocked)")
        st.warning(f"상태 코드 (Status Code): {response.status_code}")
        st.info(f"실제 응답: {response.text}")
        st.stop()

@st.cache_data(ttl=86400) 
def get_broker_list(token):
    url = f"{host_url}/api/dostk/stkinfo"
    headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": "ka10102", "authorization": f"Bearer {token}"}
    res = requests.post(url, headers=headers, json={})
    data = res.json()
    broker_dict = {}
    if "list" in data:
        for item in data["list"]: 
            broker_dict[f"{item['name']}({item['code']})"] = item["code"]
    return broker_dict

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
st.set_page_config(page_title="수급 마스터 Web", layout="wide")
st.title("📊 창구/주체별 매매강도 대시보드 (클라우드 배포판)")

auth_token = get_access_token()

with st.sidebar:
    st.header("⚙️ 설정")
    stock_number = st.text_input("종목코드", value="005930")
    selected_date = st.date_input("기준 날짜", datetime.now())
    target_date_str = selected_date.strftime('%Y%m%d')
    
    if auth_token:
        broker_dict = get_broker_list(auth_token)
        broker_names = sorted(list(broker_dict.keys()))
        
        def_brk1_idx = next((i for i, n in enumerate(broker_names) if "키움증권" in n), 0)
        selected_broker1_name = st.selectbox("🔎 창구 1 선택", broker_names, index=def_brk1_idx)
        target_broker1_code = broker_dict[selected_broker1_name]
        
        def_brk2_idx = next((i for i, n in enumerate(broker_names) if "신한투자증권" in n), 0)
        selected_broker2_name = st.selectbox("🔎 창구 2 선택 (타겟 주포)", broker_names, index=def_brk2_idx)
        target_broker2_code = broker_dict[selected_broker2_name]
        
        investor_names = sorted(list(investor_mapping.keys()))
        def_inv_idx = next((i for i, n in enumerate(investor_names) if "기관계" == n), 0)
        selected_investor_name = st.selectbox("🔎 투자자 선택 (비교용)", investor_names, index=def_inv_idx)
        target_investor_field = investor_mapping[selected_investor_name]
        
        corr_window = st.number_input("⏱️ 롤링 분석 기간 (일)", min_value=3, max_value=60, value=20)

if auth_token and len(stock_number) == 6:
    with st.spinner("데이터 동기화 및 차트 생성 중..."):
        daily_res = get_daily_chart(auth_token, stock_number, target_date_str)
        daily_list = daily_res.get('stk_dt_pole_chart_qry', [])

        if daily_list:
            df = pd.DataFrame(daily_list)
            
            def clean_val(v):
                if pd.isna(v) or v == '': return 0
                s = str(v).replace(',', '').strip()
                match = re.search(r'-?\d+', s)
                return int(match.group()) if match else 0

            df['key'] = df['dt'].astype(str).str.extract(r'(\d{8})')[0]
            df = df.sort_values('key').reset_index(drop=True)
            
            df['open'] = df['open_pric'].apply(clean_val)
            df['high'] = df['high_pric'].apply(clean_val)
            df['low'] = df['low_pric'].apply(clean_val)
            df['close'] = df['cur_prc'].apply(clean_val)
            df['volume'] = df['trde_qty'].apply(clean_val)

            for ma, d in zip(['MA5','MA20','MA60'], [5,20,60]):
                df[ma] = df['close'].rolling(window=d).mean()

            brk1_res = get_daily_broker_data(auth_token, stock_number, df['key'].min(), df['key'].max(), target_broker1_code)
            brk2_res = get_daily_broker_data(auth_token, stock_number, df['key'].min(), df['key'].max(), target_broker2_code)
            res_buy = get_investor_data_ka10059(auth_token, stock_number, target_date_str, "1")
            res_sell = get_investor_data_ka10059(auth_token, stock_number, target_date_str, "2")
            
            def get_brk_df(res):
                items = res.get('sec_stk_trde_trend', [])
                if not items: return pd.DataFrame(columns=['key', 'buy_n', 'sell_n', 'net_n'])
                t = pd.DataFrame(items)
                t['key'] = t['dt'].astype(str).str.extract(r'(\d{8})')[0]
                t['buy_n'] = t['buy_qty'].apply(clean_val)
                t['sell_n'] = t['sell_qty'].apply(clean_val)
                t['net_n'] = t['netprps_qty'].apply(clean_val)
                return t.groupby('key').agg({'buy_n':'sum', 'sell_n':'sum', 'net_n':'sum'}).reset_index()

            df_b1 = get_brk_df(brk1_res)
            df['Brk1_Buy'] = df['key'].map(df_b1.set_index('key')['buy_n']).fillna(0).abs()
            df['Brk1_Sell'] = df['key'].map(df_b1.set_index('key')['sell_n']).fillna(0).abs()
            df['Brk1_Net'] = df['key'].map(df_b1.set_index('key')['net_n']).fillna(0)
            df['Brk1_Cum'] = df['Brk1_Net'].cumsum()

            df_b2 = get_brk_df(brk2_res)
            df['Brk2_Buy'] = df['key'].map(df_b2.set_index('key')['buy_n']).fillna(0).abs()
            df['Brk2_Sell'] = df['key'].map(df_b2.set_index('key')['sell_n']).fillna(0).abs()
            df['Brk2_Net'] = df['key'].map(df_b2.set_index('key')['net_n']).fillna(0)
            df['Brk2_Cum'] = df['Brk2_Net'].cumsum()
            df['Brk2_Total_Vol'] = df['Brk2_Buy'] + df['Brk2_Sell']

            buy_list, sell_list = res_buy.get('stk_invsr_orgn', []), res_sell.get('stk_invsr_orgn', [])
            df['Inv_Buy'] = 0; df['Inv_Sell'] = 0; df['Inv_Net'] = 0
            df['Ind_Buy'] = 0; df['Ind_Sell'] = 0; df['Ind_Net'] = 0
            
            if buy_list and sell_list:
                df_buy = pd.DataFrame(buy_list).set_index('dt')
                df_sell = pd.DataFrame(sell_list).set_index('dt')
                def get_investor_sum(src_df, field):
                    num_df = src_df.map(clean_val)
                    if field == 'orgn':
                        subs = ["fnnc_invt", "insrnc", "invtrt", "etc_fnnc", "bank", "penfnd_etc", "samo_fund", "natn"]
                        return num_df[subs].sum(axis=1).combine(num_df['orgn'], max)
                    return num_df[field]
                
                df['Inv_Buy'] = df['key'].map(get_investor_sum(df_buy, target_investor_field)).fillna(0).abs()
                df['Inv_Sell'] = df['key'].map(get_investor_sum(df_sell, target_investor_field)).fillna(0).abs()
                df['Inv_Net'] = df['Inv_Buy'] - df['Inv_Sell']
                
                df['Ind_Buy'] = df['key'].map(get_investor_sum(df_buy, 'ind_invsr')).fillna(0).abs()
                df['Ind_Sell'] = df['key'].map(get_investor_sum(df_sell, 'ind_invsr')).fillna(0).abs()
                df['Ind_Net'] = df['Ind_Buy'] - df['Ind_Sell']

            df['Inv_Cum'] = df['Inv_Net'].cumsum()
            df['Inv_Total_Vol'] = df['Inv_Buy'] + df['Inv_Sell']

            # -------------------------------------------------------
            # ⭐️ 극단값(Outlier) 제한 (Clipping)
            # -------------------------------------------------------
            clip_limit = 50 
            
            df['Brk2_Intensity'] = ((df['Brk2_Net'] / df['Brk2_Total_Vol'].replace(0, np.nan)).fillna(0) * 100).clip(lower=-clip_limit, upper=clip_limit)
            df['Inv_Intensity'] = ((df['Inv_Net'] / df['Inv_Total_Vol'].replace(0, np.nan)).fillna(0) * 100).clip(lower=-clip_limit, upper=clip_limit)

            df['Corr_Inv'] = df['Ind_Net'].rolling(window=corr_window).corr(df['Inv_Net']).fillna(0)
            df['Corr_Brk'] = df['Brk1_Net'].rolling(window=corr_window).corr(df['Brk2_Net']).fillna(0)
            
            df = df.tail(100).reset_index(drop=True)
            x_labels = df['key'].apply(lambda x: f"{x[2:4]}/{x[4:6]}/{x[6:]}")

            # -------------------------------------------------------
            # ⭐️ 9단 분할 차트 생성 
            # -------------------------------------------------------
            fig = make_subplots(
                rows=9, cols=1, shared_xaxes=True, vertical_spacing=0.03, 
                row_heights=[0.14, 0.06, 0.08, 0.08, 0.08, 0.08, 0.08, 0.2, 0.2], 
                subplot_titles=(
                    "1. 가격 및 이동평균선", "2. 전체 거래량", 
                    f"3. [{selected_broker1_name}] 수급 활동", f"4. [{selected_broker2_name}] 수급 활동", f"5. [{selected_investor_name}] 수급 활동", 
                    f"🔗 6. [개인투자자] - [{selected_investor_name}] 매매 상관성",
                    f"🔗 7. [{selected_broker1_name}] - [{selected_broker2_name}] 매매 상관성",
                    f"🔥 8. [{selected_broker2_name}] 순매수 강도 (%) - (극단값 ±{clip_limit}% 커트)",
                    f"🔥 9. [{selected_investor_name}] 순매수 강도 (%) - (극단값 ±{clip_limit}% 커트)"
                ),
                specs=[[{"secondary_y": False}], [{"secondary_y": False}], 
                       [{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": True}], 
                       [{"secondary_y": False}], [{"secondary_y": False}], 
                       [{"secondary_y": False}], [{"secondary_y": False}]]
            )
            
            fig.add_trace(go.Candlestick(
                x=x_labels, open=df['open'], high=df['high'], low=df['low'], close=df['close'], 
                increasing_line_color='#ff4d4d', increasing_fillcolor='#ff4d4d', 
                decreasing_line_color='#0066ff', decreasing_fillcolor='#0066ff', name="가격"
            ), row=1, col=1)
            for ma, color in zip(['MA5', 'MA20', 'MA60'], ['#ff4d4d', '#0066ff', '#00cc44']):
                fig.add_trace(go.Scatter(x=x_labels, y=df[ma], line=dict(color=color, width=1.2), name=ma), row=1, col=1)
            
            v_colors = ['#ff4d4d' if c >= o else '#0066ff' for c, o in zip(df['close'], df['open'])]
            fig.add_trace(go.Bar(x=x_labels, y=df['volume'], marker_color=v_colors, name="거래량", opacity=0.8), row=2, col=1)
            
            def add_layer(fig, row, buy, sell, cum, name):
                fig.add_trace(go.Bar(x=x_labels, y=buy, marker_color='#ff4d4d', opacity=0.7, name=f"{name}매수"), row=row, col=1, secondary_y=False)
                fig.add_trace(go.Bar(x=x_labels, y=-sell, marker_color='#0066ff', opacity=0.7, name=f"{name}매도"), row=row, col=1, secondary_y=False)
                fig.add_trace(go.Scatter(x=x_labels, y=cum, line=dict(color='black', width=2), name=f"{name}누적"), row=row, col=1, secondary_y=True)

            add_layer(fig, 3, df['Brk1_Buy'], df['Brk1_Sell'], df['Brk1_Cum'], "창구1")
            add_layer(fig, 4, df['Brk2_Buy'], df['Brk2_Sell'], df['Brk2_Cum'], "창구2")
            add_layer(fig, 5, df['Inv_Buy'], df['Inv_Sell'], df['Inv_Cum'], f"{selected_investor_name}")

            fig.add_trace(go.Bar(x=x_labels, y=df['Corr_Inv'], marker_color=['#ff4d4d' if c > 0 else '#0066ff' for c in df['Corr_Inv']], opacity=0.8), row=6, col=1)
            fig.add_trace(go.Bar(x=x_labels, y=df['Corr_Brk'], marker_color=['#ff4d4d' if c > 0 else '#0066ff' for c in df['Corr_Brk']], opacity=0.8), row=7, col=1)

            # 8층 (창구2 매매강도 - 꺾은선 + 영역)
            fig.add_trace(go.Scatter(
                x=x_labels, y=df['Brk2_Intensity'], 
                mode='lines+markers', line=dict(color='#ff9933', width=2), marker=dict(size=4), 
                fill='tozeroy', fillcolor='rgba(255, 153, 51, 0.2)', name="창구강도"
            ), row=8, col=1)
            fig.add_hline(y=0, line_dash="solid", line_color="black", opacity=0.5, row=8, col=1)

            # 9층 (투자자 매매강도 - 꺾은선 + 영역)
            fig.add_trace(go.Scatter(
                x=x_labels, y=df['Inv_Intensity'], 
                mode='lines+markers', line=dict(color='#00cc66', width=2), marker=dict(size=4), 
                fill='tozeroy', fillcolor='rgba(0, 204, 102, 0.2)', name="투자자강도"
            ), row=9, col=1)
            fig.add_hline(y=0, line_dash="solid", line_color="black", opacity=0.5, row=9, col=1)

            fig.update_yaxes(range=[-clip_limit-5, clip_limit+5], row=8, col=1)
            fig.update_yaxes(range=[-clip_limit-5, clip_limit+5], row=9, col=1)

            fig.update_xaxes(type='category', tickangle=-45, nticks=20, showgrid=True)
            fig.update_layout(height=2600, template='plotly_white', barmode='relative', xaxis_rangeslider_visible=False, showlegend=False)
            
            st.plotly_chart(fig, use_container_width=True)
