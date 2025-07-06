import streamlit as st
import pandas as pd
import plotly.express as px
from dataclasses import dataclass

# --- 데이터 클래스 및 상수 정의 ---
@dataclass
class UserInput:
    start_age: int
    retirement_age: int
    end_age: int
    pre_retirement_return: float
    post_retirement_return: float
    inflation_rate: float
    annual_contribution: int
    non_deductible_contribution: int
    other_non_deductible_total: int
    other_pension_income: int
    other_comprehensive_income: int
    income_level: str
    contribution_timing: str

INCOME_LEVEL_LOW  = '총급여 5,500만원 이하 (종합소득 4,500만원 이하)'
INCOME_LEVEL_HIGH = '총급여 5,500만원 초과 (종합소득 4,500만원 초과)'

MIN_RETIREMENT_AGE, MIN_CONTRIBUTION_YEARS, MIN_PAYOUT_YEARS = 55, 5, 10
PENSION_TAX_THRESHOLD, SEPARATE_TAX_RATE, OTHER_INCOME_TAX_RATE = 15_000_000, 0.165, 0.165
PENSION_SAVING_TAX_CREDIT_LIMIT, MAX_CONTRIBUTION_LIMIT = 6_000_000, 18_000_000
PENSION_TAX_RATES = {"under_70": 0.055, "under_80": 0.044, "over_80": 0.033}
LOCAL_TAX_RATE = 0.1

COMPREHENSIVE_TAX_BRACKETS = [
    (14_000_000, 0.06, 0), (50_000_000, 0.15, 1_260_000),
    (88_000_000, 0.24, 5_760_000), (150_000_000, 0.35, 15_440_000),
    (300_000_000, 0.38, 19_940_000), (500_000_000, 0.40, 25_940_000),
    (1_000_000_000, 0.42, 35_940_000), (float('inf'), 0.45, 65_940_000),
]

# 투자 프로필: 은퇴 전 수익률 / 은퇴 후 수익률
PROFILES = {
    '안정형': (4.0, 3.0),
    '중립형': (6.0, 4.0),
    '공격형': (8.0, 5.0),
    '직접 입력': (6.0, 4.0),
}

# --- 계산 함수들 (이전과 동일) ---
def calculate_total_at_retirement(inputs: UserInput):
    pre_ret = inputs.pre_retirement_return / 100.0
    years = inputs.retirement_age - inputs.start_age
    data, current = [], 0
    for i in range(years):
        if inputs.contribution_timing == '연초':
            current = (current + inputs.annual_contribution) * (1 + pre_ret)
        else:
            current = current * (1 + pre_ret) + inputs.annual_contribution
        data.append({'year': inputs.start_age + i + 1, 'value': current})
    return current, pd.DataFrame(data)

def get_pension_income_deduction_amount(pension_income):
    if pension_income <= 3_500_000: return pension_income
    if pension_income <= 7_000_000:
        return 3_500_000 + (pension_income - 3_500_000) * 0.4
    if pension_income <= 14_000_000:
        return 4_900_000 + (pension_income - 7_000_000) * 0.2
    ded = 6_300_000 + (pension_income - 14_000_000) * 0.1
    return min(ded, 9_000_000)

def get_comprehensive_tax(taxable_income, include_local_tax=True):
    if taxable_income <= 0: return 0
    for thr, rate, ded in COMPREHENSIVE_TAX_BRACKETS:
        if taxable_income <= thr:
            tax = taxable_income * rate - ded
            return tax * (1 + LOCAL_TAX_RATE) if include_local_tax else tax
    return 0

