import streamlit as st
import pandas as pd
import plotly.express as px
from dataclasses import dataclass

# --- 데이터 클래스 및 상수 정의 ---
@dataclass
class UserInput:
    """
    사용자 입력을 관리하는 데이터 클래스.
    각 필드는 연금 계산에 필요한 사용자 입력값을 저장합니다.
    """
    start_age: int  # 연금 납입 시작 나이
    retirement_age: int  # 연금 수령 시작(은퇴) 나이
    end_age: int  # 연금 수령 종료 나이
    pre_retirement_return: float  # 은퇴 전 연평균 수익률 (%)
    post_retirement_return: float  # 은퇴 후 연평균 수익률 (%)
    inflation_rate: float  # 예상 연평균 물가상승률 (%)
    annual_contribution: int  # 연간 총 납입액
    non_deductible_contribution: int  # 연간 비과세 원금 (세액공제 받지 않은 금액)
    other_non_deductible_total: int  # ISA 만기 이전분 등 기타 비과세 원금 총합
    other_private_pension_income: int  # 다른 사적연금(퇴직연금 등)의 연간 소득 (세전)
    public_pension_income: int  # 공적연금(국민연금 등)의 연간 소득 (세전)
    other_comprehensive_income: int  # 연금을 제외한 종합소득 과세표준
    income_level: str  # 소득 구간 (세액공제율 결정용)
    contribution_timing: str  # 연간 납입 시점 ('연초' 또는 '연말')
    current_age_actual: int  # 현재 이용자의 실제 나이 (현재가치 계산용)

# 소득 구간 선택 옵션 정의
INCOME_LEVEL_LOW = '총급여 5,500만원 이하 (종합소득 4,500만원 이하)'
INCOME_LEVEL_HIGH = '총급여 5,500만원 초과 (종합소득 4,500만원 초과)'

# 세법 기준 상수 정의
MIN_RETIREMENT_AGE = 55  # 최소 연금 수령 시작 나이
MIN_CONTRIBUTION_YEARS = 5  # 최소 납입 기간
MIN_PAYOUT_YEARS = 10  # 최소 연금 수령 기간
PENSION_TAX_THRESHOLD = 15_000_000  # 사적연금 종합과세 기준 금액 (연 1,500만원)
SEPARATE_TAX_RATE = 0.165  # 16.5% 분리과세 세율 (지방소득세 포함)
OTHER_INCOME_TAX_RATE = 0.165  # 기타소득세율 (지방소득세 포함)
PENSION_SAVING_TAX_CREDIT_LIMIT = 6_000_000  # 연금저축 세액공제 대상 납입 한도
MAX_CONTRIBUTION_LIMIT = 18_000_000  # 연금계좌 총 납입 한도
PENSION_TAX_RATES = {"under_70": 0.055, "under_80": 0.044, "over_80": 0.033} # 연금소득세율 (나이별, 지방소득세 포함)
LOCAL_TAX_RATE = 0.1  # 지방소득세율 (본세의 10%)

# 종합소득세 과세표준 구간 및 세율 정의 (과세표준, 세율, 누진공제액)
COMPREHENSIVE_TAX_BRACKETS = [
    (14_000_000, 0.06, 0),
    (50_000_000, 0.15, 1_260_000),
    (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000),
    (300_000_000, 0.38, 19_940_000),
    (500_000_000, 0.40, 25_940_000),
    (1_000_000_000, 0.42, 35_940_000),
    (float('inf'), 0.45, 65_940_000),
]

# --- 계산 함수 ---

def calculate_total_at_retirement(inputs: UserInput):
    """
    은퇴 시점의 총 예상 적립금을 계산합니다.
    연간 납입액과 은퇴 전 수익률을 기반으로 자산 성장 시뮬레이션을 수행합니다.

    Args:
        inputs (UserInput): 사용자 입력 객체.

    Returns:
        tuple: (은퇴 시점 총 적립금, 연도별 자산 성장 데이터프레임)
    """
    pre_ret_rate = inputs.pre_retirement_return / 100.0  # 백분율을 소수로 변환
    contribution_years = inputs.retirement_age - inputs.start_age  # 납입 기간 계산

    asset_growth_data = []  # 연도별 자산 성장 데이터를 저장할 리스트
    current_value = 0  # 현재 자산 가치 (초기값 0)

    # 납입 기간 동안 자산 성장 시뮬레이션
    for year in range(contribution_years):
        if inputs.contribution_timing == '연초':
            # 연초 납입: 납입 후 수익 발생
            current_value = (current_value + inputs.annual_contribution) * (1 + pre_ret_rate)
        else:
            # 연말 납입: 수익 발생 후 납입
            current_value = current_value * (1 + pre_ret_rate) + inputs.annual_contribution
        # 연도별 자산 가치 기록
        asset_growth_data.append({'year': inputs.start_age + year + 1, 'value': current_value})
    return current_value, pd.DataFrame(asset_growth_data)

