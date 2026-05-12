import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import yfinance as yf
from flashalpha import FlashAlpha

st.set_page_config(page_title="GEX Dashboard Pro", layout="wide", initial_sidebar_state="collapsed")

# Custom CSS for dark theme
st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; }
    .metric-card {
        background: linear-gradient(145deg, #1a1a2e, #16213e);
        border: 1px solid #0f3460;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin: 8px 0;
    }
    .metric-value { font-size: 28px; font-weight: 700; margin: 8px 0; }
    .metric-label { font-size: 12px; color: #8892b0; text-transform: uppercase; letter-spacing: 1px; }
    .positive { color: #00d26a; }
    .negative { color: #ff4757; }
    .neutral { color: #ffd93d; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 GEX Dashboard Pro")
st.markdown("**Horizontal Profile • Call Wall • Put Wall • Gamma Flip • Zero Gamma**")

# Sidebar for mode selection
with st.sidebar:
    st.header("⚙️ Settings")
    mode = st.radio("Data Source", ["CSV Upload", "FlashAlpha API"], index=0)
    
    if mode == "FlashAlpha API":
        EXPIRATION = st.text_input("Expiration (YYYY-MM-DD)", value="2026-05-15")
        st.caption("💡 Fixed expiration saves 1 API call/day")

# Main content
col1, col2 = st.columns([3, 1])

with col1:
    ticker = st.text_input("**Ticker**", value="SPX", key="ticker_input").upper().strip()

# Data loading based on mode
df = None
current_price = 0

if mode == "CSV Upload":
    uploaded_file = st.file_uploader(f"Upload {ticker} CSV from CBOE", type=["csv"])
    
    if uploaded_file is not None:
        # Auto-detect header row
        content = uploaded_file.getvalue().decode("utf-8")
        lines = content.splitlines()
        header_row = next((i for i, line in enumerate(lines) if "Strike" in line), None)
        
        if header_row is None:
            st.error("Could not find 'Strike' column. Make sure you downloaded the full options chain.")
            st.stop()
        
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, skiprows=header_row, on_bad_lines='skip')
        
        # Standardize Strike
        strike_col = next((col for col in df.columns if 'strike' in str(col).lower()), None)
        df = df.dropna(subset=[strike_col])
        df = df.rename(columns={strike_col: 'Strike'})
        
        # Auto-fetch price
        try:
            t = yf.Ticker(ticker if ticker != "SPX" else "^GSPC")
            price = t.info.get('regularMarketPrice') or t.info.get('currentPrice') or t.history(period="1d")['Close'].iloc[-1]
            current_price = float(price)
        except:
            current_price = 739.24

else:  # FlashAlpha API
    api_key = st.secrets.get("FLASHALPHA_KEY")
    if not api_key:
        st.error("⚠️ Add FLASHALPHA_KEY in Streamlit Secrets")
        st.stop()
    
    if st.button("📊 Load GEX Data", type="primary"):
        with st.spinner(f"Fetching {ticker} (exp: {EXPIRATION})..."):
            try:
                fa = FlashAlpha(api_key)
                gex_data = fa.gex(ticker, expiration=EXPIRATION)
                
                net_gex = gex_data.get('net_gex', 0) / 1_000_000_000
                gamma_flip = gex_data.get('gamma_flip')
                spot = gex_data.get('spot_price') or gex_data.get('underlying_price')
                current_price = spot or 739.24
                
                gex_by_strike = gex_data.get('gex_by_strike', {})
                if isinstance(gex_by_strike, list):
                    gex_dict = {item['strike']: item['net_gex'] for item in gex_by_strike}
                    gex_by_strike = pd.Series(gex_dict)
                
                # Store in session state for rendering
                st.session_state['gex_data'] = {
                    'net_gex': net_gex,
                    'gamma_flip': gamma_flip,
                    'spot': spot,
                    'gex_by_strike': gex_by_strike,
                    'call_wall': gex_by_strike[gex_by_strike > 0].idxmax() if any(gex_by_strike > 0) else None,
                    'put_wall': gex_by_strike[gex_by_strike < 0].idxmin() if any(gex_by_strike < 0) else None
                }
                st.success(f"✅ Loaded! (1/5 requests used today)")
            except Exception as e:
                st.error(f"Error: {e}")

# Process data for both modes
if mode == "CSV Upload" and df is not None:
    current_price = st.number_input("Current Price", value=current_price, step=0.01, key="price_input")
    
    # Column detection
    call_gamma_col = next((col for col in df.columns if 'gamma' in str(col).lower() and ('call' in str(col).lower() or col == 'Gamma')), None)
    put_gamma_col = next((col for col in df.columns if 'gamma' in str(col).lower() and ('put' in str(col).lower() or col == 'Gamma.1')), None)
    call_oi_col = next((col for col in df.columns if 'open interest' in str(col).lower() and ('call' in str(col).lower() or col == 'Open Interest')), None)
    put_oi_col = next((col for col in df.columns if 'open interest' in str(col).lower() and ('put' in str(col).lower() or col == 'Open Interest.1')), None)
    
    if not call_gamma_col or not put_gamma_col:
        st.error("Could not detect Gamma columns. Check your CSV format.")
        st.stop()
    
    # Calculate GEX
    df['Call_GEX'] = df[call_gamma_col] * df[call_oi_col] * 100 * (current_price ** 2) * 0.01
    df['Put_GEX'] = df[put_gamma_col] * df[put_oi_col] * 100 * (current_price ** 2) * 0.01 * (-1)
    
    net_gex = (df['Call_GEX'].sum() + df['Put_GEX'].sum()) / 1_000_000_000
    gex_by_strike = df.groupby('Strike')[['Call_GEX', 'Put_GEX']].sum().sum(axis=1)
    
    call_wall = gex_by_strike[gex_by_strike > 0].idxmax() if any(gex_by_strike > 0) else None
    put_wall = gex_by_strike[gex_by_strike < 0].idxmin() if any(gex_by_strike < 0) else None
    
    # Gamma Flip (closest to current price)
    sorted_gex = gex_by_strike.sort_index()
    sign_change = np.where(np.diff(np.sign(sorted_gex)))[0]
    if len(sign_change) > 0:
        crossing_strikes = []
        for idx in sign_change:
            x1, x2 = sorted_gex.index[idx], sorted_gex.index[idx+1]
            y1, y2 = sorted_gex.iloc[idx], sorted_gex.iloc[idx+1]
            if y2 != y1:
                crossing = x1 + (x2 - x1) * (-y1 / (y2 - y1))
                crossing_strikes.append(crossing)
        gamma_flip = min(crossing_strikes, key=lambda x: abs(x - current_price)) if crossing_strikes else sorted_gex.index[sign_change[0]]
    else:
        gamma_flip = sorted_gex.index[np.argmin(np.abs(sorted_gex.values))]
    
    st.session_state['gex_data'] = {
        'net_gex': net_gex,
        'gamma_flip': gamma_flip,
        'spot': current_price,
        'gex_by_strike': gex_by_strike,
        'call_wall': call_wall,
        'put_wall': put_wall
    }

# Render dashboard if we have data
if 'gex_data' in st.session_state:
    data = st.session_state['gex_data']
    gex_by_strike = data['gex_by_strike']
    net_gex = data['net_gex']
    gamma_flip = data['gamma_flip']
    spot = data['spot']
    call_wall = data['call_wall']
    put_wall = data['put_wall']
    
    # Calculate Zero Gamma (strike closest to zero GEX or interpolated)
    zero_gamma = gex_by_strike.index[np.argmin(np.abs(gex_by_strike.values))]
    
    # === METRICS PANEL ===
    st.markdown("### 📊 Key Levels")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        color = "positive" if net_gex > 0 else "negative"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Net GEX</div>
            <div class="metric-value {color}">${net_gex:,.2f}B</div>
            <div style="font-size: 11px; color: #8892b0;">{'Positive = Stabilizing' if net_gex > 0 else 'Negative = Volatile'}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Call Wall</div>
            <div class="metric-value positive">{call_wall:.0f if call_wall else 'N/A'}</div>
            <div style="font-size: 11px; color: #8892b0;">Strong Resistance</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Put Wall</div>
            <div class="metric-value negative">{put_wall:.0f if put_wall else 'N/A'}</div>
            <div style="font-size: 11px; color: #8892b0;">Strong Support</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Gamma Flip</div>
            <div class="metric-value neutral">{gamma_flip:.0f}</div>
            <div style="font-size: 11px; color: #8892b0;">Dealer Hedging Flip</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Zero Gamma</div>
            <div class="metric-value neutral">{zero_gamma:.0f}</div>
            <div style="font-size: 11px; color: #8892b0;">GEX = 0</div>
        </div>
        """, unsafe_allow_html=True)
    
    # === HORIZONTAL GEX CHART ===
    st.markdown("### 📈 GEX Profile by Strike")
    
    fig = go.Figure()
    
    # Main horizontal bar chart
    fig.add_trace(go.Bar(
        x=gex_by_strike.values,
        y=gex_by_strike.index,
        orientation='h',
        marker_color=['#00d26a' if val > 0 else '#ff4757' for val in gex_by_strike.values],
        opacity=0.9,
        name="GEX",
        hovertemplate='Strike: %{y}<br>GEX: %{x:,.0f}<extra></extra>'
    ))
    
    # Key level lines
    if spot:
        fig.add_hline(y=spot, line_dash="dash", line_color="#ffd93d", line_width=2.5, 
                      annotation_text=f"CURRENT ({spot:.0f})", annotation_position="right",
                      annotation_font_color="#ffd93d", annotation_font_size=11)
    
    if gamma_flip:
        fig.add_hline(y=gamma_flip, line_dash="dot", line_color="#ffffff", line_width=2,
                      annotation_text=f"GAMMA FLIP ({gamma_flip:.0f})", annotation_position="left",
                      annotation_font_color="#ffffff", annotation_font_size=10)
    
    if call_wall:
        fig.add_hline(y=call_wall, line_dash="solid", line_color="#00d26a", line_width=1.5,
                      annotation_text=f"CALL WALL ({call_wall:.0f})", annotation_position="right",
                      annotation_font_color="#00d26a", annotation_font_size=10)
    
    if put_wall:
        fig.add_hline(y=put_wall, line_dash="solid", line_color="#ff4757", line_width=1.5,
                      annotation_text=f"PUT WALL ({put_wall:.0f})", annotation_position="left",
                      annotation_font_color="#ff4757", annotation_font_size=10)
    
    # Zero line
    fig.add_vline(x=0, line_dash="solid", line_color="#4a5568", line_width=1)
    
    fig.update_layout(
        template="plotly_dark",
        height=700,
        margin=dict(l=80, r=40, t=20, b=40),
        xaxis_title="GEX ($ notional per 1% move)",
        yaxis_title="Strike Price",
        showlegend=False,
        hovermode="closest",
        xaxis=dict(showgrid=True, gridcolor="#2d3748", zerolinecolor="#4a5568"),
        yaxis=dict(showgrid=True, gridcolor="#2d3748")
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Footer info
    st.caption(f"📊 {ticker} | Spot: ${spot:,.2f} | Net GEX: ${net_gex:,.2f}B | Updated: Just now")
    
    if mode == "FlashAlpha API":
        st.caption("⚠️ 1 of 5 daily API requests used • Resets at midnight UTC")

else:
    st.info("👆 Upload a CSV or click 'Load GEX Data' to begin")
    st.caption("💡 Tip: For best results, use SPX or SPY with active options chains")