def calculate_annual_pension_tax(payout_under_limit, other_pension_income, other_comprehensive_income, current_age):
    total_gross = payout_under_limit + other_pension_income
    if total_gross <= PENSION_TAX_THRESHOLD:
        if current_age < 70: rate = PENSION_TAX_RATES["under_70"]
        elif current_age < 80: rate = PENSION_TAX_RATES["under_80"]
        else: rate = PENSION_TAX_RATES["over_80"]
        tax = payout_under_limit * rate
        return {'chosen':tax, 'comprehensive':tax, 'separate':tax, 'choice':"저율과세"}
    # 종합 vs 분리 비교
    other_taxable = (other_pension_income - get_pension_income_deduction_amount(other_pension_income)) + other_comprehensive_income
    tax_wo = get_comprehensive_tax(other_taxable)
    tot_taxable = (total_gross - get_pension_income_deduction_amount(total_gross)) + other_comprehensive_income
    tax_w  = get_comprehensive_tax(tot_taxable)
    comp_tax = max(0, tax_w - tax_wo)
    sep_tax  = payout_under_limit * SEPARATE_TAX_RATE
    if comp_tax < sep_tax:
        return {'chosen':comp_tax, 'comprehensive':comp_tax, 'separate':sep_tax, 'choice':"종합과세"}
    else:
        return {'chosen':sep_tax, 'comprehensive':comp_tax, 'separate':sep_tax, 'choice':"분리과세"}

def calculate_lump_sum_tax(taxable_lump_sum):
    # 16.5% (기타소득세+지방세 포함)
    return taxable_lump_sum * OTHER_INCOME_TAX_RATE

def run_payout_simulation(inputs: UserInput, total_at_retirement, total_non_deductible_paid):
    post_ret = inputs.post_retirement_return / 100.0
    non_tax_w = total_non_deductible_paid
    tax_w     = total_at_retirement - non_tax_w
    years     = inputs.end_age - inputs.retirement_age
    rows = []
    for offset in range(years):
        age = inputs.retirement_age + offset
        rem = years - offset
        bal = non_tax_w + tax_w
        if bal <= 0: break
        # 연금 연초 인출 방식
        if rem <= 0:
            payout = 0
        elif post_ret == 0:
            payout = bal / rem
        else:
            factor = (1 - (1+post_ret)**-rem)/post_ret * (1+post_ret)
            payout = bal/factor if factor>0 else 0
        payout = min(payout, bal)
        from_non = min(payout, non_tax_w)
        from_tax = payout - from_non

        under = from_tax
        over_tax = 0
        if offset+1 <= MIN_PAYOUT_YEARS:
            limit = (bal * 1.2) / (MIN_PAYOUT_YEARS + 1 - (offset+1))
            if from_tax > limit:
                over = from_tax - limit
                under = limit
                over_tax = over * OTHER_INCOME_TAX_RATE

        tax_info = calculate_annual_pension_tax(under, inputs.other_pension_income,
                                                inputs.other_comprehensive_income, age) if under>0 else {'chosen':0,'comprehensive':0,'separate':0,'choice':"해당없음"}

        pen_tax    = tax_info['chosen']
        total_tax  = pen_tax + over_tax
        take_home  = payout - total_tax
        non_tax_w  = (non_tax_w - from_non) * (1 + post_ret)
        tax_w      = (tax_w     - from_tax) * (1 + post_ret)

        rows.append({
            "나이": age,
            "연간 수령액(세전)": payout,
            "연간 실수령액(세후)": take_home,
            "납부세금(총)": total_tax,
            "연금소득세": pen_tax,
            "한도초과 인출세금": over_tax,
            "연말 총 잔액": non_tax_w + tax_w,
            "과세대상 연금액": under,
            "종합과세액": tax_info['comprehensive'],
            "분리과세액": tax_info['separate'],
            "선택": tax_info['choice'],
        })
    return pd.DataFrame(rows)

# --- UI 표시 함수들은 기존과 동일 (display_initial_summary, display_asset_visuals, display_present_value_analysis, display_tax_choice_summary, display_simulation_details) ---

# (중략) …

# --- 콜백 함수 정의 ---
def reset_calculation_state():
    st.session_state.calculated = False