def calculate_annual_pension_tax(private_pension_gross: float, user_inputs: UserInput, current_age: int) -> dict:
    """
    연간 연금소득세를 계산하고, 과세 방식 선택 과정을 반환합니다.
    사적연금 금액에 따라 저율 분리과세, 종합과세, 또는 16.5% 분리과세 중 유리한 방식을 선택합니다.

    Args:
        private_pension_gross (float): 현재 계산 중인 사적연금(연금저축)의 연간 과세 대상 수령액.
        user_inputs (UserInput): UserInput 객체 전체를 전달하여 다른 연금 소득 및 종합 소득에 접근.
        current_age (int): 현재 연금 수령자의 나이.

    Returns:
        dict: 선택된 세금액, 종합과세액, 분리과세액, 선택된 과세 방식 정보.
    """

    # 1. 사적연금 1,500만원 이하인 경우: 저율 분리과세 (나이별 세율 적용)
    if private_pension_gross <= PENSION_TAX_THRESHOLD:
        if current_age < 70:
            rate = PENSION_TAX_RATES["under_70"]
        elif current_age < 80:
            rate = PENSION_TAX_RATES["under_80"]
        else:
            rate = PENSION_TAX_RATES["over_80"]
        tax = private_pension_gross * rate
        return {'chosen': tax, 'comprehensive': tax, 'separate': tax, 'choice': "저율과세"}
    # 2. 사적연금 1,500만원 초과인 경우: 종합과세 vs 16.5% 분리과세 선택
    else:
        # 옵션 A: 종합과세 시 세액 계산
        # 모든 연금소득 합산 (현재 사적연금 + 다른 사적연금 + 공적연금)
        total_pension_income_for_comp = private_pension_gross + user_inputs.other_private_pension_income + user_inputs.public_pension_income
        
        # 연금소득공제는 총 연금소득(공적 + 사적)에 대해 적용
        taxable_pension_income_for_comp = total_pension_income_for_comp - get_pension_income_deduction_amount(total_pension_income_for_comp)

        # 사적연금(현재 계산 중인 것)을 제외한 다른 종합소득만 있을 때의 세금 계산
        # (다른 사적연금 + 공적연금)의 총합에 대한 연금소득공제 적용
        total_other_pension_income_for_deduction = user_inputs.other_private_pension_income + user_inputs.public_pension_income
        taxable_other_pension_income_only = total_other_pension_income_for_deduction - get_pension_income_deduction_amount(total_other_pension_income_for_deduction)
        
        # 다른 종합소득(과세표준)과 연금 외 소득을 합산하여 현재 사적연금 제외 시 과세표준 계산
        taxable_income_without_current_private = taxable_other_pension_income_only + user_inputs.other_comprehensive_income

        # 현재 사적연금 제외 시의 종합소득세 계산
        tax_without_private_pension = get_comprehensive_tax(taxable_income_without_current_private)

        # 사적연금 포함 모든 소득이 있을 때의 과세표준 계산
        taxable_all_income = taxable_pension_income_for_comp + user_inputs.other_comprehensive_income
        # 사적연금 포함 모든 소득이 있을 때의 종합소득세 계산
        tax_with_private_pension_comprehensive = get_comprehensive_tax(taxable_all_income)

        # 사적연금으로 인해 추가되는 종합소득세 (종합과세 시)
        tax_on_private_pension_comp = max(0, tax_with_private_pension_comprehensive - tax_without_private_pension)

        # 옵션 B: 16.5% 분리과세 시 세액 계산 (사적연금 전체에 16.5% 적용)
        separate_tax = private_pension_gross * SEPARATE_TAX_RATE

        # 종합과세와 분리과세 중 유리한 방식 선택
        if tax_on_private_pension_comp < separate_tax:
            return {'chosen': tax_on_private_pension_comp, 'comprehensive': tax_on_private_pension_comp, 'separate': separate_tax, 'choice': "종합과세"}
        else:
            return {'chosen': separate_tax, 'comprehensive': tax_on_private_pension_comp, 'separate': separate_tax, 'choice': "분리과세"}


def run_payout_simulation(inputs: UserInput, total_at_retirement, total_non_deductible_paid):
    """
    연금 인출 시뮬레이션을 실행하여 연도별 상세 데이터를 생성합니다.
    비과세 재원 우선 인출, 연금수령한도, 세금 계산 등을 포함합니다.

    Args:
        inputs (UserInput): 사용자 입력 객체.
        total_at_retirement (float): 은퇴 시점의 총 적립금.
        total_non_deductible_paid (float): 총 납입 비과세 원금.

    Returns:
        pd.DataFrame: 연도별 연금 인출 상세 시뮬레이션 결과.
    """
    post_ret_rate = inputs.post_retirement_return / 100.0  # 백분율을 소수로 변환
    non_taxable_wallet = total_non_deductible_paid  # 비과세 재원
    taxable_wallet = total_at_retirement - non_taxable_wallet  # 과세 대상 재원
    payout_years = inputs.end_age - inputs.retirement_age  # 연금 수령 기간
    annual_breakdown = []  # 연도별 상세 데이터를 저장할 리스트

    # 연금 수령 기간 동안 시뮬레이션
    for year_offset in range(payout_years):
        current_balance = non_taxable_wallet + taxable_wallet  # 현재 총 잔액
        if current_balance <= 0:  # 잔액이 없으면 시뮬레이션 중단
            break

        current_age = inputs.retirement_age + year_offset  # 현재 연금 수령 나이
        payout_year_count = year_offset + 1  # 연금 수령 몇 년차인지
        remaining_years = payout_years - year_offset  # 남은 수령 기간

        # 1. 연간 수령액 계산 (연초 인출 기준, 연금 현가 공식 활용)
        if remaining_years <= 0:
            annual_payout = 0
        elif post_ret_rate == 0:  # 수익률이 0%인 경우 단순 균등 분할
            annual_payout = current_balance / remaining_years
        elif post_ret_rate <= -1: # 수익률이 -100% 이하인 경우 전액 인출
            annual_payout = current_balance
        else:
            # 연금의 현가 계수 (보통 연금)
            annuity_factor_ordinary = (1 - (1 + post_ret_rate)**-remaining_years) / post_ret_rate
            # 기시급 연금의 현가 계수 (연초 인출이므로)
            annuity_factor = annuity_factor_ordinary * (1 + post_ret_rate)
            annual_payout = current_balance / annuity_factor if annuity_factor > 0 else 0

        annual_payout = min(annual_payout, current_balance)  # 현재 잔액보다 많이 인출할 수 없음

        # 2. 인출 재원 구분 (비과세 재원 우선 인출)
        from_non_taxable = min(annual_payout, non_taxable_wallet)  # 비과세 재원에서 인출할 금액
        from_taxable = annual_payout - from_non_taxable  # 과세 대상 재원에서 인출할 금액 (사적연금 과세 대상 수령액)

        # 3. 과세 대상 인출액에 대한 세금 계산
        pension_tax_info = {'chosen': 0, 'comprehensive': 0, 'separate': 0, 'choice': "해당없음"}
        tax_on_limit_excess = 0  # 연금수령한도 초과 시 발생하는 기타소득세
        pension_payout_under_limit = from_taxable  # 한도 내 연금소득세 대상 금액

        # 연금수령한도 적용 (1~10년차)
        if payout_year_count <= 10:
            # 한도 계산: (연초 계좌 잔액 * 120%) / (11 - 현재 수령 연차)
            pension_payout_limit = (current_balance * 1.2) / (11 - payout_year_count)
            if from_taxable > pension_payout_limit:
                pension_payout_over_limit = from_taxable - pension_payout_limit  # 한도 초과분
                pension_payout_under_limit = pension_payout_limit  # 한도 내 금액은 연금소득세 대상
                tax_on_limit_excess = pension_payout_over_limit * OTHER_INCOME_TAX_RATE  # 초과분은 기타소득세
        
        # 한도 내 과세 대상 연금액에 대한 연금소득세 계산
        if pension_payout_under_limit > 0:
            pension_tax_info = calculate_annual_pension_tax(
                private_pension_gross=pension_payout_under_limit,  # 사적연금 과세 대상 금액만 전달
                user_inputs=inputs,  # UserInput 객체 전체 전달
                current_age=current_age
            )

        pension_tax = pension_tax_info['chosen']  # 최종 선택된 연금소득세
        total_tax_paid = pension_tax + tax_on_limit_excess  # 총 납부 세금
        annual_take_home = annual_payout - total_tax_paid  # 연간 실수령액 (세후)

        # 4. 연말 잔액 업데이트 (인출 후 남은 금액에 대해 수익 발생)
        non_taxable_wallet = (non_taxable_wallet - from_non_taxable) * (1 + post_ret_rate)
        taxable_wallet = (taxable_wallet - from_taxable) * (1 + post_ret_rate)

        # 연도별 상세 데이터 기록
        annual_breakdown.append({
            "나이": current_age,
            "연간 수령액(세전)": annual_payout,
            "연간 실수령액(세후)": annual_take_home,
            "납부세금(총)": total_tax_paid,
            "연금소득세": pension_tax,
            "한도초과 인출세금": tax_on_limit_excess,
            "연말 총 잔액": non_taxable_wallet + taxable_wallet,
            "과세대상 연금액": pension_payout_under_limit,
            "종합과세액": pension_tax_info['comprehensive'],
            "분리과세액": pension_tax_info['separate'],
            "선택": pension_tax_info['choice'],
        })
    return pd.DataFrame(annual_breakdown)

