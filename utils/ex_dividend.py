"""
Công thức tính giá tham chiếu ngày GDKHQ (giao dịch không hưởng quyền)
theo quy định của HOSE/HNX:

    Giá TC = (P_close + rate_issue * price_issue - cash_div_per_share)
             / (1 + rate_stock_div + rate_issue)

Trong đó:
- P_close: giá đóng cửa phiên liền trước ngày GDKHQ
- rate_stock_div: tỷ lệ cổ phiếu thưởng/chia (vd 10% => 0.10)
- rate_issue: tỷ lệ phát hành thêm cho cổ đông hiện hữu (vd 20% => 0.20)
- price_issue: giá phát hành thêm (nếu có), mặc định 0 nếu không phát hành
- cash_div_per_share: cổ tức tiền mặt / 1 cổ phiếu = tỷ lệ cổ tức tiền mặt * mệnh giá

Khi chỉ có 1 loại sự kiện, các tham số còn lại để 0 -> công thức tự rút gọn đúng
về trường hợp cổ tức tiền mặt thuần, cổ phiếu thưởng thuần, hoặc phát hành thêm thuần.
"""
import config


def calc_ex_dividend_price(
    close_price: float,
    rate_cash_div: float = 0.0,      # tỷ lệ cổ tức tiền mặt, vd 10% -> 0.10
    rate_stock_div: float = 0.0,     # tỷ lệ cổ phiếu thưởng, vd 10% -> 0.10
    rate_issue: float = 0.0,         # tỷ lệ phát hành thêm, vd 20% -> 0.20
    price_issue: float = 0.0,        # giá phát hành thêm (đồng/cp)
    face_value: float = None,
) -> float:
    face_value = face_value or config.FACE_VALUE
    cash_div_per_share = rate_cash_div * face_value

    numerator = close_price + (rate_issue * price_issue) - cash_div_per_share
    denominator = 1 + rate_stock_div + rate_issue
    return round(numerator / denominator, 0)


if __name__ == "__main__":
    # Ví dụ: cổ tức tiền mặt 10% mệnh giá 10,000, giá đóng cửa 45,000
    print(calc_ex_dividend_price(45000, rate_cash_div=0.10))