def update_retirement_age():
    new_ret = st.session_state.retirement_age
    min_end = new_ret + MIN_PAYOUT_YEARS
    # end_age가 min_end보다 작을 때만 갱신
    if st.session_state.end_age < min_end:
        st.session_state.end_age = min_end
    reset_calculation_state()

def update_from_profile():
    prof = st.session_state.investment_profile
    if prof != '직접 입력':
        pre, post = PROFILES[prof]
        st.session_state.pre_retirement_return  = pre
        st.session_state.post_retirement_return = post
    reset_calculation_state()

def auto_calculate_non_deductible():
    if st.session_state.auto_calc_non_deductible:
        ac = st.session_state.annual_contribution
        st.session_state.non_deductible_contribution = max(0, ac - PENSION_SAVING_TAX_CREDIT_LIMIT)
    else:
        st.session_state.non_deductible_contribution = 0
    reset_calculation_state()

def initialize_session():
    if st.session_state.get('initialized', False): return
    st.session_state.start_age                = 30
    st.session_state.retirement_age           = 60
    st.session_state.end_age                  = 90
    st.session_state.pre_retirement_return    = PROFILES['중립형'][0]
    st.session_state.post_retirement_return   = PROFILES['중립형'][1]
    st.session_state.inflation_rate           = 3.5
    st.session_state.annual_contribution      = 6_000_000
    st.session_state.other_non_deductible_total = 0
    st.session_state.other_pension_income     = 0
    st.session_state.other_comprehensive_income = 0
    st.session_state.income_level             = INCOME_LEVEL_LOW
    st.session_state.contribution_timing      = '연말'
    st.session_state.investment_profile       = '중립형'
    st.session_state.auto_calc_non_deductible = False
    st.session_state.non_deductible_contribution = 0
    st.session_state.calculated               = False
    st.session_state.has_calculated_once      = False
    st.session_state.initialized              = True

initialize_session()

# --- 사이드바 UI 구간 ---
st.set_page_config(layout="wide", page_title="연금저축 계산기")
st.title("연금저축 예상 수령액 계산기")