def get_pension_income_deduction_amount(pension_income):
    """
    연금소득공제액을 계산합니다.
    공적연금과 사적연금 합산 금액에 대해 적용됩니다.

    Args:
        pension_income (float): 총 연금 소득.

    Returns:
        float: 연금소득공제액.
    """
    if pension_income <= 3_500_000:
        return pension_income
    if pension_income <= 7_000_000:
        return 3_500_000 + (pension_income - 3_500_000) * 0.4
    if pension_income <= 14_000_000:
        return 4_900_000 + (pension_income - 7_000_000) * 0.2
    deduction = 6_300_000 + (pension_income - 14_000_000) * 0.1
    return min(deduction, 9_000_000) # 연금소득공제 한도 900만원

def get_comprehensive_tax(taxable_income, include_local_tax=True):
    """
    종합소득 과세표준에 대한 세액을 계산합니다.

    Args:
        taxable_income (float): 종합소득 과세표준.
        include_local_tax (bool): 지방소득세 포함 여부.

    Returns:
        float: 계산된 종합소득세액.
    """
    if taxable_income <= 0:
        return 0
    tax = 0
    # 과세표준 구간을 순회하며 세금 계산
    for threshold, rate, deduction in COMPREHENSIVE_TAX_BRACKETS:
        if taxable_income <= threshold:
            tax = taxable_income * rate - deduction
            break
    # 지방소득세 포함 여부에 따라 최종 세액 반환
    return tax * (1 + LOCAL_TAX_RATE) if include_local_tax else tax

def calculate_lump_sum_tax(taxable_lump_sum):
    """
    연금계좌 일시금 수령 시 적용될 기타소득세를 계산합니다.

    Args:
        taxable_lump_sum (float): 일시금 수령 시 과세 대상 금액.

    Returns:
        float: 계산된 기타소득세액.
    """
    if taxable_lump_sum <= 0:
        return 0
    return taxable_lump_sum * OTHER_INCOME_TAX_RATE

# --- UI 및 결과 표시 함수 ---

def display_initial_summary(inputs: UserInput, total_at_retirement, simulation_df, total_tax_credit):
    """
    핵심 예상 결과를 3개의 지표로 요약하여 보여줍니다.
    은퇴 시점 총 적립금, 연간/월간 세후 수령액, 총 예상 절세액을 표시합니다.

    Args:
        inputs (UserInput): 사용자 입력 객체.
        total_at_retirement (float): 은퇴 시점의 총 적립금.
        simulation_df (pd.DataFrame): 연금 인출 시뮬레이션 결과 데이터프레임.
        total_tax_credit (float): 총 예상 세액공제액.
    """
    st.header("📈 예상 결과 요약")
    # 첫 해 연간 실수령액 계산
    first_year_take_home = simulation_df.iloc[0]["연간 실수령액(세후)"] if not simulation_df.empty else 0
    # 월간 수령액 계산
    monthly_take_home = first_year_take_home / 12

    # 4개 열로 지표 표시
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"{inputs.retirement_age}세 시점 총 적립금", f"{total_at_retirement:,.0f} 원")
    col2.metric("연간 수령액 (세후)", f"{first_year_take_home:,.0f} 원")
    col3.metric("월간 수령액 (세후)", f"{monthly_take_home:,.0f} 원", help="연간 수령액을 12로 나눈 값입니다.")
    col4.metric("총 예상 절세액 (세액공제)", f"{total_tax_credit:,.0f} 원", help="납입 기간 동안 최대로 받을 수 있는 세액공제 혜택의 총합입니다.")

