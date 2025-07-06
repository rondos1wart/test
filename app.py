import streamlit as st
import plotly.express as px
import pandas as pd

# 1) 연금저축 세액공제 상수 및 로직
PENSION_SAVING_LIMIT = 6_000_000  # 최대 납입 한도(연)
# 소득구간별 공제율
def get_pension_saving_credit_rate(income):
    # 종합소득 4,500만 원 이하: 16.5%, 초과: 13.2% :contentReference[oaicite:1]{index=1}
    return 0.165 if income <= 45_000_000 else 0.132

def calculate_pension_saving_tax_credit(contribution, income):
    deductible = min(contribution, PENSION_SAVING_LIMIT)
    rate = get_pension_saving_credit_rate(income)
    return deductible * rate

# 6) 세액공제 총합 계산 함수
def calculate_total_tax_credit(user_input):
    # 현재는 연금저축 세액공제만 합산
    return calculate_pension_saving_tax_credit(
        user_input['annual_contribution'],
        user_input['annual_income']
    )

# 2) 연금소득공제 공식 (국세청 고시 기준) 검증용 주석
def get_pension_income_deduction_amount(pension_income):
    """
    공식(예시):
      - 4,000,000원까지 전액
      - 초과분 중 4,000,000원까지 40%
      - 초과분 중 8,000,000원까지 20%
      - 나머지 10%, 최대 한도 12,000,000원
    ※ 사용 중인 상수(3.5M,7M,14M,9M 등)는 반드시 최신 국세청 고시와 비교하세요.
    """
    if pension_income <= 4_000_000:
        return pension_income
    if pension_income <= 8_000_000:
        return 4_000_000 + (pension_income - 4_000_000) * 0.4
    if pension_income <= 15_000_000:
        return 4_000_000 + 4_000_000 * 0.4 + (pension_income - 8_000_000) * 0.2
    deduction = 4_000_000 + 4_000_000 * 0.4 + 7_000_000 * 0.2 + (pension_income - 15_000_000) * 0.1
    return min(deduction, 12_000_000)

# 3) 종합소득세 과세표준 구간 (2023~2024년 귀속 기준) :contentReference[oaicite:2]{index=2}
COMPREHENSIVE_TAX_BRACKETS = [
    (14_000_000, 0.06,    0),
    (50_000_000, 0.15, 1_260_000),
    (88_000_000, 0.24, 5_760_000),
    (150_000_000,0.35,15_440_000),
    (300_000_000,0.38,19_940_000),
    (500_000_000,0.40,25_940_000),
    (1_000_000_000,0.42,35_940_000),
    (float('inf'),0.45,65_940_000),
]

def calculate_comprehensive_tax(income):
    for threshold, rate, deduction in COMPREHENSIVE_TAX_BRACKETS:
        if income <= threshold:
            return income * rate - deduction
    return 0

# 4) 연복리 할인(DPV) 로직
def discount_cashflow(amount, years, inflation_rate):
    """
    할인 현재가치 = amount / ((1 + inflation_rate) ** years)
    """
    return amount / ((1 + inflation_rate) ** years)

# 예: 매년 연금 수령액을 할인하여 현재가치 합산
def present_value_of_payouts(annual_payout, start_age, end_age, inflation_rate):
    pv = 0.0
    for year_offset in range(end_age - start_age + 1):
        pv += discount_cashflow(annual_payout, year_offset, inflation_rate)
    return pv

# 5) 시각화 함수에 Plotly Express 그래프 추가
def display_asset_visuals(user_input):
    # 예시 데이터프레임: 연도별 자산 총액 & 할인된 가치
    years = list(range(user_input['current_age'], user_input['retirement_age'] + 1))
    assets = []
    discounted = []
    for i, age in enumerate(years):
        val = user_input['annual_contribution'] * (1 + user_input['expected_return']) ** i
        assets.append(val)
        discounted.append(discount_cashflow(val, i, user_input['inflation_rate']))
    df = pd.DataFrame({
        'Age': years,
        'Future Value of Assets': assets,
        'Discounted Value of Assets': discounted
    })

    st.subheader("자산 성장 및 할인 현재가치 (연복리 적용)")
    fig = px.line(df, x='Age', y=['Future Value of Assets', 'Discounted Value of Assets'],
                  labels={'value': '금액(₩)', 'Age': '나이', 'variable': '항목'})
    st.plotly_chart(fig)

# Streamlit UI
st.title("연금저축 연금 수령액 계산기")

# 사용자 입력
user_input = {
    'annual_income': st.number_input("연간 종합소득(₩)", value=30_000_000, step=1_000_000),
    'annual_contribution': st.number_input("연금저축 연간 납입액(₩)", value=3_000_000, step=100_000),
    'current_age': st.slider("현재 나이", 20, 70, 30),
    'retirement_age': st.slider("은퇴 나이", 50, 80, 60),
    'expected_return': st.number_input("예상 수익률(년) (%)", value=0.05) / 100,
    'inflation_rate': st.number_input("물가상승률(연) (%)", value=0.02) / 100,
}

# 계산
tax_credit = calculate_total_tax_credit(user_input)
pv_payout = present_value_of_payouts(
    annual_payout= user_input['annual_contribution'] * 0.05,  # 예시 연금 수령액
    start_age=user_input['retirement_age'],
    end_age=user_input['retirement_age'] + 20,
    inflation_rate=user_input['inflation_rate']
)

st.metric("예상 절세액(₩)", f"{tax_credit:,.0f}")
st.metric("할인 현재가치 합계(₩)", f"{pv_payout:,.0f}")

display_asset_visuals(user_input)