with st.sidebar:
    st.header("정보 입력")
    st.number_input("납입 시작 나이", 15, 100,
                    key='start_age', on_change=reset_calculation_state)
    st.number_input("은퇴 나이", MIN_RETIREMENT_AGE, 100,
                    key='retirement_age', on_change=update_retirement_age)
    # end_age의 min_value 고정 (동기화는 콜백에서만)
    st.number_input("수령 종료 나이",
                    MIN_RETIREMENT_AGE + MIN_PAYOUT_YEARS, 120,
                    key='end_age', on_change=reset_calculation_state)

    st.subheader("투자 성향 및 수익률 (%)")
    profile_help = (
        "- 안정형: 4.0% / 3.0%\n"
        "- 중립형: 6.0% / 4.0%\n"
        "- 공격형: 8.0% / 5.0%\n"
    )
    st.selectbox("투자 성향 선택", list(PROFILES.keys()),
                 key="investment_profile", on_change=update_from_profile,
                 help=profile_help)
    is_direct = st.session_state.investment_profile == '직접 입력'
    st.number_input("은퇴 전 수익률", -99.9, 99.9,
                    key='pre_retirement_return', step=0.1, format="%.1f",
                    on_change=reset_calculation_state, disabled=not is_direct)
    st.number_input("은퇴 후 수익률", -99.9, 99.9,
                    key='post_retirement_return', step=0.1, format="%.1f",
                    on_change=reset_calculation_state, disabled=not is_direct)
    st.number_input("예상 연평균 물가상승률", -99.9, 99.9,
                    key='inflation_rate', step=0.1, format="%.1f",
                    on_change=reset_calculation_state)

    st.subheader("연간 납입액 (원)")
    st.info(
        f"세액공제 한도: 연 {PENSION_SAVING_TAX_CREDIT_LIMIT/10000:,.0f} 만원\n"
        f"총 납입 한도: 연 {MAX_CONTRIBUTION_LIMIT/10000:,.0f} 만원"
    )
    st.radio("납입 시점", ['연말','연초'],
             key='contribution_timing', on_change=reset_calculation_state,
             horizontal=True)
    st.number_input("연간 총 납입액", 0, MAX_CONTRIBUTION_LIMIT,
                    key='annual_contribution', step=100000,
                    on_change=auto_calculate_non_deductible)
    st.checkbox("세액공제 한도 초과분을 비과세 원금으로 자동 계산",
                key="auto_calc_non_deductible",
                on_change=auto_calculate_non_deductible)
    st.number_input("└ 비과세 원금 (연간)", 0, MAX_CONTRIBUTION_LIMIT,
                    key='non_deductible_contribution', step=100000,
                    on_change=reset_calculation_state,
                    disabled=st.session_state.auto_calc_non_deductible)
    st.number_input("그 외, 세액공제 받지 않은 총액", 0,
                    key='other_non_deductible_total', step=100000,
                    on_change=reset_calculation_state)

    st.subheader("세금 정보")
    st.selectbox("연 소득 구간", [INCOME_LEVEL_LOW, INCOME_LEVEL_HIGH],
                 key='income_level', on_change=reset_calculation_state)
    st.number_input("국민연금 등 다른 연금 소득 (연간 세전)", 0,
                    key='other_pension_income', step=500000,
                    on_change=reset_calculation_state)
    st.number_input("임대·사업 등 기타 종합소득", 0,
                    key='other_comprehensive_income', step=1000000,
                    on_change=reset_calculation_state)

    if st.button("결과 확인하기", type="primary"):
        ui = UserInput(
            start_age=st.session_state.start_age,
            retirement_age=st.session_state.retirement_age,
            end_age=st.session_state.end_age,
            pre_retirement_return=st.session_state.pre_retirement_return,
            post_retirement_return=st.session_state.post_retirement_return,
            inflation_rate=st.session_state.inflation_rate,
            annual_contribution=st.session_state.annual_contribution,
            non_deductible_contribution=st.session_state.non_deductible_contribution,
            other_non_deductible_total=st.session_state.other_non_deductible_total,
            other_pension_income=st.session_state.other_pension_income,
            other_comprehensive_income=st.session_state.other_comprehensive_income,
            income_level=st.session_state.income_level,
            contribution_timing=st.session_state.contribution_timing
        )
        st.session_state.user_input_obj = ui

        errors = []
        if not (ui.start_age < ui.retirement_age < ui.end_age):
            errors.append("나이 순서(시작 < 은퇴 < 종료)가 올바르지 않습니다.")
        if ui.retirement_age < MIN_RETIREMENT_AGE:
            errors.append(f"은퇴 나이는 만 {MIN_RETIREMENT_AGE}세 이상이어야 합니다.")
        if ui.retirement_age - ui.start_age < MIN_CONTRIBUTION_YEARS:
            errors.append(f"최소 납입 기간은 {MIN_CONTRIBUTION_YEARS}년입니다.")
        if ui.end_age - ui.retirement_age < MIN_PAYOUT_YEARS:
            errors.append(f"최소 수령 기간은 {MIN_PAYOUT_YEARS}년입니다.")
        if ui.annual_contribution > MAX_CONTRIBUTION_LIMIT:
            errors.append(f"연간 납입액은 최대 {MAX_CONTRIBUTION_LIMIT:,.0f}원을 초과할 수 없습니다.")
        if ui.non_deductible_contribution > ui.annual_contribution:
            errors.append("'비과세 원금'은 '연간 총 납입액'보다 클 수 없습니다.")

        if errors:
            for e in errors: st.error(e, icon="🚨")
            st.session_state.calculated = False
        else:
            st.session_state.calculated = True
            st.session_state.has_calculated_once = True

# --- 결과 표시 로직 (이후 display_* 호출) ---
# … (기존과 동일)