def display_asset_visuals(total_at_retirement, total_principal, asset_growth_df, simulation_df):
    """
    자산 성장 그래프와 최종 기여도 파이 차트를 보여줍니다.
    연령별 예상 적립금 추이 (은퇴 전/후)와 총 적립금의 원금/수익 기여도를 시각화합니다.

    Args:
        total_at_retirement (float): 은퇴 시점의 총 적립금.
        total_principal (float): 총 납입 원금.
        asset_growth_df (pd.DataFrame): 은퇴 전 자산 성장 데이터프레임.
        simulation_df (pd.DataFrame): 연금 인출 시뮬레이션 결과 데이터프레임.
    """
    st.header("📊 자산 성장 시각화")
    col1, col2 = st.columns([2, 1]) # 그래프와 파이 차트의 비율 설정

    with col1:
        st.subheader("연령별 예상 적립금 추이")

        # 1. 은퇴 전 적립 기간 데이터 준비
        pre_retirement_df = asset_growth_df.rename(columns={'year': '나이', 'value': '예상 적립금'})

        # 2. 은퇴 후 인출 기간 데이터 준비
        post_retirement_df = pd.DataFrame()
        if not simulation_df.empty:
            post_retirement_df = simulation_df[['나이', '연말 총 잔액']].copy()
            post_retirement_df.rename(columns={'연말 총 잔액': '예상 적립금'}, inplace=True)

        # 3. 은퇴 시점 데이터를 포함하여 전/후 데이터 연결
        full_timeline_df = pre_retirement_df
        if not asset_growth_df.empty:
            # 은퇴 시점의 데이터를 명확히 추가하여 그래프 연결
            retirement_point = pd.DataFrame([{'나이': pre_retirement_df['나이'].iloc[-1], '예상 적립금': total_at_retirement}])
            full_timeline_df = pd.concat([pre_retirement_df, retirement_point, post_retirement_df], ignore_index=True)
        elif not post_retirement_df.empty: # 납입 없이 바로 인출 시작하는 경우 (예: 기존 연금계좌 보유자가 바로 인출 시작)
            start_point = pd.DataFrame([{'나이': simulation_df['나이'].iloc[0], '예상 적립금': total_at_retirement}])
            full_timeline_df = pd.concat([start_point, post_retirement_df], ignore_index=True)

        # 4. 라인 그래프 그리기
        st.line_chart(full_timeline_df.set_index('나이'))

    with col2:
        st.subheader("최종 적립금 기여도")
        total_profit = total_at_retirement - total_principal  # 총 투자 수익 계산
        if total_profit < 0:
            st.warning(f"총 투자 손실이 {total_profit:,.0f}원 발생했습니다.")
            # 손실 발생 시 원금만 표시
            pie_data = pd.DataFrame({'금액': [total_principal], '항목': ['총 납입 원금']})
        else:
            # 수익 발생 시 원금과 수익 함께 표시
            pie_data = pd.DataFrame({'금액': [total_principal, total_profit], '항목': ['총 납입 원금', '총 투자 수익']})
        # 파이 차트 생성 및 표시
        fig = px.pie(pie_data, values='금액', names='항목', hole=.3, color_discrete_sequence=px.colors.sequential.Blues_r)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)

