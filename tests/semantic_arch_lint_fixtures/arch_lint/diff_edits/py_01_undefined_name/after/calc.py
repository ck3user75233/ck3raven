def compute_total(prices: list[int]) -> int:
    total = 0
    for p in prices:
        total += p

    # SUBSET EDIT: hallucinated helper call
    total += add_tax(total)

    return total
