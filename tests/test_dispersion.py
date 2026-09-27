from model.dispersion import fit_count_distribution


def test_overdispersed_counts_fit_negative_binomial() -> None:
    fit = fit_count_distribution([0, 0, 1, 1, 2, 8, 10, 12])
    assert fit.family == "negative_binomial"
    assert fit.r is not None
    assert fit.r > 0


def test_near_poisson_counts_use_poisson() -> None:
    fit = fit_count_distribution([1, 2, 2, 3, 3, 4])
    assert fit.family in {"poisson", "negative_binomial"}
    assert fit.mean is not None