def display_present_value_analysis(inputs: UserInput, simulation_df, total_at_retirement, total_non_deductible_paid, current_age_actual: int):
    """
    현재가치 분석 및 일시금 수령액을 비교하여 보여줍니다.
    첫 해 연금 수령액의 현재가치, 총 연금 인출액(세후, 명목), 일시금 수령액(세후)을 표시합니다.

    Args:
        inputs (UserInput): 사용자 입력 객체.
        simulation_df (pd.DataFrame): 연금 인출 시뮬레이션 결과 데이터프레임.
        total_at_retirement (float): 은퇴 시점의 총 적립금.
        total_non_deductible_paid (float): 총 납입 비과세 원금.
        current_age_actual (int): 현재 이용자의 실제 나이.
    """
    st.header("🕒 현재가치 분석 및 일시금 수령 비교")

    # --- 변수 정의 ---
    payout_years = inputs.end_age - inputs.retirement_age
    inflation_rate = inputs.inflation_rate / 100.0

    # --- 계산: 첫 해 수령액(현재가치) ---
    first_year_pv = 0
    pv_ratio_text = None
    if not simulation_df.empty:
        first_year_row = simulation_df.iloc[0]
        first_year_take_home = first_year_row["연간 실수령액(세후)"]
        first_year_age = first_year_row["나이"]
        # 물가상승률을 고려하여 현재가치로 할인
        if 1 + inflation_rate > 0:
            first_year_pv = first_year_take_home / ((1 + inflation_rate) ** (first_year_age - current_age_actual))
        if first_year_take_home > 0:
            pv_ratio = (first_year_pv / first_year_take_home) * 100
            pv_ratio_text = f"현재의 구매력으로 환산 시 {pv_ratio:.1f}% 수준"
    # 현재가치에 대한 도움말 문구
    pv_help_text = f"즉, 연금 수령 첫 해({inputs.retirement_age}세)에 받는 세후 연금수령액(연간)을 현재를 기준으로 할인({inputs.inflation_rate}% 물가상승률 적용)한 금액입니다.\n\n참고: 인플레이션은 연금을 납입하는 중에도 발생합니다."

    # --- 계산: 일시금 수령액 ---
    taxable_lump_sum = total_at_retirement - total_non_deductible_paid  # 과세 대상 일시금
    lump_sum_tax = calculate_lump_sum_tax(taxable_lump_sum)  # 일시금 기타소득세 계산
    lump_sum_take_home = total_at_retirement - lump_sum_tax  # 세후 일시금 수령액
    lump_sum_help_text = f"은퇴 후 일시금 수령 시, 과세대상금액({taxable_lump_sum:,.0f}원)에 대해 기타소득세(16.5%)가 적용됩니다.\n\n참고: 일시금으로 수령하는 경우에 일반적으로 손해를 봅니다."

    # 일시금의 현재가치 계산 (비교용)
    discounted_lump_sum = 0
    if inputs.retirement_age >= current_age_actual and (1 + inflation_rate) > 0:
        years_to_discount = inputs.retirement_age - current_age_actual
        discounted_lump_sum = lump_sum_take_home / ((1 + inflation_rate) ** years_to_discount)

    # --- 계산: 총 연금을 분기마다 연금으로 수령 (세후, 명목) ---
    total_nominal_after_tax_pension = simulation_df['연간 실수령액(세후)'].sum() if not simulation_df.empty else 0
    # 총 명목 연금 인출액에 대한 도움말 문구
    total_nominal_after_tax_pension_help_text = f"은퇴 후 {payout_years}년간 받게 될 총 연금 실수령액(세후)의 명목 금액입니다. 이는 물가상승률이 반영되지 않은 단순 합계액입니다. 이 금액에는 은퇴 후 잔여 자산에 대한 투자 수익({inputs.post_retirement_return}% 은퇴 후 수익률 적용)이 포함됩니다."

    # --- UI 배치: 3개 열로 구성 ---
    col1, col2, col3 = st.columns([1, 1.5, 1]) # 열 비율 조정

    with col1:
        st.subheader("첫 해 연금 수령액의 현재가치")
        st.metric("현재를 기준으로 환산한 구매력", f"{first_year_pv:,.0f} 원", delta=pv_ratio_text, delta_color="off", help=pv_help_text)

    with col2:
        st.subheader("총 연금 인출액 (세후, 명목)")
        st.metric("총 인출액 (세후)", f"{total_nominal_after_tax_pension:,.0f} 원", help=total_nominal_after_tax_pension_help_text)

    with col3:
        st.subheader("일시금 수령 시 (세후)")
        lump_sum_delta_text = None
        if lump_sum_take_home > 0:
            lump_sum_delta_text = f"물가상승률을 고려하면 현재의 {discounted_lump_sum:,.0f}원과 같은 구매력을 가집니다."
        st.metric("세후 일시금 수령액", f"{lump_sum_take_home:,.0f} 원", delta=lump_sum_delta_text, delta_color="off", help=lump_sum_help_text)

def display_simulation_details(simulation_df):
    """
    연금 인출 상세 시뮬레이션 결과(그래프, 테이블)를 보여줍니다.
    연도별 연금 수령액 구성 바 차트와 상세 테이블을 표시합니다.

    Args:
        simulation_df (pd.DataFrame): 연금 인출 시뮬레이션 결과 데이터프레임.
    """
    st.info("실제 인출 순서(비과세 재원 우선) 및 연금수령한도를 반영한 연도별 상세 예상치입니다.")

    # 그래프를 위한 데이터 변환 (melt)
    chart_df = simulation_df.melt(id_vars='나이', value_vars=['연간 실수령액(세후)', '연금소득세', '한도초과 인출세금'], var_name='항목', value_name='금액')
    # 연도별 연금 수령액 구성 바 차트 생성
    fig = px.bar(chart_df, x='나이', y='금액', color='항목', title='연도별 연금 수령액 구성')
    st.plotly_chart(fig, use_container_width=True)

    display_df = simulation_df.copy()
    # '월간 실수령액(세후)' 열 추가
    display_df['월간 실수령액(세후)'] = display_df['연간 실수령액(세후)'] / 12

    # 금액 컬럼을 포맷팅하여 표시
    cols_to_format = ["연간 수령액(세전)", "연간 실수령액(세후)", "월간 실수령액(세후)", "납부세금(총)", "연금소득세", "한도초과 인출세금", "연말 총 잔액"]
    for col in cols_to_format:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f} 원" if pd.notna(x) else "0 원")

    # 표시할 컬럼 선택 및 데이터프레임 출력
    display_cols = ["나이", "연간 수령액(세전)", "연간 실수령액(세후)", "월간 실수령액(세후)", "납부세금(총)", "연금소득세", "한도초과 인출세금"]
    st.dataframe(display_df[display_cols], use_container_width=True, hide_index=True)

# --- 메인 앱 로직 ---

# Streamlit 페이지 설정
st.set_page_config(layout="wide", page_title="연금저축 계산기")
st.title("연금저축 예상 수령액 계산기")

# 투자 성향별 예상 수익률 프로필 정의 (은퇴 전, 은퇴 후)
PROFILES = {'안정형': (4.0, 3.0), '중립형': (6.0, 4.0), '공격형': (8.0, 5.0), '직접 입력': (6.0, 4.0)}

# --- 콜백 함수 정의 ---
def reset_calculation_state():
    """계산 상태를 초기화하여 '결과 확인하기' 버튼을 다시 누르도록 유도합니다."""
    st.session_state.calculated = False

def update_from_profile():
    """투자 성향 선택에 따라 수익률 입력값을 업데이트하는 콜백 함수."""
    profile_key = st.session_state.investment_profile
    if profile_key != '직접 입력':
        pre_ret, post_ret = PROFILES[profile_key]
        st.session_state.pre_retirement_return = pre_ret
        st.session_state.post_retirement_return = post_ret
    reset_calculation_state()

def auto_calculate_non_deductible():
    """
    '세액공제 한도 초과분을 비과세 원금으로 자동 계산' 체크박스에 따라
    비과세 원금 납입액을 자동 계산하거나 초기화하는 콜백 함수.
    """
    if st.session_state.auto_calc_non_deductible:
        annual_contribution = st.session_state.annual_contribution
        # 연간 총 납입액에서 세액공제 한도를 초과하는 부분을 비과세 원금으로 설정
        st.session_state.non_deductible_contribution = max(0, annual_contribution - PENSION_SAVING_TAX_CREDIT_LIMIT)
    else:
        st.session_state.non_deductible_contribution = 0
    reset_calculation_state()

def update_retirement_age_and_end_age():
    """
    은퇴 나이가 변경될 때 수령 종료 나이를 자동으로 조정하는 콜백 함수.
    최소 수령 기간(MIN_PAYOUT_YEARS)을 보장합니다.
    """
    reset_calculation_state() # 계산 상태 초기화

    # 새로운 은퇴 나이에 따른 최소 수령 종료 나이 계산
    min_required_end_age = st.session_state.retirement_age + MIN_PAYOUT_YEARS

    # 현재 수령 종료 나이가 최소 요구치보다 작으면 업데이트
    if st.session_state.end_age < min_required_end_age:
        st.session_state.end_age = min_required_end_age

# --- 세션 상태 초기화 ---
def initialize_session():
    """
    Streamlit 세션 상태를 초기화합니다.
    앱이 처음 로드될 때만 실행됩니다.
    """
    if 'initialized' in st.session_state:
        return

    # 기본값 설정
    st.session_state.start_age = 30
    st.session_state.retirement_age = 60
    st.session_state.end_age = 90
    st.session_state.pre_retirement_return = PROFILES['중립형'][0]
    st.session_state.post_retirement_return = PROFILES['중립형'][1]
    st.session_state.inflation_rate = 3.5
    st.session_state.annual_contribution = 6_000_000
    st.session_state.other_non_deductible_total = 0
    st.session_state.other_private_pension_income = 0
    st.session_state.public_pension_income = 0
    st.session_state.other_comprehensive_income = 0
    st.session_state.income_level = INCOME_LEVEL_LOW
    st.session_state.contribution_timing = '연말'
    st.session_state.current_age_actual = 30 # 초기값 설정 (납입 시작 나이와 동일하게 설정)

    st.session_state.investment_profile = '중립형'
    st.session_state.auto_calc_non_deductible = False
    st.session_state.non_deductible_contribution = 0

    st.session_state.calculated = False # 계산 결과가 있는지 여부
    st.session_state.has_calculated_once = False # 한 번이라도 계산 버튼을 눌렀는지 여부
    st.session_state.initialized = True # 초기화 완료 플래그

initialize_session()

# --- 사이드바 UI 구성 ---
with st.sidebar:
    st.header("정보 입력")

    # 연령 관련 입력 필드
    st.number_input("납입 시작 나이", 15, 100, key='start_age', on_change=reset_calculation_state)
    st.number_input("은퇴 나이", MIN_RETIREMENT_AGE, 100, key='retirement_age', on_change=update_retirement_age_and_end_age)
    st.number_input("수령 종료 나이", MIN_RETIREMENT_AGE + MIN_PAYOUT_YEARS, 120, key='end_age', on_change=reset_calculation_state)
    st.number_input("현재 이용자님의 나이", 15, 120, key='current_age_actual', on_change=reset_calculation_state, help="미래 연금액을 현재 시점의 가치로 환산하기 위해 실제 나이(현재)를 입력하세요.")


    st.subheader("투자 성향 및 수익률 (%)")
    # 투자 성향 선택 드롭다운 및 도움말
    profile_help = "각 투자 성향별 예상 수익률(은퇴 전/후)입니다:\n- 안정형: 4.0% / 3.0%\n- 중립형: 6.0% / 4.0%\n- 공격형: 8.0% / 5.0%"
    st.selectbox("투자 성향 선택", list(PROFILES.keys()), key="investment_profile", on_change=update_from_profile, help=profile_help)
    is_direct_input = st.session_state.investment_profile == '직접 입력' # '직접 입력' 선택 시에만 수익률 입력 활성화
    help_text_return = "투자는 원금 손실이 발생할 수 있으며, 손실이 예상될 경우에만 음수 값을 입력하세요."
    st.number_input("은퇴 전 수익률", -99.9, 99.9, key='pre_retirement_return', format="%.1f", step=0.1, on_change=reset_calculation_state, disabled=not is_direct_input, help=help_text_return)
    st.number_input("은퇴 후 수익률", -99.9, 99.9, key='post_retirement_return', format="%.1f", step=0.1, on_change=reset_calculation_state, disabled=not is_direct_input, help=help_text_return)
    st.number_input("예상 연평균 물가상승률", -99.9, 99.9, key='inflation_rate', format="%.1f", step=0.1, on_change=reset_calculation_state)

    st.subheader("연간 납입액 (원)")
    # 납입 한도 정보 표시
    st.info(
        f"연금저축 세액공제 한도: 연 {PENSION_SAVING_TAX_CREDIT_LIMIT/10000:,.0f}만원\n"
        f"연금계좌 총 납입 한도: 연 {MAX_CONTRIBUTION_LIMIT/10000:,.0f}만원"
    )
    # 납입 시점 선택
    st.radio("납입 시점", ['연말', '연초'], key='contribution_timing', on_change=reset_calculation_state, horizontal=True, help="연초 납입은 납입금이 1년 치 수익을 온전히 반영하여 복리 효과가 더 큽니다.")
    # 연간 총 납입액 입력
    st.number_input("연간 총 납입액", 0, MAX_CONTRIBUTION_LIMIT, key='annual_contribution', step=100000, on_change=auto_calculate_non_deductible)
    # 비과세 원금 자동 계산 체크박스
    st.checkbox("세액공제 한도 초과분을 비과세 원금으로 자동 계산", key="auto_calc_non_deductible", on_change=auto_calculate_non_deductible)
    # 비과세 원금 입력 (자동 계산 체크 시 비활성화)
    st.number_input("└ 비과세 원금 (연간)", 0, MAX_CONTRIBUTION_LIMIT, key='non_deductible_contribution', step=100000, on_change=reset_calculation_state, disabled=st.session_state.auto_calc_non_deductible)
    st.number_input("그 외, 세액공제 받지 않은 총액", 0, key='other_non_deductible_total', step=100000, on_change=reset_calculation_state, help="ISA 만기 이전분 등 납입 기간 동안 발생한 비과세 원금 총합을 입력합니다.")

    st.subheader("세금 정보")
    # 소득 구간 선택
    st.selectbox("현재 연 소득 구간 (세액공제율 결정)", [INCOME_LEVEL_LOW, INCOME_LEVEL_HIGH], key='income_level', on_change=reset_calculation_state)
    st.info("💡 은퇴 후 다른 소득이 있으신가요?\n\n미래의 다른 소득을 예상하기 어렵다면 0으로 비워둘 수 있으나, 이 경우 세금 계산이 부정확해질 수 있습니다.")
    # 기타 연금 소득 및 종합 소득 입력
    st.number_input("퇴직연금 등 다른 사적연금 소득 (연간 세전)", 0, key='other_private_pension_income', step=500000, on_change=reset_calculation_state)
    st.number_input("공적연금 소득 (연간 세전)", 0, key='public_pension_income', step=500000, on_change=reset_calculation_state)
    st.number_input("연금을 제외한 종합소득에 의한 과세표준", 0, key='other_comprehensive_income', step=1000000, on_change=reset_calculation_state, help="사업소득, 임대소득, 이자/배당소득 등 연금소득을 제외한 나머지 소득에 대해 필요경비 및 모든 소득공제(인적공제, 특별소득공제 등)를 차감한 후의 최종 과세표준을 입력하세요.")

    # 결과 확인 버튼
    if st.button("결과 확인하기", type="primary"):
        # 현재 입력값을 UserInput 객체로 묶음
        current_inputs = UserInput(
            start_age=st.session_state.start_age, retirement_age=st.session_state.retirement_age, end_age=st.session_state.end_age,
            pre_retirement_return=st.session_state.pre_retirement_return, post_retirement_return=st.session_state.post_retirement_return,
            inflation_rate=st.session_state.inflation_rate, annual_contribution=st.session_state.annual_contribution,
            non_deductible_contribution=st.session_state.non_deductible_contribution, other_non_deductible_total=st.session_state.other_non_deductible_total,
            other_private_pension_income=st.session_state.other_private_pension_income,
            public_pension_income=st.session_state.public_pension_income,
            other_comprehensive_income=st.session_state.other_comprehensive_income,
            income_level=st.session_state.income_level, contribution_timing=st.session_state.contribution_timing,
            current_age_actual=st.session_state.current_age_actual
        )
        st.session_state.user_input_obj = current_inputs

        errors = [] # 유효성 검사 오류를 저장할 리스트
        ui = current_inputs
        # 입력값 유효성 검사
        if not (ui.start_age < ui.retirement_age < ui.end_age): errors.append("나이 순서(시작 < 은퇴 < 종료)가 올바르지 않습니다.")
        if ui.retirement_age < MIN_RETIREMENT_AGE: errors.append(f"은퇴 나이는 만 {MIN_RETIREMENT_AGE}세 이상이어야 합니다.")
        if ui.retirement_age - ui.start_age < MIN_CONTRIBUTION_YEARS: errors.append(f"최소 납입 기간은 {MIN_CONTRIBUTION_YEARS}년입니다.")
        if ui.end_age - ui.retirement_age < MIN_PAYOUT_YEARS: errors.append(f"최소 연금 수령 기간은 {MIN_PAYOUT_YEARS}년입니다.")
        if ui.annual_contribution > MAX_CONTRIBUTION_LIMIT: errors.append(f"연간 총 납입액은 최대 한도({MAX_CONTRIBUTION_LIMIT:,.0f}원)를 초과할 수 없습니다.")
        if ui.non_deductible_contribution > ui.annual_contribution: errors.append("'비과세 원금'은 '연간 총 납입액'보다 클 수 없습니다.")

        if errors:
            # 오류가 있을 경우 오류 메시지 표시 및 계산 상태 초기화
            for error in errors: st.error(error, icon="🚨")
            st.session_state.calculated = False
        else:
            # 오류가 없으면 계산 상태를 True로 설정하고, 한 번 계산했음을 표시
            st.session_state.calculated = True
            st.session_state.has_calculated_once = True

# --- 결과 표시 로직 ---
if st.session_state.get('calculated', False):
    ui = st.session_state.user_input_obj # UserInput 객체 가져오기
    contribution_years = ui.retirement_age - ui.start_age # 납입 기간
    total_principal_paid = ui.annual_contribution * contribution_years # 총 납입 원금
    non_deductible_from_annual = ui.non_deductible_contribution * contribution_years # 연간 비과세 납입액의 총합
    total_non_deductible_paid = non_deductible_from_annual + ui.other_non_deductible_total # 총 비과세 원금

    # 세액공제율 결정
    tax_credit_rate = 0.165 if ui.income_level == INCOME_LEVEL_LOW else 0.132
    # 세액공제 대상 금액
    tax_credit_base = ui.annual_contribution - ui.non_deductible_contribution
    # 연간 세액공제액
    tax_credit_per_year = min(tax_credit_base, PENSION_SAVING_TAX_CREDIT_LIMIT) * tax_credit_rate
    # 총 예상 세액공제액
    total_tax_credit = tax_credit_per_year * contribution_years

    # 은퇴 시점 총 적립금 계산 및 자산 성장 데이터프레임 가져오기
    total_at_retirement, asset_growth_df = calculate_total_at_retirement(ui)

    if total_at_retirement > 0:
        # 연금 인출 시뮬레이션 실행
        simulation_df = run_payout_simulation(ui, total_at_retirement, total_non_deductible_paid)

        # 결과 요약 및 시각화 표시
        display_initial_summary(ui, total_at_retirement, simulation_df, total_tax_credit)
        display_asset_visuals(total_at_retirement, total_principal_paid, asset_growth_df, simulation_df)
        display_present_value_analysis(ui, simulation_df, total_at_retirement, total_non_deductible_paid, ui.current_age_actual)

        if not simulation_df.empty:
            st.header("💡 연금소득세 비교 분석")
            # 종합과세 또는 분리과세 선택이 필요한 연도만 필터링
            choice_df = simulation_df[simulation_df['선택'].isin(['종합과세', '분리과세'])].copy()
            if choice_df.empty:
                st.info("모든 연금 수령 기간 동안 총 연금소득이 1,500만원 이하로 예상되어, 유리한 저율 분리과세(3.3%~5.5%)가 적용됩니다.")
            else:
                st.info(
                    "**연간 사적연금 소득**이 **1,500만원을 넘**는 해에는, "
                    "그 해의 **사적연금 소득 전액**에 대해 **종합과세** 또는 **16.5% 분리과세** 중 유리한 방식을 선택할 수 있습니다.\n\n"
                    "이 선택권은 **과거 신고 방식과 무관**하게 매년 부여되므로, "
                    "연간 소득이 기준을 초과하는 해마다 유불리를 따져 과세 방식을 결정하시면 됩니다."
                )
                # 예시 연도의 세금 정보 표시
                first_choice_year = choice_df.iloc[0]
                age_example = int(first_choice_year['나이'])
                annual_comp_tax = first_choice_year['종합과세액']
                annual_sep_tax = first_choice_year['분리과세액']

                col1_tax, col2_tax = st.columns(2)
                with col1_tax:
                    st.markdown(f'<p style="text-align: center;">종합과세 선택 시 (예: {age_example}세)</p>', unsafe_allow_html=True)
                    st.markdown(f'<p style="text-align: center; font-size: 1.75rem; font-weight: bold;">{annual_comp_tax:,.0f} 원</p>', unsafe_allow_html=True)
                with col2_tax:
                    st.markdown(f'<p style="text-align: center;">분리과세(16.5%) 선택 시 (예: {age_example}세)</p>', unsafe_allow_html=True)
                    st.markdown(f'<p style="text-align: center; font-size: 1.75rem; font-weight: bold;">{annual_sep_tax:,.0f} 원</p>', unsafe_allow_html=True)
                
                # 전체 기간 동안의 종합과세/분리과세 총액 비교
                total_comprehensive_tax = choice_df['종합과세액'].sum()
                total_separate_tax = choice_df['분리과세액'].sum()
                st.write("") # Spacer

                if total_comprehensive_tax < total_separate_tax:
                    conclusion_text = f"전체 기간을 고려하면 종합과세가 약 {(total_separate_tax - total_comprehensive_tax):,.0f}원 더 유리할 것으로 보입니다."
                elif total_separate_tax < total_comprehensive_tax:
                    conclusion_text = f"전체 기간을 고려하면 분리과세가 약 {(total_comprehensive_tax - total_separate_tax):,.0f}원 더 유리할 것으로 보입니다."
                else:
                    conclusion_text = "두 방식의 예상 세금 총액이 동일합니다."

                # 최종 결론 텍스트 표시
                st.markdown(f"""
                <div style="background-color: #1C3B31; color: white; padding: 12px; border-radius: 5px; text-align: center; font-size: 1.1rem; margin-top: 1rem;">
                    {conclusion_text}
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---") # 구분선 추가
            st.header("📊 연금 인출 상세 시뮬레이션")
            display_simulation_details(simulation_df) # 상세 시뮬레이션 결과 표시
        else:
            st.warning("인출 기간 동안 수령할 금액이 없습니다. 은퇴 시점 잔액이 너무 적거나 인출 기간이 짧을 수 있습니다.")
    else:
        st.warning("계산 결과, 은퇴 시점 적립금이 0원 이하입니다. 납입액이나 수익률을 조정해주세요.")
else:
    # 계산 버튼을 한 번이라도 눌렀고, 현재 계산 상태가 False인 경우 (입력값 변경됨)
    if st.session_state.get('has_calculated_once', False):
        st.info("입력값이 바뀌었습니다. 사이드바에서 '결과 확인하기' 버튼을 다시 눌러주세요.")
    else:
        # 앱 초기 로드 시 메시지
        st.info("사이드바에서 정보를 입력하고 '결과 확인하기' 버튼을 눌러주세요.")

# 주의사항 및 가정 Expander
with st.expander("주의사항 및 가정 보기"):
    st.caption("""
    1. **계산 대상**: '연금저축' 계좌만을 가정하며, IRP 계좌의 퇴직금 재원은 고려하지 않습니다.
    2. **납입 및 수령 가정**: 연간 납입은 사이드바 옵션(연초/연말)을 따르며, 연금 수령은 **매년 초**에 이루어진다고 가정합니다. (인출 후 잔액에 대해 연간 수익 발생)
    3. **세금**: 모든 세금 계산은 **지방소득세(소득세의 10%)를 포함**하며, 개인별 공제 항목에 따라 실제 세금은 달라질 수 있습니다.
    4. **수익률 및 물가**: 입력된 수익률과 물가상승률이 매년 일정하게 유지된다고 가정한 결과입니다. 실제 투자는 원금 손실의 위험이 있습니다.
    5. **연금수령한도**: 연금 수령 1~10년차에 적용되는 한도는 **'해당 연도 개시 시점의 연금계좌 평가액'**을 기준으로 계산됩니다. 한도 초과 인출액은 기타소득세(16.5%)가 적용됩니다.
    6. **일시금 수령 세금**: 연금 수령 연령에 도달하여 연금 외 형태로 수령하는 경우, **기타소득세(16.5%)**가 적용되어 계산됩니다.
    7. **세법 기준**: 이 계산기는 **2025년 현행 세법**을 기반으로 하며, 향후 세법 개정 시 결과가 달라질 수 있습니다.
    """)
